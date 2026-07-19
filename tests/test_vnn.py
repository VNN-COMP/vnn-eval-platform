"""VNN-COMP plugin: the six seams, validated against core with ACTIVE_COMPETITION=vnn."""
import uuid

import pytest

pytestmark = pytest.mark.django_db


def _user():
    from comp_eval_platform.core.models import User

    return User.objects.create_user(email=f"{uuid.uuid4().hex[:8]}@x.test", password="pw", enabled=True)


def test_active_competition_is_vnn():
    from comp_eval_platform.competitions import get_competition

    assert get_competition().name == "vnn"


def test_validate_tool_requires_repository():
    from django.core.exceptions import ValidationError

    from comp_eval_platform.competitions import get_competition
    from comp_eval_platform.core.models import Category, Tool

    comp = get_competition()
    cat = Category.objects.create(name="default")
    bad = Tool.objects.create(owner=_user(), category=cat, name="t", repository="")
    with pytest.raises(ValidationError):
        comp.validate_submission(bad)
    ok = Tool.objects.create(owner=_user(), category=cat, name="t2", repository="https://x/y")
    comp.validate_submission(ok)  # no raise


def test_validate_benchmark_requires_repository():
    from django.core.exceptions import ValidationError

    from comp_eval_platform.competitions import get_competition
    from comp_eval_platform.core.models import Benchmark, Category

    comp = get_competition()
    cat = Category.objects.create(name="default")
    b = Benchmark.objects.create(owner=_user(), category=cat, name="b")
    with pytest.raises(ValidationError):
        comp.validate_submission(b)  # no source repo
    b.extra = {"repository": "https://example.com/repo.git"}
    comp.validate_submission(b)  # no raise


def test_benchmark_auto_publishes_when_export_done():
    from comp_eval_platform.competitions import get_competition
    from comp_eval_platform.core.models import Benchmark, Category, Task

    from vnn_comp import kinds

    cat = Category.objects.create(name="default")
    b = Benchmark.objects.create(owner=_user(), category=cat, name="autopub",
                                 extra={"repository": "https://example.com/repo.git"})
    assert b.published is False
    task = Task.objects.create(owner=b.owner, benchmark=b)
    get_competition().build_steps(task)
    # Completing the export step publishes the benchmark (no manual publish step).
    task.step_set.get(kind=kinds.BENCHMARK_EXPORT).handler.on_marked_done()
    b.refresh_from_db()
    assert b.published is True


def test_generate_records_resolved_commit(monkeypatch):
    from comp_eval_platform.competitions import get_competition
    from comp_eval_platform.core.models import Benchmark, Category, Node, Task

    from vnn_comp import kinds

    cat = Category.objects.create(name="default")
    b = Benchmark.objects.create(owner=_user(), category=cat, name="rev",
                                 extra={"repository": "https://example.com/repo.git"})  # no hash
    task = Task.objects.create(owner=b.owner, benchmark=b)
    get_competition().build_steps(task)
    Node.objects.create(id="n1", node_type="local", state="running",
                        reachability="ok", ip="1.2.3.4", task=task)
    monkeypatch.setattr("comp_eval_platform.compute.shell.node_exec",
                        lambda ip, cmd, **kw: "deadbeefcafe\n")
    task.step_set.get(kind=kinds.GENERATE).handler.on_marked_done()
    b.refresh_from_db()
    assert b.extra["hash"] == "deadbeefcafe"


def test_toolkit_records_resolved_commit(monkeypatch):
    from comp_eval_platform.competitions import get_competition
    from comp_eval_platform.core.models import Category, Node, Task, Tool

    from vnn_comp import kinds

    cat = Category.objects.create(name="default")
    tool = Tool.objects.create(owner=_user(), category=cat, name="t", repository="https://x/y", hash="")
    task = Task.objects.create(owner=tool.owner, tool=tool)
    get_competition().build_steps(task)
    Node.objects.create(id="n2", node_type="local", state="running",
                        reachability="ok", ip="1.2.3.4", task=task)
    monkeypatch.setattr("comp_eval_platform.compute.shell.node_exec",
                        lambda ip, cmd, **kw: "feedface1234\n")
    task.step_set.get(kind=kinds.INSTALL).handler.on_marked_done()
    tool.refresh_from_db()
    assert tool.hash == "feedface1234"


def test_build_steps_basic_graph():
    from comp_eval_platform.competitions import get_competition
    from comp_eval_platform.core.models import Benchmark, Category, Task, Tool

    from vnn_comp import kinds

    cat = Category.objects.create(name="default")
    tool = Tool.objects.create(owner=_user(), category=cat, name="t", repository="r")
    Benchmark.objects.create(owner=_user(), category=cat, name="b1", published=True)
    Benchmark.objects.create(owner=_user(), category=cat, name="b2", published=True)
    Benchmark.objects.create(owner=_user(), category=cat, name="unpub", published=False)

    task = Task.objects.create(owner=tool.owner, tool=tool)
    get_competition().build_steps(task)

    kinds_in_order = list(task.step_set.order_by("order").values_list("kind", flat=True))
    assert kinds_in_order == [
        kinds.CREATE, "assign", kinds.INSTALL, kinds.POST_INSTALL,
        # only the two published benchmarks, each validated after it runs
        kinds.RUN_BENCHMARK, kinds.CHECK_RESULTS, kinds.RUN_BENCHMARK, kinds.CHECK_RESULTS,
        "shutdown",
    ]


def test_build_steps_with_pause_and_export():
    from comp_eval_platform.competitions import get_competition
    from comp_eval_platform.core.models import Benchmark, Category, Task, Tool

    from vnn_comp import kinds

    cat = Category.objects.create(name="default")
    tool = Tool.objects.create(owner=_user(), category=cat, name="t", repository="r",
                               extra={"pause": True, "export_results": True})
    Benchmark.objects.create(owner=_user(), category=cat, name="b1", published=True)

    task = Task.objects.create(owner=tool.owner, tool=tool)
    get_competition().build_steps(task)

    assert list(task.step_set.order_by("order").values_list("kind", flat=True)) == [
        kinds.CREATE, "assign", kinds.INSTALL, "pause", kinds.POST_INSTALL,
        kinds.RUN_BENCHMARK, kinds.CHECK_RESULTS, kinds.EXPORT,
        "shutdown",
    ]


def test_build_steps_pause_after_post_install():
    """The pre-port option names still arrive on imported tools."""
    from comp_eval_platform.competitions import get_competition
    from comp_eval_platform.core.models import Benchmark, Category, Task, Tool

    from vnn_comp import kinds

    cat = Category.objects.create(name="default")
    tool = Tool.objects.create(owner=_user(), category=cat, name="t", repository="r",
                               extra={"manual_installation_step": True,
                                      "pause_after_postinstallation": True})
    Benchmark.objects.create(owner=_user(), category=cat, name="b1", published=True)

    task = Task.objects.create(owner=tool.owner, tool=tool)
    get_competition().build_steps(task)

    assert list(task.step_set.order_by("order").values_list("kind", flat=True)) == [
        kinds.CREATE, "assign", kinds.INSTALL, "pause", kinds.POST_INSTALL, "pause",
        kinds.RUN_BENCHMARK, kinds.CHECK_RESULTS,
        "shutdown",
    ]


def test_root_flags_come_from_the_submission_form():
    """The form's key names, verbatim. Reading a name the form never sends silently
    falls back to the default on every submission, which is how the install once ran
    as root against the submitter's wishes."""
    from comp_eval_platform.competitions import get_competition
    from comp_eval_platform.core.models import Benchmark, Category, Task, Tool

    from vnn_comp import kinds

    cat = Category.objects.create(name="default")
    tool = Tool.objects.create(owner=_user(), category=cat, name="t", repository="r",
                               extra={"run_installation_script_as_root": True,
                                      "run_post_installation_script_as_root": False,
                                      "run_toolkit_as_root": True})
    Benchmark.objects.create(owner=_user(), category=cat, name="b1", published=True)

    task = Task.objects.create(owner=tool.owner, tool=tool)
    get_competition().build_steps(task)
    as_root = dict(task.step_set.values_list("kind", "run_as_root"))

    assert as_root[kinds.INSTALL] is True
    assert as_root[kinds.POST_INSTALL] is False
    assert as_root[kinds.RUN_BENCHMARK] is True
    assert as_root[kinds.CHECK_RESULTS] is False  # the scorer is never privileged


def test_root_flags_default_off():
    """A tool that asked for nothing gets nothing: root leaves root-owned files in ~
    that the unprivileged scoring step then cannot write."""
    from comp_eval_platform.competitions import get_competition
    from comp_eval_platform.core.models import Benchmark, Category, Task, Tool

    from vnn_comp import kinds

    cat = Category.objects.create(name="default")
    tool = Tool.objects.create(owner=_user(), category=cat, name="t", repository="r")
    Benchmark.objects.create(owner=_user(), category=cat, name="b1", published=True)

    task = Task.objects.create(owner=tool.owner, tool=tool)
    get_competition().build_steps(task)
    as_root = dict(task.step_set.values_list("kind", "run_as_root"))

    assert not any(as_root[k] for k in
                   (kinds.INSTALL, kinds.POST_INSTALL, kinds.RUN_BENCHMARK, kinds.CHECK_RESULTS))


def test_parse_results_reads_the_official_csv_layout(tmp_path):
    """category,onnx,vnnlib,prepare_time,result,runtime — what the scorer also reads.
    The name is derived backend-side from the two paths."""
    from comp_eval_platform.competitions import get_competition

    (tmp_path / "results.csv").write_text(
        "acasxu,onnx/net_a.onnx,vnnlib/prop_1.vnnlib,0.30,sat,1.5\n"
        "acasxu,onnx/net_b.onnx,vnnlib/prop_1.vnnlib,0.25,run_instance_timeout,116.0\n"
        "bad_row\n"
    )
    records = get_competition().parse_results(None, str(tmp_path))
    assert [(r.instance, r.result, r.time) for r in records] == [
        ("net_a/prop_1", "sat", 1.5),
        ("net_b/prop_1", "run_instance_timeout", 116.0),
    ]
    assert records[0].extra == {"prepare_time": 0.30}


def test_guides_link_the_github_skeleton_repos():
    """The guides point submitters at the example repos on GitHub. A dead or wrong link
    would leave the info page pointing nowhere and nothing else would notice, the copy
    being prose."""
    from comp_eval_platform.competitions import get_competition

    prose = repr([g.sections for g in get_competition().presentation().guides.values()])
    assert "https://github.com/VNN-COMP/example_toolkit" in prose
    assert "https://github.com/VNN-COMP/example_benchmark" in prose
    # The skeletons live on GitHub now, not as shipped zip assets.
    assert "/api/competition/assets/" not in prose


def test_guides_cover_both_submission_pages():
    """The shell asks for these two by name and falls back to neutral copy without them,
    which would quietly drop every VNN-specific instruction from the info pages."""
    from comp_eval_platform.competitions import get_competition

    guides = get_competition().presentation().guides

    assert set(guides) == {"toolkit", "benchmark"}
    for g in guides.values():
        assert g.intro and g.pipeline and g.sections
        # The strip is one line of boxes; the cards below carry the prose.
        assert all(s["title"] and s["details"] for s in g.pipeline)


def test_only_the_benchmark_run_reports_a_timeout_cap():
    """The timer's cap must name a limit that exists: only BenchmarkRunHandler enforces
    one, so every other kind is covered by the task-wide backstop instead."""
    from comp_eval_platform.competitions import get_competition
    from comp_eval_platform.core.models import Benchmark, Category, RuntimeSettings, Task, Tool

    from vnn_comp import kinds

    s = RuntimeSettings.get()
    s.benchmark_timeout = 6
    s.save()

    cat = Category.objects.create(name="default")
    tool = Tool.objects.create(owner=_user(), category=cat, name="t", repository="r")
    Benchmark.objects.create(owner=_user(), category=cat, name="b1", published=True)
    task = Task.objects.create(owner=tool.owner, tool=tool)
    comp = get_competition()
    comp.build_steps(task)

    caps = {st.kind: comp.step_timeout_hours(st) for st in task.step_set.all()}
    assert caps[kinds.RUN_BENCHMARK] == 6
    assert caps[kinds.INSTALL] is None
    assert caps[kinds.CHECK_RESULTS] is None
    assert caps["shutdown"] is None


def test_run_folder_carries_the_year_the_scorer_expects():
    """The scorer rebuilds each witness path as ../<tool>/<year>_<category>/<..>.gz, so a
    folder without the year makes every counterexample read as MISSING — and silently, a
    missing witness being a legitimate verdict rather than an error."""
    from vnn_comp.export_layout import run_folder

    assert run_folder("acasxu") == "2026_acasxu"


def test_ensure_instances_records_cases_and_is_idempotent():
    from comp_eval_platform.core.models import Benchmark, Category, Instance

    from vnn_comp.instances import ensure_instances

    cat = Category.objects.create(name="default")
    b = Benchmark.objects.create(owner=_user(), category=cat, name="acasxu")
    csv_text = ("onnx/net_a.onnx,vnnlib/prop_1.vnnlib,116\n"
                "onnx/net_b.onnx,vnnlib/prop_1.vnnlib,116\n")

    by_name = ensure_instances(b, csv_text)

    assert sorted(by_name) == ["net_a/prop_1", "net_b/prop_1"]
    assert by_name["net_a/prop_1"].spec == {
        "onnx": "onnx/net_a.onnx", "vnnlib": "vnnlib/prop_1.vnnlib", "timeout": 116.0,
    }
    ensure_instances(b, csv_text)  # a re-run must not duplicate them
    assert Instance.objects.filter(benchmark=b).count() == 2


def test_run_results_link_to_their_instance_rows(tmp_path):
    """The whole point: a stored Result must resolve to the case it ran, which needs
    the run's names and the benchmark's Instance names to agree."""
    from comp_eval_platform.competitions import get_competition
    from comp_eval_platform.core.models import Benchmark, Category, Result, Task, Tool

    from vnn_comp.instances import ensure_instances

    cat = Category.objects.create(name="default")
    u = _user()
    tool = Tool.objects.create(owner=u, category=cat, name="t", repository="r")
    b = Benchmark.objects.create(owner=u, category=cat, name="acasxu")
    task = Task.objects.create(owner=u, tool=tool)
    instances = ensure_instances(b, "onnx/net_a.onnx,vnnlib/prop_1.vnnlib,116\n")

    (tmp_path / "results.csv").write_text(
        "acasxu,onnx/net_a.onnx,vnnlib/prop_1.vnnlib,0.3,unsat,50.4\n")
    records = get_competition().parse_results(task, str(tmp_path))
    Result.store(task, tool, b, cat, records, instances_by_name=instances)

    stored = Result.objects.get(task=task)
    assert stored.instance is not None and stored.instance.name == "net_a/prop_1"
    assert (stored.result, stored.time) == ("unsat", 50.4)


def test_score_builds_scoreboard():
    from comp_eval_platform.competitions import get_competition
    from comp_eval_platform.core.models import (
        Benchmark, Category, Result, Task, Tool, Track,
    )

    cat = Category.objects.create(name="default")
    u = _user()
    tool = Tool.objects.create(owner=u, category=cat, name="alpha", repository="r")
    bench = Benchmark.objects.create(owner=u, category=cat, name="b1", published=True)
    task = Task.objects.create(owner=u, tool=tool)
    Result.objects.create(task=task, tool=tool, benchmark=bench, category=cat, result="sat", time=1.0)
    Result.objects.create(task=task, tool=tool, benchmark=bench, category=cat, result="unknown", time=2.0)

    track = Track.objects.create(name="main")
    track.benchmarks.add(bench)

    board = get_competition().score(track)
    assert board.columns == ["tool", "solved", "time"]
    assert board.rows == [{"tool": "alpha", "solved": 1, "time": 3.0}]


def test_parse_overall_summary_reads_the_scorers_report():
    """The block process_results.py prints; its witness tallies are why we run it."""
    from vnn_comp.scoring import parse_overall_summary, severity

    log = (
        "Checking ce path: ...\n"
        "================================================================================\n"
        "Overall Summary for vibecheck:\n"
        "Total categories: 1\n"
        "Total instances: 12\n"
        "  - holds:   5\n"
        "  - violated: 4\n"
        "  - timeout:  2\n"
        "  - error:    1\n"
        "  - unknown:  0\n"
        "Counterexample Summary:\n"
        "  - valid:   2 (50.0%)\n"
        "  - valid_with_tolerance: 1 (25.0%)\n"
        "  - invalid: 1 (25.0%)\n"
        "  - missing: 0 (0.0%)\n"
        "================================================================================\n"
    )
    got = parse_overall_summary(log)
    assert got["instances"] == 12
    assert got["verdicts"] == {"holds": 5, "violated": 4, "timeout": 2, "error": 1, "unknown": 0}
    assert got["witnesses"] == {"valid": 2, "valid_with_tolerance": 1, "invalid": 1, "missing": 0}
    assert severity(got) == "error"  # an invalid witness (and an error) is not a clean run


def test_summary_is_absent_until_the_scorer_reports():
    from vnn_comp.scoring import parse_overall_summary, severity

    assert parse_overall_summary("") is None
    assert parse_overall_summary("[ERROR] skipping validation") is None
    assert severity(None) == "unknown"


def test_a_clean_run_reads_as_success():
    from vnn_comp.scoring import parse_overall_summary, severity

    log = ("Overall Summary for t:\nTotal instances: 3\n"
           "  - holds:   2\n  - violated: 1\n  - timeout:  0\n  - error:    0\n  - unknown:  0\n"
           "Counterexample Summary:\n  - valid:   1 (100.0%)\n"
           "  - valid_with_tolerance: 0 (0.0%)\n  - invalid: 0 (0.0%)\n  - missing: 0 (0.0%)\n")
    assert severity(parse_overall_summary(log)) == "success"


def test_a_timeout_only_run_is_still_clean():
    """A per-instance timeout is an ordinary outcome, not a fault."""
    from vnn_comp.scoring import parse_overall_summary, severity

    log = ("Overall Summary for t:\nTotal instances: 2\n"
           "  - holds:   0\n  - violated: 0\n  - timeout:  2\n  - error:    0\n  - unknown:  0\n")
    got = parse_overall_summary(log)
    assert got["witnesses"] == {}  # the scorer prints none without violations
    assert severity(got) == "success"


def test_a_missing_witness_is_not_a_clean_run():
    from vnn_comp.scoring import parse_overall_summary, severity

    log = ("Overall Summary for t:\nTotal instances: 1\n"
           "  - holds:   0\n  - violated: 1\n  - timeout:  0\n  - error:    0\n  - unknown:  0\n"
           "Counterexample Summary:\n  - valid:   0 (0.0%)\n"
           "  - valid_with_tolerance: 0 (0.0%)\n  - invalid: 0 (0.0%)\n  - missing: 1 (100.0%)\n")
    assert severity(parse_overall_summary(log)) == "error"


def test_count_verdicts_buckets_raw_results():
    """Infra failures are surfaced as errors (submission-health), matching the frontend."""
    from vnn_comp.scoring import count_verdicts

    assert count_verdicts([]) is None
    assert count_verdicts([
        "unsat", "holds", "sat", "violated", "unknown", "run_instance_timeout",
        "timeout(200)", "prepare_instance_error_1", "no_result_in_file", "",
    ]) == {"holds": 2, "violated": 2, "unknown": 1, "timeout": 2, "error": 3}


def test_reconcile_replaces_a_dropped_all_unknown_category():
    """process_results.py drops an all-unknown category, zeroing its summary; the stored
    Result rows are the only place those verdicts survive, so they win — the cifar100 bug."""
    from vnn_comp.scoring import parse_overall_summary, reconcile_with_results, severity

    dropped = parse_overall_summary(
        "Overall Summary for t:\nTotal instances: 0\n"
        "  - holds:   0\n  - violated: 0\n  - timeout:  0\n  - error:    0\n  - unknown:  0\n")
    db = {"holds": 0, "violated": 0, "timeout": 0, "error": 0, "unknown": 3}
    got = reconcile_with_results(dropped, db)
    assert got["verdicts"]["unknown"] == 3
    assert got["instances"] == 3
    assert severity(got) == "success"  # all-unknown is a valid outcome


def test_reconcile_keeps_a_nondegenerate_scorer_summary():
    """A summary with real verdicts wins over the raw rows: the scorer reconciles forced
    per-instance timeouts, keeping violated equal to the witness breakdown."""
    from vnn_comp.scoring import parse_overall_summary, reconcile_with_results

    summary = parse_overall_summary(
        "Overall Summary for t:\nTotal instances: 4\n"
        "  - holds:   0\n  - violated: 2\n  - timeout:  2\n  - error:    0\n  - unknown:  0\n"
        "Counterexample Summary:\n  - valid:   2 (100.0%)\n"
        "  - valid_with_tolerance: 0\n  - invalid: 0\n  - missing: 0\n")
    # results.csv kept the tool's raw verdicts (2 sat finished a hair late -> timeout).
    db = {"holds": 0, "violated": 4, "timeout": 0, "error": 0, "unknown": 0}
    got = reconcile_with_results(summary, db)
    assert got["verdicts"]["violated"] == 2
    assert got["verdicts"]["timeout"] == 2


def test_reconcile_surfaces_errors_the_scorer_hid_in_unknown():
    """An infra failure the scorer folds into unknown must read as an error (red), moved
    across without changing the total."""
    from vnn_comp.scoring import parse_overall_summary, reconcile_with_results, severity

    summary = parse_overall_summary(
        "Overall Summary for t:\nTotal instances: 3\n"
        "  - holds:   1\n  - violated: 0\n  - timeout:  0\n  - error:    0\n  - unknown:  2\n")
    db = {"holds": 1, "violated": 0, "timeout": 0, "error": 2, "unknown": 0}
    got = reconcile_with_results(summary, db)
    assert got["verdicts"]["error"] == 2
    assert got["verdicts"]["unknown"] == 0
    assert got["verdicts"]["holds"] == 1
    assert got["instances"] == 3
    assert severity(got) == "error"


def test_build_summary_is_none_without_a_scorer_report():
    """No scorer summary -> nothing frozen, so the frontend keeps its results.csv fallback
    (which can flag verdicts but not witness validity)."""
    from vnn_comp.scoring import build_summary

    db = {"holds": 0, "violated": 0, "timeout": 0, "error": 0, "unknown": 3}
    assert build_summary("[ERROR] skipping validation", db) == (None, None)


def test_check_results_freezes_the_reconciled_tally():
    """End to end: an all-unknown run whose scorer dropped the category still freezes the
    real unknown count onto the step (read back by the details page)."""
    from comp_eval_platform.core.models import (
        Benchmark, Category, Result, Task, Tool,
    )
    from comp_eval_platform.core.models.execution import StepStatus, TaskStep

    from vnn_comp import kinds
    from vnn_comp.steps import freeze_check_summary

    cat = Category.objects.create(name="default")
    u = _user()
    tool = Tool.objects.create(owner=u, category=cat, name="t", repository="r")
    b = Benchmark.objects.create(owner=u, category=cat, name="acasxu")
    task = Task.objects.create(owner=u, tool=tool)
    for _ in range(3):
        Result.objects.create(task=task, tool=tool, benchmark=b, category=cat, result="unknown", time=5.0)

    step = TaskStep.objects.create(
        task=task, kind=kinds.CHECK_RESULTS, order=1, status=StepStatus.DONE,
        payload={"benchmark_id": b.id})
    step.set_log("Overall Summary for t:\nTotal instances: 0\n"
                 "  - holds:   0\n  - violated: 0\n  - timeout:  0\n  - error:    0\n  - unknown:  0\n")

    assert freeze_check_summary(step) is True
    step.refresh_from_db()
    assert step.payload["summary"]["verdicts"]["unknown"] == 3
    assert step.payload["severity"] == "success"
