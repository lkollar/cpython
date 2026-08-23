"""Small public-API external collector used by sampling profiler tests."""

import json
import os

from profiling.sampling import Collector, StackTraceCollector


class JsonTraceCollector(StackTraceCollector):
    """Write one JSON record per sampled stack."""

    def __init__(self, context):
        super().__init__(
            skip_idle=context.sampling_mode not in (None, "wall")
        )
        suffix = (
            "replay" if context.command == "replay" else context.target_pid
        )
        self.output_file = context.requested_output_file or os.path.abspath(
            f"external-profile-{suffix}.jsonl"
        )
        self.records = []

    def process_frames(self, frames, thread_id, weight=1, timestamps_us=None):
        timestamps = timestamps_us or (None,) * weight
        for timestamp_us in timestamps:
            self.records.append({
                "timestamp_us": timestamp_us,
                "thread_id": thread_id,
                "stack": [
                    {"file": frame[0], "line": frame[1], "function": frame[2]}
                    for frame in frames
                ],
            })

    def export(self, filename):
        with open(filename, "w", encoding="utf-8") as output:
            for record in self.records:
                output.write(json.dumps(record) + "\n")
        return bool(self.records)


def create_collector(context):
    return JsonTraceCollector(context)


assert issubclass(JsonTraceCollector, Collector)
