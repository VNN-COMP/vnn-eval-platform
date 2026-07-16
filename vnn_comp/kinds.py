"""Step kinds this variant contributes (core provides 'assign', 'shutdown', 'pause')."""

CREATE = "vnn_create"
INSTALL = "vnn_install"
RUN_BENCHMARK = "run_benchmark"  # counted by Task.effective_timeout_hours
EXPORT = "vnn_export"
# Benchmark-submission pipeline (generate instances from a git repo, then push the
# generated files to the benchmarks repo).
GENERATE = "vnn_generate"
BENCHMARK_EXPORT = "vnn_benchmark_export"
