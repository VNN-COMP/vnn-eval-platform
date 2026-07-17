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
        kinds.RUN_BENCHMARK, kinds.RUN_BENCHMARK,  # only the two published benchmarks
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
        kinds.RUN_BENCHMARK, kinds.EXPORT,
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
        kinds.RUN_BENCHMARK,
        "shutdown",
    ]


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
