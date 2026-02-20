# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
"""
Namespace Layers - Transform hybrid starter projects.

Namespaces internal layer packages (Domain, Application, Infrastructure, ...)
under the project root package to prevent GPR compilation-unit collisions
when composing libraries and applications.

Usage:
    python3 namespace_layers/namespace_layers.py /path/to/project
    python3 namespace_layers/namespace_layers.py /path/to/project --dry-run
"""

from .namespace_layers import NamespaceTransformer, main

__all__ = ['NamespaceTransformer', 'main']
