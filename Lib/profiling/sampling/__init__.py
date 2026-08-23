"""Statistical sampling profiler for Python.

This module provides low-overhead profiling by periodically sampling the
call stack rather than tracing every function call.
"""

from .collector import Collector, CollectorContext
from .pstats_collector import PstatsCollector
from .stack_collector import CollapsedStackCollector, StackTraceCollector
from .heatmap_collector import HeatmapCollector
from .gecko_collector import GeckoCollector
from .jsonl_collector import JsonlCollector
from .string_table import StringTable

__all__ = (
    "Collector",
    "CollectorContext",
    "StackTraceCollector",
    "PstatsCollector",
    "CollapsedStackCollector",
    "HeatmapCollector",
    "GeckoCollector",
    "JsonlCollector",
    "StringTable",
)
