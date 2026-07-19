"""Step kinds this variant contributes (core provides 'assign', 'shutdown', 'pause')."""

CREATE = "vnn_create"
INSTALL = "vnn_install"
#: Runs after install_tool.sh: the submitter's own script (licence activation and the
#: like), else the one the tool repo ships. Same name the pre-port tasks used.
POST_INSTALL = "vnn_post_install"
RUN_BENCHMARK = "run_benchmark"  # counted by Task.effective_timeout_hours
#: Validates a finished benchmark's counterexamples with the official scorer.
CHECK_RESULTS = "vnn_check_results"
EXPORT = "vnn_export"
# Benchmark-submission pipeline (generate instances from a git repo, then push the
# generated files to the benchmarks repo). Setup (clone + build the generator venv),
# generation, and the VNNLIB 1.0->2.0 conversion are separate steps so each phase — the
# slow clone/pip installs and the conversion especially — shows its own live log.
GENERATE_SETUP = "vnn_generate_setup"
GENERATE = "vnn_generate"
#: Best-effort VNNLIB 1.0 -> 2.0 conversion; only added for 1.0 submissions.
CONVERT = "vnn_convert"
BENCHMARK_EXPORT = "vnn_benchmark_export"
