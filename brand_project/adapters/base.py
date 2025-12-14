#!/usr/bin/env python3
# ==============================================================================
# adapters/base.py - Base adapter for brand_project
# ==============================================================================
# Copyright (c) 2025 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
#
# Purpose:
#   Abstract base class for language-specific project branding adapters.
#   Provides common functionality for file operations and text replacement.
#
# ==============================================================================

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Set, Tuple
from datetime import date
import shutil
import re
import subprocess

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from common import print_success, print_error, print_warning, print_info


class BaseAdapter(ABC):
    """
    Abstract base class for language-specific branding adapters.

    Subclasses must implement:
        - excluded_dirs: Directories to skip during copy
        - excluded_patterns: File patterns to skip
        - text_file_extensions: Extensions to process for text replacement
        - update_config_files(): Language-specific config updates
    """

    # Common directories to exclude (all languages)
    COMMON_EXCLUDED_DIRS: Set[str] = {
        '.git',
        '__pycache__',
        '.pytest_cache',
        '.mypy_cache',
        '.venv',
        'venv',
        '.idea',
        '.vscode',
        'docs',  # Handled specially - submodule becomes docs/common
    }

    # Submodule paths to exclude during copy and create as empty mount points
    # These are relative paths from project root
    SUBMODULE_PATHS: Set[str] = {
        'scripts/python',  # hybrid_python_scripts submodule
        'test/python',     # hybrid_test_python submodule
    }

    # Common file patterns to exclude
    COMMON_EXCLUDED_PATTERNS: Set[str] = {
        '*.gz',
        '*.zip',
        '*.tar',
        '*.pyc',
        '*.pyo',
        '.DS_Store',
        'Thumbs.db',
    }

    # Common text file extensions
    COMMON_TEXT_EXTENSIONS: Set[str] = {
        '.md',
        '.txt',
        '.yml',
        '.yaml',
        '.json',
        '.toml',
        '.py',
        '.sh',
        '.bash',
        '.puml',  # PlantUML diagrams
        '.svg',   # Generated diagrams (contain text)
        '.html',  # HTML files (coverage reports, etc.)
        '.xml',   # XML config files
    }

    # Files without extensions that should be processed
    COMMON_TEXT_FILENAMES: Set[str] = {
        'Makefile',
        'Dockerfile',
        'LICENSE',
    }

    # Files to skip during text replacement (but still copy)
    # These files should not have project name replacements applied
    SKIP_TEXT_REPLACEMENT_FILES: Set[str] = {
        '.gitmodules',  # Submodule config - handled specially by setup_docs_structure
    }

    # Path patterns to skip during text replacement
    # Files whose path contains any of these patterns will be skipped
    SKIP_TEXT_REPLACEMENT_PATTERNS: Set[str] = {
        'hybrid_python_scripts',  # Shared Python scripts submodule - should not be renamed
    }

    @property
    @abstractmethod
    def excluded_dirs(self) -> Set[str]:
        """Directories to exclude from copy (language-specific + common)."""
        pass

    @property
    @abstractmethod
    def excluded_patterns(self) -> Set[str]:
        """File patterns to exclude from copy."""
        pass

    @property
    @abstractmethod
    def text_file_extensions(self) -> Set[str]:
        """File extensions to process for text replacement."""
        pass

    @abstractmethod
    def update_config_files(self, config) -> List[str]:
        """
        Update language-specific configuration files.

        Args:
            config: ProjectConfig instance

        Returns:
            List of updated file paths (relative to target_dir)
        """
        pass

    @abstractmethod
    def get_replacement_pairs(self, config) -> List[Tuple[str, str]]:
        """
        Get text replacement pairs for this language.

        Args:
            config: ProjectConfig instance

        Returns:
            List of (old_text, new_text) tuples in order of replacement
        """
        pass

    def should_exclude_dir(self, dir_name: str) -> bool:
        """Check if a directory should be excluded."""
        return dir_name in self.excluded_dirs

    def should_exclude_file(self, file_path: Path) -> bool:
        """Check if a file should be excluded."""
        for pattern in self.excluded_patterns:
            if file_path.match(pattern):
                return True
        return False

    def is_text_file(self, file_path: Path) -> bool:
        """Check if a file should be processed for text replacement."""
        # Check by extension
        if file_path.suffix.lower() in self.text_file_extensions:
            return True
        # Check by filename (for files without extensions like Makefile)
        if file_path.name in self.COMMON_TEXT_FILENAMES:
            return True
        return False

    def should_skip_text_replacement(self, file_path: Path) -> bool:
        """
        Check if a file should be skipped during text replacement.

        Some files (like .gitmodules) should be copied but not have
        project name replacements applied to avoid breaking submodule
        configurations.

        Args:
            file_path: Path to check

        Returns:
            True if file should be skipped for text replacement
        """
        # Check if filename is in skip list
        if file_path.name in self.SKIP_TEXT_REPLACEMENT_FILES:
            return True

        # Check if path contains any skip patterns
        path_str = str(file_path)
        for pattern in self.SKIP_TEXT_REPLACEMENT_PATTERNS:
            if pattern in path_str:
                return True

        return False

    def is_submodule_path(self, path: Path, source_dir: Path) -> bool:
        """
        Check if a path is a submodule directory that should be excluded.

        Args:
            path: Path to check
            source_dir: Root source directory

        Returns:
            True if path is a submodule that should be excluded
        """
        try:
            rel_path = path.relative_to(source_dir)
            return str(rel_path) in self.SUBMODULE_PATHS
        except ValueError:
            return False

    def copy_template(self, config, verbose: bool = False) -> int:
        """
        Copy template directory to target, excluding build artifacts.

        Args:
            config: ProjectConfig instance
            verbose: Print detailed progress

        Returns:
            Number of files copied
        """
        if config.target_dir.exists():
            print_error(f"Target directory already exists: {config.target_dir}")
            return 0

        file_count = 0

        def copy_tree(src: Path, dst: Path):
            nonlocal file_count

            if not config.dry_run:
                dst.mkdir(parents=True, exist_ok=True)

            for item in src.iterdir():
                if item.is_dir():
                    if self.should_exclude_dir(item.name):
                        if verbose:
                            print_info(f"  Skipping directory: {item.name}/")
                        continue
                    # Check if this is a submodule path
                    if self.is_submodule_path(item, config.source_dir):
                        if verbose:
                            print_info(f"  Skipping submodule: {item.relative_to(config.source_dir)}/")
                        continue
                    copy_tree(item, dst / item.name)
                else:
                    if self.should_exclude_file(item):
                        if verbose:
                            print_info(f"  Skipping file: {item.name}")
                        continue

                    if config.dry_run:
                        if verbose:
                            print_info(f"  Would copy: {item.name}")
                    else:
                        shutil.copy2(item, dst / item.name)
                        if verbose:
                            print_info(f"  Copied: {item.name}")
                    file_count += 1

        if config.dry_run:
            print_info(f"[DRY RUN] Would copy template to: {config.target_dir}")
        else:
            print_info(f"Copying template to: {config.target_dir}")

        copy_tree(config.source_dir, config.target_dir)
        return file_count

    def rename_files(self, config, verbose: bool = False) -> List[str]:
        """
        Rename files containing the old project name.

        Args:
            config: ProjectConfig instance
            verbose: Print detailed progress

        Returns:
            List of renamed files (new paths)
        """
        renamed = []
        replacements = self.get_replacement_pairs(config)

        # Collect all files first, then rename (to avoid issues during iteration)
        files_to_rename: List[Tuple[Path, Path]] = []

        for file_path in config.target_dir.rglob('*'):
            if file_path.is_dir():
                continue

            # Skip files that should not be renamed
            if self.should_skip_text_replacement(file_path):
                continue

            new_name = file_path.name
            for old_text, new_text in replacements:
                if old_text in new_name:
                    new_name = new_name.replace(old_text, new_text)

            if new_name != file_path.name:
                new_path = file_path.parent / new_name
                files_to_rename.append((file_path, new_path))

        # Perform renames
        for old_path, new_path in files_to_rename:
            if config.dry_run:
                if verbose:
                    print_info(f"  Would rename: {old_path.name} -> {new_path.name}")
            else:
                old_path.rename(new_path)
                if verbose:
                    print_info(f"  Renamed: {old_path.name} -> {new_path.name}")
            renamed.append(str(new_path.relative_to(config.target_dir)))

        return renamed

    def replace_in_files(self, config, verbose: bool = False) -> int:
        """
        Replace old project name with new name in file contents.

        Args:
            config: ProjectConfig instance
            verbose: Print detailed progress

        Returns:
            Number of files modified
        """
        modified_count = 0
        replacements = self.get_replacement_pairs(config)

        for file_path in config.target_dir.rglob('*'):
            if file_path.is_dir():
                continue

            if not self.is_text_file(file_path):
                continue

            # Skip files that should not have text replacements applied
            if self.should_skip_text_replacement(file_path):
                if verbose:
                    rel_path = file_path.relative_to(config.target_dir)
                    print_info(f"  Skipping (protected): {rel_path}")
                continue

            try:
                content = file_path.read_text(encoding='utf-8')
                original_content = content

                for old_text, new_text in replacements:
                    content = content.replace(old_text, new_text)

                if content != original_content:
                    if config.dry_run:
                        if verbose:
                            rel_path = file_path.relative_to(config.target_dir)
                            print_info(f"  Would modify: {rel_path}")
                    else:
                        file_path.write_text(content, encoding='utf-8')
                        if verbose:
                            rel_path = file_path.relative_to(config.target_dir)
                            print_info(f"  Modified: {rel_path}")
                    modified_count += 1

            except UnicodeDecodeError:
                # Skip binary files
                continue
            except Exception as e:
                print_warning(f"Error processing {file_path}: {e}")

        return modified_count

    def verify_no_old_references(self, config) -> List[str]:
        """
        Verify no old project name references remain.

        Args:
            config: ProjectConfig instance

        Returns:
            List of files still containing old references
        """
        files_with_old_refs = []
        old_patterns = [
            config.old_name,
            config.old_name_pascal,
            config.old_name_ada_pascal,
        ]

        for file_path in config.target_dir.rglob('*'):
            if file_path.is_dir():
                continue

            # Skip protected files (submodules, etc.)
            if self.should_skip_text_replacement(file_path):
                continue

            # Check filename
            for pattern in old_patterns:
                if pattern in file_path.name:
                    files_with_old_refs.append(
                        f"{file_path.relative_to(config.target_dir)} (filename)"
                    )
                    break

            # Check content of text files
            if self.is_text_file(file_path):
                try:
                    content = file_path.read_text(encoding='utf-8')
                    for pattern in old_patterns:
                        if pattern in content:
                            files_with_old_refs.append(
                                f"{file_path.relative_to(config.target_dir)} (content: {pattern})"
                            )
                            break
                except (UnicodeDecodeError, Exception):
                    continue

        return files_with_old_refs

    def reset_changelog(self, config, verbose: bool = False) -> bool:
        """
        Reset CHANGELOG.md to a fresh state before any release.

        Creates a new CHANGELOG.md with standard header and empty [Unreleased]
        section, replacing any existing changelog from the template.

        Args:
            config: ProjectConfig instance
            verbose: Print detailed progress

        Returns:
            True if changelog was reset, False otherwise
        """
        changelog_path = config.target_dir / 'CHANGELOG.md'

        # Get current date in ISO format (YYYY-MM-DD)
        today = date.today().strftime("%Y-%m-%d")

        # Create fresh changelog content
        changelog_content = f"""# Changelog

**Version:** Unreleased<br>
**Date:** {today}<br>
**SPDX-License-Identifier:** BSD-3-Clause<br>
**License File:** See the LICENSE file in the project root<br>
**Copyright:** © 2025 Michael Gardner, A Bit of Help, Inc.<br>
**Status:** Development

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security
"""

        if config.dry_run:
            if verbose:
                print_info("  [DRY RUN] Would reset CHANGELOG.md")
            return True

        try:
            changelog_path.write_text(changelog_content, encoding='utf-8')
            if verbose:
                print_info("  Reset CHANGELOG.md to fresh state")
            return True
        except Exception as e:
            print_warning(f"Error resetting CHANGELOG.md: {e}")
            return False

    def setup_docs_structure(self, config, verbose: bool = False) -> bool:
        """
        Set up the docs directory structure for the new project.

        In REF projects, the docs submodule attaches to /docs.
        In cloned projects, the same submodule attaches to /docs/common,
        and /docs is used for project-specific documentation.

        This method:
        1. Updates .gitmodules to change submodule path from 'docs' to 'docs/common'
        2. Creates docs/common/.gitkeep (submodule mount point)
        3. Creates docs/diagrams/.gitkeep (project-specific diagrams)
        4. Creates docs/guides/.gitkeep (project-specific guides)
        5. Copies docs/templates/* to docs/formal/* (branded)
        6. Copies docs/index.md to docs/index.md (branded)
        7. Copies docs/quick_start.md to docs/quick_start.md (branded)

        Args:
            config: ProjectConfig instance
            verbose: Print detailed progress

        Returns:
            True if successful, False otherwise
        """
        source_docs = config.source_dir / 'docs'
        target_docs = config.target_dir / 'docs'

        if not source_docs.exists():
            print_warning("Source docs directory not found, skipping docs setup")
            return False

        if config.dry_run:
            print_info("  [DRY RUN] Would set up docs structure")
            return True

        try:
            # Create target docs directory
            target_docs.mkdir(parents=True, exist_ok=True)

            # 1. Update .gitmodules to change submodule path
            self._update_gitmodules_docs_path(config, verbose)

            # 2. Create docs/common directory for submodule mount point
            common_dir = target_docs / 'common'
            common_dir.mkdir(exist_ok=True)
            (common_dir / '.gitkeep').touch()
            if verbose:
                print_info("  Created docs/common/.gitkeep (submodule mount point)")

            # 3. Create docs/diagrams with .gitkeep
            diagrams_dir = target_docs / 'diagrams'
            diagrams_dir.mkdir(exist_ok=True)
            (diagrams_dir / '.gitkeep').touch()
            if verbose:
                print_info("  Created docs/diagrams/.gitkeep")

            # 4. Create docs/guides with .gitkeep
            guides_dir = target_docs / 'guides'
            guides_dir.mkdir(exist_ok=True)
            (guides_dir / '.gitkeep').touch()
            if verbose:
                print_info("  Created docs/guides/.gitkeep")

            # 5. Copy templates to docs/formal (with branding)
            source_templates = source_docs / 'templates'
            if source_templates.exists():
                target_formal = target_docs / 'formal'
                target_formal.mkdir(exist_ok=True)
                self._copy_and_brand_docs(
                    source_templates, target_formal, config, verbose
                )

            # 6. Copy and brand index.md
            source_index = source_docs / 'index.md'
            if source_index.exists():
                self._copy_and_brand_file(
                    source_index, target_docs / 'index.md', config, verbose
                )

            # 7. Copy and brand quick_start.md
            source_quickstart = source_docs / 'quick_start.md'
            if source_quickstart.exists():
                self._copy_and_brand_file(
                    source_quickstart, target_docs / 'quick_start.md', config, verbose
                )

            # 8. Create mount points for other submodules (scripts/python, test/python)
            for submodule_path in self.SUBMODULE_PATHS:
                mount_point = config.target_dir / submodule_path
                mount_point.mkdir(parents=True, exist_ok=True)
                (mount_point / '.gitkeep').touch()
                if verbose:
                    print_info(f"  Created {submodule_path}/.gitkeep (submodule mount point)")

            return True

        except Exception as e:
            print_warning(f"Error setting up docs structure: {e}")
            return False

    def _update_gitmodules_docs_path(self, config, verbose: bool = False) -> bool:
        """
        Update .gitmodules to change docs submodule path from 'docs' to 'docs/common'.

        Args:
            config: ProjectConfig instance
            verbose: Print detailed progress

        Returns:
            True if updated, False otherwise
        """
        gitmodules_path = config.target_dir / '.gitmodules'

        if not gitmodules_path.exists():
            if verbose:
                print_info("  No .gitmodules file found")
            return False

        try:
            content = gitmodules_path.read_text(encoding='utf-8')
            original = content

            # Update the docs submodule path from 'docs' to 'docs/common'
            # Match: path = docs (but not path = docs/something)
            content = re.sub(
                r'^(\s*path\s*=\s*)docs\s*$',
                r'\1docs/common',
                content,
                flags=re.MULTILINE
            )

            # Also update the submodule name from [submodule "docs"] to [submodule "docs/common"]
            content = re.sub(
                r'^\[submodule\s+"docs"\]',
                '[submodule "docs/common"]',
                content,
                flags=re.MULTILINE
            )

            if content != original:
                gitmodules_path.write_text(content, encoding='utf-8')
                if verbose:
                    print_info("  Updated .gitmodules: docs -> docs/common")
                return True
            else:
                if verbose:
                    print_info("  .gitmodules already configured for docs/common")
                return True

        except Exception as e:
            print_warning(f"Error updating .gitmodules: {e}")
            return False

    def _copy_and_brand_docs(
        self, source_dir: Path, target_dir: Path, config, verbose: bool = False
    ) -> int:
        """
        Copy and brand all files from source directory to target directory.

        Args:
            source_dir: Source directory
            target_dir: Target directory
            config: ProjectConfig instance
            verbose: Print detailed progress

        Returns:
            Number of files copied
        """
        count = 0
        replacements = self.get_replacement_pairs(config)

        for item in source_dir.iterdir():
            if item.is_file():
                target_file = target_dir / item.name
                self._copy_and_brand_file(item, target_file, config, verbose)
                count += 1
            elif item.is_dir():
                # Recursively copy subdirectories
                target_subdir = target_dir / item.name
                target_subdir.mkdir(exist_ok=True)
                count += self._copy_and_brand_docs(item, target_subdir, config, verbose)

        return count

    def _copy_and_brand_file(
        self, source_file: Path, target_file: Path, config, verbose: bool = False
    ) -> bool:
        """
        Copy a file and apply branding replacements.

        Args:
            source_file: Source file path
            target_file: Target file path
            config: ProjectConfig instance
            verbose: Print detailed progress

        Returns:
            True if successful, False otherwise
        """
        try:
            content = source_file.read_text(encoding='utf-8')

            # Apply branding replacements
            for old_text, new_text in self.get_replacement_pairs(config):
                content = content.replace(old_text, new_text)

            target_file.write_text(content, encoding='utf-8')
            if verbose:
                print_info(f"  Copied and branded: {target_file.name}")
            return True

        except UnicodeDecodeError:
            # Binary file - just copy without branding
            shutil.copy2(source_file, target_file)
            if verbose:
                print_info(f"  Copied (binary): {target_file.name}")
            return True

        except Exception as e:
            print_warning(f"Error copying {source_file}: {e}")
            return False

    def initialize_git_and_submodules(self, config, verbose: bool = False) -> bool:
        """
        Initialize git repository and add submodules.

        This method:
        1. Runs 'git init' in the target directory
        2. Parses .gitmodules to get submodule URLs and paths
        3. Removes empty mount point directories
        4. Runs 'git submodule add <url> <path>' for each submodule

        Args:
            config: ProjectConfig instance
            verbose: Print detailed progress

        Returns:
            True if successful, False otherwise
        """
        if config.dry_run:
            print_info("  [DRY RUN] Would initialize git and submodules")
            return True

        try:
            # Step 1: git init
            result = subprocess.run(
                ['git', 'init'],
                cwd=config.target_dir,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                print_warning(f"git init failed: {result.stderr}")
                return False
            if verbose:
                print_info("  Initialized git repository")

            # Step 2: Parse .gitmodules to get submodule info
            gitmodules_path = config.target_dir / '.gitmodules'
            if not gitmodules_path.exists():
                if verbose:
                    print_info("  No .gitmodules found, skipping submodule setup")
                return True

            submodules = self._parse_gitmodules(gitmodules_path)
            if not submodules:
                if verbose:
                    print_info("  No submodules defined in .gitmodules")
                return True

            # Step 3: For each submodule, remove empty mount point and add submodule
            for path, url in submodules:
                mount_point = config.target_dir / path

                # Remove empty mount point directory (created earlier with .gitkeep)
                if mount_point.exists():
                    import shutil
                    shutil.rmtree(mount_point)

                # Add submodule
                result = subprocess.run(
                    ['git', 'submodule', 'add', url, path],
                    cwd=config.target_dir,
                    capture_output=True,
                    text=True
                )
                if result.returncode != 0:
                    print_warning(f"git submodule add failed for {path}: {result.stderr}")
                    # Continue with other submodules
                elif verbose:
                    print_info(f"  Added submodule: {path}")

            return True

        except FileNotFoundError:
            print_warning("git command not found")
            return False
        except Exception as e:
            print_warning(f"Error initializing git: {e}")
            return False

    def _parse_gitmodules(self, gitmodules_path: Path) -> list:
        """
        Parse .gitmodules file to extract submodule paths and URLs.

        Args:
            gitmodules_path: Path to .gitmodules file

        Returns:
            List of (path, url) tuples
        """
        submodules = []
        current_path = None
        current_url = None

        try:
            content = gitmodules_path.read_text(encoding='utf-8')
            for line in content.splitlines():
                line = line.strip()
                if line.startswith('path = '):
                    current_path = line[7:].strip()
                elif line.startswith('url = '):
                    current_url = line[6:].strip()

                if current_path and current_url:
                    submodules.append((current_path, current_url))
                    current_path = None
                    current_url = None
        except Exception:
            pass

        return submodules
