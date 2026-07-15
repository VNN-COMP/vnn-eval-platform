"""Test settings for the VNN variant: core's sqlite test settings + this plugin."""
from comp_eval_platform.settings_test import *  # noqa: F401,F403

ACTIVE_COMPETITION = "vnn"
INSTALLED_APPS += ["vnn_comp"]  # noqa: F405
