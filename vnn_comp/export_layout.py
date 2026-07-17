"""Where the export steps write in the results repo.

The export script, the step handler that hands it a name, and the download endpoint
that serves the folder afterwards all have to agree on this layout, so it is described
once here rather than in each of them.

Layout: ``<tool>/<benchmark>/`` holding results.csv and any *.counterexample.gz.
"""
import os
import re


def slug(name: str) -> str:
    """A submission name as a git-path-safe folder (names carry spaces and punctuation)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "tool"


def results_dir(tool_name: str, benchmark_name: str) -> str:
    """Absolute path of one run's exported folder, once the export step has pushed it."""
    from django.conf import settings

    return os.path.join(settings.LOCAL_REPOS_DIR, "results", slug(tool_name), benchmark_name)
