# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

import os
import time
import datetime
import argparse
import concurrent.futures
from random import randint
import numpy as np
import subprocess

if os.sys.version_info >= (3,):
    from io import BytesIO
else:
    from cStringIO import StringIO as BytesIO

from azure.storage.blob import (
    BlockBlobService,
)
from azure.common import (
    AzureException
)

# constants
DETACHED_PROCESS = 0x00000008

# percentile numbers
PERCENTILE_LIST = [80, 90, 95, 96, 97, 98, 99, 99.9]
ONE_KB = 1024

# container used for performance tests
CONTAINER_NAME = 'performance'
DEFAULT_ACCOUNT_NAME = ''
DEFAULT_ACCOUNT_KEY = ''


def main():
    # step 0: perform setup, parse the command line arguments
    parser = argparse.ArgumentParser(description='Performance tests for blob')
    parser.add_argument('--blobs', '-n')
    parser.add_argument('--blobSize', '-b')
    parser.add_argument('--concurrency', '-c')
    parser.add_argument('--parallelRequests', '-m')
    parser.add_argument('--output_upload_result_file_name', '-ou')
    parser.add_argument('--output_download_result_file_name', '-od')
    parser.add_argument('--output_delete_file_name', '-or')
    parser.add_argument('--output_graph_file_name', '-g')
    parser.add_argument('--useHttps', '-p')
    parser.add_argument('--account', '-a')
    parser.add_argument('--key', '-k')
    args = parser.parse_args()

    # read in inputs
    num_of_blobs = int(args.blobs)
    blob_size_in_kb = int(args.blobSize)
    concurrency = int(args.concurrency)
    max_connections = int(args.parallelRequests)
    output_upload_result_file_name = args.output_upload_result_file_name
    output_download_result_file_name = args.output_download_result_file_name
    output_delete_result_file_name = args.output_delete_file_name
    output_graph_file_name = args.output_graph_file_name
    protocol = 'https' if args.useHttps == 'true' else 'http'
    account_name = DEFAULT_ACCOUNT_NAME if args.account is None else args.account
    account_key = DEFAULT_ACCOUNT_KEY if args.key is None else args.key

    # step 1: delete the existing result file and log the arguments that were given by the user
    delete_file_if_exists(output_upload_result_file_name)
    delete_file_if_exists(output_delete_result_file_name)
    delete_file_if_exists(output_download_result_file_name)

    # step 2: set up the container
    bs = BlockBlobService(account_name, account_key, protocol=protocol)
    bs.create_container(CONTAINER_NAME)

    # step 3: generate list of files to upload/download
    list_of_blob_names = ['test-file-' + str(i) for i in range(num_of_blobs)]
    blob_content = create_random_content(blob_size_in_kb)

    # step 4: launch watchdog to monitor memory and CPU usage, in the detached mode, so that when the perf test exits
    # the watch dog process does not die
    # processes are handled a bit differently on windows
    if os.name == 'Windows':
        subprocess.Popen(['python', 'watch_dog.py', '-p', str(os.getpid()), '-g', output_graph_file_name], creationflags=DETACHED_PROCESS)
    else:
        subprocess.Popen(['python', 'watch_dog.py', '-p', str(os.getpid()), '-g', output_graph_file_name])

    print("Waiting for watch dog to boot up...")
    time.sleep(5)

    # step 5: perform uploads
    operation_start_time = datetime.datetime.utcnow()
    executor = concurrent.futures.ThreadPoolExecutor(concurrency)
    futures = []
    blob_size_in_bytes = blob_size_in_kb * ONE_KB
    for blob_name in list_of_blob_names:
        future = executor.submit(upload_blob, bs, blob_name, BytesIO(blob_content), blob_size_in_bytes, max_connections)
        futures.append(future)

    # each future returns the amount of time it took to perform the action
    upload_results = [future.result() for future in futures]
    print("UPLOAD DONE FOR", len(upload_results), "FILES")
    compute_result_indicators(upload_results, "Insert", output_upload_result_file_name, operation_start_time, args)

    # step 6: take off the files that we failed to upload
    list_of_blob_names = filter_out_unsuccessful_files(list_of_blob_names, upload_results)

    # step 7: perform downloads
    operation_start_time = datetime.datetime.utcnow()
    futures = []
    for blob_name in list_of_blob_names:
        future = executor.submit(download_blob, bs, blob_name, max_connections)
        futures.append(future)

    # each future returns the amount of time it took to perform the action
    download_results = [future.result() for future in futures]
    print("DOWNLOAD DONE FOR", len(download_results), "FILES")
    compute_result_indicators(download_results, "Get", output_download_result_file_name, operation_start_time, args)

    # step 8: take off the files that we failed to download
    list_of_blob_names = filter_out_unsuccessful_files(list_of_blob_names, download_results)

    # step 9: perform deletes
    operation_start_time = datetime.datetime.utcnow()
    futures = []
    for blob_name in list_of_blob_names:
        future = executor.submit(delete_blob, bs, blob_name)
        futures.append(future)

    # each future returns the amount of time it took to perform the action
    delete_results = [future.result() for future in futures]
    print("DELETE DONE FOR", len(delete_results), "FILES")
    compute_result_indicators(delete_results, "Delete", output_delete_result_file_name, operation_start_time, args)


# given a blob name, find the local input file and upload it
def upload_blob(bs, blob_name, stream, count, max_connections):

    # time the upload
    start_time = datetime.datetime.utcnow()
    try:
        bs.create_blob_from_stream(CONTAINER_NAME, blob_name, stream, count, max_connections=max_connections)
    except AzureException as e:
        # if failed, return -1 to indicate exception
        print(e)
        return -1

    return compute_elapsed_time(start_time)


# given a blob name, download it to a local output file
def download_blob(bs, blob_name, max_connections):

    # time the download
    start_time = datetime.datetime.utcnow()

    try:
        bs.get_blob_to_bytes(CONTAINER_NAME, blob_name, max_connections=max_connections)
    except AzureException as e:
        # if failed, return -1 to indicate exception
        print(e)
        return -1

    return compute_elapsed_time(start_time)


# given a blob name, delete it on the service
def delete_blob(bs, file_name):

    # time the delete
    start_time = datetime.datetime.utcnow()

    try:
        bs.delete_blob(CONTAINER_NAME, file_name)
    except AzureException as e:
        # if failed, return -1 to indicate exception
        print(e)
        return -1

    return compute_elapsed_time(start_time)


# delete the output file if it already exists
def delete_file_if_exists(name):
    if os.path.exists(name):
        os.remove(name)


# filter out files that failed during the previous action, their result (for time) would be -1
def filter_out_unsuccessful_files(list_of_files, results):
    new_list = []
    for index, result in enumerate(results):
        if result != -1:
            new_list.append(list_of_files[index])
    return new_list


# this function generates random data for the given size_in_kb
def create_random_content(size_in_kb):
    return os.urandom(ONE_KB * size_in_kb)


# compute the time that has elapsed since the given start_time, in seconds
def compute_elapsed_time(start_time):
    return (datetime.datetime.utcnow() - start_time).total_seconds() * 1000 * 1000


# compute the min/max/avg of the result times, as well as percentile average and percentile values
def compute_result_indicators(results, title, output_file_name, operation_start_time, args):
    total_count = len(results)
    successful_times = [x for x in results if x != -1]
    successful_count = len(successful_times)
    np_results = np.sort(successful_times)
    np_cumsum = np.cumsum(np_results)

    with open(output_file_name, 'a') as the_file:
        the_file.write("Total time taken to run the test in ms : " +
                       str(compute_elapsed_time(operation_start_time)) + "\n\n")
        the_file.write("Start time : " + str(operation_start_time) + ", End time : "
                       + str(datetime.datetime.utcnow()) + "\n\n")
        the_file.write("Args:")
        for key, value in args.__dict__.items():
            # ignore the account key
            if key != "key" and value is not None:
                the_file.write(key + ": " + value + ", ")
        the_file.write("\nRequest IDs for requests that took more than 90th percentile latency :\n\n")

        the_file.write(title + "," + str(np.amin(np_results)) + "," + str(np.average(np_results))
                       + "," + str(np.amax(np_results)) + ",\n")
        the_file.write("Standard Deviation, " + str(np.std(np_results)) + ",\n")
        the_file.write("Percentile, ")

        for i in PERCENTILE_LIST:
            the_file.write(str(np.percentile(np_results, i)) + ",")

        the_file.write("\nAverages, ")

        for i in PERCENTILE_LIST:
            the_file.write(str(np.percentile(np_cumsum, i) / (i / 100 * total_count)) + ",")

        the_file.write("\nException Count = " + str(total_count - successful_count) + "\n")

        the_file.write("UserProcessorTime,, PrivilegedProcessorTime, TotalProcessorTime\n\
0,,0,0,\n\
Working Set - Current,, Working Set - Peak in KB\n\
0,,0,\n\
Virtual Memory - Current,, Virtual Memory - Peak in KB\n\
0,,0,\n\
PagedMemory - Current,, PagedMemory - Peak in KB\n\
0,,0,\n\
NonPagedMemory in KB\n\
0\n\
PagedMemory in KB\n\
0\n")

    return results


if __name__ == '__main__':
    main()
