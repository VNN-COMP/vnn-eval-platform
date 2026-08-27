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
    node_log_path = "logs/install.log" 

    def is_local_execution(self):
        from comp_eval_platform.core.models import RuntimeSettings
        try:
            return RuntimeSettings.get().execution_backend == "local_docker"
        except:
            ip = self.node_ip or ""
            return ip in ("127.0.0.1", "localhost") or ip.startswith(("172.", "10.", "192.168."))

    def execute(self):
        if self.is_local_execution():
            self.task.step_succeeded(check_status=False)
            return
            
        ip = self.node_ip
        if ip is None:
            self.task.step_failed(check_status=False)
            return
            
        tool = self.task.tool
        _ping("node", "install_tool.sh", {
            "benchmark_ip": ip,
            "task_id": str(self.task.id),
            "repository": tool.repository,
            "hash": tool.hash or "",
            "script_dir": tool.script_dir or ".",
            "run_as_root": str(self.step.run_as_root).lower(),
            "version": "v1",
            "tool_dir": "toolkit",
        })

    def retry_until_success(self) -> bool:
        return True 

    def on_marked_done(self):
        from comp_eval_platform.compute.shell import node_exec

        ip, tool = self.node_ip, self.task.tool
        if ip is None or tool is None:
            return
            
        base_dir = "/app" if self.is_local_execution() else "/home/ubuntu"
        sha = node_exec(ip, f"git -C {base_dir}/toolkit rev-parse HEAD 2>/dev/null").strip()
        if sha and sha != tool.hash:
            tool.hash = sha
            tool.save(update_fields=["hash"])


@register_step_handler
class PostInstallHandler(StepHandler):
    """Run the post-installation script on the node, after install_tool.sh."""
    kind = kinds.POST_INSTALL
    node_log_path = "logs/post_install.log"

    def execute(self):
        from comp_eval_platform.core.models import RuntimeSettings
        try:
            is_local = RuntimeSettings.get().execution_backend == "local_docker"
        except:
            ip = self.node_ip or ""
            is_local = ip in ("127.0.0.1", "localhost") or ip.startswith(("172.", "10.", "192.168."))

        if is_local:
            self.task.step_succeeded(check_status=False)
            return
            
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

    def is_local_execution(self):
        from comp_eval_platform.core.models import RuntimeSettings
        try:
            return RuntimeSettings.get().execution_backend == "local_docker"
        except:
            ip = self.node_ip or ""
            return ip in ("127.0.0.1", "localhost") or ip.startswith(("172.", "10.", "192.168."))

    def _benchmark(self):
        return _benchmark_of(self.step)

    @property
    def node_log_path(self):
        b = self._benchmark()
        return f"logs/run_{b.name}.log" if b else None

    def execute(self):
        from django.conf import settings

        if self.node_ip is None:
            self.task.step_failed(check_status=False)
            return
        b = self._benchmark()
        tool = self.task.tool
        params = {
            "benchmark_ip": self.node_ip,
            "task_id": str(self.task.id),
            "benchmark_name": b.name if b else "",
            "competition_year": settings.COMPETITION_YEAR,
            "script_dir": (tool.script_dir if tool else ".") or ".",
            "run_networks": self.step.payload.get("run_networks", "all"),
            "vnnlib_version": self.step.payload.get("version", "1.0"),
            "run_as_root": str(self.step.run_as_root).lower(),
        }
        params.update(_repo_params("benchmarks"))
        _ping("toolkit", "run_benchmark.sh", params)

    def while_active(self):
        super().while_active()
        b = self._benchmark()
        if b is not None:
            ip = self.node_ip
            base_dir = "/app" if self.is_local_execution() else "/home/ubuntu"
            self.refresh_run_progress(f"{base_dir}/logs/results_{b.name}.csv", b)
            
            if self.is_local_execution():
                import os
                log_path = f"{base_dir}/logs/run_{b.name}.log"
                if os.path.exists(log_path):
                    try:
                        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                            if "End — finished" in f.read():
                                self.task.step_succeeded(check_status=False)
                                return
                    except Exception:
                        pass
            # ------------------------------------
            
        from comp_eval_platform.core.models import RuntimeSettings

        s = RuntimeSettings.get()
        if not s.enforce_timeouts or self.step.started_at is None:
            return
        elapsed_h = (timezone.now() - self.step.started_at).total_seconds() / 3600.0
        if elapsed_h > s.benchmark_timeout:
            print(f"Benchmark {self.step} exceeded {s.benchmark_timeout}h cap; skipping.")
            self._kill_run()
            self.task.step_succeeded(check_status=False)

    def _kill_run(self):
        from comp_eval_platform.compute.shell import node_exec

        ip = self.node_ip
        if ip is None:
            return
            
        if self.is_local_execution():
            node_exec(ip, "pkill -f harness.py 2>/dev/null; true")
        else:
            node_exec(ip, "kill -- -$(cat /home/ubuntu/measurement.pgid) 2>/dev/null; "
                                  "tmux kill-session -t measurements 2>/dev/null; true")

    def can_abort_benchmark(self) -> bool:
        return True

    def abort_benchmark(self):
        self._kill_run()
        self.task.step_aborted()

    def collect_results_safely(self, path):
        if self.is_local_execution():
            import tempfile
            import shutil
            import os
            temp_dir = tempfile.mkdtemp()
            if os.path.exists(path):
                shutil.copy(path, temp_dir)
            return temp_dir
        return self.collect_results(path)

    def on_marked_done(self):
        import shutil
        from comp_eval_platform.competitions import get_competition
        from comp_eval_platform.core.models import Result

        b = self._benchmark()
        if b is None:
            return
            
        base_dir = "/app" if self.is_local_execution() else "/home/ubuntu"
        
        artifacts = self.collect_results_safely(f"{base_dir}/logs/results_{b.name}.csv")
        if artifacts is None:
            return
        try:
            records = get_competition().parse_results(self.task, artifacts)
            Result.store(self.task, self.task.tool, b, b.category, records,
                         instances_by_name=self._instances(b))
        finally:
            shutil.rmtree(artifacts, ignore_errors=True)

    def _instances(self, benchmark) -> dict:
        from django.conf import settings
        from comp_eval_platform.compute.shell import node_exec
        from comp_eval_platform.core.models import Instance
        from .instances import ensure_instances

        ip = self.node_ip
        if ip is not None:
            if self.is_local_execution():
                csv_text = node_exec(ip, "find /app -type f -name 'instances.csv' -exec cat {} + 2>/dev/null | head -n 1000")
            else:
                version = self.step.payload.get("version", "1.0")
                base_dir = f"/home/ubuntu/vnncomp{settings.COMPETITION_YEAR}_benchmarks"
                path = f"{base_dir}/benchmarks/{benchmark.name}/{version}/instances.csv"
                csv_text = node_exec(ip, f"cat {path} 2>/dev/null")
                
            if csv_text and csv_text.strip():
                return ensure_instances(benchmark, csv_text)
        return {i.name: i for i in Instance.objects.filter(benchmark=benchmark)}

@register_step_handler
class CheckResultsHandler(StepHandler):
    """Validate the benchmark's counterexamples with the official scorer.

    Kept out of the run step: the scorer's verdict tallies belong in their own log, and
    a scorer failure should not be mistaken for the tool failing.
    """

    kind = kinds.CHECK_RESULTS

    @property
    def node_log_path(self):
        b = _benchmark_of(self.step)
        return f"logs/check_{b.name}.log" if b else None

    def execute(self):
        from django.conf import settings

        from .export_layout import run_folder, slug

        if self.node_ip is None:
            self.task.step_succeeded(check_status=False)  # validation is best-effort
            return
        b = _benchmark_of(self.step)
        tool = self.task.tool
        _ping("toolkit", "check_results.sh", {
            "benchmark_ip": self.node_ip,
            "task_id": str(self.task.id),
            "benchmark_name": b.name if b else "",
            "run_folder": run_folder(b.name) if b else "",
            "tool_name": slug(tool.name) if tool else "tool",
            "scoring_repo": settings.SCORING_REPO,
            "scoring_ref": settings.SCORING_REF,
        })

    def on_marked_done(self):
        """Freeze the scorer's summary onto the step. Its log is already stored (the node
        POSTs it with the callback), and it is the only place that says whether each
        counterexample actually held up — but the scorer drops an all-unknown/all-timeout
        category, so the verdict tally is reconciled against the stored Result rows."""
        freeze_check_summary(self.step)

    def is_instance_loss_valid_end(self) -> bool:
        return True  # a lost node during validation shouldn't fail the whole task


def _benchmark_of(step):
    from comp_eval_platform.core.models import Benchmark

    return Benchmark.objects.filter(id=step.payload.get("benchmark_id")).first()


def compute_check_summary(step):
    """A validation step's reconciled ``(summary, severity)``: the scorer's report folded
    together with the authoritative per-instance Result rows (see scoring.reconcile_with_results).
    Pure — no save; ``(None, None)`` when the scorer produced no summary at all."""
    from comp_eval_platform.core.models import Result

    from .scoring import build_summary, count_verdicts

    benchmark = _benchmark_of(step)
    verdict_counts = None
    if benchmark is not None:
        verdict_counts = count_verdicts(
            Result.objects.filter(task=step.task, benchmark=benchmark).values_list("result", flat=True)
        )
    return build_summary(step.logs or "", verdict_counts)


def freeze_check_summary(step) -> bool:
    """Persist a validation step's reconciled summary + severity onto its payload. Reused by
    CheckResultsHandler.on_marked_done and the reconcile_summaries command (which re-freezes
    runs finished before the reconciliation existed). Returns whether a summary was stored —
    False when the scorer produced none, leaving the results.csv fallback."""
    summary, sev = compute_check_summary(step)
    if summary is None:
        return False
    step.payload = {**(step.payload or {}), "summary": summary, "severity": sev}
    step.save(update_fields=["payload"])
    return True


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
class GenerateSetupHandler(StepHandler):
    """Prepare the node for generation: clone the source repo @ hash and build the
    generator's virtualenv. Split from generation so the clone and the (often slow)
    dependency install show as their own live step."""

    kind = kinds.GENERATE_SETUP
    node_log_path = "logs/generate_setup.log"  # setup_benchmark.sh tees the run here

    def execute(self):
        if self.node_ip is None:
            self.task.step_failed(check_status=False)
            return
        _b, params = _generation_params(self.task, self.step)
        _ping("benchmark", "setup_benchmark.sh", params)

    def retry_until_success(self) -> bool:
        return True  # clone + pip are flaky over the network; retry rather than fail


@register_step_handler
class GenerateHandler(StepHandler):
    """Run the benchmark's generator on the node: generate_properties.py <seed>, then
    normalize into instances.csv + onnx/vnnlib. The repo and generator venv are already
    in place from the setup step. The node curls back on completion."""

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
class ConvertHandler(StepHandler):
    """Best-effort VNNLIB 1.0 -> 2.0 conversion on the node (only for 1.0 submissions).
    Its own step so the conversion's Python 3.12 venv + pip installs show a live log
    instead of a silent stretch inside generation. A failed conversion is not fatal:
    convert_vnnlib.sh always reports success, so the benchmark still exports its 1.0
    files."""

    kind = kinds.CONVERT
    node_log_path = "logs/convert.log"  # convert_vnnlib.sh tees the run here

    def execute(self):
        if self.node_ip is None:
            self.task.step_succeeded(check_status=False)  # conversion is best-effort
            return
        _b, params = _generation_params(self.task, self.step)
        _ping("benchmark", "convert_vnnlib.sh", params)

    def is_instance_loss_valid_end(self) -> bool:
        return True  # a lost node during conversion shouldn't fail the task


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
        from .export_layout import run_folder, slug

        b = _benchmark_of(self.step)
        tool = self.task.tool
        params = {
            "benchmark_ip": self.node_ip,
            "task_id": str(self.task.id),
            "benchmark_name": b.name if b else "",
            "run_folder": run_folder(b.name) if b else "",
            "tool_name": slug(tool.name) if tool else "tool",
        }
        params.update(_repo_params("results"))
        _ping("toolkit", "export_results.sh", params)

    def is_instance_loss_valid_end(self) -> bool:
        return True  # a lost node during export shouldn't fail the whole task
