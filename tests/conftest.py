"""Pytest bootstrap for the ``tests/`` package.

Inserts the repo root on ``sys.path`` so ``from arch_guard.adapters.ada``
imports work under a bare ``python3 -m pytest tests/`` invocation
without requiring package installation or PYTHONPATH configuration.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
