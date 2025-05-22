import argparse
import collections
import marshal
import pathlib
import time
import pstats
from dataclasses import dataclass

import _remote_debugging


@dataclass
class CallCounts:
    total_calls: int
    inline_calls: int


def summarize_samples(stack_frames, sample_interval_usec):
    result = collections.defaultdict(
        lambda: CallCounts(total_calls=0, inline_calls=0)
    )
    # sample_interval_sec = sample_interval_usec / 1_000_000
    sample_interval_sec = sample_interval_usec / 10_000

    print("Processing samples...")
    # FIXME pstats expects file, line, func triplets, but get_stack_trace emits
    # func, file, line. Should we reorder these in get_stack_trace instead?
    for frames in stack_frames:
        func, file, line = frames[0]
        result[(file, line, func)].inline_calls += 1
        for frame in frames:
            func, file, line = frame
            result[(file, line, func)].total_calls += 1

    pstats = {}
    for fname, call_counts in result.items():
        total = call_counts.inline_calls * sample_interval_sec
        cumulative = call_counts.total_calls * sample_interval_sec
        pstats[fname] = (
            call_counts.total_calls,
            call_counts.total_calls,  # FIXME recursive calls aren't handled
            total,
            cumulative,
            {}  # FIXME
        )

    import pprint
    pprint.pprint(pstats)
    return pstats


def capture_frames(pid, duration_seconds, sample_interval_usec):
    sample_interval_sec = sample_interval_usec / 1_000_000
    print(f"running for {duration_seconds} seconds")
    stack_frames = []

    next_time = time.perf_counter()
    cur_time = next_time
    while (cur_time - next_time) < duration_seconds:
        cur_time = time.perf_counter()
        next_time += sample_interval_sec
        sleep_time = next_time - cur_time
        if sleep_time > 0:
            time.sleep(sleep_time)
        stack_frames.append(_remote_debugging.get_stack_trace(pid))

    print(f"captured {len(stack_frames)} samples")
    return stack_frames


class ProfileStats:
    def __init__(self, stats):
        self.stats = stats

    def create_stats(self):
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Remote Sampling Profiler", color=True
    )
    parser.add_argument("pid", type=int, help="attach to the specified PID")
    parser.add_argument(
        "-d",
        "--duration",
        type=int,
        help="number of seconds to sample for (default: 10)",
        default=10,
    )
    parser.add_argument(
        "-i",
        "--sample-interval",
        type=int,
        help="sample interval (usec) (default: 100)",
        default=100,
    )
    parser.add_argument(
        "-o",
        "--output-file",
        help="pstats output file name",
    )
    args = parser.parse_args()
    print(f"Sampling PID {args.pid} for {args.duration} seconds. "
          f"Sample rate: {args.sample_interval} usec ({args.sample_interval / 1_000_000} sec)")

    stack_frames = capture_frames(
        args.pid,
        duration_seconds=args.duration,
        sample_interval_usec=args.sample_interval,
    )
    pstat_results = summarize_samples(stack_frames, args.sample_interval)

    if args.output_file:
        with pathlib.Path(args.output_file).open("wb") as fp:
            marshal.dump(pstat_results, fp)
    else:
        stats = pstats.Stats(ProfileStats(pstat_results))
        stats.strip_dirs().sort_stats("time").print_stats()


if __name__ == "__main__":
    main()
