import collections
import marshal
import os
import pathlib
import time
from dataclasses import dataclass

import _remote_debugging


@dataclass
class CallCounts:
    total_calls: int
    inline_calls: int


def summarize_samples(stack_frames, sample_interval):
    duration = len(stack_frames) * sample_interval
    frequency = duration / sample_interval
    print(
        f"sample interval: {sample_interval * 1000}ms duration: {duration}s frequency: {frequency}hz"
    )

    result = collections.defaultdict(
        lambda: CallCounts(total_calls=0, inline_calls=0)
    )
    for frames in stack_frames:
        func, file, line = frames[0]
        fname = (file, line, func)
        result[fname].inline_calls += 1
        for frame in frames:
            # TODO figure out how file and line are stored
            func, file, line = frame
            result[fname].total_calls += 1

    print("Cumulative call times")
    for fname, call_counts in result.items():
        print(f"{fname}:{call_counts.total_calls * sample_interval}s")

    print("Inline call times")
    for fname, call_counts in result.items():
        print(f"{fname}:{call_counts.inline_calls * sample_interval}s")

    pstats = {}
    for fname, call_counts in result.items():
        total = call_counts.total_calls * sample_interval
        cumulative = call_counts.inline_calls * sample_interval
        pstats[fname] = (
            call_counts.total_calls,
            call_counts.total_calls,
            total,
            cumulative,
            [],
        )

    with pathlib.Path("output.pstat").open("wb") as fp:
        marshal.dump(pstats, fp)


def profile_pid(pid):
    num_samples = 100
    sample_counter = 0
    interval = 0.001  # 1 ms
    next_time = time.perf_counter()
    stack_frames = []
    while sample_counter < num_samples:
        next_time += interval
        sleep_time = next_time - time.perf_counter()
        if sleep_time > 0:
            time.sleep(sleep_time)

        stack_frames.append(_remote_debugging.get_stack_trace(pid))
        sample_counter += 1

    summarize_samples(stack_frames, interval)


def read_pid_from_pipe():
    pipe_path = "/tmp/remote_profiler.pipe"

    if not os.path.exists(pipe_path):
        raise RuntimeError(f"Pipe {pipe_path} does not exist")

    try:
        with open(pipe_path, "r") as pipe:
            print(f"Waiting to read from {pipe_path}...")
            pid = int(pipe.readline().strip())
            print(f"Got pid {pid}")
            return pid
    except Exception as e:
        print(f"An error occurred while reading from the pipe: {e}")
    finally:
        if os.path.exists(pipe_path):
            os.remove(pipe_path)



def main():
    pid = read_pid_from_pipe()
    profile_pid(pid)


if __name__ == "__main__":
    main()
