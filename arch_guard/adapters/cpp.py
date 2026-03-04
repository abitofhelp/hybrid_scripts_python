# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Michael Gardner, A Bit of Help, Inc.
"""
C++ language adapter for architecture validation.
"""

import re
from pathlib import Path
from typing import List, Tuple, Set

from .base import LanguageAdapter

# Support both direct script execution and module import
try:
    from ..models import ArchitectureViolation
except ImportError:
    from models import ArchitectureViolation


class CppAdapter(LanguageAdapter):
    """
    C++-specific architecture validation adapter.

    Handles:
    - .hpp/.cpp file extensions
    - #include directive parsing (project includes only)
    - GPR project file validation (C++ language check)
    - Domain I/O purity validation
    """

    # I/O headers forbidden in domain layer (side effects / infrastructure)
    DOMAIN_FORBIDDEN_HEADERS = {
        'iostream', 'fstream', 'sstream', 'ostream', 'istream',
        'cstdio', 'stdio.h',
        'filesystem',
        'print',
    }

    @property
    def name(self) -> str:
        return "C++"

    @property
    def file_extensions(self) -> List[str]:
        return ['.hpp', '.cpp']

    @property
    def forbidden_test_imports(self) -> List[str]:
        return ['catch2', 'catch.hpp', 'gtest/', 'gmock/', 'doctest']

    @property
    def source_root_subdir(self) -> str | None:
        """C++ projects using this architecture have sources under src/."""
        return 'src'

    @property
    def domain_allowed_external_prefixes(self) -> Set[str]:
        """
        C++ standard library headers allowed in domain layer.

        Since extract_imports() only returns project-local #include "..."
        directives (not system #include <...>), this set is empty.
        All system headers are filtered at extraction time.
        """
        return set()

    def extract_imports(self, file_path: Path) -> List[Tuple[int, str]]:
        """
        Extract all #include "..." directives from a C++ file.

        Only project-local includes (#include "...") are extracted.
        System includes (#include <...>) are skipped because they are
        never architectural layer dependencies.

        Relative paths are resolved against the file's directory and
        normalized to source-root-relative paths for layer detection.
        """
        includes = []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, start=1):
                    stripped = line.strip()

                    # Skip comments
                    if stripped.startswith('//'):
                        continue

                    # Match: #include "relative/path.hpp"
                    match = re.match(r'^\s*#\s*include\s+"([^"]+)"', stripped)
                    if match:
                        include_path = match.group(1)

                        # Resolve relative path against file's directory
                        resolved = (file_path.parent / include_path).resolve()

                        # Try to find the source root by walking up from the file
                        # looking for a parent named 'src'
                        source_root = self._find_source_root(file_path)
                        if source_root:
                            try:
                                relative = str(resolved.relative_to(source_root))
                                includes.append((line_num, relative))
                            except ValueError:
                                # Include resolves outside source root
                                includes.append((line_num, include_path))
                        else:
                            includes.append((line_num, include_path))

        except Exception as e:
            print(f"Warning: Could not read {file_path}: {e}")

        return includes

    def _find_source_root(self, file_path: Path) -> Path | None:
        """Find the source root directory (src/) by walking up from the file."""
        current = file_path.parent
        while current != current.parent:
            if current.name == 'src':
                return current
            current = current.parent
        return None

    def get_layer_from_import(self, import_path: str, project_root: Path) -> str | None:
        """
        Determine which layer a C++ include belongs to.

        The import_path is expected to be a source-root-relative path
        (e.g., 'domain/error/result.hpp'). The first path component
        is checked against known layer names.
        """
        # Normalize separators
        normalized = import_path.replace('\\', '/')

        # Split into components
        parts = normalized.split('/')

        # Layer names from architecture rules
        layer_names = {
            'domain', 'application', 'infrastructure',
            'api', 'presentation', 'bootstrap',
        }

        # Find the first component matching a layer name
        for part in parts:
            if part in layer_names:
                return part

        return None

    def validate_config(self, project_root: Path, layers_present: Set[str]) -> Tuple[bool, List[str]]:
        """
        Validate GPR configuration for C++ projects.

        Checks that GPR files exist and specify C++ as the language.
        C++ projects do not need Ada-specific Library_Standalone or
        Library_Interface configuration.
        """
        messages = []
        valid = True

        gpr_files = list(project_root.glob('*.gpr'))
        if not gpr_files:
            messages.append("  ❌ No GPR project files found in project root.")
            return False, messages

        found_cpp_gpr = False
        for gpr_file in gpr_files:
            try:
                content = gpr_file.read_text(encoding='utf-8')
                if re.search(r'for\s+Languages\s+use\s*\(\s*"C\+\+"', content, re.IGNORECASE):
                    found_cpp_gpr = True
                    messages.append(f"  ✓ {gpr_file.name}: C++ language declared.")
            except Exception as e:
                messages.append(f"  ⚠ Could not read {gpr_file.name}: {e}")

        if not found_cpp_gpr:
            messages.append("  ❌ No GPR file declares C++ as a language.")
            valid = False
        else:
            messages.append(f"  ✓ GPR configuration valid for C++ project.")

        return valid, messages

    def is_test_file(self, file_path: Path) -> bool:
        """Check if this is a C++ test file."""
        filename_lower = file_path.name.lower()

        # Files with test prefix or suffix
        if filename_lower.startswith('test_') or '_test.' in filename_lower:
            return True

        # Files in a test/ or tests/ directory
        parts = file_path.parts
        for part in parts:
            if part.lower() in ('test', 'tests'):
                return True

        return False

    def is_domain_allowed_import(self, import_path: str) -> bool:
        """
        Check if an import is allowed in the domain layer.

        Since extract_imports() only returns project-local includes,
        this checks for same-directory includes (no layer component)
        which are always intra-layer and thus allowed.
        """
        # Same-directory includes (e.g., "error.hpp", "person.hpp")
        if '/' not in import_path:
            return True

        # Intra-domain includes (resolved path starts with domain/)
        normalized = import_path.lower().replace('\\', '/')
        if normalized.startswith('domain/') or normalized.startswith('domain\\'):
            return True

        return False

    def language_specific_validations(self, file_path: Path) -> List[ArchitectureViolation]:
        """
        Perform C++-specific validations.

        Checks that domain layer files do not include I/O headers
        that would violate domain purity.
        """
        violations = []

        # Only validate production code
        if self.is_test_file(file_path):
            return violations

        # Only check domain layer files for I/O header violations
        source_root = self._find_source_root(file_path)
        if not source_root:
            return violations

        try:
            relative = file_path.relative_to(source_root)
            if relative.parts and relative.parts[0] != 'domain':
                return violations
        except ValueError:
            return violations

        violations.extend(self._validate_domain_io_purity(file_path))
        return violations

    def _validate_domain_io_purity(self, file_path: Path) -> List[ArchitectureViolation]:
        """Ensure domain layer files do not include I/O headers."""
        violations = []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, start=1):
                    stripped = line.strip()

                    # Skip comments
                    if stripped.startswith('//'):
                        continue

                    # Match: #include <header>
                    match = re.match(r'^\s*#\s*include\s+<([^>]+)>', stripped)
                    if match:
                        header = match.group(1)
                        # Check against forbidden I/O headers
                        for forbidden in self.DOMAIN_FORBIDDEN_HEADERS:
                            if header == forbidden or header.startswith(forbidden + '/'):
                                violations.append(ArchitectureViolation(
                                    file_path=str(file_path),
                                    line_number=line_num,
                                    violation_type='DOMAIN_IO_HEADER',
                                    details=(
                                        f"Domain layer must not include I/O header: <{header}>\n"
                                        f"         Domain must be pure with no side effects."
                                    )
                                ))

        except Exception as e:
            print(f"Warning: Could not validate I/O purity in {file_path}: {e}")

        return violations

    def get_config_step_name(self) -> str:
        return "GPR Configuration (C++ Project)"
