#!/usr/bin/env python3
# ==============================================================================
# models.py - Data models for release management
# ==============================================================================
# Copyright (c) 2025 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
#
# Purpose:
#   Data classes and enums for the unified release management system.
#   Provides ReleaseConfig and Language enum for multi-language support.
#
# Usage:
#   from models import ReleaseConfig, Language
#
#   config = ReleaseConfig(
#       project_root=Path('/path/to/project'),
#       version='1.0.0',
#       language=Language.GO,
#   )
#
# ==============================================================================

import sys
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

# Add parent directory to path for common imports (before importing common)
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import Language from common to avoid duplication
try:
    from ..common import Language
except ImportError:
    from common import Language


class ReleaseAction(Enum):
    """Release workflow actions."""
    PREPARE = 'prepare'
    RELEASE = 'release'
    VALIDATE = 'validate'
    RC_TAG = 'rc-tag'


@dataclass
class ReleaseConfig:
    """Configuration for release operations."""
    project_root: Path
    version: str
    language: Language
    dry_run: bool = False

    # Computed fields (set in __post_init__)
    date_str: str = ""
    year: int = 0
    project_name: str = ""
    project_url: str = ""
    applies_to_range: str = ""

    def __post_init__(self):
        """Initialize computed fields."""
        self.date_str = datetime.now().strftime("%Y-%m-%d")
        self.year = datetime.now().year
        self.applies_to_range = self._compute_applies_to_range()

    def _compute_applies_to_range(self) -> str:
        """
        Compute the alire-style version range for the document metadata
        ``Applies to`` field.

        Format: ``^{major}.{minor}`` (e.g., 1.0.0 -> ^1.0, 4.1.7 -> ^4.1).

        Used by the release-time metadata sync to populate the
        ``Applies to <project>`` row when the doc has no explicit
        author override. Doc-author overrides are preserved by the
        header rewriter and never replaced by this value.
        """
        # Strip any pre-release / build suffix (1.0.0-rc1 -> 1.0.0)
        core = self.version.split('-')[0].split('+')[0]
        parts = core.split('.')
        if len(parts) >= 2:
            return f"^{parts[0]}.{parts[1]}"
        # Defensive fallback: malformed version -> "^0.0"
        return "^0.0"

    @property
    def is_prerelease(self) -> bool:
        """Check if this is a pre-release version (contains - or +)."""
        return '-' in self.version

    @property
    def is_initial_release(self) -> bool:
        """Check if this is an initial release (<= 1.0.0)."""
        try:
            from packaging import version as pkg_version
            return pkg_version.parse(self.version) <= pkg_version.parse("1.0.0")
        except ImportError:
            # Fallback without packaging library
            return self.version in ["0.1.0", "1.0.0"] or self.version.startswith("0.")

    @property
    def tag_name(self) -> str:
        """Get the git tag name for this version."""
        return f"v{self.version}"
