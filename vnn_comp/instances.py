"""Instance identity for VNN-COMP benchmarks.

A benchmark's cases come from its generated ``instances.csv`` (``onnx,vnnlib,timeout``).
Both the generator (recording a benchmark's Instance rows) and a tool run (linking its
results back to them) name a case through ``instance_name`` here — one rule, so the two
sides cannot drift apart and leave results unlinkable.
"""
import csv
import os


def instance_name(onnx: str, vnnlib: str) -> str:
    """Name of the case pairing this network with this property. Neither file alone
    identifies it: acasxu runs the same property against many networks."""
    stem = lambda p: os.path.splitext(os.path.basename(p.strip()))[0]  # noqa: E731
    return f"{stem(onnx)}/{stem(vnnlib)}"


def parse_instances_csv(text: str):
    """Yield ``(onnx, vnnlib, timeout)`` per row of an instances.csv."""
    for row in csv.reader(text.splitlines()):
        if len(row) < 2 or not row[0].strip():
            continue
        try:
            timeout = float(row[2]) if len(row) > 2 and row[2].strip() else None
        except ValueError:
            timeout = None
        yield row[0].strip(), row[1].strip(), timeout


def ensure_instances(benchmark, csv_text: str) -> dict:
    """Record ``benchmark``'s cases from its instances.csv, and return ``{name: Instance}``.

    Idempotent, so a benchmark generated before instances were recorded picks them up on
    its next run rather than needing a regeneration.
    """
    from comp_eval_platform.core.models import Instance

    by_name = {i.name: i for i in Instance.objects.filter(benchmark=benchmark)}
    missing = []
    for order, (onnx, vnnlib, timeout) in enumerate(parse_instances_csv(csv_text)):
        name = instance_name(onnx, vnnlib)
        if name in by_name:
            continue
        missing.append(Instance(benchmark=benchmark, name=name, order=order,
                                spec={"onnx": onnx, "vnnlib": vnnlib, "timeout": timeout}))
    if missing:
        Instance.objects.bulk_create(missing, ignore_conflicts=True)
        by_name = {i.name: i for i in Instance.objects.filter(benchmark=benchmark)}
    return by_name
