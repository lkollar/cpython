import collections
import pstats
import time
import _remote_debugging

class SampleProfile:
    def __init__(self, pid, sample_interval_usec, all_threads):
        self.pid = pid
        self.sample_interval_usec = sample_interval_usec
        self.all_threads = all_threads
        self.unwinder = _remote_debugging.RemoteUnwinder(self.pid, all_threads=self.all_threads)
        self.stats = {}

    def sample(self, duration_sec=10):
        result = collections.defaultdict(lambda: dict(total_calls=0, total_rec_calls=0, inline_calls=0))
        sample_interval_sec = self.sample_interval_usec / 1_000_000

        running_time = 0
        num_samples = 0
        errors = 0
        start_time = next_time = time.perf_counter()
        while running_time < duration_sec:
            if next_time < time.perf_counter():
                try:
                    stack_frames = self.unwinder.get_stack_trace()
                    self.aggregate_stack_frames(result, stack_frames)
                except RuntimeError, UnicodeDecodeError:
                    errors += 1

                num_samples += 1
                next_time += sample_interval_sec

            running_time = time.perf_counter() - start_time

        print(f"Captured {num_samples} samples in {running_time:.2f} seconds")
        print(f"Sample rate: {num_samples/running_time:.2f} samples/sec")
        print(f"Error rate: {(errors/num_samples)*100:.2f}%")

        expected_samples = int(duration_sec / sample_interval_sec)
        if num_samples < expected_samples:
            print(f"Warning: missed {expected_samples - num_samples} samples "
                f"from the expected total of {expected_samples} "
                f"({(expected_samples - num_samples)/expected_samples*100:.2f}%)")

        self.stats = self.convert_to_pstats(result)

    def print_stats(self, sort=-1):
        if not isinstance(sort, tuple):
            sort = (sort,)
        pstats.SampledStats(self).strip_dirs().sort_stats(*sort).print_stats()

    def dump_stats(self, file):
        with open(file, 'wb') as f:
            marshal.dump(self.stats, f)

    # Needed for compatibility with pstats.Stats
    def create_stats(self):
        pass

    def convert_to_pstats(self, raw_results):
        sample_interval_sec = self.sample_interval_usec / 1_000_000
        pstats = {}
        callers = {}
        for fname, call_counts in raw_results.items():
            total = call_counts["inline_calls"] * sample_interval_sec
            cumulative = call_counts["total_calls"] * sample_interval_sec
            pstats[fname] = (
                call_counts["total_calls"],
                call_counts["total_rec_calls"] if call_counts["total_rec_calls"] else call_counts["total_calls"],
                total,
                cumulative,
                callers, # FIXME this is most certainly broken
            )

        return pstats

    def aggregate_stack_frames(self, result, stack_frames):
        callers = {}

        for thread_id, frames in stack_frames:
            if not frames:
                continue
            top_location = frames[0]
            if not top_location in callers:
                callers[top_location] = {}

            result[top_location]["inline_calls"] += 1
            result[top_location]["total_calls"] += 1

            if len(frames) > 1:
                next_frame_loc = frames[1]
                callers[top_location][next_frame_loc] = callers[top_location].get(next_frame_loc, 0) + 1
            else:
                continue

            for location in frames[1:]:
                result[location]["total_calls"] += 1
                if top_location == location:
                    result[location]["total_rec_calls"] += 1



def sample(pid, *, sort=-1, sample_interval_usec=100, duration_sec=10, filename=None):
    profile = SampleProfile(pid, sample_interval_usec, all_threads=False)
    profile.sample(duration_sec)
    if filename:
        profile.dump_stats(filename)
    else:
        profile.print_stats(sort)

def main():
    ...

if __name__ == '__main__':
    main()
