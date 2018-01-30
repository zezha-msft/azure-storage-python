# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import psutil
import time
import argparse


def main():
    parser = argparse.ArgumentParser(description='Performance tests for blob')
    parser.add_argument('--output_graph_name', '-g')
    parser.add_argument('--pid', '-p')
    args = parser.parse_args()

    # from command line
    output_graph_name = args.output_graph_name
    pid_to_monitor = int(args.pid)

    # note down the time at which monitoring started
    start_time = datetime.utcnow()
    p = psutil.Process(pid_to_monitor)
    num_of_cpus = psutil.cpu_count(False)

    system_cpu = []
    system_mem = []
    process_cpu = []
    process_mem = []
    times = []

    while p.is_running():
        # get system CPU usage
        system_cpu.append(psutil.cpu_percent(interval=0.0, percpu=False))

        # compute system memory usage
        system_virtual_mem = psutil.virtual_memory()
        system_mem.append(system_virtual_mem.used / system_virtual_mem.total * 100)

        # compute times delta since the start of monitoring
        times.append((datetime.utcnow() - start_time).total_seconds())

        with p.oneshot():
            # get process CPU usage, it needs to be divided by the number of CPUs
            # because this value is aggregated across several CPUs
            process_cpu.append(p.cpu_percent() / num_of_cpus)

            # get process memory usage
            process_mem.append(p.memory_percent())

        # sleep for some time before capturing the state again
        time.sleep(1)

    # plot the system usage
    plt.figure(1)
    # row 3, column 1, index 1, this is at the top of the page
    plt.subplot(311)
    # cpu in red line, mem in blue line
    plt.plot(times, system_cpu, 'ro', times, system_mem, 'b^')
    plt.xlabel('times(s)')
    plt.ylabel('usage(%)')
    plt.title('System CPU(red) and Memory Usage(blue)')

    # plot the process usage
    # row 3, column 1, index 3, so this graph is at the bottom of the page
    # index 2 is kept empty on purpose, otherwise the axis label of the previous graph goes onto this graph
    plt.subplot(313)
    # cpu in red line, mem in blue line
    plt.plot(times, process_cpu, 'ro', times, process_mem, 'b^')
    plt.xlabel('times(s)')
    plt.ylabel('usage(%)')
    plt.title('Process CPU(red) and Memory Usage(blue)')

    plt.savefig(output_graph_name)


if __name__ == '__main__':
    main()
