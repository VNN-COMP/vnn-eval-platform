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


def canonical_verdict(raw: str) -> str:
    """Bucket a raw results.csv verdict into one of ``VERDICT_KEYS``.

    A submission-health view, not the scorer's: the scorer folds an infrastructure
    failure into ``unknown`` (so the tool merely scores 0), whereas here anything that is
    not a legitimate verification outcome reads as ``error`` — matching the frontend's
    ``canonicalVerdict`` so the two never disagree.
    """
    r = (raw or "").strip().lower()
    if r in ("unsat", "holds"):
        return "holds"
    if r in ("sat", "violated"):
        return "violated"
    if r == "unknown":
        return "unknown"
    # Deliberately narrow: prepare_instance_timeout is a prepare-phase fault, not this.
    if r == "run_instance_timeout" or r == "timed-out" or r.startswith("timeout"):
        return "timeout"
    return "error"


def count_verdicts(results):
    """Tally raw ``Result.result`` strings into ``VERDICT_KEYS`` buckets, or None when
    there are no rows (so callers can fall back to the scorer's own count)."""
    counts = {k: 0 for k in VERDICT_KEYS}
    seen = False
    for result in results:
        counts[canonical_verdict(result)] += 1
        seen = True
    return counts if seen else None


def reconcile_with_results(summary, verdict_counts):
    """Fold the authoritative per-instance verdict tallies (from the stored ``Result``
    rows) into the scorer's summary.

    ``process_results.py`` drops any category with no holds/violated result
    (``delete_empty_categories``), zeroing its verdict line even when every instance was
    unknown or timed out — so a degenerate (all-zero) summary is replaced by the real
    tallies. A non-degenerate summary is kept: the scorer reconciles forced per-instance
    timeouts (a definitive answer returned just past the budget) that the raw rows do not,
    keeping ``violated`` equal to the witness breakdown. Either way, infra failures the
    scorer hid in ``unknown`` are surfaced as errors (submission-health). ``verdict_counts``
    is a full-bucket dict from :func:`count_verdicts` (or None); ``witnesses`` is untouched.
    """
    if not summary or verdict_counts is None:
        return summary
    log_verdicts = summary.get("verdicts") or {}
    if sum(log_verdicts.values()) > 0:
        verdicts = {k: log_verdicts.get(k, 0) for k in VERDICT_KEYS}
        if verdict_counts["error"] > verdicts["error"]:
            delta = verdict_counts["error"] - verdicts["error"]
            verdicts["unknown"] = max(0, verdicts["unknown"] - delta)
            verdicts["error"] = verdict_counts["error"]
    else:
        verdicts = dict(verdict_counts)
    return {"instances": sum(verdicts.values()), "verdicts": verdicts,
            "witnesses": summary.get("witnesses") or {}}


def build_summary(log: str, verdict_counts):
    """The frozen ``(summary, severity)`` for a validation run: the scorer's verdict/witness
    report reconciled against the authoritative per-instance verdict counts. Returns
    ``(None, None)`` when the scorer produced no summary at all (skipped/failed), so the
    caller leaves the payload empty and the frontend keeps its results.csv fallback.
    """
    summary = reconcile_with_results(parse_overall_summary(log), verdict_counts)
    if not summary:
        return None, None
    return summary, severity(summary)
