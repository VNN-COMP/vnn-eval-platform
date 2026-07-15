"""Step kinds this variant contributes (core provides 'assign' and 'shutdown')."""

CREATE = "vnn_create"
INSTALL = "vnn_install"
PAUSE = "vnn_pause"
RUN_BENCHMARK = "run_benchmark"  # counted by Task.effective_timeout_hours
EXPORT = "vnn_export"
