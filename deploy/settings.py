"""VNN-COMP deployment settings: the whole per-variant Django config.

Extends the core base settings and does the two things that make this a VNN
deployment: select the competition and install its plugin app.
"""
from decouple import config

from comp_eval_platform.settings import *  # noqa: F401,F403

ACTIVE_COMPETITION = "vnn"
INSTALLED_APPS += ["vnn_comp"]  # noqa: F405

# The official scorer (SCORING/process_results.py), which validates a run's
# counterexamples. Always the competition's own results repo, never the one this
# deployment exports to: a sat is only meaningful once the code the competition
# actually scores with has checked its witness.
COMPETITION_YEAR = config("COMPETITION_YEAR", default="2026")
SCORING_REPO = config(
    "SCORING_REPO",
    default=f"https://github.com/{config('VNNCOMP_GITHUB_ORG', default='VNN-COMP')}"
            f"/vnncomp{COMPETITION_YEAR}_results.git",
)
SCORING_REF = config("SCORING_REF", default="main")

# Everything else (DATABASE_URL, EXECUTION_BACKEND, MAX_PARALLEL_NODES,
# SCHEDULER_AUTOSTART, ROOT_URL, …) comes from the environment via the core base.
