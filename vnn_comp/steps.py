"""VNN-COMP step handlers.

Each ``execute`` fires a node script (fire-and-forget); the node runs it and
curls back to ``/update/<task_id>/success|failure``, which advances the task.
The per-benchmark run additionally enforces a wall-clock cap in ``while_active``
and parses+persists results in ``on_marked_done`` (so the log-free overview can
read the scored outcome back). Ported from VNN's ToolkitInstall/ToolkitRun/etc.
"""
from django.utils import timezone

from comp_eval_platform.compute.shell import _ping
from comp_eval_platform.core.steps import StepHandler, register_step_handler

from . import kinds


def _node_ip(task):
    node = task.node
    return node.ip if node is not None else None


@register_step_handler
class CreateHandler(StepHandler):
    """Prepare the submission record; nothing to run on a node yet."""

    kind = kinds.CREATE

    def execute(self):
        self.task.step_succeeded(check_status=False)

    def status_check(self):
        return  # no node needed yet


@register_step_handler
class InstallHandler(StepHandler):
    kind = kinds.INSTALL

    def execute(self):
        ip = _node_ip(self.task)
        if ip is None:
            self.task.step_failed(check_status=False)
            return
        _ping("toolkit", "install_tool.sh", {
            "benchmark_ip": ip,
            "task_id": str(self.task.id),
            "repository": self.task.tool.repository,
            "run_as_root": str(self.step.run_as_root).lower(),
        })

    def retry_until_success(self) -> bool:
        return True  # installs are flaky (network); retry rather than fail the task


@register_step_handler
class PauseHandler(StepHandler):
    """Hold until an operator resumes (manual step). Stays active indefinitely."""

    kind = kinds.PAUSE

    def status_check(self):
        return  # do not advance automatically

    def can_be_aborted(self) -> bool:
        return True


@register_step_handler
class RunBenchmarkHandler(StepHandler):
    """Run one benchmark (the node loops its instances via run_all/run_single)."""

    kind = kinds.RUN_BENCHMARK

    def _benchmark(self):
        from comp_eval_platform.core.models import Benchmark

        bid = self.step.payload.get("benchmark_id")
        return Benchmark.objects.filter(id=bid).first()

    def execute(self):
        ip = _node_ip(self.task)
        if ip is None:
            self.task.step_failed(check_status=False)
            return
        b = self._benchmark()
        _ping("toolkit", "run_benchmark.sh", {
            "benchmark_ip": ip,
            "task_id": str(self.task.id),
            "benchmark_name": b.name if b else "",
            "run_networks": self.step.payload.get("run_networks", "all"),
            "vnnlib_version": self.step.payload.get("version", "1.0"),
            "run_as_root": str(self.step.run_as_root).lower(),
        })

    def while_active(self):
        """Enforce the per-benchmark wall-clock cap (safety net for hangs)."""
        from comp_eval_platform.core.models import RuntimeSettings

        s = RuntimeSettings.get()
        if not s.enforce_timeouts or self.step.started_at is None:
            return
        elapsed_h = (timezone.now() - self.step.started_at).total_seconds() / 3600.0
        if elapsed_h > s.benchmark_timeout:
            # Time out just this benchmark and continue with the rest of the task.
            print(f"Benchmark {self.step} exceeded {s.benchmark_timeout}h cap; skipping.")
            self.task.step_succeeded(check_status=False)

    def can_abort_benchmark(self) -> bool:
        return True

    def abort_benchmark(self):
        self.task.step_succeeded(check_status=False)

    def on_marked_done(self):
        """Fetch the node's results.csv, parse and persist normalized Result rows."""
        from comp_eval_platform.competitions import get_competition
        from comp_eval_platform.core.models import Instance, Result

        b = self._benchmark()
        if b is None:
            return
        artifacts = self._fetch_artifacts()
        if artifacts is None:
            return
        records = get_competition().parse_results(self.task, artifacts)
        instances = {i.name: i for i in Instance.objects.filter(benchmark=b)}
        Result.store(self.task, self.task.tool, b, b.category, records, instances_by_name=instances)

    def _fetch_artifacts(self):
        """Where the node's results.csv was collected for this benchmark. Wired to
        the log/artifact collection path; returns a dir or None."""
        # Placeholder for the artifact-collection integration (SCP from node);
        # returns None until wired, so scoring simply has no rows yet.
        return None


@register_step_handler
class ExportHandler(StepHandler):
    kind = kinds.EXPORT

    def execute(self):
        ip = _node_ip(self.task)
        if ip is None:
            self.task.step_succeeded(check_status=False)  # export is best-effort
            return
        _ping("toolkit", "export_results.sh", {
            "benchmark_ip": ip,
            "task_id": str(self.task.id),
            "benchmark_id": self.step.payload.get("benchmark_id", ""),
        })

    def is_instance_loss_valid_end(self) -> bool:
        return True  # a lost node during export shouldn't fail the whole task
