"""Reading the official scorer's summary back out of a validation run.

``process_results.py`` reports what it found as text, so this lifts it into structured
form for the submission page. Its counterexample tallies are the reason the step exists:
a `violated` only counts if the witness held up, and only the scorer can say that.
"""
import re

#: Verdict buckets, in the scorer's own order.
VERDICT_KEYS = ("holds", "violated", "timeout", "error", "unknown")
#: How each counterexample fared. The scorer only prints these when a run had violations.
WITNESS_KEYS = ("valid", "valid_with_tolerance", "invalid", "missing")

_COUNT = re.compile(r"^\s*-\s*([a-z_]+):\s*(\d+)", re.MULTILINE)
_TOTAL = re.compile(r"^Total instances:\s*(\d+)", re.MULTILINE)


def parse_overall_summary(log: str):
    """The scorer's "Overall Summary" + "Counterexample Summary" as
    ``{instances, verdicts, witnesses}``, or None if it never got that far (it prints
    the block only after a successful run).
    """
    if not log or "Overall Summary" not in log:
        return None
    # A step may have been retried; the last run is the one that counts.
    tail = log[log.rindex("Overall Summary"):]
    counts = {key: int(value) for key, value in _COUNT.findall(tail)}
    verdicts = {k: counts[k] for k in VERDICT_KEYS if k in counts}
    if not verdicts:
        return None
    total = _TOTAL.search(tail)
    return {
        "instances": int(total.group(1)) if total else sum(verdicts.values()),
        "verdicts": verdicts,
        "witnesses": {k: counts[k] for k in WITNESS_KEYS if k in counts},
    }


def severity(summary) -> str:
    """How the run should read at a glance, following the old site's rule: only a fully
    valid run is clean. A counterexample the scorer rejected or could not find is as
    serious as an errored instance — the tool claimed a violation it cannot back up.
    A per-instance timeout is an ordinary outcome and does not count against it.
    """
    if not summary:
        return "unknown"
    witnesses = summary.get("witnesses") or {}
    if (summary["verdicts"].get("error")
            or witnesses.get("invalid") or witnesses.get("missing")):
        return "error"
    return "success"
