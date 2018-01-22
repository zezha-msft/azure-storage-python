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


def main():
    # step 0: perform setup, parse the command line arguments and set up the container
    parser = argparse.ArgumentParser(description='Performance tests for blob')
    parser.add_argument('--number_of_blobs', '-n')
    parser.add_argument('--blob_size', '-b')
    parser.add_argument('--concurrency', '-c')
    parser.add_argument('--max_connections', '-m')
    parser.add_argument('--output_result_file_name', '-o')
    parser.add_argument('--output_graph_file_name', '-g')
    parser.add_argument('--protocol', '-p')
    parser.add_argument('--account', '-a')
    parser.add_argument('--key', '-k')
    args = parser.parse_args()

    # read in inputs
    num_of_blobs = int(args.number_of_blobs)
    blob_size_in_kb = int(args.blob_size)
    concurrency = int(args.concurrency)
    max_connections = int(args.max_connections)
    output_result_file_name = args.output_result_file_name
    output_graph_file_name = args.output_graph_file_name
    protocol = args.protocol
    account_name = args.account
    account_key = args.key

    # delete the existing result file and log the arguments that were given by the user
    delete_file_if_exists(output_result_file_name)
    log_args(args, output_result_file_name)
    bs = BlockBlobService(account_name, account_key, protocol=protocol)
    bs.create_container(CONTAINER_NAME)

    # step 1: generate list of files to upload/download
    list_of_files = ['test-file-' + str(i) + '.txt' for i in range(num_of_blobs)]
    for file in list_of_files:
        create_random_content_file(file, blob_size_in_kb)

    # step 2: launch watchdog to monitor memory and CPU usage, in the detached mode, so that when the perf test exits
    # the watch dog process does not die
    subprocess.Popen(['python', 'watch_dog.py', '-p', str(os.getpid()), '-g', output_graph_file_name], creationflags=DETACHED_PROCESS)
    print("Waiting for watch dog to boot up...")
    time.sleep(5)
    overall_start_time = datetime.datetime.utcnow()

    # step 3: perform uploads
    executor = concurrent.futures.ThreadPoolExecutor(concurrency)
    futures = []
    for file in list_of_files:
        future = executor.submit(upload_blob, bs, file, max_connections)
        futures.append(future)

    # each future returns the amount of time it took to perform the action
    upload_results = [future.result() for future in futures]
    print("UPLOAD DONE FOR", len(upload_results), "FILES")
    compute_result_indicators(upload_results, "===UPLOAD RESULTS===", output_result_file_name, overall_start_time)

    # step 4: take off the files that we failed to upload
    list_of_files = filer_out_unsuccessful_files(list_of_files, upload_results)

    # step 5: perform downloads
    futures = []
    for file in list_of_files:
        future = executor.submit(download_blob, bs, file, max_connections)
        futures.append(future)

    # each future returns the amount of time it took to perform the action
    download_results = [future.result() for future in futures]
    print("DOWNLOAD DONE FOR", len(download_results), "FILES")
    compute_result_indicators(download_results, "\n===DOWNLOAD RESULTS===", output_result_file_name, overall_start_time)

    # step 6: pick a random file to check the content
    random_check = list_of_files[randint(0, num_of_blobs - 1)]
    if not compare_local_files_for_blob(random_check):
        print("Random inspection failed on file:", random_check, "exiting tests as something is SERIOUSLY WRONG")
        return

    # step 7: take off the files that we failed to download
    list_of_files = filer_out_unsuccessful_files(list_of_files, download_results)

    # step 8: perform deletes
    futures = []
    for file in list_of_files:
        future = executor.submit(delete_blob, bs, file)
        futures.append(future)

    # each future returns the amount of time it took to perform the action
    delete_results = [future.result() for future in futures]
    print("DELETE DONE FOR", len(delete_results), "FILES")
    compute_result_indicators(delete_results, "\n===DELETE RESULTS===", output_result_file_name, overall_start_time)


# given a blob name, find the local input file and upload it
def upload_blob(bs, file_name, max_connections):
    source_file_name = input_file(file_name)
    destination_blob_name = file_name

    # time the upload
    start_time = datetime.datetime.utcnow()
    try:
        bs.create_blob_from_path(CONTAINER_NAME, destination_blob_name, source_file_name,
                                 max_connections=max_connections)
    except AzureException as e:
        # if failed, return -1 to indicate exception
        print(e)
        return -1

    return compute_elapsed_time(start_time)


# given a blob name, download it to a local output file
def download_blob(bs, file_name, max_connections):
    source_blob_name = file_name
    destination_file_name = output_file(file_name)

    delete_file_if_exists(destination_file_name)

    # time the download
    start_time = datetime.datetime.utcnow()

    try:
        bs.get_blob_to_path(CONTAINER_NAME, source_blob_name, destination_file_name, max_connections=max_connections)
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


# this function produces a file name that indicates it was uploaded to the service
def input_file(name):
    return 'input-' + name


# this function produces a file name that indicates it was downloaded from the service
def output_file(name):
    return 'output-' + name


# delete the output file if it already exists
def delete_file_if_exists(name):
    if os.path.exists(name):
        os.remove(name)


# filter out files that failed during the previous action, their result (for time) would be -1
def filer_out_unsuccessful_files(list_of_files, results):
    new_list = []
    for index, result in enumerate(results):
        if result != -1:
            new_list.append(list_of_files[index])
    return new_list


# this function generates random data and write them into a given file(with 'input-' prepended)
# this is done so that we can identify the state of the file before it was uploaded
def create_random_content_file(name, size_in_kb):
    file_name = input_file(name)

    # if the file already exists and is the right size, do not regenerate
    if not os.path.exists(file_name) or os.path.getsize(file_name) != size_in_kb * 1024:
        print('generating {0}'.format(name))
        with open(file_name, 'wb') as stream:
            for i in range(size_in_kb):
                # write a KB at a time
                stream.write(os.urandom(ONE_KB))


# this function verifies if two given files have equal contents
def are_file_contents_equal(first_file_path, second_file_path):
    first_size = os.path.getsize(first_file_path)
    second_size = os.path.getsize(second_file_path)

    # fail fast if the files do not have the same size
    if first_size != second_size:
        return False
    with open(first_file_path, 'rb') as first_stream:
        with open(second_file_path, 'rb') as second_stream:
            while True:
                # read one KB at a time to compare
                first_data = first_stream.read(ONE_KB)
                second_data = second_stream.read(ONE_KB)

                if first_data != second_data:
                    return False
                if not first_data:
                    return True


# given a blob name, compare its content before uploading and after downloading
def compare_local_files_for_blob(name):
    first_file_path = input_file(name)
    second_file_path = output_file(name)

    return are_file_contents_equal(first_file_path, second_file_path)


# compute the time that has elapsed since the given start_time, in seconds
def compute_elapsed_time(start_time):
    return (datetime.datetime.utcnow() - start_time).total_seconds()


# write out what the command line arguments were
def log_args(args, output_file_name):
    with open(output_file_name, 'a') as the_file:
        the_file.write("===ARGS===" + "\n")

        for key, value in args.__dict__.items():
            # ignore the account key
            if key != "key":
                the_file.write("Arg:" + key + "=" + value + "\n")
        the_file.write("\n")


# compute the min/max/avg of the result times, as well as percentile average and
def compute_result_indicators(results, title, output_file_name, overall_start_time):
    total_count = len(results)
    successful_times = [x for x in results if x != -1]
    successful_count = len(successful_times)
    np_results = np.sort(successful_times)
    np_cumsum = np.cumsum(np_results)

    with open(output_file_name, 'a') as the_file:
        the_file.write(title + "\n")
        the_file.write("operation completed at: " + str(compute_elapsed_time(overall_start_time))
                       + " s after watch dog started.\n")
        the_file.write("total count: " + str(total_count) + "\n")
        the_file.write("success count: " + str(successful_count) + "\n")
        the_file.write("exception count: " + str(total_count - successful_count) + "\n")
        the_file.write("min: " + str(np.amin(np_results)) + "\n")
        the_file.write("max: " + str(np.amax(np_results)) + "\n")
        the_file.write("avg: " + str(np.average(np_results)) + "\n")
        the_file.write("standard deviation: " + str(np.std(np_results)) + "\n")

        for i in PERCENTILE_LIST:
            the_file.write("percentile " + str(i) + ": "
                           + str(np.percentile(np_results, i)) + "\n")

        for i in PERCENTILE_LIST:
            the_file.write("average " + str(i) + ": "
                           + str(np.percentile(np_cumsum, i) / (i / 100 * total_count)) + "\n")

    return results


if __name__ == '__main__':
    main()
