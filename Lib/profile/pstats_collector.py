import collections
import marshal
import pstats
from _colorize import ANSIColors

from .collector import Collector


class PstatsCollector(Collector):
    def __init__(self, sample_interval_usec):
        self.result = collections.defaultdict(
            lambda: dict(total_calls=0, total_rec_calls=0, inline_calls=0)
        )
        self.stats = {}
        self.sample_interval_usec = sample_interval_usec
        self.callers = collections.defaultdict(
            lambda: collections.defaultdict(int)
        )

    def collect(self, stack_frames):
        for thread_id, frames in stack_frames:
            if not frames:
                continue

            top_frame = frames[0]
            top_location = (
                top_frame.filename,
                top_frame.lineno,
                top_frame.funcname,
            )

            self.result[top_location]["inline_calls"] += 1
            self.result[top_location]["total_calls"] += 1

            for i in range(1, len(frames)):
                callee_frame = frames[i - 1]
                caller_frame = frames[i]

                callee = (
                    callee_frame.filename,
                    callee_frame.lineno,
                    callee_frame.funcname,
                )
                caller = (
                    caller_frame.filename,
                    caller_frame.lineno,
                    caller_frame.funcname,
                )

                self.callers[callee][caller] += 1

            if len(frames) <= 1:
                continue

            for frame in frames[1:]:
                location = (frame.filename, frame.lineno, frame.funcname)
                self.result[location]["total_calls"] += 1

    def export(self, filename):
        self.create_stats()
        self._dump_stats(filename)

    def _dump_stats(self, file):
        stats_with_marker = dict(self.stats)
        stats_with_marker[("__sampled__",)] = True
        with open(file, "wb") as f:
            marshal.dump(stats_with_marker, f)

    # Needed for compatibility with pstats.Stats
    def create_stats(self):
        sample_interval_sec = self.sample_interval_usec / 1_000_000
        callers = {}
        for fname, call_counts in self.result.items():
            total = call_counts["inline_calls"] * sample_interval_sec
            cumulative = call_counts["total_calls"] * sample_interval_sec
            callers = dict(self.callers.get(fname, {}))
            self.stats[fname] = (
                call_counts["total_calls"],
                call_counts["total_rec_calls"]
                if call_counts["total_rec_calls"]
                else call_counts["total_calls"],
                total,
                cumulative,
                callers,
            )


def print_pstats(pstats_collector, sort=-1, limit=None, show_summary=True):
    if not isinstance(sort, tuple):
        sort = (sort,)
    stats = pstats.SampledStats(pstats_collector).strip_dirs()

    # Get the stats data
    stats_list = []
    for func, (cc, nc, tt, ct, callers) in stats.stats.items():
        stats_list.append((func, cc, nc, tt, ct, callers))

    # Sort based on the requested field
    sort_field = sort[0]
    if sort_field == -1:  # stdname
        stats_list.sort(key=lambda x: str(x[0]))
    elif sort_field == 0:  # calls
        stats_list.sort(key=lambda x: x[2], reverse=True)
    elif sort_field == 1:  # time
        stats_list.sort(key=lambda x: x[3], reverse=True)
    elif sort_field == 2:  # cumulative
        stats_list.sort(key=lambda x: x[4], reverse=True)
    elif sort_field == 3:  # percall
        stats_list.sort(
            key=lambda x: x[3] / x[2] if x[2] > 0 else 0, reverse=True
        )
    elif sort_field == 4:  # cumpercall
        stats_list.sort(
            key=lambda x: x[4] / x[2] if x[2] > 0 else 0, reverse=True
        )

    # Apply limit if specified
    if limit is not None:
        stats_list = stats_list[:limit]

    # Find the maximum values for each column to determine units
    max_tt = max((tt for _, _, _, tt, _, _ in stats_list), default=0)
    max_ct = max((ct for _, _, _, _, ct, _ in stats_list), default=0)

    # Determine appropriate units and format strings
    if max_tt >= 1.0:
        tt_unit = "s"
        tt_scale = 1.0
    elif max_tt >= 0.001:
        tt_unit = "ms"
        tt_scale = 1000.0
    else:
        tt_unit = "μs"
        tt_scale = 1000000.0

    if max_ct >= 1.0:
        ct_unit = "s"
        ct_scale = 1.0
    elif max_ct >= 0.001:
        ct_unit = "ms"
        ct_scale = 1000.0
    else:
        ct_unit = "μs"
        ct_scale = 1000000.0

    # Print header with colors and units
    header = (
        f"{ANSIColors.BOLD_BLUE}Profile Stats:{ANSIColors.RESET}\n"
        f"{ANSIColors.BOLD_BLUE}nsamples{ANSIColors.RESET} "
        f"{ANSIColors.BOLD_BLUE}tottime ({tt_unit}){ANSIColors.RESET} "
        f"{ANSIColors.BOLD_BLUE}persample ({tt_unit}){ANSIColors.RESET} "
        f"{ANSIColors.BOLD_BLUE}cumtime ({ct_unit}){ANSIColors.RESET} "
        f"{ANSIColors.BOLD_BLUE}persample ({ct_unit}){ANSIColors.RESET} "
        f"{ANSIColors.BOLD_BLUE}filename:lineno(function){ANSIColors.RESET}"
    )
    print(header)

    # Print each line with colors
    for func, cc, nc, tt, ct, callers in stats_list:
        if nc != cc:
            ncalls = f"{nc}/{cc}"
        else:
            ncalls = str(nc)

        # Format numbers with proper alignment and precision (no colors)
        tottime = f"{tt * tt_scale:8.3f}"
        percall = f"{(tt / nc) * tt_scale:8.3f}" if nc > 0 else "    N/A"
        cumtime = f"{ct * ct_scale:8.3f}"
        cumpercall = f"{(ct / nc) * ct_scale:8.3f}" if nc > 0 else "    N/A"

        # Format the function name with colors
        func_name = (
            f"{ANSIColors.GREEN}{func[0]}{ANSIColors.RESET}:"
            f"{ANSIColors.YELLOW}{func[1]}{ANSIColors.RESET}("
            f"{ANSIColors.CYAN}{func[2]}{ANSIColors.RESET})"
        )

        # Print the formatted line
        print(
            f"{ncalls:>8}  {tottime}    {percall}        {cumtime}    {cumpercall}        {func_name}"
        )

    def _format_func_name(func):
        """Format function name with colors."""
        return (
            f"{ANSIColors.GREEN}{func[0]}{ANSIColors.RESET}:"
            f"{ANSIColors.YELLOW}{func[1]}{ANSIColors.RESET}("
            f"{ANSIColors.CYAN}{func[2]}{ANSIColors.RESET})"
        )

    def _print_top_functions(stats_list, title, key_func, format_line, n=3):
        """Print top N functions sorted by key_func with formatted output."""
        print(f"\n{ANSIColors.BOLD_BLUE}{title}:{ANSIColors.RESET}")
        sorted_stats = sorted(stats_list, key=key_func, reverse=True)
        for stat in sorted_stats[:n]:
            if line := format_line(stat):
                print(f"  {line}")

    # Print summary of interesting functions if enabled
    if show_summary and stats_list:
        print(
            f"\n{ANSIColors.BOLD_BLUE}Summary of Interesting Functions:{ANSIColors.RESET}"
        )

        # Most time-consuming functions (by total time)
        def format_time_consuming(stat):
            func, _, nc, tt, _, _ = stat
            if tt > 0:
                return (
                    f"{tt * tt_scale:8.3f} {tt_unit} total time, "
                    f"{(tt / nc) * tt_scale:8.3f} {tt_unit} per call: {_format_func_name(func)}"
                )
            return None

        _print_top_functions(
            stats_list,
            "Most Time-Consuming Functions",
            key_func=lambda x: x[3],
            format_line=format_time_consuming,
        )

        # Most called functions
        def format_most_called(stat):
            func, _, nc, tt, _, _ = stat
            if nc > 0:
                return (
                    f"{nc:8d} calls, {(tt / nc) * tt_scale:8.3f} {tt_unit} "
                    f"per call: {_format_func_name(func)}"
                )
            return None

        _print_top_functions(
            stats_list,
            "Most Called Functions",
            key_func=lambda x: x[2],
            format_line=format_most_called,
        )

        # Functions with highest per-call overhead
        def format_overhead(stat):
            func, _, nc, tt, _, _ = stat
            if nc > 0 and tt > 0:
                return (
                    f"{(tt / nc) * tt_scale:8.3f} {tt_unit} per call, "
                    f"{nc:8d} calls: {_format_func_name(func)}"
                )
            return None

        _print_top_functions(
            stats_list,
            "Functions with Highest Per-Call Overhead",
            key_func=lambda x: x[3] / x[2] if x[2] > 0 else 0,
            format_line=format_overhead,
        )

        # Functions with highest cumulative impact
        def format_cumulative(stat):
            func, _, nc, _, ct, _ = stat
            if ct > 0:
                return (
                    f"{ct * ct_scale:8.3f} {ct_unit} cumulative time, "
                    f"{(ct / nc) * ct_scale:8.3f} {ct_unit} per call: "
                    f"{_format_func_name(func)}"
                )
            return None

        _print_top_functions(
            stats_list,
            "Functions with Highest Cumulative Impact",
            key_func=lambda x: x[4],
            format_line=format_cumulative,
        )
