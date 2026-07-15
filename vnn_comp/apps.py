from django.apps import AppConfig


class VnnCompConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "vnn_comp"
    label = "vnn_comp"
    verbose_name = "VNN-COMP"

    def ready(self):
        # Register the competition + its step handlers (import side effects populate
        # the core registries). This is the entire wiring a variant needs.
        from comp_eval_platform.competitions import register

        from . import steps  # noqa: F401  (registers step handlers)
        from .competition import VNNCompetition

        register(VNNCompetition)
