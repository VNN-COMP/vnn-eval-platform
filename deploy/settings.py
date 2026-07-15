"""VNN-COMP deployment settings: the whole per-variant Django config.

Extends the core base settings and does the two things that make this a VNN
deployment: select the competition and install its plugin app.
"""
from comp_eval_platform.settings import *  # noqa: F401,F403

ACTIVE_COMPETITION = "vnn"
INSTALLED_APPS += ["vnn_comp"]  # noqa: F405

# Everything else (DATABASE_URL, EXECUTION_BACKEND, MAX_PARALLEL_NODES,
# SCHEDULER_AUTOSTART, ROOT_URL, …) comes from the environment via the core base.
