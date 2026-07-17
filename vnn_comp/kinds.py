"""Step kinds this variant contributes (core provides 'assign', 'shutdown', 'pause')."""

CREATE = "vnn_create"
INSTALL = "vnn_install"
#: Runs after install_tool.sh: the submitter's own script (licence activation and the
#: like), else the one the tool repo ships. Same name the pre-port tasks used.
POST_INSTALL = "vnn_post_install"
RUN_BENCHMARK = "run_benchmark"  # counted by Task.effective_timeout_hours
EXPORT = "vnn_export"
# Benchmark-submission pipeline (generate instances from a git repo, then push the
# generated files to the benchmarks repo).
GENERATE = "vnn_generate"
BENCHMARK_EXPORT = "vnn_benchmark_export"
