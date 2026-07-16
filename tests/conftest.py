"""Shared test configuration."""

import os

from hypothesis import settings

# CI hammers properties across many examples; local default stays fast so the
# suite is cheap to run after every task.
settings.register_profile("ci", max_examples=200)
settings.register_profile("dev", max_examples=25)
settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "dev"))
