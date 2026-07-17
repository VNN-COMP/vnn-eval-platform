"""Where the export steps write in the results repo.

The export script, the step handler that hands it a name, and the download endpoint
that serves the folder afterwards all have to agree on this layout, so it is described
once here rather than in each of them.

Layout: ``<tool>/<year>_<benchmark>/`` holding results.csv and any *.counterexample.gz.
"""
import os
import re


def slug(name: str) -> str:
    """A submission name as a git-path-safe folder (names carry spaces and punctuation)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "tool"


def run_folder(benchmark_name: str) -> str:
    """``<year>_<benchmark>``. The year is load-bearing, not decoration: the official
    scorer finds a witness's benchmark repo by looking for the year *inside* the
    counterexample's path (Settings.BENCHMARK_REPOS), and asserts if it is absent."""
    from django.conf import settings

    return f"{settings.COMPETITION_YEAR}_{benchmark_name}"


def results_dir(tool_name: str, benchmark_name: str) -> str:
    """Absolute path of one run's exported folder, once the export step has pushed it."""
    from django.conf import settings

    return os.path.join(settings.LOCAL_REPOS_DIR, "results",
                        slug(tool_name), run_folder(benchmark_name))
