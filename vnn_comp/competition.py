"""The VNN-COMP variant: the six Competition seams.

Structured rung of the decomposition ladder: install-once → per-benchmark run
(each run loops its instances on the node) → export → shutdown. A single implicit
``default`` category. Competition-specific submission options live in Tool.extra.
"""
import csv
import os

from django.core.exceptions import ValidationError

from comp_eval_platform.competitions import Competition
from comp_eval_platform.core.models.execution import PAUSE_KIND, SHUTDOWN_KIND
from comp_eval_platform.results import Branding, Landing, Presentation, ResultRecord, Scoreboard

from . import kinds


class VNNCompetition(Competition):
    name = "vnn"
    display_name = "VNN-COMP"
    uses_categories = False  # a single implicit 'default' category

    # (1) Submission spec + validation ------------------------------------
    def validate_submission(self, submission) -> None:
        from comp_eval_platform.core.models import Tool

        if isinstance(submission, Tool):
            if not submission.repository:
                raise ValidationError("A VNN-COMP tool must provide a git repository.")
        else:  # Benchmark: generated from a git repo and stored in the benchmarks
            # repo (instances live there, not in the DB), so just require the source.
            if not (submission.extra or {}).get("repository"):
                raise ValidationError("A VNN-COMP benchmark must provide a git repository "
                                      "with a generator (generate_properties.py).")

    # (2) Step-graph builder ----------------------------------------------
    def build_steps(self, task) -> list:
        from comp_eval_platform.core.models import Benchmark, TaskStep

        order = 0

        def add(kind, *, run_as_root=True, **payload):
            nonlocal order
            step = TaskStep.objects.create(
                task=task, kind=kind, order=order, run_as_root=run_as_root, payload=payload,
            )
            order += 1
            return step

        steps = []
        if task.tool is not None:
            tool = task.tool
            opts = tool.extra or {}
            version = opts.get("vnnlib_version", "1.0")
            run_networks = opts.get("run_networks", "all")
            export = bool(opts.get("export_results", False))

            steps += [
                add(kinds.CREATE),
                add("assign"),
                add(kinds.INSTALL, run_as_root=opts.get("install_as_root", True)),
            ]
            # A hold here lets the submitter finish the install by hand before the
            # post-install script runs; `manual_installation_step` is the pre-port key.
            if opts.get("pause") or opts.get("manual_installation_step"):
                steps.append(add(PAUSE_KIND))
            # Always present: it is the tool's own hook, and a submission that has no
            # script is a no-op rather than a skipped step.
            steps.append(add(kinds.POST_INSTALL, run_as_root=opts.get(
                "post_install_as_root", opts.get("run_post_installation_script_as_root", True))))
            if opts.get("pause_after_postinstallation"):
                steps.append(add(PAUSE_KIND))
            # Per-benchmark runs. If the submission selected specific benchmarks
            # (from the form), run exactly those; otherwise the whole category.
            selected = opts.get("benchmarks") or []
            if selected:
                benchmarks = Benchmark.objects.filter(id__in=selected, published=True).order_by("name")
            else:
                benchmarks = Benchmark.objects.filter(category=tool.category, published=True).order_by("name")
            for b in benchmarks:
                steps.append(add(kinds.RUN_BENCHMARK, benchmark_id=str(b.id),
                                 run_networks=run_networks, version=version,
                                 run_as_root=opts.get("run_as_root", True)))
                if export:
                    steps.append(add(kinds.EXPORT, benchmark_id=str(b.id), version=version))
            steps.append(add(SHUTDOWN_KIND))
        else:  # benchmark submission: generate instances from the repo, then export them
            bench = task.benchmark
            opts = bench.extra or {}
            steps += [
                add(kinds.CREATE),
                add("assign"),
                add(kinds.GENERATE, benchmark_id=str(bench.id),
                    version=opts.get("vnnlib_version", "1.0")),
                add(kinds.BENCHMARK_EXPORT, benchmark_id=str(bench.id),
                    version=opts.get("vnnlib_version", "1.0")),
                add(SHUTDOWN_KIND),
            ]
        return steps

    # (3) Node scripts + I/O contract -------------------------------------
    def script_root(self) -> str:
        return os.path.join(os.path.dirname(__file__), "scripts")

    def assets_dir(self) -> str:
        return os.path.join(os.path.dirname(__file__), "assets")

    # (4) Result parsing → normalized records -----------------------------
    def parse_results(self, run, artifacts_dir: str) -> list:
        """Read the node's ``results.csv`` into records.

        Official harness layout: ``category,onnx,vnnlib,prepare_time,result,runtime``.
        Rows carry the case's two paths rather than a name, so the name is derived
        here, the same way the benchmark's Instance rows were named."""
        from .instances import instance_name

        def number(value):
            try:
                return float(value)
            except ValueError:
                return None

        path = os.path.join(artifacts_dir, "results.csv")
        records = []
        if not os.path.exists(path):
            return records
        with open(path, newline="") as fh:
            for row in csv.reader(fh):
                if len(row) < 6:
                    continue
                _category, onnx, vnnlib, prepare_time, result, runtime = (c.strip() for c in row[:6])
                records.append(ResultRecord(
                    instance=instance_name(onnx, vnnlib),
                    result=result,
                    time=number(runtime),
                    extra={"prepare_time": number(prepare_time)},
                ))
        return records

    # (5) Scoring ---------------------------------------------------------
    def score(self, track) -> Scoreboard:
        from collections import defaultdict

        from comp_eval_platform.core.models import Result

        benchmark_ids = track.benchmarks.values_list("id", flat=True)
        rows = defaultdict(lambda: {"solved": 0, "time": 0.0})
        for r in Result.objects.filter(benchmark_id__in=benchmark_ids).select_related("tool"):
            key = r.tool.name
            rows[key]["tool"] = key
            if r.result and r.result.lower() not in ("unknown", "error", "timeout"):
                rows[key]["solved"] += 1
            rows[key]["time"] += r.time or 0.0
        return Scoreboard(
            columns=["tool", "solved", "time"],
            rows=sorted(rows.values(), key=lambda x: (-x["solved"], x["time"])),
        )

    def exported_artifacts_dir(self, step) -> str:
        """One run's exported folder (results.csv + counterexamples). Only the export
        step has one, so only it offers a download — a run submitted without
        export_results never pushed its artifacts anywhere."""
        from comp_eval_platform.core.models import Benchmark

        from .export_layout import results_dir

        if step.kind != kinds.EXPORT:
            return None
        bench = Benchmark.objects.filter(id=step.payload.get("benchmark_id")).first()
        tool = step.task.tool
        if bench is None or tool is None:
            return None
        return results_dir(tool.name, bench.name)

    # (6) Presentation / export -------------------------------------------
    def presentation(self) -> Presentation:
        return Presentation(
            result_columns=["instance", "result", "time"],
            submission_fields=[
                {"name": "vnnlib_version", "type": "select", "options": ["1.0", "2.0"]},
                {"name": "run_networks", "type": "select", "options": ["all", "some"]},
                {"name": "install_as_root", "type": "bool"},
                {"name": "export_results", "type": "bool"},
            ],
            benchmark_fields=[
                {"name": "vnnlib_version", "type": "select", "options": ["1.0", "2.0"]},
            ],
            score_columns=["tool", "solved", "time"],
            branding=Branding(
                primary_color="#1e3a8a",  # deep blue, matching the VNN-COMP logo
                hero_image="https://miro.medium.com/max/1400/1*zlt_wRZCGofSbmSqduds9w.png",
                favicon="/api/competition/assets/favicon.png",
            ),
            landing=Landing(
                tagline="The premier competition for neural network verification. Test your "
                        "toolkit against cutting-edge benchmarks and compete with researchers worldwide.",
                links=[
                    {"label": "Main Website", "url": "https://vnn-comp.github.io/"},
                    {"label": "GitHub", "url": "https://github.com/VNN-COMP"},
                ],
                contacts=["kaulen@aim.rwth-aachen.de", "tobias.ladner@tum.de"],
                related={
                    "text": "Interested in verifying neural network control systems? Check out ARCH-COMP!",
                    "label": "Visit ARCH-COMP",
                    "url": "https://arch.repeatability.cps.cit.tum.de",
                },
            ),
        )
