#!/usr/bin/env python3
# ==============================================================================
# adapters/base.py - Base adapter for release management
# ==============================================================================
# Copyright (c) 2025 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
#
# Purpose:
#   Abstract base class for language-specific release adapters.
#   Provides common release operations and defines the interface for
#   language-specific implementations.
#
# Design Notes:
#   Following the same adapter pattern as brand_project and arch_guard.
#   Each language adapter implements version management, build, test,
#   and configuration file handling specific to that language.
#
# ==============================================================================

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
import re
import subprocess
import sys

# Support both direct script execution and module import
try:
    from ..models import Language
except ImportError:
    from models import Language


class BaseReleaseAdapter(ABC):
    """
    Abstract base class for language-specific release operations.

    Subclasses must implement:
        - name: Human-readable language name
        - detect(): Check if project is this language
        - load_project_info(): Load project metadata from config files
        - update_version(): Update version in config files
        - run_build(): Execute build commands
        - run_tests(): Execute test commands
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable language name (e.g., 'Go', 'Ada')."""
        pass

    @staticmethod
    @abstractmethod
    def detect(project_root: Path) -> bool:
        """
        Detect if a directory is a project of this language.

        Args:
            project_root: Path to check

        Returns:
            True if project detected
        """
        pass

    @abstractmethod
    def load_project_info(self, config) -> Tuple[str, str]:
        """
        Load project name and URL from language-specific config.

        Args:
            config: ReleaseConfig instance

        Returns:
            Tuple of (project_name, project_url)
        """
        pass

    @abstractmethod
    def update_version(self, config) -> bool:
        """
        Update version in language-specific configuration files.

        Args:
            config: ReleaseConfig instance

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    def run_build(self, config) -> bool:
        """
        Run language-specific build commands.

        Args:
            config: ReleaseConfig instance

        Returns:
            True if build successful
        """
        pass

    @abstractmethod
    def run_tests(self, config) -> bool:
        """
        Run language-specific test commands.

        Args:
            config: ReleaseConfig instance

        Returns:
            True if tests pass
        """
        pass

    def run_format(self, config) -> bool:
        """
        Run language-specific code formatting (optional).

        Default implementation does nothing.

        Args:
            config: ReleaseConfig instance

        Returns:
            True if successful
        """
        return True

    def sync_versions(self, config) -> bool:
        """
        Synchronize versions across project (optional).

        Default implementation does nothing.

        Args:
            config: ReleaseConfig instance

        Returns:
            True if successful
        """
        return True

    def generate_version_file(self, config) -> bool:
        """
        Generate version source file (optional).

        Default implementation does nothing.

        Args:
            config: ReleaseConfig instance

        Returns:
            True if successful
        """
        return True

    def cleanup_temp_files(self, config) -> bool:
        """
        Clean up temporary and build files.

        Default implementation runs 'make clean' if Makefile exists.

        Args:
            config: ReleaseConfig instance

        Returns:
            True if successful
        """
        makefile = config.project_root / 'Makefile'
        if makefile.exists():
            if getattr(config, 'dry_run', False):
                print("  [DRY-RUN] Would run 'make clean'")
                return True
            return self.run_command(['make', 'clean'], config.project_root) is not None
        return True

    def validate_makefile(self, config) -> bool:
        """
        Validate that all key Makefile targets work properly.

        Default implementation does basic validation. Language-specific
        adapters can override with comprehensive target lists.

        Args:
            config: ReleaseConfig instance

        Returns:
            True if all targets work
        """
        makefile = config.project_root / 'Makefile'
        if not makefile.exists():
            print("  No Makefile found, skipping validation")
            return True

        # Default targets to validate (override in subclass for language-specific)
        targets = ['help', 'build', 'clean']

        print("Validating Makefile targets...")
        for target in targets:
            result = self.run_command(
                ['make', target],
                config.project_root,
                capture_output=True,
                check=False
            )
            if result is None:
                print(f"  ✗ 'make {target}' failed")
                return False
            print(f"  ✓ make {target}")

        return True

    # =========================================================================
    # Common Operations (shared by all adapters)
    # =========================================================================

    def run_command(
        self,
        cmd: List[str],
        cwd: Path,
        capture_output: bool = False,
        check: bool = True
    ) -> Optional[str]:
        """
        Run a shell command.

        Args:
            cmd: Command as list of strings
            cwd: Working directory
            capture_output: Capture stdout/stderr
            check: Return None on non-zero exit (don't raise)

        Returns:
            stdout if capture_output, "SUCCESS" if succeeded, None on failure
        """
        try:
            if capture_output:
                # Capture output with encoding error handling for colorized output
                result = subprocess.run(
                    cmd,
                    cwd=cwd,
                    capture_output=True,
                    encoding='utf-8',
                    errors='replace'  # Handle non-UTF-8 chars (e.g., ANSI color codes)
                )
            else:
                result = subprocess.run(
                    cmd,
                    cwd=cwd,
                    text=True
                )
            if result.returncode != 0:
                if check:
                    print(f"Command failed: {' '.join(cmd)}")
                    if capture_output and result.stderr:
                        print(f"Error: {result.stderr}")
                return None
            return result.stdout if capture_output else "SUCCESS"
        except Exception as e:
            print(f"Command exception: {' '.join(cmd)}: {e}")
            return None

    def find_markdown_files(self, project_root: Path) -> List[Path]:
        """Find all markdown files with version headers."""
        md_files = []

        # Search in docs and root (exclude docs/common submodule)
        for pattern in ["docs/**/*.md", "*.md"]:
            for f in project_root.glob(pattern):
                if "/common/" not in str(f):
                    md_files.append(f)

        # Filter to only files with version headers
        versioned_files = []
        for md_file in md_files:
            try:
                content = md_file.read_text(encoding='utf-8')
                if re.search(
                    r'Version\s*[:)]|version\s*[:)]|\*\*Version\s+\d+\.\d+|Copyright\s*©\s*\d{4}',
                    content, re.IGNORECASE
                ):
                    versioned_files.append(md_file)
            except Exception:
                pass

        return versioned_files

    def replace_markdown_header(self, file_path: Path, config) -> bool:
        """
        Replace markdown metadata header with canonical format.

        Finds the header block (Version through Status lines) and replaces
        it entirely with a freshly generated canonical header.
        """
        try:
            content = file_path.read_text(encoding='utf-8')
            lines = content.split('\n')

            # Find header block boundaries
            header_start = None
            header_end = None

            for i, line in enumerate(lines):
                # Header starts at first **Version:** line
                if header_start is None and re.match(r'^\*\*Version:', line):
                    header_start = i
                # Header ends after **Status:** line
                elif header_start is not None and re.match(r'^\*\*Status:', line):
                    header_end = i + 1
                    break

            if header_start is None or header_end is None:
                return False  # No valid header block found

            # Generate canonical header
            status = "Unreleased" if config.is_prerelease else "Released"
            header_lines = [
                f"**Version:** {config.version}<br>",
                f"**Date:** {config.date_str}<br>",
                "**SPDX-License-Identifier:** BSD-3-Clause<br>",
                "**License File:** See the LICENSE file in the project root<br>",
                f"**Copyright:** © {config.year} Michael Gardner, A Bit of Help, Inc.<br>",
                f"**Status:** {status}",
            ]

            # Replace header block
            new_lines = lines[:header_start] + header_lines + lines[header_end:]
            new_content = '\n'.join(new_lines)

            if new_content != content:
                if getattr(config, 'dry_run', False):
                    return True  # Report as updated in dry-run
                file_path.write_text(new_content, encoding='utf-8')
                return True

            return False

        except Exception as e:
            print(f"Error replacing header in {file_path}: {e}")
            return False

    def add_markdown_header(self, file_path: Path, config) -> bool:
        """Add metadata header to markdown file if missing."""
        try:
            content = file_path.read_text(encoding='utf-8')
            lines = content.splitlines(keepends=True)

            # Find first # heading
            title_idx = None
            for i, line in enumerate(lines):
                if re.match(r'^#\s+\S', line):
                    title_idx = i
                    break

            if title_idx is None:
                return False

            # Check if header already exists (any bold metadata after title)
            # Look at lines immediately after title for existing header content
            if title_idx + 1 < len(lines):
                next_lines = ''.join(lines[title_idx + 1:title_idx + 10])
                if re.search(r'\*\*(?:Version|Project|Date|Copyright|SPDX)', next_lines):
                    # Header already exists, don't add another
                    return False

            # Create header
            status = "Unreleased" if config.is_prerelease else "Released"
            header = (
                "\n"
                f"**Version:** {config.version}<br>\n"
                f"**Date:** {config.date_str}<br>\n"
                f"**SPDX-License-Identifier:** BSD-3-Clause<br>\n"
                f"**License File:** See the LICENSE file in the project root<br>\n"
                f"**Copyright:** © {config.year} Michael Gardner, A Bit of Help, Inc.<br>\n"
                f"**Status:** {status}\n"
                "\n"
            )

            lines.insert(title_idx + 1, header)

            if getattr(config, 'dry_run', False):
                return True  # Report as added in dry-run

            file_path.write_text(''.join(lines), encoding='utf-8')
            return True

        except Exception as e:
            print(f"Error adding header to {file_path}: {e}")
            return False

    def update_all_markdown_files(self, config) -> int:
        """Update version in all markdown files. Returns count of updated files."""
        # Note: No files are skipped - all markdown files with version headers
        # are updated, including formal docs (SRS, SDS, STG)

        all_md_files = []
        # Include config/ directory for embedded restrictions README
        for pattern in ["docs/**/*.md", "*.md", "config/*.md"]:
            for f in config.project_root.glob(pattern):
                # Exclude docs/common submodule
                if "/common/" not in str(f):
                    all_md_files.append(f)

        updated_count = 0

        for md_file in all_md_files:
            try:
                content = md_file.read_text(encoding='utf-8')
                # Check for canonical header format (Version through Status block)
                has_header = bool(re.search(r'^\*\*Version:', content, re.MULTILINE))

                dry_prefix = "[DRY-RUN] Would update" if getattr(config, 'dry_run', False) else "Updated"
                dry_prefix_add = "[DRY-RUN] Would add" if getattr(config, 'dry_run', False) else "Added"

                if has_header:
                    if self.replace_markdown_header(md_file, config):
                        rel_path = md_file.relative_to(config.project_root)
                        print(f"  {dry_prefix} {rel_path}")
                        updated_count += 1
                else:
                    if self.add_markdown_header(md_file, config):
                        rel_path = md_file.relative_to(config.project_root)
                        print(f"  {dry_prefix_add} header to {rel_path}")
                        updated_count += 1

            except Exception as e:
                print(f"  Warning: Error processing {md_file}: {e}")

        return updated_count

    def validate_links(self, config) -> bool:
        """
        Validate links in documentation files.

        Checks:
        - External URLs (HTTP status)
        - Internal file references
        - Anchor links in markdown

        Args:
            config: ReleaseConfig instance

        Returns:
            True if all links are valid
        """
        import urllib.request
        import urllib.error

        print("Validating documentation links...")
        errors = []

        # Collect all markdown files
        md_files = list(config.project_root.glob("*.md"))
        md_files.extend(config.project_root.glob("docs/**/*.md"))

        # Extract and validate URLs
        external_urls = set()
        for md_file in md_files:
            try:
                content = md_file.read_text(encoding='utf-8')

                # Extract external URLs
                url_matches = re.findall(r'https?://[^\s\)\]"\'<>]+', content)
                for url in url_matches:
                    # Clean trailing punctuation
                    url = url.rstrip('.,;:')
                    # Skip SVG namespace URLs
                    if 'w3.org' in url:
                        continue
                    external_urls.add(url)

                # Check internal file references like [text](./path/file.md)
                internal_refs = re.findall(r'\]\((\./[^)#]+)\)', content)
                for ref in internal_refs:
                    ref_path = md_file.parent / ref
                    if not ref_path.exists():
                        errors.append(f"  ✗ {md_file.name}: broken reference '{ref}'")

                # Check anchor links like [text](#section-name)
                anchor_refs = re.findall(r'\]\((#[^)]+)\)', content)
                for anchor in anchor_refs:
                    # Convert anchor to expected heading format
                    expected_heading = anchor[1:].replace('-', ' ').lower()
                    # Extract all headings from the file
                    headings = re.findall(r'^#+\s+(.+)$', content, re.MULTILINE)
                    heading_slugs = [h.lower().replace(' ', '-').replace('/', '').replace('(', '').replace(')', '') for h in headings]
                    anchor_slug = anchor[1:].lower()
                    if anchor_slug not in heading_slugs:
                        # Be lenient - just warn, don't fail
                        print(f"  ⚠ {md_file.name}: anchor '{anchor}' may not exist")

            except Exception as e:
                print(f"  ⚠ Error reading {md_file}: {e}")

        # Validate external URLs (sample check - don't hammer servers)
        checked = 0
        max_checks = 10  # Limit external checks

        # Get project URL to skip self-references (won't exist until published)
        project_url = getattr(config, 'project_url', '') or ''

        for url in sorted(external_urls):
            if checked >= max_checks:
                remaining = len(external_urls) - checked
                print(f"  ... skipping {remaining} more URLs")
                break

            # Skip self-referencing URLs (project's own repo)
            if project_url and url.startswith(project_url):
                print(f"  ⊘ {url[:60]}... (self-reference, skipped)")
                continue

            try:
                req = urllib.request.Request(
                    url,
                    headers={'User-Agent': 'Mozilla/5.0 (link validator)'},
                    method='HEAD'
                )
                with urllib.request.urlopen(req, timeout=10) as response:
                    if response.status < 400:
                        print(f"  ✓ {url[:60]}...")
                    else:
                        errors.append(f"  ✗ {url} (HTTP {response.status})")
            except urllib.error.HTTPError as e:
                if e.code == 405:  # Method not allowed - try GET
                    try:
                        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                        with urllib.request.urlopen(req, timeout=10) as response:
                            print(f"  ✓ {url[:60]}...")
                    except Exception:
                        errors.append(f"  ✗ {url} (HTTP {e.code})")
                else:
                    errors.append(f"  ✗ {url} (HTTP {e.code})")
            except Exception as e:
                errors.append(f"  ✗ {url} ({type(e).__name__})")

            checked += 1

        # Check diagram files exist
        diagrams_dir = config.project_root / "docs" / "diagrams"
        if diagrams_dir.exists():
            puml_files = list(diagrams_dir.glob("*.puml"))
            svg_files = list(diagrams_dir.glob("*.svg"))

            for puml in puml_files:
                svg_path = puml.with_suffix('.svg')
                if svg_path not in svg_files:
                    errors.append(f"  ✗ Missing SVG for {puml.name}")
                else:
                    print(f"  ✓ {puml.name} → {svg_path.name}")

        if errors:
            print("\nLink validation errors:")
            for error in errors:
                print(error)
            return False

        print("  All links validated successfully")
        return True

    def verify_clean_working_tree(self, config) -> bool:
        """Verify git working tree is clean."""
        result = self.run_command(
            ["git", "status", "--porcelain"],
            config.project_root,
            capture_output=True
        )
        if result is None:
            return False
        return len(result.strip()) == 0

    def verify_submodules_current(self, config) -> Tuple[bool, List[str]]:
        """
        Verify all git submodules are clean and up-to-date with their remotes.

        Checks:
        1. Submodule working trees are clean (no uncommitted changes)
        2. Submodules are on their tracked branch (usually main)
        3. Submodules are not behind their upstream remote

        Args:
            config: ReleaseConfig instance

        Returns:
            Tuple of (all_current, list_of_issues)
            all_current: True if all submodules are clean and current
            issues: List of submodule issues found
        """
        print("Verifying git submodules are current...")
        issues = []

        # Check if project has submodules
        gitmodules = config.project_root / ".gitmodules"
        if not gitmodules.exists():
            print("  No submodules found (.gitmodules not present)")
            return True, []

        # Get submodule status
        result = self.run_command(
            ["git", "submodule", "status"],
            config.project_root,
            capture_output=True
        )

        if result is None:
            issues.append("  Could not read submodule status")
            return False, issues

        if not result.strip():
            print("  No submodules configured")
            return True, []

        submodules = []
        for line in result.strip().split('\n'):
            if not line.strip():
                continue
            # Format: " <sha> <path> (<branch>)" or "+<sha> <path> (<branch>)" for modified
            parts = line.split()
            if len(parts) >= 2:
                sha = parts[0].lstrip('+-')
                path = parts[1]
                has_changes = parts[0].startswith('+')
                submodules.append((path, sha, has_changes))

        print(f"  Found {len(submodules)} submodule(s)")

        for path, sha, has_local_changes in submodules:
            submodule_path = config.project_root / path
            submodule_name = path.split('/')[-1]

            # Check 1: Local changes in submodule
            if has_local_changes:
                issues.append(f"  {submodule_name}: Has uncommitted changes (marked with +)")

            # Check 2: Verify submodule working tree is clean
            status_result = self.run_command(
                ["git", "status", "--porcelain"],
                submodule_path,
                capture_output=True
            )
            if status_result and status_result.strip():
                issues.append(f"  {submodule_name}: Working tree is dirty")

            # Check 3: Fetch and compare with upstream
            # Fetch without modifying local state
            fetch_result = self.run_command(
                ["git", "fetch", "origin"],
                submodule_path,
                capture_output=True,
                check=False
            )

            if fetch_result is not None:
                # Check if behind origin/main
                behind_result = self.run_command(
                    ["git", "log", "HEAD..origin/main", "--oneline"],
                    submodule_path,
                    capture_output=True,
                    check=False
                )

                if behind_result and behind_result.strip():
                    commit_count = len(behind_result.strip().split('\n'))
                    issues.append(
                        f"  {submodule_name}: Behind origin/main by {commit_count} commit(s)"
                    )
                    # Show the commits
                    for commit in behind_result.strip().split('\n')[:3]:
                        issues.append(f"    - {commit}")
                    if commit_count > 3:
                        issues.append(f"    ... and {commit_count - 3} more")
                else:
                    print(f"  ✓ {submodule_name}: Up to date @ {sha[:8]}")
            else:
                # Couldn't fetch - maybe offline, just check local state
                print(f"  ⚠ {submodule_name}: Could not fetch (offline?), local state @ {sha[:8]}")

        all_current = len(issues) == 0

        if not all_current:
            print(f"\n  Found {len(issues)} submodule issue(s):")
            for issue in issues:
                print(issue)
            print("\n  To update submodules:")
            print("    git submodule update --remote --merge")
            print("    git add <submodule-path>")
            print("    git commit -m 'chore(deps): update submodules'")

        return all_current, issues

    def create_git_tag(self, config) -> bool:
        """Create annotated git tag, or skip if it already exists."""
        import subprocess
        tag_name = config.tag_name
        message = f"Release version {config.version}"

        # Check if tag already exists
        check_result = subprocess.run(
            ["git", "tag", "-l", tag_name],
            cwd=config.project_root,
            capture_output=True,
            text=True
        )
        if check_result.stdout.strip() == tag_name:
            print(f"  Tag {tag_name} already exists, skipping creation")
            return True

        result = self.run_command(
            ["git", "tag", "-a", tag_name, "-m", message],
            config.project_root
        )

        if result:
            print(f"  Created tag {tag_name}")
        return result is not None

    def push_changes(self, config) -> bool:
        """Push changes and tags to origin."""
        commands = [
            (["git", "push", "origin", "main"], "Pushed to main"),
            (["git", "push", "origin", config.tag_name], f"Pushed tag {config.tag_name}")
        ]

        for cmd, success_msg in commands:
            if self.run_command(cmd, config.project_root) is None:
                return False
            print(f"  {success_msg}")

        return True

    def create_github_release(self, config) -> bool:
        """Create or update GitHub release using gh CLI."""
        import subprocess
        changelog_file = config.project_root / "CHANGELOG.md"
        release_notes = f"Release version {config.version}"

        if changelog_file.exists():
            try:
                content = changelog_file.read_text(encoding='utf-8')
                version_pattern = (
                    rf'## \[{re.escape(config.version)}\][^\n]*\n'
                    r'(.*?)(?=\n## |\Z)'
                )
                match = re.search(version_pattern, content, re.DOTALL)
                if match:
                    release_notes = match.group(1).strip()
            except Exception as e:
                print(f"Warning: Could not extract release notes: {e}")

        # Check if release already exists
        check_result = subprocess.run(
            ["gh", "release", "view", config.tag_name],
            cwd=config.project_root,
            capture_output=True,
            text=True
        )

        if check_result.returncode == 0:
            # Release exists - update it
            cmd = [
                "gh", "release", "edit", config.tag_name,
                "--title", f"Release {config.version}",
                "--notes", release_notes
            ]
            result = self.run_command(cmd, config.project_root)
            if result:
                print(f"  Updated existing GitHub release {config.tag_name}")
            return result is not None
        else:
            # Release doesn't exist - create it
            cmd = [
                "gh", "release", "create", config.tag_name,
                "--title", f"Release {config.version}",
                "--notes", release_notes
            ]
            result = self.run_command(cmd, config.project_root)
            if result:
                print(f"  Created GitHub release {config.tag_name}")
            return result is not None

    def validate_documentation(self, config) -> Tuple[bool, List[str]]:
        """
        Validate documentation consistency across source code, tests, and docs.

        Checks for discrepancies between:
        - Source code comments (.go, .adb, .ads files)
        - Test files
        - Documentation files (docs/**, README.md, index.md)
        - Architecture terminology (library vs application patterns)

        Args:
            config: ReleaseConfig instance

        Returns:
            Tuple of (has_discrepancies, list_of_discrepancy_messages)
        """
        print("Validating documentation consistency...")
        discrepancies = []

        # Determine project type (library vs application)
        is_library = self._detect_project_type(config.project_root)
        project_type = "library" if is_library else "application"
        print(f"  Detected project type: {project_type}")

        # Define terminology checks based on project type
        if is_library:
            # Library should NOT have these terms (they belong to applications)
            forbidden_terms = [
                (r'\bbootstrap\b', "bootstrap", "api/adapter/desktop (composition root)"),
                (r'\bpresentation\b', "presentation", "api (facade)"),
                (r'\b5[-\s]?layer\b', "5-layer", "4-layer"),
                (r'\bCLI\s+command\b', "CLI command", "API facade"),
                (r'\bBootstrap\s+layer\b', "Bootstrap layer", "API layer"),
                (r'\bPresentation\s+layer\b', "Presentation layer", "API layer"),
            ]
            required_terms = [
                (r'\bapi\b', "api layer/facade"),
                (r'\b4[-\s]?layer\b', "4-layer architecture"),
            ]
        else:
            # Application should NOT have these terms (they belong to libraries)
            forbidden_terms = [
                (r'\bapi\s+facade\b', "api facade", "bootstrap/presentation"),
                (r'\bapi/adapter/desktop\b', "api/adapter/desktop", "bootstrap/cli"),
                (r'\b4[-\s]?layer\b', "4-layer", "5-layer"),
            ]
            required_terms = [
                (r'\bbootstrap\b', "bootstrap layer"),
                (r'\bpresentation\b', "presentation layer"),
                (r'\b5[-\s]?layer\b', "5-layer architecture"),
            ]

        # Collect all files to check
        files_to_check = []

        # Source code files
        for pattern in ["**/*.go", "**/*.adb", "**/*.ads"]:
            files_to_check.extend(config.project_root.glob(pattern))

        # Documentation files
        files_to_check.extend(config.project_root.glob("docs/**/*.md"))
        files_to_check.extend(config.project_root.glob("*.md"))

        # Exclude common false positive locations
        exclude_patterns = [
            "vendor/", "node_modules/", ".git/",
            "alire/cache/",  # Alire dependency cache (Ada)
            "docs/common/",  # Shared submodule docs (belong to reference project, not this project)
            "CHANGELOG.md",  # Changelog may reference old versions
            "architecture_enforcement.md",  # Generic architecture guide uses all layer terms
        ]

        for file_path in files_to_check:
            file_str = str(file_path)
            if any(excl in file_str for excl in exclude_patterns):
                continue

            try:
                content = file_path.read_text(encoding='utf-8')
                rel_path = file_path.relative_to(config.project_root)

                # Check for forbidden terms
                for pattern, term, replacement in forbidden_terms:
                    matches = list(re.finditer(pattern, content, re.IGNORECASE))
                    for match in matches:
                        # Get line number
                        line_num = content[:match.start()].count('\n') + 1
                        # Get context (the line containing the match)
                        lines = content.split('\n')
                        context = lines[line_num - 1].strip()[:60]

                        # Skip if this is in a comparison table (lib vs app) or markdown table
                        if '|' in context:
                            continue

                        discrepancies.append(
                            f"  {rel_path}:{line_num}: Found '{term}' "
                            f"(should be '{replacement}')\n    Context: {context}..."
                        )

                # Check for stale file references
                file_refs = re.findall(r'`([^`]+\.(go|md|ads|adb))`', content)
                for ref, _ in file_refs:
                    # Skip glob patterns like *_test.go
                    if '*' in ref:
                        continue
                    # Skip home directory references
                    if ref.startswith('~'):
                        continue
                    # Skip pattern templates like <layer> or <component>
                    if '<' in ref and '>' in ref:
                        continue
                    # Normalize path
                    ref_clean = ref.lstrip('./')
                    ref_path = config.project_root / ref_clean

                    # If file doesn't exist at root, check common subdirectories
                    if not ref_path.exists() and not ref_clean.startswith('http'):
                        found = False

                        # Try common parent directories for test files
                        if ref_clean.startswith('test_'):
                            for subdir in ['test/unit', 'test/integration', 'test/e2e']:
                                alt_path = config.project_root / subdir / ref_clean
                                if alt_path.exists():
                                    found = True
                                    break

                        # Search entire project for the filename if not found
                        # This handles cases where docs reference files by name only
                        if not found:
                            filename = Path(ref_clean).name
                            matches = list(config.project_root.glob(f"**/{filename}"))
                            # Exclude vendor, node_modules, .git, alire/cache
                            matches = [m for m in matches if not any(
                                excl in str(m) for excl in
                                ['vendor/', 'node_modules/', '.git/', 'alire/cache/']
                            )]
                            if matches:
                                found = True

                        # Also check if it's inside a tree block (contextual reference)
                        if not found:
                            idx = content.find(f'`{ref}`')
                            if idx >= 0:
                                # Check if this reference is inside a tree block
                                before_ref = content[:idx]
                                # If we're inside a tree block (odd number of ``` before)
                                tree_delims_before = before_ref.count('```')
                                if tree_delims_before % 2 == 1:
                                    # Inside a tree block - skip (contextual reference)
                                    found = True

                        if not found:
                            idx = content.find(f'`{ref}`')
                            if idx >= 0:
                                line_num = content[:idx].count('\n') + 1
                                discrepancies.append(
                                    f"  {rel_path}:{line_num}: Reference to non-existent file '{ref}'"
                                )

            except Exception as e:
                print(f"  Warning: Could not read {file_path}: {e}")

        # Check for directory structure consistency in docs
        # Only check top-level directories mentioned in trees
        top_level_dirs = {d.name for d in config.project_root.iterdir() if d.is_dir()}
        for md_file in config.project_root.glob("docs/**/*.md"):
            try:
                content = md_file.read_text(encoding='utf-8')
                rel_path = md_file.relative_to(config.project_root)

                # Find directory tree blocks and validate paths
                tree_blocks = re.findall(r'```\n([^`]+)\n```', content)
                for block in tree_blocks:
                    # Only check if this looks like a directory tree
                    if '/' in block and ('├' in block or '└' in block or '│' in block):
                        # Detect the tree root (first line with a path ending in /)
                        lines = block.strip().split('\n')
                        tree_root = None
                        for line in lines:
                            # Look for tree root like "test/" or "src/"
                            root_match = re.match(r'^(\w+)/$', line.strip())
                            if root_match:
                                tree_root = root_match.group(1)
                                break

                        # If tree has a root, validate directories relative to that root
                        if tree_root and tree_root in top_level_dirs:
                            # Tree is rooted at a valid directory (e.g., test/)
                            # Skip validation - subdirectories are relative to tree root
                            continue

                        # Only validate trees that appear to be project-root relative
                        # Look for top-level directory references (direct children of root)
                        top_refs = re.findall(r'^[├└│─\s]{0,4}(\w+)/', block, re.MULTILINE)
                        for dir_name in top_refs:
                            # Skip project name references (hybrid_lib_go, hybrid_app_go, etc.)
                            project_name = config.project_root.resolve().name
                            # Skip if it's already a known tree root (validated above)
                            if dir_name == tree_root:
                                continue
                            if dir_name not in top_level_dirs and dir_name not in ['hybrid', 'go', project_name]:
                                discrepancies.append(
                                    f"  {rel_path}: Directory tree shows '{dir_name}/' but it doesn't exist at project root"
                                )
            except Exception as e:
                continue

        # Report results
        has_discrepancies = len(discrepancies) > 0

        if has_discrepancies:
            print(f"\n  Found {len(discrepancies)} potential discrepancy(ies):\n")
            for d in discrepancies:
                print(d)
        else:
            print("  All documentation is consistent")

        return has_discrepancies, discrepancies

    def _detect_project_type(self, project_root: Path) -> bool:
        """
        Detect if project is a library (vs application).

        Args:
            project_root: Path to project root

        Returns:
            True if library, False if application
        """
        # Check for library indicators
        # Go structure: api/, bootstrap/, cmd/ at root
        # Ada structure: src/api/, src/bootstrap/, src/cmd/ under src/
        api_dir = project_root / "api"
        api_dir_ada = project_root / "src" / "api"
        bootstrap_dir = project_root / "bootstrap"
        bootstrap_dir_ada = project_root / "src" / "bootstrap"
        cmd_dir = project_root / "cmd"
        cmd_dir_ada = project_root / "src" / "cmd"

        has_api = api_dir.exists() or api_dir_ada.exists()
        has_bootstrap = bootstrap_dir.exists() or bootstrap_dir_ada.exists()
        has_cmd = cmd_dir.exists() or cmd_dir_ada.exists()

        # Libraries have api/ but not bootstrap/ or cmd/
        if has_api and not has_bootstrap and not has_cmd:
            return True

        # Applications have bootstrap/ and/or cmd/
        if has_bootstrap or has_cmd:
            return False

        # Check GPR files for Library_Name or Library_Kind (Ada projects)
        for gpr_file in project_root.glob("*.gpr"):
            try:
                content = gpr_file.read_text()
                # Library_Name or Library_Kind in GPR indicates a library
                if "Library_Name" in content or "Library_Kind" in content:
                    return True
            except Exception:
                pass

        # Check project name as fallback
        project_name = project_root.name.lower()
        if "_lib_" in project_name or project_name.endswith("_lib"):
            return True
        if "_app_" in project_name or project_name.endswith("_app"):
            return False

        # Default to application
        return False

    def validate_ai_assistance_section(self, config) -> Tuple[bool, List[str]]:
        """
        Validate that README.md contains the required AI Assistance & Authorship section.

        This is a LEGALLY CRITICAL validation. The section MUST:
        1. Exist in README.md
        2. Appear BETWEEN Contributing and License sections (standard position 12)
        3. Contain the required content about AI tools being tools, not authors

        Args:
            config: ReleaseConfig instance

        Returns:
            Tuple of (is_valid, list_of_error_messages)
        """
        print("Validating AI Assistance & Authorship section...")
        errors = []

        readme_path = config.project_root / "README.md"

        # Check if README.md exists
        if not readme_path.exists():
            errors.append("  ✗ README.md not found")
            return False, errors

        try:
            content = readme_path.read_text(encoding='utf-8')
            lines = content.split('\n')

            # Find the AI Assistance section
            ai_section_pattern = r'^#{1,3}\s+AI\s+Assist\w*\s*[&]\s*Author\w*'
            ai_section_match = re.search(ai_section_pattern, content, re.MULTILINE | re.IGNORECASE)

            if not ai_section_match:
                errors.append("  ✗ Missing 'AI Assistance & Authorship' section")
                errors.append("    Required section heading: '## AI Assistance & Authorship'")
                errors.append("    See documentation agent for required content")
                return False, errors

            ai_section_start = ai_section_match.start()
            ai_section_line = content[:ai_section_start].count('\n') + 1
            print(f"  ✓ Found AI Assistance section at line {ai_section_line}")

            # Find key sections to validate placement
            # Standard order: Contributing (11) -> AI Assistance (12) -> License (13)
            contributing_match = re.search(
                r'^#{1,3}\s+Contribut',
                content, re.MULTILINE | re.IGNORECASE
            )
            license_match = re.search(
                r'^#{1,3}\s+License\b',
                content, re.MULTILINE | re.IGNORECASE
            )

            # Validate: AI section should appear AFTER Contributing (if present)
            if contributing_match:
                contributing_line = content[:contributing_match.start()].count('\n') + 1
                if ai_section_line < contributing_line:
                    errors.append(f"  ✗ AI Assistance section (line {ai_section_line}) appears BEFORE Contributing section (line {contributing_line})")
                    errors.append("    It should appear AFTER Contributing section")
                else:
                    print(f"  ✓ AI Assistance section correctly placed after Contributing (line {contributing_line})")

            # Validate: AI section should appear BEFORE License
            if license_match:
                license_line = content[:license_match.start()].count('\n') + 1
                if ai_section_line > license_line:
                    errors.append(f"  ✗ AI Assistance section (line {ai_section_line}) appears AFTER License section (line {license_line})")
                    errors.append("    It MUST appear BEFORE License section")
                else:
                    print(f"  ✓ AI Assistance section correctly placed before License (line {license_line})")

            # Validate required content keywords
            # Extract the AI section content (until next heading or end)
            ai_section_end_match = re.search(
                r'\n#{1,3}\s+\S',
                content[ai_section_start + len(ai_section_match.group()):],
            )
            if ai_section_end_match:
                ai_section_content = content[ai_section_start:ai_section_start + len(ai_section_match.group()) + ai_section_end_match.start()]
            else:
                ai_section_content = content[ai_section_start:]

            # Check for required phrases
            required_phrases = [
                (r'human\s+developer', "human developer(s)"),
                (r'AI\s+(?:coding\s+)?assistant', "AI coding assistants"),
                (r'tool', "tools (not authors)"),
                (r'responsible|accountable|maintain', "responsibility/accountability"),
            ]

            missing_phrases = []
            for pattern, description in required_phrases:
                if not re.search(pattern, ai_section_content, re.IGNORECASE):
                    missing_phrases.append(description)

            if missing_phrases:
                errors.append("  ⚠ AI Assistance section may be missing required content:")
                for phrase in missing_phrases:
                    errors.append(f"    - Missing reference to: {phrase}")
            else:
                print("  ✓ AI Assistance section contains required content")

        except Exception as e:
            errors.append(f"  ✗ Error reading README.md: {e}")
            return False, errors

        is_valid = len([e for e in errors if '✗' in e]) == 0

        if is_valid:
            print("  ✓ AI Assistance & Authorship section validation passed")
        else:
            print("\n  AI Assistance section validation FAILED:")
            for error in errors:
                print(error)

        return is_valid, errors

    def validate_spark_section(self, config) -> Tuple[bool, List[str]]:
        """
        Validate SPARK Formal Verification section in README.md.

        Rules (per documentation agent):
        - Ada projects: SPARK section MUST exist
        - Go projects: SPARK section MUST NOT exist (SPARK is Ada-specific)

        Args:
            config: ReleaseConfig instance

        Returns:
            Tuple of (is_valid, list_of_error_messages)
        """
        print("Validating SPARK Formal Verification section...")
        errors = []

        readme_path = config.project_root / "README.md"

        # Check if README.md exists
        if not readme_path.exists():
            errors.append("  ✗ README.md not found")
            return False, errors

        try:
            content = readme_path.read_text(encoding='utf-8')

            # Look for SPARK section
            spark_section_pattern = r'^#{1,3}\s+SPARK\s+(?:Formal\s+)?Verification'
            spark_section_match = re.search(spark_section_pattern, content, re.MULTILINE | re.IGNORECASE)

            # Determine expected presence based on language
            if config.language == Language.ADA:
                # Ada projects MUST have SPARK section
                if not spark_section_match:
                    errors.append("  ✗ Missing 'SPARK Formal Verification' section")
                    errors.append("    Ada projects MUST include a SPARK section in README.md")
                    errors.append("    See documentation agent for required format")
                    return False, errors

                spark_section_line = content[:spark_section_match.start()].count('\n') + 1
                print(f"  ✓ Found SPARK Formal Verification section at line {spark_section_line}")

                # Validate that Results references CHANGELOG (not hardcoded metrics)
                # Extract section content until next heading
                spark_section_start = spark_section_match.start()
                spark_section_end_match = re.search(
                    r'\n#{1,3}\s+(?!Verification|SPARK)',
                    content[spark_section_start + len(spark_section_match.group()):],
                )
                if spark_section_end_match:
                    spark_section_content = content[spark_section_start:spark_section_start + len(spark_section_match.group()) + spark_section_end_match.start()]
                else:
                    spark_section_content = content[spark_section_start:]

                # Check for CHANGELOG reference in Results
                if re.search(r'CHANGELOG', spark_section_content, re.IGNORECASE):
                    print("  ✓ SPARK Results references CHANGELOG (no drift)")
                else:
                    # Check if there are hardcoded metrics (numbers followed by checks/proved/etc)
                    if re.search(r'\d+\s+(?:checks|proved|unproved|subprograms)', spark_section_content, re.IGNORECASE):
                        errors.append("  ⚠ SPARK Results contains hardcoded metrics")
                        errors.append("    Results should reference CHANGELOG to prevent drift")
                        errors.append("    Use: See <a href=\"CHANGELOG.md\">CHANGELOG</a> for current proof statistics")

                print("  ✓ SPARK Formal Verification section validation passed")

            elif config.language == Language.GO:
                # Go projects MUST NOT have SPARK section
                if spark_section_match:
                    spark_section_line = content[:spark_section_match.start()].count('\n') + 1
                    errors.append(f"  ✗ SPARK section found at line {spark_section_line} but should not exist")
                    errors.append("    SPARK is Ada-specific; Go projects should omit this section")
                    return False, errors

                print("  ✓ No SPARK section found (correct for Go projects)")

            else:
                # Future languages (Rust, etc.) - skip for now
                print(f"  ℹ SPARK validation not applicable for {config.language.value} projects")

        except Exception as e:
            errors.append(f"  ✗ Error reading README.md: {e}")
            return False, errors

        is_valid = len([e for e in errors if '✗' in e]) == 0

        return is_valid, errors

    def scan_git_history_for_ai_markers(self, config) -> Tuple[bool, List[str]]:
        """
        Scan entire git history for AI assistant attribution markers.

        This validation checks all commits across all branches for prohibited
        AI attribution patterns that violate our git attribution policy.

        Patterns searched:
        - Co-Authored-By: Claude
        - Co-Authored-By: GPT
        - Generated with [Claude Code]
        - 🤖 Generated with
        - AI-assisted commit
        - Any anthropic.com or openai.com email addresses

        Args:
            config: ReleaseConfig instance

        Returns:
            Tuple of (is_clean, list_of_violations)
            is_clean: True if NO AI markers found (clean history)
            violations: List of commit hashes and details with AI markers
        """
        print("Scanning git history for AI assistant markers...")
        violations = []

        # Patterns to search for in commit messages
        ai_patterns = [
            r'Co-Authored-By:\s*Claude',
            r'Co-Authored-By:\s*GPT',
            r'Co-Authored-By:\s*Copilot',
            r'Co-Authored-By:.*@anthropic\.com',
            r'Co-Authored-By:.*@openai\.com',
            r'Generated with \[Claude Code\]',
            r'Generated with Claude',
            r'🤖\s*Generated',
            r'AI-assisted commit',
            r'Generated by Claude',
            r'Generated by GPT',
            r'Generated by AI',
            r'noreply@anthropic\.com',
            r'noreply@openai\.com',
        ]

        combined_pattern = '|'.join(ai_patterns)

        try:
            # Get all commits from all branches
            result = self.run_command(
                ['git', 'log', '--all', '--format=%H|%s|%an|%ae', '--'],
                config.project_root,
                capture_output=True,
                check=False
            )

            if result is None:
                print("  ⚠ Could not read git history")
                return True, []  # Assume clean if can't read

            commits = result.strip().split('\n') if result.strip() else []
            print(f"  Scanning {len(commits)} commits...")

            for commit_line in commits:
                if not commit_line or '|' not in commit_line:
                    continue

                parts = commit_line.split('|', 3)
                if len(parts) < 4:
                    continue

                commit_hash, subject, author_name, author_email = parts

                # Check author name/email
                if re.search(r'claude|anthropic|openai|gpt|copilot',
                            f"{author_name} {author_email}", re.IGNORECASE):
                    violations.append(
                        f"  Commit {commit_hash[:8]}: Author contains AI reference\n"
                        f"    Author: {author_name} <{author_email}>"
                    )
                    continue

                # Check commit subject
                if re.search(combined_pattern, subject, re.IGNORECASE):
                    violations.append(
                        f"  Commit {commit_hash[:8]}: Subject contains AI marker\n"
                        f"    Subject: {subject[:60]}..."
                    )
                    continue

                # Check full commit message
                full_msg_result = self.run_command(
                    ['git', 'log', '-1', '--format=%B', commit_hash],
                    config.project_root,
                    capture_output=True,
                    check=False
                )

                if full_msg_result and re.search(combined_pattern, full_msg_result, re.IGNORECASE):
                    # Find which pattern matched
                    for pattern in ai_patterns:
                        match = re.search(pattern, full_msg_result, re.IGNORECASE)
                        if match:
                            violations.append(
                                f"  Commit {commit_hash[:8]}: Message contains AI marker\n"
                                f"    Subject: {subject[:50]}...\n"
                                f"    Match: {match.group()}"
                            )
                            break

            # Also check all branches for AI-related names
            branches_result = self.run_command(
                ['git', 'branch', '-a', '--format=%(refname:short)'],
                config.project_root,
                capture_output=True,
                check=False
            )

            if branches_result:
                for branch in branches_result.strip().split('\n'):
                    if re.search(r'claude|gpt|copilot|ai-gen', branch, re.IGNORECASE):
                        violations.append(f"  Branch '{branch}': Name contains AI reference")

        except Exception as e:
            print(f"  ⚠ Error scanning git history: {e}")
            return True, []  # Assume clean on error

        is_clean = len(violations) == 0

        if is_clean:
            print(f"  ✓ Git history is clean - no AI markers found in {len(commits)} commits")
        else:
            print(f"\n  ⚠ Found {len(violations)} AI marker(s) in git history:")
            for violation in violations:
                print(violation)
            print("\n  These commits need to be cleaned from git history before release.")
            print("  Options:")
            print("    1. git rebase -i to edit commit messages")
            print("    2. git filter-branch to remove patterns")
            print("    3. BFG Repo-Cleaner for large-scale cleanup")

        return is_clean, violations

    def _extract_roadmap_description(
        self, lines: List[str], marker_line_idx: int
    ) -> str:
        """
        Extract a meaningful description for a ROADMAP marker.

        Looks at the marker line and following lines to find descriptive
        content like feature names, function stubs, or explanatory comments.

        Args:
            lines: All lines of the file
            marker_line_idx: 0-indexed line number of the ROADMAP marker

        Returns:
            A concise description string, or empty string if none found
        """
        # First, check the marker line itself for inline description
        # e.g., "ROADMAP: Strengthen postconditions (see roadmap.md)"
        marker_line = lines[marker_line_idx].strip()
        if 'ROADMAP:' in marker_line:
            # Extract text after "ROADMAP:"
            after_marker = marker_line.split('ROADMAP:', 1)[1].strip()
            # Remove trailing references like "(see roadmap.md)" and trailing
            # punctuation
            after_marker = re.sub(r'\s*\(see\s+\S+\)\s*:?$', '', after_marker)
            after_marker = after_marker.rstrip(':')
            if after_marker and after_marker.lower() not in [
                'deferred pending user demand',
                'deferred',
                'disabled'
            ]:
                return after_marker[:70]

        # Look at up to 5 lines after the marker for context
        max_look_ahead = 5

        for i in range(marker_line_idx + 1,
                       min(marker_line_idx + max_look_ahead + 1, len(lines))):
            line = lines[i].strip()

            # Skip empty lines and separator lines
            if not line or line.startswith('--  ===') or line == '--':
                continue

            # Strip Ada comment prefix
            if line.startswith('--'):
                line = line[2:].strip()

            # Skip if still just decoration or pragma
            if (line.startswith('===') or line.startswith('---') or
                    line.startswith('pragma ')):
                continue

            # Look for "with" imports (indicates feature ports)
            if line.startswith('with '):
                # Extract package name
                pkg = line.replace('with ', '').rstrip(';')
                if 'Import_Cache' in pkg:
                    return "Import_Cache - Load timezone cache from file"
                elif 'Export_Cache' in pkg:
                    return "Export_Cache - Save timezone cache to file"
                else:
                    return f"Feature: {pkg.split('.')[-1]}"

            # Look for subtype/function declarations (commented out)
            if line.startswith('subtype ') or line.startswith('function '):
                name = line.split()[1].rstrip('(').rstrip(';')
                if 'Import' in name:
                    return "Import_Cache types - Cache import path/result types"
                elif 'Export' in name:
                    return "Export_Cache types - Cache export path/result types"
                return f"Stub: {name}"

            # Skip Ada code artifacts
            if (line.startswith('Buffer ') or line.startswith('end ') or
                    line.startswith('procedure ') or line.startswith('package ')):
                continue

            # Look for descriptive comments
            if any(kw in line.lower() for kw in
                   ['cache', 'import', 'export', 'implement', 'windows',
                    'postcondition', 'buffer', 'configurable', 'disabled',
                    'parser', 'validation', 'management', 'strategy']):
                # Capitalize first letter and truncate
                desc = line[0].upper() + line[1:] if line else line
                return desc[:60] + "..." if len(desc) > 60 else desc

        # Fallback: return first meaningful line after marker (non-code)
        for i in range(marker_line_idx + 1,
                       min(marker_line_idx + 3, len(lines))):
            line = lines[i].strip()
            if line.startswith('--'):
                line = line[2:].strip()
            # Skip code-like lines
            if (line and not line.startswith('===') and
                    not line.startswith('Buffer ') and
                    not line.startswith('pragma ') and
                    not line.startswith('end ')):
                return line[:60] + "..." if len(line) > 60 else line

        return ""

    def scan_for_code_markers(self, config) -> Tuple[bool, List[str]]:
        """
        Scan source code for TODO, FIXME, STUB, XXX, HACK, and ROADMAP markers.

        These markers indicate incomplete or temporary code that should be
        reviewed before release. Finding these doesn't necessarily block
        release, but the user should be aware of them.

        ROADMAP markers indicate planned future work tracked in roadmap.md.

        Args:
            config: ReleaseConfig instance

        Returns:
            Tuple of (is_clean, list_of_findings)
            is_clean: True if NO markers found
            findings: List of file:line details with markers
        """
        print("Scanning source code for TODO/FIXME/STUB/ROADMAP markers...")
        findings = []

        # Patterns to search for (case-insensitive)
        # Note: ROADMAP pattern excludes "roadmap.md" file references
        marker_patterns = [
            (r'\bTODO\b', 'TODO'),
            (r'\bFIXME\b', 'FIXME'),
            (r'\bSTUB\b', 'STUB'),
            (r'\bXXX\b', 'XXX'),
            (r'\bHACK\b', 'HACK'),
            (r'\bROADMAP\b(?!\.\w)', 'ROADMAP'),
            (r'\bnot\s+implemented\b', 'NOT IMPLEMENTED'),
            (r'\bunimplemented\b', 'UNIMPLEMENTED'),
        ]

        # File patterns to scan based on language
        file_patterns = []
        if hasattr(config, 'language'):
            if config.language == Language.ADA:
                file_patterns = ['**/*.ads', '**/*.adb']
            elif config.language == Language.GO:
                file_patterns = ['**/*.go']

        # Fallback: scan common source file types
        if not file_patterns:
            file_patterns = ['**/*.ads', '**/*.adb', '**/*.go', '**/*.py']

        # Directories to exclude
        exclude_dirs = [
            'vendor/', 'node_modules/', '.git/', 'alire/cache/',
            '__pycache__/', '.mypy_cache/', 'obj/', 'lib/', 'bin/',
        ]

        # Collect all source files
        source_files = []
        for pattern in file_patterns:
            source_files.extend(config.project_root.glob(pattern))

        # Filter excluded directories
        source_files = [
            f for f in source_files
            if not any(excl in str(f) for excl in exclude_dirs)
        ]

        print(f"  Scanning {len(source_files)} source files...")

        for file_path in source_files:
            try:
                content = file_path.read_text(encoding='utf-8')
                lines = content.split('\n')
                rel_path = file_path.relative_to(config.project_root)

                for line_num, line in enumerate(lines, 1):
                    for pattern, marker_name in marker_patterns:
                        if re.search(pattern, line, re.IGNORECASE):
                            # Get trimmed context
                            context = line.strip()[:70]
                            if len(line.strip()) > 70:
                                context += "..."

                            # For ROADMAP markers, extract description from
                            # following lines
                            description = ""
                            if marker_name == 'ROADMAP':
                                description = self._extract_roadmap_description(
                                    lines, line_num - 1  # 0-indexed
                                )

                            finding = f"  [{marker_name}] {rel_path}:{line_num}:"
                            if description:
                                finding += f"\n    {description}"
                            else:
                                finding += f"\n    {context}"

                            findings.append(finding)
                            break  # Only report first marker per line

            except Exception as e:
                print(f"  ⚠ Error reading {file_path}: {e}")

        is_clean = len(findings) == 0

        if is_clean:
            print(f"  ✓ No TODO/FIXME/STUB markers found in {len(source_files)} files")
        else:
            print(f"\n  Found {len(findings)} code marker(s):")
            for finding in findings:
                print(finding)

        return is_clean, findings

    def scan_for_long_files(self, config, max_lines: int = 800) -> Tuple[bool, List[str]]:
        """
        Scan source files for those exceeding the line limit.

        Long files often indicate need for refactoring or decomposition.
        This is advisory - user can continue without penalty.

        Args:
            config: ReleaseConfig instance
            max_lines: Maximum lines before flagging (default 800)

        Returns:
            Tuple of (is_clean, list_of_findings)
            is_clean: True if NO files exceed limit
            findings: List of file details exceeding limit
        """
        print(f"Scanning for source files exceeding {max_lines} lines...")
        findings = []

        # File patterns to scan (polyglot)
        file_patterns = ['**/*.ads', '**/*.adb', '**/*.go', '**/*.py', '**/*.rs']

        # Directories to exclude
        exclude_dirs = [
            'vendor/', 'node_modules/', '.git/', 'alire/cache/',
            '__pycache__/', '.mypy_cache/', 'obj/', 'lib/', 'bin/',
        ]

        # Collect all source files
        source_files = []
        for pattern in file_patterns:
            source_files.extend(config.project_root.glob(pattern))

        # Filter excluded directories
        source_files = [
            f for f in source_files
            if not any(excl in str(f) for excl in exclude_dirs)
        ]

        print(f"  Checking {len(source_files)} source files...")

        for file_path in source_files:
            try:
                content = file_path.read_text(encoding='utf-8')
                line_count = content.count('\n') + 1
                rel_path = file_path.relative_to(config.project_root)

                if line_count > max_lines:
                    findings.append(
                        f"  {rel_path}: {line_count} lines (exceeds {max_lines})"
                    )

            except Exception as e:
                print(f"  ⚠ Error reading {file_path}: {e}")

        # Sort by line count (descending) - extract count from string
        findings.sort(key=lambda x: int(x.split(': ')[1].split(' ')[0]), reverse=True)

        is_clean = len(findings) == 0

        if is_clean:
            print(f"  ✓ All {len(source_files)} files are under {max_lines} lines")
        else:
            print(f"\n  Found {len(findings)} file(s) exceeding {max_lines} lines:")
            for finding in findings:
                print(finding)

        return is_clean, findings

    def validate_exception_boundaries(self, config) -> Tuple[bool, List[str]]:
        """
        Validate exception handling follows architectural rules.

        Architecture Rules (per SDS Section 6.3/4.7):
        - Infrastructure/Presentation: MUST use Functional.Try, NO manual exception handlers
        - Domain/Application/API: NO exception keyword allowed (Result types only)
        - Bootstrap/Main/Test: exception handlers ALLOWED

        This validation is Ada-specific. Go projects do not have exceptions.

        Args:
            config: ReleaseConfig instance

        Returns:
            Tuple of (is_valid, list_of_violations)
            is_valid: True if no violations found
            violations: List of file:line details with violations
        """
        # Only validate Ada projects
        if hasattr(config, 'language') and config.language != Language.ADA:
            print("  ℹ Skipping exception boundary check (Go projects don't have exceptions)")
            return True, []

        # Check if this is an Ada project
        if not (config.project_root / 'alire.toml').exists():
            print("  ℹ Skipping exception boundary check (not an Ada project)")
            return True, []

        print("Validating exception handling boundaries...")
        violations = []

        # Layer definitions with their rules
        # Format: (path_pattern, layer_name, requires_functional_try, allows_manual_exception)
        layer_rules = [
            ('src/infrastructure/', 'Infrastructure', True, False),
            ('src/presentation/', 'Presentation', True, False),
            ('src/domain/', 'Domain', False, False),
            ('src/application/', 'Application', False, False),
            ('src/api/', 'API', False, False),
            # Bootstrap and Main are allowed to have exceptions
            ('src/bootstrap/', 'Bootstrap', False, True),
        ]

        # Main entry points that are allowed to have exceptions
        main_patterns = ['main.adb', 'greeter.adb']

        # Test files are exempt
        exempt_dirs = ['test/', 'tests/', 'examples/']

        # Pattern to detect exception block start
        exception_keyword_pattern = re.compile(r'\bexception\b', re.IGNORECASE)

        # Pattern to detect Functional.Try usage
        functional_try_pattern = re.compile(
            r'with\s+Functional\.Try\s*;', re.IGNORECASE
        )

        # Pattern to detect DESIGN DECISION or DELIBERATE comments that
        # indicate an intentional exception handler (e.g., for Preelaborate
        # packages that cannot use Functional.Try)
        design_decision_pattern = re.compile(
            r'--\s*(DESIGN DECISION|DELIBERATE)', re.IGNORECASE
        )

        # Collect all .adb source files in src/
        src_dir = config.project_root / 'src'
        if not src_dir.exists():
            print("  ℹ No src/ directory found, skipping exception boundary check")
            return True, []

        all_adb_files = list(src_dir.glob('**/*.adb'))

        # Filter exempt files
        def is_exempt(file_path: Path) -> bool:
            rel_path = str(file_path.relative_to(config.project_root))
            # Check exempt directories
            for exempt_dir in exempt_dirs:
                if rel_path.startswith(exempt_dir):
                    return True
            # Check main entry points
            if file_path.name in main_patterns:
                return True
            return False

        all_adb_files = [f for f in all_adb_files if not is_exempt(f)]

        print(f"  Scanning {len(all_adb_files)} Ada source files...")

        for file_path in all_adb_files:
            try:
                content = file_path.read_text(encoding='utf-8')
                rel_path = file_path.relative_to(config.project_root)
                rel_path_str = str(rel_path)

                # Determine which layer this file belongs to
                layer_name = None
                requires_functional_try = False
                allows_manual_exception = False

                for path_prefix, name, requires_try, allows_exc in layer_rules:
                    if rel_path_str.startswith(path_prefix):
                        layer_name = name
                        requires_functional_try = requires_try
                        allows_manual_exception = allows_exc
                        break

                # Skip files not in a known layer
                if layer_name is None:
                    continue

                # Skip Bootstrap (allowed to have exceptions)
                if allows_manual_exception:
                    continue

                # Check for exception keyword (excluding comments and design decisions)
                lines = content.split('\n')
                has_exception_keyword = False
                exception_line_num = 0

                for i, line in enumerate(lines, 1):
                    # Skip comments
                    stripped = line.strip()
                    if stripped.startswith('--'):
                        continue
                    # Remove inline comments
                    if '--' in line:
                        line = line[:line.index('--')]
                    # Check for exception keyword
                    if exception_keyword_pattern.search(line):
                        # Check if there's a DESIGN DECISION comment in
                        # the next 5 lines (covers 'when others =>' plus comment)
                        has_design_decision = False
                        for j in range(i, min(i + 6, len(lines) + 1)):
                            if j <= len(lines) and design_decision_pattern.search(lines[j - 1]):
                                has_design_decision = True
                                break
                        if has_design_decision:
                            continue  # Skip this exception - it's documented as intentional
                        has_exception_keyword = True
                        exception_line_num = i
                        break

                # Check for Functional.Try usage
                has_functional_try = bool(functional_try_pattern.search(content))

                # Validate rules based on layer
                if layer_name in ('Infrastructure', 'Presentation'):
                    # Boundary layers: must use Functional.Try, NO manual exceptions
                    if has_exception_keyword:
                        violations.append(
                            f"  [FORBIDDEN] {rel_path}:{exception_line_num}: "
                            f"Manual exception handler in {layer_name} layer. "
                            f"MUST use Functional.Try.Map_To_Result instead."
                        )

                elif layer_name in ('Domain', 'Application', 'API'):
                    # Core layers: NO exception keyword allowed at all
                    if has_exception_keyword:
                        violations.append(
                            f"  [FORBIDDEN] {rel_path}:{exception_line_num}: "
                            f"Exception keyword in {layer_name} layer. "
                            f"Core layers must use Result types only - no exceptions."
                        )

            except Exception as e:
                print(f"  ⚠ Error reading {file_path}: {e}")

        is_valid = len(violations) == 0

        if is_valid:
            print(f"  ✓ Exception boundary rules validated for {len(all_adb_files)} files")
        else:
            print(f"\n  Found {len(violations)} exception boundary violation(s):")
            for violation in violations:
                print(violation)
            print("\n  Reference: See SDS Section 6.3 (lib) or 4.7 (app) for exception boundary rules.")

        return is_valid, violations
