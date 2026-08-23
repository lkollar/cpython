import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from profiling.sampling import Collector, CollectorContext, StackTraceCollector
from profiling.sampling import __all__ as sampling_exports
from profiling.sampling import cli
from profiling.sampling.sample import _store_builtin_run_stats
from profiling.sampling.sample import sample as run_sampling
from profiling.sampling.stack_collector import FlamegraphCollector

from .external_collector import JsonTraceCollector


class _PathCollector(Collector):
    def __init__(self, output_file):
        self.output_file = output_file

    def collect(self, stack_frames, timestamps_us=None):
        pass

    def export(self, filename):
        return True


class _NoOutputCollector(Collector):
    def collect(self, stack_frames, timestamps_us=None):
        pass

    def export(self, filename):
        return True


class ExternalCollectorApiTests(unittest.TestCase):
    def make_context(self, output=None):
        return CollectorContext(
            command="attach", target_pid=123, input_file=None,
            requested_output_file=output, sample_interval_usec=1000,
            duration_sec=1.0, sampling_mode="wall", all_threads=True,
            async_aware="running", native=False, gc=True, opcodes=False,
            blocking=False,
        )

    def test_context_is_frozen_and_slots(self):
        context = self.make_context()
        self.assertIsInstance(context, CollectorContext)
        self.assertFalse(hasattr(context, "__dict__"))
        with self.assertRaises(TypeError):
            CollectorContext("attach", 123, None, None, 1000, 1.0, "wall",
                             True, None, False, True, False, False)
        with self.assertRaises(AttributeError):
            context.command = "run"

    def test_public_exports_are_limited_to_documented_additions(self):
        self.assertIn("Collector", sampling_exports)
        self.assertIn("CollectorContext", sampling_exports)
        self.assertIn("StackTraceCollector", sampling_exports)
        self.assertNotIn("resolve_collector", sampling_exports)
        self.assertNotIn("filter_internal_frames", sampling_exports)
        self.assertFalse(hasattr(Collector, "set_run_metadata"))

    def test_resolver_and_diagnostics(self):
        self.assertIs(
            cli._resolve_collector_factory(
                "test.test_profiling.test_sampling_profiler.external_collector:create_collector"
            ),
            __import__(
                "test.test_profiling.test_sampling_profiler.external_collector",
                fromlist=["create_collector"],
            ).create_collector,
        )
        for spec in ("bad", "bad:", ":factory", "a:b:c"):
            with self.assertRaisesRegex(ValueError, "collector"):
                cli._resolve_collector_factory(spec)
        with self.assertRaisesRegex(ValueError, "Could not load collector"):
            cli._resolve_collector_factory("no_such_module_xyz:create")
        with mock.patch(
            "pkgutil.resolve_name", side_effect=ImportError("missing dep")
        ):
            with self.assertRaisesRegex(ValueError, "missing dep"):
                cli._resolve_collector_factory("pkg.mod:create")
        with mock.patch(
            "pkgutil.resolve_name", side_effect=AttributeError("missing attr")
        ):
            with self.assertRaisesRegex(ValueError, "missing attr"):
                cli._resolve_collector_factory("pkg.mod:create")
        with mock.patch("pkgutil.resolve_name", return_value=object()):
            with self.assertRaisesRegex(TypeError, "not callable"):
                cli._resolve_collector_factory("pkg.mod:create")
        with mock.patch(
            "pkgutil.resolve_name", side_effect=RuntimeError("plugin bug")
        ):
            with self.assertRaisesRegex(RuntimeError, "plugin bug"):
                cli._resolve_collector_factory("pkg.mod:create")

    def test_parser_resolves_before_target_launch(self):
        with (
            mock.patch(
                "sys.argv",
                ["sampling", "run", "--collector", "bad", __file__],
            ),
            mock.patch("profiling.sampling.cli._run_with_sync") as run,
            mock.patch("sys.stderr", new_callable=io.StringIO) as err,
            self.assertRaises(SystemExit) as cm,
        ):
            cli.main()
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("--collector", err.getvalue())
        run.assert_not_called()

    def test_external_output_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            requested = os.path.join(tmp, "trace.jsonl")
            context = self.make_context(requested)
            collector = cli._make_external_collector(
                lambda _context: _PathCollector(Path(requested)), context
            )
            self.assertIsInstance(collector.output_file, Path)
            self.assertIs(
                cli._make_external_collector(
                    lambda _context: _PathCollector(requested), context
                ).output_file.__class__,
                str,
            )
            for output in (None, "", 1, b"trace.jsonl"):
                with self.subTest(output=output):
                    with self.assertRaises((TypeError, ValueError)):
                        cli._make_external_collector(
                            lambda _context, output=output: _PathCollector(output),
                            context,
                        )
            with self.assertRaisesRegex(ValueError, "does not match"):
                cli._make_external_collector(
                    lambda _context: _PathCollector(os.path.join(tmp, "other")),
                    context,
                )

    def test_factory_runtime_error_has_cause(self):
        with self.assertRaisesRegex(RuntimeError, "factory failed") as cm:
            cli._make_external_collector(
                lambda _context: (_ for _ in ()).throw(
                    RuntimeError("factory failed")
                ),
                self.make_context(),
            )
        self.assertIsInstance(cm.exception.__cause__, RuntimeError)

    def test_run_factory_failure_terminates_target(self):
        with tempfile.NamedTemporaryFile(suffix=".py") as script:
            process = mock.MagicMock()
            process.pid = 123
            process.poll.return_value = None
            args = SimpleNamespace(
                module=False, target=script.name, args=[], live=False,
                collector="pkg.mod:create", _collector_factory=lambda _ctx: (_ for _ in ()).throw(
                    RuntimeError("plugin failed")
                ), format="pstats", mode="wall", sample_interval_usec=1000,
                duration=None, all_threads=False, realtime_stats=False,
                async_aware=False, async_mode="running", native=False,
                gc=True, opcodes=False, blocking=False, subprocesses=False,
                outfile=None, browser=False,
            )
            with mock.patch(
                "profiling.sampling.cli._run_with_sync", return_value=process
            ):
                with self.assertRaisesRegex(RuntimeError, "plugin failed") as cm:
                    cli._handle_run(args)
            process.terminate.assert_called_once_with()
            self.assertIsInstance(cm.exception.__cause__, RuntimeError)

    def test_non_collector_and_default_output(self):
        with self.assertRaisesRegex(TypeError, "must return a Collector"):
            cli._make_external_collector(lambda _context: object(), self.make_context())
        with self.assertRaisesRegex(TypeError, "output_file"):
            cli._make_external_collector(
                lambda _context: _NoOutputCollector(), self.make_context()
            )
        collector = cli._make_external_collector(
            lambda context: JsonTraceCollector(context), self.make_context()
        )
        self.assertTrue(os.fspath(collector.output_file))

    def test_context_fields_and_explicit_interval(self):
        args = SimpleNamespace(
            outfile="out.jsonl", sample_interval_usec=1234, duration=2,
            mode="cpu", all_threads=True, async_aware=True,
            async_mode="all", native=True, gc=False, opcodes=True,
            blocking=True,
        )
        context = cli._collector_context(
            "run", args, target_pid=99, sample_interval_usec=1234
        )
        self.assertEqual(context.target_pid, 99)
        self.assertEqual(context.sample_interval_usec, 1234)
        self.assertEqual(context.duration_sec, 2.0)
        self.assertEqual(context.sampling_mode, "cpu")
        self.assertEqual(context.async_aware, "all")
        replay = cli._collector_context(
            "replay", args, input_file="in.bin", sample_interval_usec=77,
        )
        self.assertEqual(replay.sample_interval_usec, 77)
        self.assertEqual(replay.input_file, "in.bin")
        for field in ("target_pid", "duration_sec", "sampling_mode", "all_threads",
                      "async_aware", "native", "gc", "opcodes", "blocking"):
            self.assertIsNone(getattr(replay, field))

    def test_attach_smoke_context_sampling_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "attach.jsonl")
            contexts = []

            def factory(context):
                contexts.append(context)
                return JsonTraceCollector(context)

            def sample(pid, collector, **kwargs):
                self.assertEqual(pid, 321)
                self.assertEqual(kwargs["sample_interval_usec"], 4321)
                collector.process_frames(
                    [("attach.py", (5, 5, -1, -1), "work", None)],
                    9, timestamps_us=[456],
                )
                return collector

            args = SimpleNamespace(
                pid=321, live=False, collector="pkg.mod:create",
                _collector_factory=factory, outfile=output, browser=False,
                sample_interval_usec=4321, duration=1, mode="cpu",
                all_threads=True, realtime_stats=False, async_aware=True,
                async_mode="all", native=False, gc=True, opcodes=True,
                blocking=True, subprocesses=False, format="pstats",
            )
            with (
                mock.patch(
                    "profiling.sampling.cli._is_process_running",
                    return_value=True,
                ),
                mock.patch("profiling.sampling.cli.sample", side_effect=sample),
            ):
                cli._handle_attach(args)

            self.assertEqual(len(contexts), 1)
            context = contexts[0]
            self.assertEqual(context.command, "attach")
            self.assertEqual(context.target_pid, 321)
            self.assertEqual(context.sample_interval_usec, 4321)
            self.assertEqual(context.async_aware, "all")
            with open(output, encoding="utf-8") as stream:
                content = stream.read()
            self.assertIn('"timestamp_us": 456', content)

    def test_replay_smoke_context_and_single_export(self):
        class Reader:
            def get_info(self):
                return {"sample_count": 1, "sample_interval_us": 77,
                        "compression_type": 0}

            def replay_samples(self, collector, progress_callback):
                collector.process_frames(
                    [("replay.py", (4, 4, -1, -1), "work", None)],
                    8, timestamps_us=[123],
                )
                progress_callback(1, 1)
                return 1

        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "replay.jsonl")
            captured = []
            instances = []

            def factory(context):
                captured.append(context)
                collector = JsonTraceCollector(context)
                collector.export = mock.Mock(wraps=collector.export)
                instances.append(collector)
                return collector

            args = SimpleNamespace(
                collector="pkg.mod:create", _collector_factory=factory,
                input_file="input.bin", outfile=output, browser=False,
                format="pstats", diff_baseline=None,
            )
            cli._replay_with_reader(args, Reader())
            self.assertEqual(len(captured), 1)
            context = captured[0]
            self.assertEqual(context.sample_interval_usec, 77)
            self.assertEqual(context.input_file, "input.bin")
            self.assertIsNone(context.target_pid)
            self.assertIsNone(context.sampling_mode)
            self.assertEqual(instances[0].export.call_count, 1)
            # The real factory above was exported once by replay; smoke output
            # confirms timestamped records were written.
            with open(output, encoding="utf-8") as stream:
                content = stream.read()
            self.assertIn('"timestamp_us": 123', content)

    def test_builtin_replay_keeps_existing_output_directory(self):
        collector = mock.Mock()
        collector.export.return_value = True
        with tempfile.TemporaryDirectory() as output:
            args = SimpleNamespace(
                format="heatmap", outfile=output, browser=False
            )
            cli._handle_replay_output(collector, args, 123)
        collector.export.assert_called_once_with(output)

    def test_browser_is_rejected_for_external_collectors(self):
        with (
            mock.patch(
                "sys.argv",
                ["sampling", "attach", "--collector", "pkg.mod:create",
                 "--browser", "123"],
            ),
            mock.patch("sys.stderr", new_callable=io.StringIO) as err,
            self.assertRaises(SystemExit) as cm,
        ):
            cli.main()
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("--browser", err.getvalue())

    def test_cli_rejects_incompatible_options_and_accepts_opcodes(self):
        cases = (
            (["sampling", "run", "--collector", "pkg.mod:create",
              "--live", __file__], "--live is incompatible"),
            (["sampling", "run", "--collector", "pkg.mod:create",
              "--sort", "name", __file__], "--sort"),
            (["sampling", "attach", "--collector", "pkg.mod:create",
              "--limit", "1", "123"], "--limit"),
            (["sampling", "replay", "--collector", "pkg.mod:create",
              "--no-summary", "input.bin"], "--no-summary"),
            (["sampling", "replay", "--collector", "pkg.mod:create",
              "--sort", "name", "input.bin"], "--sort"),
        )
        for argv, message in cases:
            with self.subTest(argv=argv):
                with (
                    mock.patch("sys.argv", argv),
                    mock.patch(
                        "sys.stderr", new_callable=io.StringIO
                    ) as err,
                    self.assertRaises(SystemExit) as cm,
                ):
                    cli.main()
            self.assertEqual(cm.exception.code, 2)
            self.assertIn(message, err.getvalue())

        def factory(_context):
            return None

        with (
            mock.patch(
                "sys.argv",
                ["sampling", "attach", "--collector", "pkg.mod:create",
                 "--opcodes", "123"],
            ),
            mock.patch(
                "profiling.sampling.cli._resolve_collector_factory",
                return_value=factory,
            ),
            mock.patch("profiling.sampling.cli._handle_attach") as attach,
        ):
            cli.main()
        attach.assert_called_once()
        parsed_args = attach.call_args.args[0]
        self.assertEqual(parsed_args.format, "pstats")
        self.assertIs(parsed_args._collector_factory, factory)
        self.assertFalse(hasattr(parsed_args, "collector_factory"))

        with (
            mock.patch(
                "sys.argv", ["sampling", "run", "--opcodes", __file__]
            ),
            mock.patch("sys.stderr", new_callable=io.StringIO) as err,
            self.assertRaises(SystemExit) as cm,
        ):
            cli.main()
        self.assertEqual(cm.exception.code, 2)
        self.assertNotIn("--collector", err.getvalue())

    def test_sample_accepts_collector_without_interval_attribute(self):
        collector = _PathCollector("trace")
        profiler = mock.MagicMock()
        with mock.patch(
            "profiling.sampling.sample.SampleProfiler", return_value=profiler
        ) as profiler_type:
            self.assertIs(
                run_sampling(123, collector, sample_interval_usec=77),
                collector,
            )
        profiler_type.assert_called_once()
        self.assertEqual(profiler_type.call_args.args[:2], (123, 77))
        profiler.sample.assert_called_once_with(
            collector, None, async_aware=None
        )

    def test_child_external_propagation_and_defaults(self):
        args = SimpleNamespace(
            sample_interval_usec=1000, duration=None, all_threads=False,
            realtime_stats=False, native=False, gc=True, opcodes=False,
            async_aware=False, mode="wall", blocking=False,
            collector="pkg.mod:create",
            format="pstats", diff_baseline=None, outfile=None,
        )
        child_args = cli._build_child_profiler_args(args)
        self.assertIn("--collector", child_args)
        self.assertEqual(child_args[child_args.index("--collector") + 1],
                         "pkg.mod:create")
        self.assertIsNone(cli._build_output_pattern(args))

    def test_stack_trace_hook_receives_timestamps(self):
        self.assertTrue(issubclass(JsonTraceCollector, StackTraceCollector))
        collector = JsonTraceCollector(self.make_context())
        frames = [("example.py", (3, 3, -1, -1), "work", None)]
        collector.process_frames(frames, 7, weight=2, timestamps_us=[10, 20])
        self.assertEqual([r["timestamp_us"] for r in collector.records], [10, 20])

    def test_builtin_run_stats_remain_internal(self):
        collector = FlamegraphCollector(1000)
        _store_builtin_run_stats(
            collector, 1000, 1.5, 2.0, 0.0, 0.0, "wall"
        )
        self.assertEqual(collector.stats["sample_interval_usec"], 1000)
        self.assertEqual(collector.stats["mode"], "wall")


if __name__ == "__main__":
    unittest.main()
