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
    node_log_path = "logs/install.log"  # install_tool.sh tees the run here

    def execute(self):
        ip = self.node_ip
        if ip is None:
            self.task.step_failed(check_status=False)
            return
        tool = self.task.tool
        _ping("toolkit", "install_tool.sh", {
            "benchmark_ip": ip,
            "task_id": str(self.task.id),
            "repository": tool.repository,
            "hash": tool.hash or "",
            "script_dir": tool.script_dir or ".",
            "run_as_root": str(self.step.run_as_root).lower(),
        })

    def retry_until_success(self) -> bool:
        return True  # installs are flaky (network); retry rather than fail the task

    def on_marked_done(self):
        """Record the exact installed commit so a tool submitted as 'latest' is
        reproducible. Assumes install_tool.sh clones the tool repo to
        /home/ubuntu/toolkit; best-effort (no-op if unavailable)."""
        from comp_eval_platform.compute.shell import node_exec

        ip, tool = self.node_ip, self.task.tool
        if ip is None or tool is None:
            return
        sha = node_exec(ip, "git -C /home/ubuntu/toolkit rev-parse HEAD").strip()
        if sha and sha != tool.hash:
            tool.hash = sha
            tool.save(update_fields=["hash"])


@register_step_handler
class PostInstallHandler(StepHandler):
    """Run the post-installation script on the node, after install_tool.sh.

    The submitter's own script (``post_install_tool`` in Tool.extra, typed into the
    submission form) wins over whatever the repo ships under script_dir, matching what
    the field is for: activating a licence on the machine the tool was just built on.
    A submission with neither is a no-op, not a failure.
    """

    kind = kinds.POST_INSTALL
    node_log_path = "logs/post_install.log"

    def execute(self):
        ip = self.node_ip
        if ip is None:
            self.task.step_failed(check_status=False)
            return
        tool = self.task.tool
        _ping("toolkit", "post_install_tool.sh", {
            "benchmark_ip": ip,
            "task_id": str(self.task.id),
            "script_dir": (tool.script_dir if tool else ".") or ".",
            "post_install_tool": ((tool.extra or {}).get("post_install_tool") or "") if tool else "",
            "run_as_root": str(self.step.run_as_root).lower(),
        })


@register_step_handler
class RunBenchmarkHandler(StepHandler):
    """Run one benchmark (the node loops its instances via run_all/run_single)."""

    kind = kinds.RUN_BENCHMARK

    def _benchmark(self):
        return _benchmark_of(self.step)

    @property
    def node_log_path(self):
        """run_instances.sh tees each benchmark's run to its own log."""
        b = self._benchmark()
        return f"logs/run_{b.name}.log" if b else None

    def execute(self):
        if self.node_ip is None:
            self.task.step_failed(check_status=False)
            return
        b = self._benchmark()
        tool = self.task.tool
        params = {
            "benchmark_ip": self.node_ip,
            "task_id": str(self.task.id),
            "benchmark_name": b.name if b else "",
            "script_dir": (tool.script_dir if tool else ".") or ".",
            "run_networks": self.step.payload.get("run_networks", "all"),
            "vnnlib_version": self.step.payload.get("version", "1.0"),
            "run_as_root": str(self.step.run_as_root).lower(),
        }
        params.update(_repo_params("benchmarks"))  # the run script copies the tree to the node
        _ping("toolkit", "run_benchmark.sh", params)

    def while_active(self):
        """Stream the node log, then enforce the per-benchmark wall-clock cap."""
        super().while_active()
        from comp_eval_platform.core.models import RuntimeSettings

        s = RuntimeSettings.get()
        if not s.enforce_timeouts or self.step.started_at is None:
            return
        elapsed_h = (timezone.now() - self.step.started_at).total_seconds() / 3600.0
        if elapsed_h > s.benchmark_timeout:
            # Time out just this benchmark and continue with the rest of the task.
            print(f"Benchmark {self.step} exceeded {s.benchmark_timeout}h cap; skipping.")
            self._kill_run()
            self.task.step_succeeded(check_status=False)

    def _kill_run(self):
        """Stop the node-side run, or it would keep the CPU busy while the next
        benchmark runs. run_instances.sh records its process group for this."""
        from comp_eval_platform.compute.shell import node_exec

        if self.node_ip is None:
            return
        node_exec(self.node_ip, "kill -- -$(cat /home/ubuntu/measurement.pgid) 2>/dev/null; "
                                "tmux kill-session -t measurements 2>/dev/null; true")

    def can_abort_benchmark(self) -> bool:
        return True

    def abort_benchmark(self):
        self._kill_run()
        self.task.step_succeeded(check_status=False)

    def on_marked_done(self):
        """Fetch the node's results.csv, parse and persist normalized Result rows."""
        import shutil

        from comp_eval_platform.competitions import get_competition
        from comp_eval_platform.core.models import Result

        b = self._benchmark()
        if b is None:
            return
        artifacts = self._fetch_artifacts()
        if artifacts is None:
            return
        try:
            records = get_competition().parse_results(self.task, artifacts)
            Result.store(self.task, self.task.tool, b, b.category, records,
                         instances_by_name=self._instances(b))
        finally:
            shutil.rmtree(artifacts, ignore_errors=True)

    def _instances(self, benchmark) -> dict:
        """This benchmark's cases, keyed by name, so results link to their Instance row.
        Recorded from the copy that actually ran, which also backfills a benchmark
        generated before instances were recorded at all."""
        from comp_eval_platform.compute.shell import node_exec
        from comp_eval_platform.core.models import Instance

        from .instances import ensure_instances

        if self.node_ip is not None:
            csv_text = node_exec(
                self.node_ip, f"cat /home/ubuntu/benchmarks/{benchmark.name}/instances.csv 2>/dev/null")
            if csv_text.strip():
                return ensure_instances(benchmark, csv_text)
        return {i.name: i for i in Instance.objects.filter(benchmark=benchmark)}

    def _fetch_artifacts(self):
        """Pull the run's results.csv off the node into a temp dir for parse_results.
        Read here because the node is torn down before the task ends. Returns the dir,
        or None when the run produced nothing."""
        import os
        import tempfile

        from comp_eval_platform.compute.shell import node_exec

        b = self._benchmark()
        if self.node_ip is None or b is None:
            return None
        csv_text = node_exec(self.node_ip, f"cat /home/ubuntu/logs/results_{b.name}.csv 2>/dev/null")
        if not csv_text.strip():
            return None
        # Keep the node's file verbatim: the submission page shows it as-is, and the
        # node it lives on is torn down at the end of the task.
        self.step.payload = {**(self.step.payload or {}), "results_csv": csv_text}
        self.step.save(update_fields=["payload"])
        d = tempfile.mkdtemp(prefix=f"results_{self.task.id}_")
        with open(os.path.join(d, "results.csv"), "w") as fh:
            fh.write(csv_text)
        return d


def _benchmark_of(step):
    from comp_eval_platform.core.models import Benchmark

    return Benchmark.objects.filter(id=step.payload.get("benchmark_id")).first()


def _repo_params(kind: str) -> dict:
    """Where a script reads/writes the ``benchmarks``/``results`` repo: the configured
    remote, else a persistent local repo under LOCAL_REPOS_DIR (local dev needs no
    external setup). Deploy keys stay on the host, never copied to a node."""
    import os

    from django.conf import settings

    remote = {"benchmarks": settings.BENCHMARKS_PUSH_REPO,
              "results": settings.RESULTS_PUSH_REPO}[kind]
    key = {"benchmarks": settings.BENCHMARKS_DEPLOY_KEY,
           "results": settings.RESULTS_DEPLOY_KEY}[kind]
    return {
        f"{kind}_repo": remote,
        "deploy_key": key if remote else "",
        "local_repo": os.path.join(settings.LOCAL_REPOS_DIR, kind),
    }


def _generation_params(task, step):
    """Params shared by the generate/export node scripts: source repo, layout, seed."""
    from django.conf import settings

    b = _benchmark_of(step)
    opts = (b.extra if b else {}) or {}
    return b, {
        "benchmark_ip": task.node.ip if task.node else None,
        "task_id": str(task.id),
        "benchmark_id": str(b.id) if b else "",
        "benchmark_name": b.name if b else "",
        "repository": opts.get("repository", ""),
        "hash": opts.get("hash", ""),
        "script_dir": opts.get("script_dir", ".") or ".",
        "onnx_dir": opts.get("onnx_dir", "onnx"),
        "vnnlib_dir": opts.get("vnnlib_dir", "vnnlib"),
        "csv_file": opts.get("csv_file", "instances.csv"),
        "vnnlib_version": step.payload.get("version", "1.0"),
        "seed": str(settings.BENCHMARK_SEED),
    }


@register_step_handler
class GenerateHandler(StepHandler):
    """Generate a benchmark on the node: clone the source repo @ hash, run its
    generator (generate_properties.py <seed>) and normalize into instances.csv +
    onnx/vnnlib. The node curls back on completion."""

    kind = kinds.GENERATE
    node_log_path = "logs/generate.log"  # generate_benchmark.sh tees the run here

    def execute(self):
        if self.node_ip is None:
            self.task.step_failed(check_status=False)
            return
        _b, params = _generation_params(self.task, self.step)
        _ping("benchmark", "generate_benchmark.sh", params)

    def on_marked_done(self):
        """Record the exact commit that was generated, so a benchmark submitted as
        'latest' (no hash) is reproducible, and the cases it generated. The node is
        still up (export runs next)."""
        from comp_eval_platform.compute.shell import node_exec

        from .instances import ensure_instances

        ip, b = self.node_ip, _benchmark_of(self.step)
        if ip is None or b is None:
            return
        sha = node_exec(ip, "git -C /home/ubuntu/benchmark rev-parse HEAD").strip()
        if sha:
            b.extra = {**(b.extra or {}), "hash": sha}
            b.save(update_fields=["extra"])
        script_dir = (b.extra or {}).get("script_dir", ".") or "."
        csv_file = (b.extra or {}).get("csv_file", "instances.csv")
        csv_text = node_exec(ip, f"cat /home/ubuntu/benchmark/{script_dir}/{csv_file} 2>/dev/null")
        if csv_text.strip():
            ensure_instances(b, csv_text)


@register_step_handler
class BenchmarkExportHandler(StepHandler):
    """Push the generated files + a source README to the benchmarks git repo, under
    a ``<category>/`` folder when the variant uses categories (VNN: flat)."""

    kind = kinds.BENCHMARK_EXPORT

    def execute(self):
        from comp_eval_platform.competitions import get_competition

        if self.node_ip is None:
            self.task.step_succeeded(check_status=False)  # export is best-effort
            return
        b, params = _generation_params(self.task, self.step)
        params.update({
            "category": b.category.name if b else "",
            "uses_categories": str(get_competition().uses_categories).lower(),
        })
        params.update(_repo_params("benchmarks"))
        _ping("benchmark", "export_benchmark.sh", params)

    def on_marked_done(self):
        """Auto-publish once the benchmark is generated, exported, and validates —
        a successful run is the publish gate; there is no manual publish step."""
        from comp_eval_platform.competitions import get_competition

        b = _benchmark_of(self.step)
        if b is None or b.published:
            return
        try:
            get_competition().validate_submission(b)
        except Exception as exc:
            print(f"benchmark {b} left unpublished (validation failed): {exc}")
            return
        b.published = True
        b.save(update_fields=["published"])

    def is_instance_loss_valid_end(self) -> bool:
        return True  # a lost node during export shouldn't fail the whole task


@register_step_handler
class ExportHandler(StepHandler):
    """Push one benchmark run's results.csv + counterexamples to the results repo."""

    kind = kinds.EXPORT

    def execute(self):
        if self.node_ip is None:
            self.task.step_succeeded(check_status=False)  # export is best-effort
            return
        from .export_layout import slug

        b = _benchmark_of(self.step)
        tool = self.task.tool
        params = {
            "benchmark_ip": self.node_ip,
            "task_id": str(self.task.id),
            "benchmark_name": b.name if b else "",
            "tool_name": slug(tool.name) if tool else "tool",
        }
        params.update(_repo_params("results"))
        _ping("toolkit", "export_results.sh", params)

    def is_instance_loss_valid_end(self) -> bool:
        return True  # a lost node during export shouldn't fail the whole task
