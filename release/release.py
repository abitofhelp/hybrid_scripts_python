#!/usr/bin/env python3
# ==============================================================================
# release.py - Unified Release Management Script
# ==============================================================================
# Copyright (c) 2025 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
#
# Purpose:
#   Unified release management for Go and Ada projects.
#   Auto-detects project language and applies appropriate release workflow.
#
# Usage:
#   python scripts/python/release/release.py prepare <version>
#   python scripts/python/release/release.py release <version>
#   python scripts/python/release/release.py validate <version>
#
# Examples:
#   python scripts/python/release/release.py prepare 1.0.0
#   python scripts/python/release/release.py release 1.0.0
#
# Design Notes:
#   Uses adapter pattern for language-specific operations.
#   Follows same patterns as arch_guard and brand_project.
#   Supports Go (go.mod) and Ada (alire.toml) projects.
#
# ==============================================================================

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple

# Support both direct script execution and module import
try:
    from .models import ReleaseConfig, Language, ReleaseAction
    from .adapters import GoReleaseAdapter, AdaReleaseAdapter
except ImportError:
    from models import ReleaseConfig, Language, ReleaseAction
    from adapters import GoReleaseAdapter, AdaReleaseAdapter

# Add parent directory to path for common imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from common import print_success, print_error, print_warning, print_info, print_section


def detect_language(project_root: Path) -> Optional[Language]:
    """
    Detect the project language from source directory.

    Args:
        project_root: Path to project directory

    Returns:
        Detected Language or None
    """
    if GoReleaseAdapter.detect(project_root):
        return Language.GO
    if AdaReleaseAdapter.detect(project_root):
        return Language.ADA
    return None


def get_adapter(language: Language):
    """
    Get the appropriate adapter for a language.

    Args:
        language: Target language

    Returns:
        Language adapter instance
    """
    adapters = {
        Language.GO: GoReleaseAdapter(),
        Language.ADA: AdaReleaseAdapter(),
    }
    return adapters.get(language)


def prompt_user_continue(message: str, allow_skip: bool = False) -> bool:
    """
    Prompt user to perform a manual task and continue.

    Args:
        message: Instructions for the user
        allow_skip: If True, user can skip this step

    Returns:
        True if user wants to continue, False to abort
    """
    print(f"\n{'='*70}")
    print(f"MANUAL STEP REQUIRED")
    print(f"{'='*70}")
    print(f"\n{message}\n")

    while True:
        if allow_skip:
            response = input("Press ENTER to continue, 's' to skip, or 'q' to quit: ").strip().lower()
            if response == '':
                return True
            elif response == 's':
                print("Skipping this step...")
                return True
            elif response == 'q':
                print("Release process aborted by user")
                return False
        else:
            response = input("Press ENTER to continue, or 'q' to quit: ").strip().lower()
            if response == '':
                return True
            elif response == 'q':
                print("Release process aborted by user")
                return False

        print("Invalid input. Please try again.")


def create_initial_changelog(config) -> str:
    """Create a clean Common Changelog format CHANGELOG.md for initial release."""
    today = datetime.now().strftime("%Y-%m-%d")

    return f"""# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Common Changelog](https://common-changelog.org),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Changed

### Added

### Removed

### Fixed

---

## [{config.version}] - {today}

_Initial release of {config.project_name}._

### Added

- Initial implementation with hexagonal architecture
- Domain layer with core business logic
- Application layer with use cases
- Infrastructure layer with adapters
- Presentation layer with CLI
- Comprehensive test suite

---

## License & Copyright

- **License**: BSD-3-Clause
- **Copyright**: (c) {config.year} Michael Gardner, A Bit of Help, Inc.
- **SPDX-License-Identifier**: BSD-3-Clause
"""


def has_meaningful_content(section_content: str) -> bool:
    """
    Check if a CHANGELOG section has meaningful content.

    Returns True if the section contains actual bullet points with content,
    not just placeholder text like "_Initial release._" or "TBD".

    Args:
        section_content: The content of a version section

    Returns:
        True if section has meaningful content (bullet points with text)
    """
    # Look for bullet points with actual content (- followed by text)
    has_bullets = bool(re.search(r'^-\s+\S', section_content, re.MULTILINE))

    # Check for placeholder text patterns
    placeholder_patterns = [
        r'^\s*_[^_]+_\s*$',  # Single italic line like "_Initial release._"
        r'TBD',
        r'placeholder',
        r'TODO',
    ]
    is_placeholder = any(
        re.search(pattern, section_content, re.IGNORECASE | re.MULTILINE)
        for pattern in placeholder_patterns
    )

    return has_bullets or (not is_placeholder and len(section_content.strip()) > 50)


def update_changelog(config) -> bool:
    """
    Update or create CHANGELOG.md with new version.

    Behavior:
    - For initial releases: Create or overwrite with clean template
    - For later versions: Update [Unreleased] to new version
    - If version section exists but is placeholder, check [Unreleased] for content
    """
    changelog_file = config.project_root / "CHANGELOG.md"

    # Check if version already exists in CHANGELOG
    if changelog_file.exists():
        existing_content = changelog_file.read_text(encoding='utf-8')
        version_match = re.search(
            rf'## \[{re.escape(config.version)}\]\s*-?\s*[^\n]*\n(.*?)(?=\n## |\Z)',
            existing_content,
            re.DOTALL
        )
        if version_match:
            version_content = version_match.group(1).strip()
            if has_meaningful_content(version_content):
                print(f"  Version [{config.version}] already exists with content")
                print(f"  Skipping CHANGELOG update (already prepared)")
                return True
            else:
                print_warning(f"Version [{config.version}] exists but has placeholder content")
                print_info("Checking [Unreleased] section for content to merge...")

    # Handle initial release - only create template if CHANGELOG doesn't exist
    # or is essentially empty/template-only
    if config.is_initial_release:
        if changelog_file.exists():
            existing_content = changelog_file.read_text(encoding='utf-8')
            # Check if existing CHANGELOG has substantial content (not just a template)
            # Look for actual content beyond headers and empty sections
            has_content = bool(re.search(r'###\s+\w+.*\n\s*-\s+\S', existing_content, re.DOTALL))
            if has_content:
                print(f"  CHANGELOG.md has existing content - preserving it")
                print(f"  Skipping template generation for initial release")
                return True

        content = create_initial_changelog(config)

        if config.dry_run:
            print(f"  [DRY-RUN] Would create CHANGELOG.md for initial release {config.version}")
            return True

        if changelog_file.exists():
            backup_file = config.project_root / "CHANGELOG.md.backup"
            changelog_file.rename(backup_file)
            print(f"  Backed up existing CHANGELOG.md to {backup_file.name}")

        changelog_file.write_text(content, encoding='utf-8')
        print(f"  Created CHANGELOG.md for initial release {config.version}")
        return True

    # Handle subsequent releases
    if not changelog_file.exists():
        print_error("CHANGELOG.md not found!")
        print_info("For releases after 1.0.0, CHANGELOG.md must exist.")
        return False

    try:
        content = changelog_file.read_text(encoding='utf-8')

        # Check if this version already exists
        if re.search(rf'## \[{re.escape(config.version)}\]', content):
            print_warning(f"Version [{config.version}] already exists in CHANGELOG.md")
            print_info("Skipping CHANGELOG update (appears to be already prepared)")
            return True

        # Find the [Unreleased] section
        unreleased_pattern = r'## \[Unreleased\]\s*\n(.*?)(?=\n## |\Z)'
        match = re.search(unreleased_pattern, content, re.DOTALL)

        if not match:
            print_error("Could not find [Unreleased] section in CHANGELOG.md")
            return False

        unreleased_content = match.group(1).strip()

        # Create new release section
        today = datetime.now().strftime("%Y-%m-%d")
        release_section = f"""## [Unreleased]

### Changed

### Added

### Removed

### Fixed

---

## [{config.version}] - {today}

{unreleased_content}

"""

        # Replace the unreleased section
        content = re.sub(
            r'## \[Unreleased\]\s*\n.*?(?=\n## |\Z)',
            release_section,
            content,
            flags=re.DOTALL,
            count=1
        )

        if config.dry_run:
            print(f"  [DRY-RUN] Would update CHANGELOG.md with release {config.version}")
            return True

        changelog_file.write_text(content, encoding='utf-8')
        print(f"  Updated CHANGELOG.md with release {config.version}")
        return True

    except Exception as e:
        print_error(f"Error updating changelog: {e}")
        return False


def run_windows_validation(config) -> Tuple[bool, str]:
    """
    Trigger Windows CI workflow and wait for completion.

    Uses GitHub CLI (gh) to trigger the workflow and monitor its status.

    Args:
        config: Release configuration

    Returns:
        Tuple of (success, message)
    """
    workflow_name = "windows-release.yml"

    # Check if gh CLI is available
    try:
        result = subprocess.run(
            ["gh", "--version"],
            capture_output=True,
            text=True,
            cwd=config.project_root
        )
        if result.returncode != 0:
            return False, "GitHub CLI (gh) not found. Install from https://cli.github.com/"
    except FileNotFoundError:
        return False, "GitHub CLI (gh) not found. Install from https://cli.github.com/"

    # Check if workflow file exists
    workflow_path = config.project_root / ".github" / "workflows" / workflow_name
    if not workflow_path.exists():
        return False, f"Workflow file not found: {workflow_path}"

    # Get current git ref (branch or commit)
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=config.project_root
    )
    if result.returncode != 0:
        return False, "Could not get current git commit"
    current_ref = result.stdout.strip()

    print_info(f"  Triggering Windows CI workflow...")
    print_info(f"  Ref: {current_ref[:8]}")
    print_info(f"  Version: {config.version}")

    if config.dry_run:
        print_info("  [DRY-RUN] Would trigger Windows workflow and wait for completion")
        return True, "Dry run - skipped"

    # Trigger the workflow
    result = subprocess.run(
        [
            "gh", "workflow", "run", workflow_name,
            "-f", f"version={config.version}",
            "-f", f"ref={current_ref}"
        ],
        capture_output=True,
        text=True,
        cwd=config.project_root
    )
    if result.returncode != 0:
        return False, f"Failed to trigger workflow: {result.stderr}"

    print_info("  Workflow triggered. Waiting for run to start...")

    # Wait a moment for the run to be created
    time.sleep(3)

    # Get the most recent run ID for this workflow
    max_attempts = 10
    run_id = None
    for attempt in range(max_attempts):
        result = subprocess.run(
            [
                "gh", "run", "list",
                "--workflow", workflow_name,
                "--limit", "1",
                "--json", "databaseId,status,headSha"
            ],
            capture_output=True,
            text=True,
            cwd=config.project_root
        )
        if result.returncode == 0:
            try:
                runs = json.loads(result.stdout)
                if runs and runs[0].get("headSha", "").startswith(current_ref[:7]):
                    run_id = runs[0]["databaseId"]
                    break
            except json.JSONDecodeError:
                pass
        time.sleep(2)

    if not run_id:
        return False, "Could not find workflow run. Check GitHub Actions manually."

    print_info(f"  Run ID: {run_id}")
    print_info("  Waiting for workflow to complete (this may take several minutes)...")

    # Watch the run until completion
    result = subprocess.run(
        ["gh", "run", "watch", str(run_id), "--exit-status"],
        capture_output=True,
        text=True,
        cwd=config.project_root
    )

    if result.returncode == 0:
        return True, "Windows validation passed"
    else:
        # Get more details about the failure
        detail_result = subprocess.run(
            ["gh", "run", "view", str(run_id), "--json", "conclusion,jobs"],
            capture_output=True,
            text=True,
            cwd=config.project_root
        )
        details = ""
        if detail_result.returncode == 0:
            try:
                run_info = json.loads(detail_result.stdout)
                details = f"\nConclusion: {run_info.get('conclusion', 'unknown')}"
                for job in run_info.get("jobs", []):
                    if job.get("conclusion") != "success":
                        details += f"\n  Failed job: {job.get('name')}"
            except json.JSONDecodeError:
                pass

        view_url = f"{config.project_url}/actions/runs/{run_id}" if config.project_url else ""
        return False, f"Windows validation failed.{details}\nView: {view_url}"


def prepare_release(config, adapter) -> bool:
    """Prepare release by updating versions and running checks."""
    print_section(f"\n{'='*70}")
    print_section(f"PREPARING RELEASE {config.version} ({adapter.name})")
    print_section(f"{'='*70}\n")

    # Step 0a: Validate Makefile targets
    print_info("\nStep 0a: Validating Makefile targets...")
    if not adapter.validate_makefile(config):
        print_error("Makefile validation failed - fix targets before release")
        return False

    # Step 0b: Validate documentation links
    print_info("\nStep 0b: Validating documentation links...")
    if not adapter.validate_links(config):
        print_error("Link validation failed - fix broken links before release")
        return False

    # Step 0c: Validate documentation consistency
    print_info("\nStep 0c: Validating documentation consistency...")
    has_discrepancies, discrepancies = adapter.validate_documentation(config)
    if has_discrepancies:
        message = f"""Documentation validation found {len(discrepancies)} potential discrepancy(ies).

Please review the items listed above.

These may be:
- Incorrect terminology for project type (library vs application)
- References to non-existent files
- Outdated directory structures in documentation

You can:
- Press ENTER to acknowledge and continue (if they are false positives)
- Press 'q' to quit and fix the issues before releasing"""
        if not prompt_user_continue(message):
            return False

    # Step 0d: Validate AI Assistance & Authorship section (LEGALLY CRITICAL)
    print_info("\nStep 0d: Validating AI Assistance & Authorship section...")
    is_valid, ai_errors = adapter.validate_ai_assistance_section(config)
    if not is_valid:
        print_error("AI Assistance & Authorship section validation FAILED")
        print_error("This is a LEGALLY CRITICAL requirement for all releases")
        print_info("")
        print_info("Required section in README.md:")
        print_info("  ### AI Assistance & Authorship")
        print_info("")
        print_info("  This project — including its source code, tests, documentation,")
        print_info("  and other deliverables — is designed, implemented, and maintained")
        print_info("  by human developers, with Michael Gardner as the Principal Software")
        print_info("  Engineer and project lead.")
        print_info("")
        print_info("  [... see documentation agent for full required content ...]")
        print_info("")
        print_info("Placement: After project description, BEFORE installation instructions")
        return False

    # Step 0e: Scan git history for AI markers (CRITICAL - git hygiene)
    print_info("\nStep 0e: Scanning git history for AI assistant markers...")
    is_clean, git_violations = adapter.scan_git_history_for_ai_markers(config)
    if not is_clean:
        print_warning(f"Found {len(git_violations)} AI marker(s) in git history")
        message = f"""Git history contains {len(git_violations)} AI attribution marker(s).

These MUST be removed before release per our git attribution policy.

Options to clean git history:
1. For recent commits: git rebase -i HEAD~N and edit messages
2. For older commits: git filter-branch or BFG Repo-Cleaner
3. Contact the maintainer for assistance

You can:
- Press ENTER to acknowledge and continue (if cleanup is planned)
- Press 'q' to quit and clean history before releasing"""
        if not prompt_user_continue(message):
            return False

    # Step 0f: Scan for TODO/FIXME/STUB/ROADMAP markers
    print_info("\nStep 0f: Scanning for TODO/FIXME/STUB/ROADMAP markers...")
    is_clean, code_markers = adapter.scan_for_code_markers(config)
    if not is_clean:
        message = f"""Found {len(code_markers)} code marker(s) in source code.

These markers indicate incomplete or temporary code that should be
reviewed before release:

- TODO: Planned work not yet completed
- FIXME: Known issues requiring fixes
- STUB: Placeholder implementations
- ROADMAP: Planned future work (see roadmap.md)
- XXX/HACK: Technical debt or workarounds

You can:
- Press ENTER to acknowledge and continue (if these are acceptable for release)
- Press 'q' to quit and address the markers before releasing"""
        if not prompt_user_continue(message):
            return False

    # Step 0g: Scan for long files
    print_info("\nStep 0g: Scanning for long source files...")
    is_clean, long_files = adapter.scan_for_long_files(config, max_lines=800)
    if not is_clean:
        message = f"""Found {len(long_files)} source file(s) exceeding 800 lines.

Long files may indicate:
- Need for refactoring or decomposition
- Single Responsibility Principle violations
- Accumulated technical debt

You can:
- Press ENTER to acknowledge and continue (advisory only)
- Press 'q' to quit and refactor before releasing"""
        if not prompt_user_continue(message):
            return False

    # Step 0h: Validate exception handling boundaries (Ada only)
    if 'exceptions' not in getattr(config, 'skip_stages', set()):
        print_info("\nStep 0h: Validating exception handling boundaries...")
        is_valid, violations = adapter.validate_exception_boundaries(config)
        if not is_valid:
            message = f"""Found {len(violations)} exception boundary violation(s).

Architecture Rules (per SDS):
- Infrastructure/Presentation: MUST use Functional.Try.Map_To_Result
- Domain/Application/API: NO exception keyword allowed (Result types only)
- Bootstrap/Main/Test: exceptions allowed

These violations MUST be fixed before release.
See SDS Section 6.3 (lib) or 4.7 (app) for details.

Press 'q' to quit and fix the violations."""
            if not prompt_user_continue(message):
                return False
    else:
        print_info("\nStep 0h: Skipping exception boundary validation (--skip=exceptions)")

    # Step 1: Clean up temporary files
    print_info("\nStep 1: Cleaning up temporary files...")
    if not adapter.cleanup_temp_files(config):
        print_warning("Could not clean up temporary files (continuing)")

    # Step 2: Update version in config files
    print_info(f"\nStep 2: Updating {adapter.name} version...")
    if not adapter.update_version(config):
        return False

    # Step 3: Sync versions (if applicable)
    print_info("\nStep 3: Syncing layer versions...")
    if not adapter.sync_versions(config):
        print_warning("Could not sync layer versions (continuing)")

    # Step 4: Generate version file (if applicable)
    print_info("\nStep 4: Generating version file...")
    if not adapter.generate_version_file(config):
        print_warning("Could not generate version file (continuing)")

    # Step 5: Update markdown documentation
    print_info("\nStep 5: Updating markdown documentation...")
    adapter.update_all_markdown_files(config)

    # Step 5a: Validate SPARK section in README (after doc update)
    print_info("\nStep 5a: Validating SPARK Formal Verification section...")
    is_valid, spark_errors = adapter.validate_spark_section(config)
    if not is_valid:
        print_error("SPARK section validation FAILED")
        print_info("")
        print_info("Rules (per documentation agent):")
        print_info("  - Ada projects: SPARK section MUST exist in README.md")
        print_info("  - Go projects: SPARK section MUST NOT exist (Ada-specific)")
        print_info("")
        print_info("For Ada projects, see documentation agent for required format.")
        print_info("Results field should reference CHANGELOG, not hardcoded metrics.")
        message = """SPARK section validation failed.

You can:
- Press ENTER to acknowledge and continue (if fix is planned)
- Press 'q' to quit and fix before releasing"""
        if not prompt_user_continue(message):
            return False

    # Step 6: CHANGELOG checkpoint
    changelog_file = config.project_root / "CHANGELOG.md"
    if changelog_file.exists():
        content = changelog_file.read_text(encoding='utf-8')
        if not re.search(rf'## \[{re.escape(config.version)}\]', content):
            message = f"""FINAL CHECKPOINT: CHANGELOG.md Review

The script is about to modify CHANGELOG.md:
- It will move [Unreleased] content -> [{config.version}] section
- It will create a fresh [Unreleased] section

LAST CHANCE to edit CHANGELOG.md if needed:
1. Edit CHANGELOG.md (add/modify release notes in [Unreleased])
2. If you made changes, commit them:
   git add CHANGELOG.md
   git commit -m "docs: Update release notes for {config.version}"
3. Press ENTER to let the script process CHANGELOG.md

If CHANGELOG is already correct, just press ENTER to continue."""
            if not prompt_user_continue(message):
                return False

    # Step 6: Update CHANGELOG.md
    print_info("\nStep 6: Updating CHANGELOG.md...")
    if not update_changelog(config):
        return False

    # Step 7: Build verification (before commit - verify code compiles)
    print_info("\nStep 7: Running build...")
    if not adapter.run_build(config):
        print_error("Build failed")
        return False

    # Step 8: Test verification (before commit - verify tests pass and capture counts)
    print_info("\nStep 8: Running tests...")
    if not adapter.run_tests(config):
        print_error("Tests failed")
        return False

    # Step 8a: Update test counts in docs (Ada only - before commit)
    if hasattr(adapter, 'update_test_counts_in_docs'):
        print_info("\nStep 8a: Updating test counts in docs...")
        adapter.update_test_counts_in_docs(config)

    # Step 8b: Update README body version references (Ada only)
    if hasattr(adapter, 'update_readme_body_versions'):
        print_info("\nStep 8b: Updating README.md body versions...")
        adapter.update_readme_body_versions(config)

    # Checkpoint: Review and commit changes (now includes test counts)
    message = f"""All files have been updated for release {config.version}
>>>> DO NOT STAGE FOR COMMIT: /config/*_config.gpr, /config/*_config.h, /config/*_config.ads <<<<

Build and tests have passed. Test counts have been added to docs.

IMPORTANT: Review and commit changes NOW:

1. Review what changed:
   git diff

2. Commit the prepared release:
   git add -A
   git commit -m "chore: Prepare release {config.version}"

After committing, press ENTER to continue with additional verification."""
    if not prompt_user_continue(message):
        return False

    # Step 9: SPARK check (Ada libraries only - fast gate)
    skip_stages = getattr(config, 'skip_stages', set())
    if hasattr(adapter, 'run_spark_check') and 'spark' not in skip_stages:
        print_info("\nStep 9: Running SPARK legality check...")
        if not adapter.run_spark_check(config):
            print_error("SPARK check failed")
            return False
    elif 'spark' in skip_stages:
        print_info("\nStep 9: Skipping SPARK check (--skip=spark)")

    # Step 10: Windows CI validation (pre-flight check)
    workflow_path = config.project_root / ".github" / "workflows" / "windows-release.yml"
    if workflow_path.exists() and 'windows' not in skip_stages:
        print_info("\nStep 10: Running Windows CI validation (pre-flight)...")
        success, message = run_windows_validation(config)
        if not success:
            print_error(f"Windows validation failed: {message}")
            print_info("Use --skip=windows to bypass this check for local dev releases")
            return False
        print_success(f"  {message}")
    elif 'windows' in skip_stages:
        print_info("\nStep 10: Skipping Windows CI validation (--skip=windows)")
    else:
        print_info("\nStep 10: No Windows workflow found, skipping Windows validation")

    # Step 11: Verify submodules are current
    print_info("\nStep 11: Verifying submodules are current...")
    all_current, submodule_issues = adapter.verify_submodules_current(config)
    if not all_current:
        message = f"""Found {len(submodule_issues)} submodule issue(s).

Submodules should be up-to-date before release to ensure:
- Reproducible builds from the tagged release
- Correct dependency versions are captured
- No surprises when users clone the release

You can:
- Press ENTER to acknowledge and continue (if updating later)
- Press 'q' to quit and update submodules now"""
        if not prompt_user_continue(message):
            return False

    # Step 12: Reset config files to development mode (cleanup)
    # This ensures working tree is clean for 'release release' command
    print_info("\nStep 12: Resetting config files to development mode...")
    if hasattr(adapter, 'reset_config_to_development'):
        if adapter.reset_config_to_development(config):
            print_success("  Config files reset to development mode")
        else:
            print_warning("  Could not reset config files (manual cleanup may be needed)")
    else:
        # Fallback: use git checkout for config directory
        result = subprocess.run(
            ["git", "checkout", "config/"],
            capture_output=True,
            text=True,
            cwd=config.project_root
        )
        if result.returncode == 0:
            print_success("  Config files restored via git checkout")
        else:
            print_warning("  Could not reset config files (manual cleanup may be needed)")

    print_section(f"\n{'='*70}")
    print_success(f"RELEASE {config.version} PREPARED AND VERIFIED SUCCESSFULLY!")
    print_section(f"{'='*70}\n")
    print_info("All files updated")
    print_info("Build passing")
    print_info("Tests passing (macOS)")
    if workflow_path.exists() and 'windows' not in skip_stages:
        print_info("Tests passing (Windows CI)")
    print_info("Submodules verified")
    print()
    print_info("Next step:")
    print_info(f"   python3 scripts/python/release/release.py release {config.version}")
    print()
    print_info("This will:")
    print_info(f"  - Create git tag v{config.version}")
    print_info("  - Push to GitHub")
    print_info("  - Create GitHub release with release notes")
    print()

    return True


def create_release(config, adapter) -> bool:
    """Create the actual release (tag and publish)."""
    print_section(f"\n{'='*70}")
    print_section(f"CREATING RELEASE {config.version} ({adapter.name})")
    print_section(f"{'='*70}\n")

    # Verify working tree is clean
    print_info("Verifying clean working tree...")
    if not adapter.verify_clean_working_tree(config):
        print_error("Working tree is not clean. Please commit changes first.")
        print_info("   Run: git status")
        return False
    print_success("Working tree is clean")

    # Create git tag
    print_info("\nCreating git tag...")
    if not adapter.create_git_tag(config):
        return False

    # Push changes and tag
    print_info("\nPushing to GitHub...")
    if not adapter.push_changes(config):
        return False

    # Create GitHub release
    print_info("\nCreating GitHub release...")
    if not adapter.create_github_release(config):
        return False

    # Alire index reminder (Ada projects)
    if config.language == 'ada':
        print_info("\n" + "="*60)
        print_info("ALIRE PUBLISH REMINDER")
        print_info("="*60)
        print_info("Before running 'alr publish', update your local Alire index")
        print_info("to access any new dependency releases:")
        print_info("")
        print_info("  # Update local Alire index cache")
        print_info("  alr index --update-all")
        print_info("")
        print_info("  # Verify dependency is visible (example)")
        print_info("  alr search <crate>=<version>")
        print_info("="*60 + "\n")

    # SPARK PROVE (Ada libraries only - post-release verification)
    spark_summary = None
    skip_stages = getattr(config, 'skip_stages', set())
    if hasattr(adapter, 'run_spark_prove') and 'spark' not in skip_stages:
        print_info("\nRunning SPARK PROVE formal verification...")
        print_info("(This may take several minutes - go have lunch!)")
        success, spark_summary = adapter.run_spark_prove(config)
        if success and spark_summary:
            # Update GitHub release with SPARK results
            if hasattr(adapter, 'update_github_release_with_spark'):
                adapter.update_github_release_with_spark(config, spark_summary)
            # Update README.md SPARK badges (Checked→Proved, mode→prove)
            if hasattr(adapter, 'update_spark_badges_in_readme'):
                adapter.update_spark_badges_in_readme(config, spark_summary)
            # Update CHANGELOG.md SPARK Status line
            if hasattr(adapter, 'update_changelog_spark_status'):
                adapter.update_changelog_spark_status(config, spark_summary)
            # Commit and push SPARK documentation updates
            import subprocess
            try:
                subprocess.run(['git', 'add', 'README.md', 'CHANGELOG.md'],
                             cwd=config.project_root, check=True, capture_output=True)
                subprocess.run(['git', 'commit', '-m', 'docs: update SPARK status after verification'],
                             cwd=config.project_root, check=True, capture_output=True)
                subprocess.run(['git', 'push'],
                             cwd=config.project_root, check=True, capture_output=True)
                print("  Committed and pushed SPARK documentation updates")
            except subprocess.CalledProcessError:
                print("  Note: No SPARK doc changes to commit (already up to date)")
    elif 'spark' in skip_stages:
        print_info("\nSkipping SPARK PROVE (--skip=spark)")

    print_section(f"\n{'='*70}")
    print_success(f"RELEASE {config.version} CREATED SUCCESSFULLY!")
    print_section(f"{'='*70}\n")
    print_info("Release is now live on GitHub!")
    if config.project_url:
        release_url = f"{config.project_url}/releases/tag/v{config.version}"
        print_info(f"View at: {release_url}")
    if spark_summary:
        print_info(f"SPARK verification: {spark_summary}")
    print()

    return True


def _run_capture(cmd, cwd):
    """Run a command capturing stdout/stderr. Never raises."""
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, errors='replace'
    )


def _verify_remote_annotated_tag(
    project_root,
    tag_name,
    expected_target_sha,
    expected_message,
):
    """Verify a remote annotated tag against a target commit + message via
    the GitHub Git Data API.

    Why not `git ls-remote`: on GitHub's smart-HTTP protocol, an exact-ref
    refspec like ``refs/tags/<tag>`` returns only the tag-object line and
    omits the peeled ``^{}`` line. The protocol is allowed to do this for
    exact-ref discovery (the peeled-commit advertisement is optional), so
    verifying the target commit from ``git ls-remote`` alone is unreliable
    on GitHub remotes. The Git Data API instead returns object types and
    target SHAs as explicit JSON fields and is authoritative.

    This function bit the rc-tag flow on adafmt v1.0.0-rc3 (2026-06-12).

    Verifies, in order, all five of:
      1. ``refs/tags/<tag>`` ref exists on the remote.
      2. ref object type is ``"tag"`` (annotated; lightweight rejected).
      3. tag object's ``object.type`` is ``"commit"``.
      4. tag object's ``object.sha`` equals ``expected_target_sha``.
      5. tag object's ``message`` equals ``expected_message`` after
         trailing-newline normalisation on both sides.

    The function is intentionally side-effect-free (read-only `gh api`
    calls) and returns a tuple instead of printing, so it can be unit-
    tested by mocking ``subprocess.run``.

    Args:
        project_root:        cwd for the ``gh`` CLI calls; ``gh`` auto-
                             detects the GitHub repo from the cwd's
                             git remote.
        tag_name:            e.g. ``"v1.0.0-rc3"``.
        expected_target_sha: full 40-char commit SHA the tag should peel
                             to.
        expected_message:    full annotated tag message expected on the
                             remote. Trailing newlines are normalised
                             out before comparison; internal whitespace,
                             blank lines, and body structure are
                             compared verbatim.

    Returns:
        ``(ok, diagnostic)``. On success, ``diagnostic`` is a short
        one-line descriptor of what was verified. On failure,
        ``diagnostic`` explains exactly which sub-check failed and why.
    """
    # 1. Resolve owner/repo so we can build absolute Git Data API paths.
    r = _run_capture(
        ["gh", "repo", "view", "--json", "owner,name",
         "--jq", "\"\\(.owner.login)/\\(.name)\""],
        project_root,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return False, (
            f"gh repo view failed (rc={r.returncode}): "
            f"{r.stderr.strip() or r.stdout.strip()}"
        )
    owner_repo = r.stdout.strip().strip('"')

    # 2. Fetch the tag ref. Non-zero rc covers both "not found" and
    # auth/network failure; either way, fail closed.
    r = _run_capture(
        ["gh", "api",
         f"repos/{owner_repo}/git/refs/tags/{tag_name}",
         "--jq", "{type: .object.type, sha: .object.sha}"],
        project_root,
    )
    if r.returncode != 0:
        return False, (
            f"gh api repos/{owner_repo}/git/refs/tags/{tag_name} failed "
            f"(rc={r.returncode}): {r.stderr.strip() or r.stdout.strip()}"
        )
    try:
        ref_data = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        return False, f"git/refs/tags JSON parse error: {e}; stdout={r.stdout!r}"

    # 3. Reject lightweight tags. GitHub reports a lightweight tag's ref
    # object.type as "commit" (it points straight at the commit, no
    # intermediate tag object). Annotated tags report "tag".
    ref_obj_type = ref_data.get("type")
    if ref_obj_type != "tag":
        return False, (
            f"remote ref object type is {ref_obj_type!r}, expected 'tag' "
            f"(annotated; lightweight tags are rejected)"
        )
    tag_obj_sha = ref_data.get("sha")
    if not tag_obj_sha:
        return False, "git/refs/tags response missing object.sha"

    # 4. Fetch the tag object to get target type, target SHA, and message.
    r = _run_capture(
        ["gh", "api",
         f"repos/{owner_repo}/git/tags/{tag_obj_sha}",
         "--jq",
         "{target_type: .object.type, target_sha: .object.sha, "
         "message: .message}"],
        project_root,
    )
    if r.returncode != 0:
        return False, (
            f"gh api repos/{owner_repo}/git/tags/{tag_obj_sha} failed "
            f"(rc={r.returncode}): {r.stderr.strip() or r.stdout.strip()}"
        )
    try:
        tag_data = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        return False, f"git/tags JSON parse error: {e}; stdout={r.stdout!r}"

    # 5. Verify target type, target SHA, and message.
    target_type = tag_data.get("target_type")
    if target_type != "commit":
        return False, (
            f"remote tag target type is {target_type!r}, expected 'commit'"
        )
    target_sha_remote = tag_data.get("target_sha") or ""
    if target_sha_remote != expected_target_sha:
        return False, (
            f"remote tag target {target_sha_remote} != expected "
            f"{expected_target_sha}"
        )
    remote_msg = (tag_data.get("message") or "").rstrip('\n')
    expected_norm = (expected_message or "").rstrip('\n')
    if remote_msg != expected_norm:
        return False, (
            f"remote tag message mismatch — "
            f"expected ({len(expected_norm)} chars): {expected_norm!r}; "
            f"remote ({len(remote_msg)} chars): {remote_msg!r}"
        )

    return True, (
        f"obj={tag_obj_sha[:12]}, target={target_sha_remote[:12]}, "
        f"msg={len(remote_msg)} chars"
    )


# ---------------------------------------------------------------------------
# Partial-state remediation messages for rc-tag.
#
# Each helper is called on a hard failure that occurs after one or more
# mutations succeeded, so the user always knows what state to clean up.
# ---------------------------------------------------------------------------

def _emit_remediation_local_tag_only(tag_name):
    print_warning(
        "\n  PARTIAL STATE: a local annotated tag was created but no remote "
        "action completed.\n"
        f"  Local tag present     : {tag_name}\n"
        "  Remote tag present    : NO\n"
        "  GitHub Release present: NO\n"
        "  release-linux.yml run : NOT DISPATCHED\n"
        "  Roll back the local-only tag:\n"
        f"    git tag -d {tag_name}\n"
    )


def _emit_remediation_remote_tag_only(tag_name):
    print_warning(
        "\n  PARTIAL STATE: the annotated tag was pushed to origin but the "
        "GitHub Release was not created.\n"
        f"  Local tag present     : {tag_name}\n"
        f"  Remote tag present    : {tag_name}\n"
        "  GitHub Release present: NO\n"
        "  release-linux.yml run : MAY HAVE DISPATCHED (tag push triggers it)\n"
        "  Choices:\n"
        "    (a) Retry Release creation (tag is already in place):\n"
        f"        gh release create {tag_name} --draft --prerelease "
        "--verify-tag \\\n"
        "          --title <TITLE> --notes-file <PATH>\n"
        "    (b) Roll back the tag (cancels release-linux.yml if still "
        "running):\n"
        f"        git push origin :refs/tags/{tag_name}\n"
        f"        git tag -d {tag_name}\n"
    )


def _emit_remediation_release_created(tag_name):
    print_warning(
        "\n  PARTIAL STATE: the tag and a draft Release exist; verification "
        "of the Release failed.\n"
        f"  Local tag present     : {tag_name}\n"
        f"  Remote tag present    : {tag_name}\n"
        f"  GitHub Release present: {tag_name} (state unverified)\n"
        "  release-linux.yml run : likely dispatched\n"
        "  Inspect:\n"
        f"    gh release view {tag_name} --json "
        "isDraft,isPrerelease,tagName,targetCommitish\n"
        "    gh run list --workflow=release-linux.yml --event=push --limit 5\n"
        "  Roll back (if needed):\n"
        f"    gh release delete {tag_name} --yes\n"
        f"    git push origin :refs/tags/{tag_name}\n"
        f"    git tag -d {tag_name}\n"
    )


def _emit_remediation_workflow_missing(tag_name):
    print_warning(
        "\n  PARTIAL STATE: tag and draft Release exist, but no matching "
        "release-linux.yml run was detected.\n"
        f"  Local tag present     : {tag_name}\n"
        f"  Remote tag present    : {tag_name}\n"
        f"  GitHub Release present: {tag_name} (draft, prerelease)\n"
        "  release-linux.yml run : NOT DETECTED\n"
        "  Inspect:\n"
        "    gh workflow view release-linux.yml\n"
        "    gh run list --workflow=release-linux.yml --limit 10\n"
        "  Possible causes:\n"
        f"    - on:push:tags filter in the workflow file does not match "
        f"{tag_name}\n"
        "    - repository Actions are disabled\n"
        "    - GitHub Actions outage\n"
        "  Manual dispatch (if the workflow supports workflow_dispatch):\n"
        f"    gh workflow run release-linux.yml --ref {tag_name}\n"
        "  Roll back (if needed):\n"
        f"    gh release delete {tag_name} --yes\n"
        f"    git push origin :refs/tags/{tag_name}\n"
        f"    git tag -d {tag_name}\n"
    )


def create_rc_release(config, adapter, args) -> bool:
    """Create a release candidate as a DRAFT + PRERELEASE GitHub Release
    backed by an explicit annotated tag at a caller-supplied commit SHA.

    SAFETY ORDERING (post-Codex review of PR #16):
      The annotated tag is created and pushed BEFORE the GitHub Release is
      created, and the Release is created with --verify-tag. This prevents
      `gh release create` from auto-creating a remote tag of its own
      (which could be lightweight or otherwise unintended).

    Every gh/git boundary operation is followed by an explicit post-state
    verification step. Silent return is never inferred as success
    (see feedback_no_silent_success_inference_at_boundaries).

    Ordered steps:
      1. Preflight (read-only, fail-closed):
         - clean working tree
         - HEAD == main == origin/main == target (single canonical state;
           caller may not tag anything other than the current main HEAD)
         - local tag absent
         - remote tag absent (distinguish not-found from query-failure)
         - GitHub Release absent (distinguish not-found from query-failure)
         - release-notes file present, non-empty, and byte-identical to
           its committed content at the target SHA
      2. git tag -a <tag> <SHA> -m <message>
      3. Verify local tag:
         - object type is "tag" (annotated, not lightweight)
         - peels to target SHA
         - FULL annotated tag message matches the expected message
           (only trailing newlines are normalized; internal structure
           and body content are compared verbatim)
      4. Capture before_push UTC timestamp; git push origin refs/tags/<tag>
         (tag only — never main)
      5. Verify remote tag peels to target SHA
      6. gh release create <tag> --draft --prerelease --verify-tag
         (refuses to create if tag absent; never auto-creates a tag)
      7. Verify Release: isDraft + isPrerelease + tagName
      8. Confirm release-linux.yml dispatched a matching run.
         Filter: workflow=release-linux.yml AND event=push AND
                 createdAt >= before_push_iso - 30s AND
                 (headBranch == <tag> OR headSha == <target>)
         Hard failure if no matching run is found within ~40 s.
      9. Summary + manual publish step (gh release edit <tag> --draft=false).

    --dry-run is strictly non-mutating: every mutation step (including
    `git fetch`, `git tag`, `git push`, `gh release create`) is skipped.
    Read-only preflight verifications still run; they use whatever cached
    remote-tracking refs already exist (caller should `git fetch` first
    if fresh state is required).

    On hard failure at any step *after* a mutation has succeeded, a
    PARTIAL-STATE remediation block is printed naming exactly what
    survived and how to roll it back or recover.

    Args:
        config:  ReleaseConfig (project_root, version, dry_run).
        adapter: Language adapter (only used for verify_clean_working_tree).
        args:    argparse.Namespace carrying target, tag_message,
                 release_title, release_notes_file.

    Returns:
        True on success, False on any failure.
    """
    tag_name = config.tag_name  # "v<version>"
    target_sha = args.target
    tag_message = args.tag_message or f"Release candidate {config.version}"
    release_title = args.release_title or f"Release {config.version}"
    dry = bool(config.dry_run)

    print_section(f"\n{'='*70}")
    print_section(
        f"RC-TAG {tag_name} -> {target_sha[:12]} (DRAFT, PRERELEASE)"
        + (" [DRY-RUN]" if dry else "")
    )
    print_section(f"{'='*70}\n")

    # =====================================================================
    # Step 1: PREFLIGHT (read-only; runs in dry-run too; fail-closed)
    # =====================================================================
    print_section("Step 1/9: Preflight")

    # 1a. Working tree clean
    print_info("  1a. Verifying clean working tree...")
    if not adapter.verify_clean_working_tree(config):
        print_error("  Working tree is not clean.")
        return False
    print_success("  Working tree is clean")

    # 1b. Fetch origin (refs + tags). NOT a no-op — it writes to
    # .git/refs/remotes/origin/. Codex review: skip in dry-run.
    if dry:
        print_info(
            "  1b. [DRY-RUN] Skipping `git fetch origin --tags` "
            "(would mutate refs/remotes/origin/*).\n"
            "      Using cached remote-tracking refs. Run "
            "`git fetch origin --tags` before --dry-run if fresh state "
            "is required."
        )
    else:
        print_info("  1b. Fetching origin (refs + tags)...")
        r = _run_capture(
            ["git", "fetch", "origin", "--tags"], config.project_root
        )
        if r.returncode != 0:
            print_error(f"  git fetch failed: {r.stderr.strip()}")
            return False
        print_success("  Fetched origin")

    # 1c. HEAD == main == origin/main == target (single canonical state).
    print_info(
        "  1c. Verifying HEAD == main == origin/main == target..."
    )
    head_r = _run_capture(
        ["git", "rev-parse", "HEAD"], config.project_root
    )
    main_r = _run_capture(
        ["git", "rev-parse", "main"], config.project_root
    )
    remote_r = _run_capture(
        ["git", "rev-parse", "origin/main"], config.project_root
    )
    if (head_r.returncode != 0 or main_r.returncode != 0
            or remote_r.returncode != 0):
        print_error(
            "  Query failed: cannot resolve one of HEAD/main/origin/main.\n"
            f"  HEAD       : rc={head_r.returncode} {head_r.stderr.strip()!r}\n"
            f"  main       : rc={main_r.returncode} {main_r.stderr.strip()!r}\n"
            f"  origin/main: rc={remote_r.returncode} {remote_r.stderr.strip()!r}"
        )
        return False
    head_sha = head_r.stdout.strip()
    main_sha = main_r.stdout.strip()
    remote_main_sha = remote_r.stdout.strip()

    # Resolve target SHA to a full canonical commit SHA.
    r = _run_capture(
        ["git", "rev-parse", "--verify", f"{target_sha}^{{commit}}"],
        config.project_root,
    )
    if r.returncode != 0:
        print_error(
            f"  Target SHA does not resolve to a commit: {target_sha} "
            f"({r.stderr.strip()})"
        )
        return False
    resolved_target = r.stdout.strip()

    if not (head_sha == main_sha == remote_main_sha == resolved_target):
        print_error(
            "  Required canonical state not satisfied:\n"
            f"    HEAD        = {head_sha}\n"
            f"    main        = {main_sha}\n"
            f"    origin/main = {remote_main_sha}\n"
            f"    target      = {resolved_target}\n"
            "  All four must be equal. To recover, either:\n"
            "    - check out main + fast-forward to origin/main, OR\n"
            "    - re-invoke rc-tag with --target equal to current "
            "origin/main HEAD."
        )
        return False
    print_success(
        f"  HEAD == main == origin/main == target == {resolved_target[:12]}"
    )

    # 1d. Local tag absent (fail-closed on query failure).
    print_info(f"  1d. Verifying local tag {tag_name} absent...")
    r = _run_capture(
        ["git", "tag", "-l", tag_name], config.project_root
    )
    if r.returncode != 0:
        print_error(
            f"  Query failed (git tag -l, rc={r.returncode}): "
            f"{r.stderr.strip()}. Aborting (fail-closed)."
        )
        return False
    if r.stdout.strip() == tag_name:
        print_error(f"  Local tag {tag_name} already exists.")
        return False
    print_success(f"  Local tag {tag_name} absent")

    # 1e. Remote tag absent — distinguish not-found from query-failure
    # using `git ls-remote --exit-code`:
    #   rc=0  -> ref(s) found       (= tag exists, abort)
    #   rc=2  -> no matching refs   (= tag absent, ok)
    #   other -> network / auth     (= query failed, fail-closed)
    print_info(f"  1e. Verifying remote tag {tag_name} absent...")
    r = _run_capture(
        ["git", "ls-remote", "--exit-code", "--tags", "origin",
         f"refs/tags/{tag_name}"],
        config.project_root,
    )
    if r.returncode == 0:
        print_error(
            f"  Remote tag {tag_name} already exists:\n  {r.stdout.strip()}"
        )
        return False
    elif r.returncode == 2:
        print_success(
            f"  Remote tag {tag_name} absent (ls-remote --exit-code=2)"
        )
    else:
        print_error(
            f"  Query failed (git ls-remote, rc={r.returncode}): "
            f"{r.stderr.strip() or r.stdout.strip()}.\n"
            "  Cannot determine whether remote tag exists. "
            "Aborting (fail-closed)."
        )
        return False

    # 1f. GitHub Release absent — fail-closed on query failure.
    #   rc=0                          -> exists, abort
    #   rc!=0 + "release not found"   -> absent, ok
    #   rc!=0 otherwise               -> query failed, fail-closed
    print_info(f"  1f. Verifying GitHub Release {tag_name} absent...")
    r = _run_capture(
        ["gh", "release", "view", tag_name, "--json", "tagName"],
        config.project_root,
    )
    if r.returncode == 0:
        print_error(f"  GitHub Release {tag_name} already exists.")
        return False
    stderr_lower = (r.stderr or "").lower()
    if "release not found" in stderr_lower:
        print_success(f"  GitHub Release {tag_name} absent")
    else:
        print_error(
            f"  Query failed (gh release view, rc={r.returncode}): "
            f"{r.stderr.strip() or r.stdout.strip()}\n"
            "  Cannot determine whether GitHub Release exists. "
            "Aborting (fail-closed)."
        )
        return False

    # 1g. Release-notes file present, non-empty, AND byte-identical to
    # the same path committed at the target SHA. This is what guarantees
    # the notes that ship with the Release are the ones reviewed under
    # the target commit.
    notes_path = Path(args.release_notes_file).expanduser()
    if not notes_path.is_absolute():
        notes_path = (config.project_root / notes_path).resolve()
    print_info(f"  1g. Verifying release-notes file: {notes_path}")
    if not notes_path.is_file():
        print_error(f"  Release-notes file not found: {notes_path}")
        return False
    if notes_path.stat().st_size == 0:
        print_error(f"  Release-notes file is empty: {notes_path}")
        return False
    try:
        rel_notes_path = notes_path.relative_to(config.project_root)
    except ValueError:
        print_error(
            f"  Release-notes file {notes_path} is outside project root "
            f"{config.project_root}; cannot verify it matches target SHA."
        )
        return False
    show_r = _run_capture(
        ["git", "show", f"{resolved_target}:{rel_notes_path}"],
        config.project_root,
    )
    if show_r.returncode != 0:
        print_error(
            f"  Notes file {rel_notes_path} not present at target SHA "
            f"{resolved_target[:12]}: {show_r.stderr.strip()}.\n"
            "  The release notes must already be committed at the target SHA."
        )
        return False
    tree_content = notes_path.read_text(encoding='utf-8', errors='replace')
    git_content = show_r.stdout
    if tree_content != git_content:
        # Tolerate LF/CRLF normalization on platforms that round-trip
        # text files through autocrlf — but only that.
        if (tree_content.replace('\r\n', '\n')
                != git_content.replace('\r\n', '\n')):
            print_error(
                "  Working-tree notes file content differs from the "
                f"content committed at target SHA {resolved_target[:12]}.\n"
                f"  Working tree: {len(tree_content)} chars\n"
                f"  Target SHA  : {len(git_content)} chars"
            )
            return False
    print_success(
        f"  Release-notes file present + matches target SHA "
        f"({notes_path.stat().st_size} bytes)"
    )

    # =====================================================================
    # Step 2: Create local annotated tag
    # =====================================================================
    print_section("\nStep 2/9: Create annotated tag locally")
    tag_cmd = [
        "git", "tag", "-a", tag_name, resolved_target, "-m", tag_message,
    ]
    state_local_tag_created = False
    if dry:
        print_info(f"  [DRY-RUN] Would run: {' '.join(tag_cmd)}")
    else:
        r = _run_capture(tag_cmd, config.project_root)
        if r.returncode != 0:
            print_error(
                f"  git tag failed (rc={r.returncode}): {r.stderr.strip()}"
            )
            return False  # no remediation: nothing to clean up yet
        state_local_tag_created = True
        print_success(f"  Created local annotated tag {tag_name}")

    # =====================================================================
    # Step 3: Verify local tag (annotated, peels to target, subject matches)
    # =====================================================================
    print_section("\nStep 3/9: Verify local tag is annotated + correct")
    local_tag_obj_sha = "(unknown)"
    if dry:
        _exp_msg_norm = tag_message.rstrip('\n')
        _exp_subject = _exp_msg_norm.split('\n', 1)[0]
        print_info(
            f"  [DRY-RUN] Would verify {tag_name}: object type=tag, "
            f"peels to {resolved_target[:12]}, full annotated message "
            f"matches expected ({len(_exp_msg_norm)} chars, "
            f"subject={_exp_subject!r})"
        )
    else:
        # 3a. Object type must be "tag" (annotated, not lightweight).
        r = _run_capture(
            ["git", "cat-file", "-t", tag_name], config.project_root
        )
        if r.returncode != 0:
            print_error(
                f"  git cat-file -t failed: {r.stderr.strip()}"
            )
            _emit_remediation_local_tag_only(tag_name)
            return False
        obj_type = r.stdout.strip()
        if obj_type != "tag":
            print_error(
                f"  Tag is not annotated (object type={obj_type}, expected "
                "'tag'). Lightweight tags are rejected."
            )
            _emit_remediation_local_tag_only(tag_name)
            return False

        # 3b. Tag peels to target SHA.
        r = _run_capture(
            ["git", "rev-list", "-n", "1", tag_name], config.project_root
        )
        if r.returncode != 0:
            print_error(f"  git rev-list failed: {r.stderr.strip()}")
            _emit_remediation_local_tag_only(tag_name)
            return False
        tagged_commit = r.stdout.strip()
        if tagged_commit != resolved_target:
            print_error(
                f"  Tag commit {tagged_commit} != expected "
                f"{resolved_target}"
            )
            _emit_remediation_local_tag_only(tag_name)
            return False

        # 3c. FULL annotated tag message matches expected.
        # `git for-each-ref --format=%(contents)` on an annotated tag ref
        # returns the entire tag message (subject + blank line + body, if
        # any), excluding the header lines (object/type/tag/tagger).
        #
        # Newline normalization: only trailing '\n' characters are stripped
        # from both sides; internal whitespace, blank lines, and body
        # structure are compared verbatim. A multi-line message is therefore
        # verified in full, not only by its subject line.
        r = _run_capture(
            ["git", "for-each-ref",
             "--format=%(contents)",
             f"refs/tags/{tag_name}"],
            config.project_root,
        )
        if r.returncode != 0:
            print_error(
                f"  git for-each-ref --format failed: {r.stderr.strip()}"
            )
            _emit_remediation_local_tag_only(tag_name)
            return False
        # An empty stdout here would indicate the ref didn't resolve to an
        # annotated tag (or didn't resolve at all); treat as fail.
        if r.stdout == "":
            print_error(
                f"  git for-each-ref returned empty output for "
                f"refs/tags/{tag_name}; cannot verify tag message."
            )
            _emit_remediation_local_tag_only(tag_name)
            return False
        actual_message = r.stdout.rstrip('\n')
        expected_message = tag_message.rstrip('\n')
        if actual_message != expected_message:
            print_error(
                "  Annotated tag message mismatch (full-message compare).\n"
                f"  Expected ({len(expected_message)} chars): "
                f"{expected_message!r}\n"
                f"  Actual   ({len(actual_message)} chars): "
                f"{actual_message!r}"
            )
            _emit_remediation_local_tag_only(tag_name)
            return False
        actual_subject = actual_message.split('\n', 1)[0]

        # 3d. Capture tag object SHA for reporting.
        r = _run_capture(
            ["git", "rev-parse", tag_name], config.project_root
        )
        if r.returncode == 0:
            local_tag_obj_sha = r.stdout.strip()

        print_success(
            f"  Annotated tag {tag_name} OK (obj={local_tag_obj_sha[:12]}, "
            f"commit={tagged_commit[:12]}, "
            f"msg={len(actual_message)} chars, "
            f"subject={actual_subject!r})"
        )

    # =====================================================================
    # Step 4: Capture before_push timestamp + push tag only
    # =====================================================================
    print_section("\nStep 4/9: Push tag to origin (tag only)")
    push_cmd = ["git", "push", "origin", f"refs/tags/{tag_name}"]
    before_push_dt = None
    state_remote_tag_pushed = False
    if dry:
        print_info(
            "  [DRY-RUN] Would capture before_push UTC timestamp, then "
            f"run: {' '.join(push_cmd)}"
        )
    else:
        before_push_dt = datetime.now(timezone.utc)
        before_push_iso = before_push_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        print_info(f"  before_push = {before_push_iso}")
        r = _run_capture(push_cmd, config.project_root)
        if r.returncode != 0:
            print_error(
                f"  git push failed (rc={r.returncode}): {r.stderr.strip()}"
            )
            _emit_remediation_local_tag_only(tag_name)
            return False
        state_remote_tag_pushed = True
        print_success(f"  Pushed tag {tag_name}")

    # =====================================================================
    # Step 5: Verify remote tag (annotated + correct target + correct
    # message) via GitHub Git Data API dereference.
    #
    # Note: a `git ls-remote --tags origin refs/tags/<tag>` exact-ref
    # query on GitHub smart-HTTP returns only the tag-object line, never
    # the peeled `^{}` line — so verifying the target commit from
    # ls-remote alone is unreliable. The Git Data API is authoritative.
    # See _verify_remote_annotated_tag for the full rationale.
    # =====================================================================
    print_section(
        "\nStep 5/9: Verify remote tag (via gh api Git Data dereference)"
    )
    if dry:
        _exp_msg_norm = (tag_message or "").rstrip('\n')
        print_info(
            f"  [DRY-RUN] Would verify via gh api: "
            f"refs/tags/{tag_name} object type=tag, "
            f"target type=commit, target SHA={resolved_target[:12]}, "
            f"message matches expected ({len(_exp_msg_norm)} chars)"
        )
    else:
        ok, diag = _verify_remote_annotated_tag(
            project_root=config.project_root,
            tag_name=tag_name,
            expected_target_sha=resolved_target,
            expected_message=tag_message,
        )
        if not ok:
            print_error(
                f"  Remote tag verification failed: {diag}"
            )
            _emit_remediation_remote_tag_only(tag_name)
            return False
        print_success(
            f"  Remote tag {tag_name} verified — {diag} "
            f"(local obj={local_tag_obj_sha[:12]})"
        )

    # =====================================================================
    # Step 6: Create GitHub draft prerelease using existing remote tag.
    # `--verify-tag` makes gh refuse the call if the tag does not already
    # exist on the remote — closing the door on accidental tag auto-create.
    # =====================================================================
    print_section(
        "\nStep 6/9: Create GitHub Release (draft, prerelease, --verify-tag)"
    )
    create_cmd = [
        "gh", "release", "create", tag_name,
        "--draft",
        "--prerelease",
        "--verify-tag",
        "--title", release_title,
        "--notes-file", str(notes_path),
    ]
    state_release_created = False
    if dry:
        print_info(f"  [DRY-RUN] Would run: {' '.join(create_cmd)}")
    else:
        r = _run_capture(create_cmd, config.project_root)
        if r.returncode != 0:
            print_error(
                f"  gh release create failed (rc={r.returncode}): "
                f"{r.stderr.strip()}"
            )
            _emit_remediation_remote_tag_only(tag_name)
            return False
        state_release_created = True
        print_success(
            f"  Created draft prerelease: {r.stdout.strip() or tag_name}"
        )

    # =====================================================================
    # Step 7: Verify Release state via re-query
    # =====================================================================
    print_section("\nStep 7/9: Verify Release state")
    if dry:
        print_info(
            "  [DRY-RUN] Would verify isDraft=true, isPrerelease=true, "
            f"tagName={tag_name}"
        )
    else:
        r = _run_capture(
            ["gh", "release", "view", tag_name,
             "--json", "isDraft,isPrerelease,tagName"],
            config.project_root,
        )
        if r.returncode != 0:
            print_error(f"  gh release view failed: {r.stderr.strip()}")
            _emit_remediation_release_created(tag_name)
            return False
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError as e:
            print_error(f"  Could not parse gh release view JSON: {e}")
            _emit_remediation_release_created(tag_name)
            return False
        if not data.get("isDraft"):
            print_error(f"  Release is not draft: {data}")
            _emit_remediation_release_created(tag_name)
            return False
        if not data.get("isPrerelease"):
            print_error(f"  Release is not prerelease: {data}")
            _emit_remediation_release_created(tag_name)
            return False
        if data.get("tagName") != tag_name:
            print_error(
                f"  Tag name mismatch: {data.get('tagName')} != {tag_name}"
            )
            _emit_remediation_release_created(tag_name)
            return False
        # targetCommitish on a Release created with --verify-tag may be
        # reported as the default branch name (e.g., "main") rather than
        # the commit SHA, because the tag→SHA binding lives on the tag
        # itself — which step 5 has already verified.
        print_success(
            f"  Release verified: draft + prerelease, tagName={tag_name}"
        )

    # =====================================================================
    # Step 8: Confirm release-linux.yml run started (HARD FAILURE if not)
    # Filter criteria:
    #   workflow == release-linux.yml
    #   event    == push
    #   createdAt >= before_push_iso - 30s  (clock-skew tolerance)
    #   headBranch == tag_name OR headSha == resolved_target
    # =====================================================================
    print_section("\nStep 8/9: Confirm release-linux.yml workflow run")
    new_run = None
    if dry:
        print_info(
            "  [DRY-RUN] Would filter `gh run list "
            "--workflow=release-linux.yml --event=push` by createdAt >= "
            "before_push - 30s AND (headBranch == tag OR headSha == "
            "target). HARD FAILURE if no match within ~40 s."
        )
    else:
        filter_floor_dt = before_push_dt - timedelta(seconds=30)
        filter_floor_iso = filter_floor_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        print_info(
            f"  Filter floor (before_push - 30s) = {filter_floor_iso}"
        )
        for attempt in range(8):  # up to ~40 s
            r = _run_capture(
                ["gh", "run", "list",
                 "--workflow=release-linux.yml",
                 "--event=push",
                 "--limit", "20",
                 "--json",
                 "databaseId,event,headBranch,headSha,status,createdAt,url"],
                config.project_root,
            )
            if r.returncode == 0:
                try:
                    runs = json.loads(r.stdout)
                except json.JSONDecodeError:
                    runs = []
                for run in runs:
                    if run.get("event") != "push":
                        continue
                    created_at = run.get("createdAt") or ""
                    if created_at < filter_floor_iso:
                        continue
                    head_branch = run.get("headBranch") or ""
                    head_sha = run.get("headSha") or ""
                    if (head_branch != tag_name
                            and head_sha != resolved_target):
                        continue
                    new_run = run
                    break
            if new_run is not None:
                break
            time.sleep(5)
        if new_run is None:
            print_error(
                "  HARD FAILURE: release-linux.yml run not found within "
                "40 s of tag push.\n"
                "  Filter criteria:\n"
                "    workflow  = release-linux.yml\n"
                "    event     = push\n"
                f"    createdAt >= {filter_floor_iso}\n"
                f"    headBranch == {tag_name} OR headSha == "
                f"{resolved_target[:12]}\n"
            )
            _emit_remediation_workflow_missing(tag_name)
            return False
        print_success(
            f"  Found run {new_run['databaseId']} "
            f"(status={new_run.get('status', 'unknown')}, "
            f"createdAt={new_run.get('createdAt')})"
        )

    # =====================================================================
    # Step 9: Summary + manual next steps
    # =====================================================================
    print_section("\nStep 9/9: Summary")
    print_section(f"\n{'='*70}")
    print_success(
        f"RC-TAG {tag_name} COMPLETE (draft + prerelease)"
        + (" [DRY-RUN]" if dry else "")
    )
    print_section(f"{'='*70}")
    print_info(f"Tag      : {tag_name} -> {resolved_target}")
    if not dry:
        print_info(f"Tag obj  : {local_tag_obj_sha}")
    if config.project_url:
        print_info(
            f"Release  : {config.project_url}/releases/tag/{tag_name}"
        )
    if not dry and new_run is not None:
        url = new_run.get('url') or f"(run id {new_run['databaseId']})"
        print_info(f"CI run   : {url}")
        print_info(f"CI state : {new_run.get('status', 'unknown')}")
    print_info("")
    print_info("NEXT STEPS (manual, after CI passes and artifacts uploaded):")
    print_info("  1. Smoke-test the release-linux.yml artifacts.")
    print_info(f"  2. Publish: gh release edit {tag_name} --draft=false")
    print()
    return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Unified release management for Go and Ada projects',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s prepare 1.0.0                Prepare release (all stages)
  %(prog)s prepare 1.0.0 --skip=spark   Skip SPARK verification
  %(prog)s prepare 1.0.0 --skip=windows,spark
                                        Skip multiple stages
  %(prog)s release 1.0.0                Create release (tag, push, GitHub)
  %(prog)s rc-tag 1.0.0-rc3 --target <SHA> \\
        --release-notes-file docs/release_notes/v1.0.0_draft.md
                                        Tag an RC at an explicit SHA as a
                                        draft, prerelease GitHub Release.

Skippable stages: windows, spark, exceptions, all

The script auto-detects the project language (Go/Ada) and applies
the appropriate release workflow.
        """
    )

    parser.add_argument(
        'action',
        choices=['prepare', 'release', 'validate', 'rc-tag'],
        help='Action to perform'
    )

    parser.add_argument(
        'version',
        nargs='?',
        help='Version to release (e.g., 1.0.0) - required for prepare/release'
    )

    parser.add_argument(
        '--project-root', '-p',
        type=Path,
        default=None,
        help='Project root directory (default: auto-detect from script location)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )

    # Define skippable stages with their descriptions
    skippable_stages = {
        'windows': 'Windows CI validation',
        'spark': 'SPARK verification',
        'exceptions': 'Exception boundary validation',
    }
    stage_list = ', '.join(skippable_stages.keys())

    parser.add_argument(
        '--skip',
        type=str,
        default='',
        metavar='STAGES',
        help=f'Skip specific stages (comma-separated). Available: {stage_list}, all'
    )

    # rc-tag-specific arguments (ignored by other actions)
    parser.add_argument(
        '--target',
        type=str,
        default=None,
        metavar='SHA',
        help='[rc-tag] Explicit commit SHA to tag (must be ancestor of '
             'origin/main).'
    )
    parser.add_argument(
        '--tag-message',
        type=str,
        default=None,
        metavar='MSG',
        help='[rc-tag] Annotated-tag message (default: '
             '"Release candidate <version>").'
    )
    parser.add_argument(
        '--release-title',
        type=str,
        default=None,
        metavar='TITLE',
        help='[rc-tag] GitHub Release title (default: "Release <version>").'
    )
    parser.add_argument(
        '--release-notes-file',
        type=str,
        default=None,
        metavar='PATH',
        help='[rc-tag] Path to release-notes markdown file. Relative paths '
             'resolve from --project-root.'
    )

    args = parser.parse_args()

    # Parse --skip into a set of stages
    if args.skip:
        if args.skip.lower() == 'all':
            args.skip_stages = set(skippable_stages.keys())
        else:
            args.skip_stages = set(s.strip().lower() for s in args.skip.split(','))
            # Validate stage names
            invalid = args.skip_stages - set(skippable_stages.keys())
            if invalid:
                print_error(f"Unknown skip stage(s): {', '.join(invalid)}")
                print_info(f"Available stages: {stage_list}, all")
                return 1
    else:
        args.skip_stages = set()

    # Validate version is provided for prepare/release/rc-tag
    if args.action in ['prepare', 'release', 'validate', 'rc-tag'] and not args.version:
        print_error(f"Version is required for {args.action} action")
        parser.print_help()
        return 1

    # Validate semantic version format
    if args.version and not re.match(
        r'^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?(\+[a-zA-Z0-9.]+)?$',
        args.version
    ):
        print_error("Version must follow semantic versioning (e.g., 1.0.0, 1.0.0-dev)")
        return 1

    # rc-tag-specific argument validation
    if args.action == 'rc-tag':
        missing = []
        if not args.target:
            missing.append('--target')
        if not args.release_notes_file:
            missing.append('--release-notes-file')
        if missing:
            print_error(
                f"rc-tag action requires: {', '.join(missing)}"
            )
            return 1
        if not re.match(r'^[0-9a-fA-F]{7,40}$', args.target):
            print_error(
                f"--target must be a 7-40 char hex SHA, got: {args.target!r}"
            )
            return 1

    # Determine project root
    if args.project_root:
        project_root = args.project_root.resolve()
    else:
        # Auto-detect: go up from script location to find project root
        # scripts/python/shared/release/release.py -> release -> shared -> python -> scripts -> project_root
        script_dir = Path(__file__).parent
        project_root = script_dir.parent.parent.parent.parent

    if not project_root.exists():
        print_error(f"Project root does not exist: {project_root}")
        return 1

    # Detect language
    language = detect_language(project_root)
    if not language:
        print_error(f"Could not detect language in: {project_root}")
        print_info("Supported languages: Go, Ada")
        return 1

    # Get adapter
    adapter = get_adapter(language)
    if not adapter:
        print_error(f"No adapter available for language: {language.value}")
        return 1

    # Load project info
    project_name, project_url = adapter.load_project_info(
        type('Config', (), {'project_root': project_root})()
    )

    # Create config
    config = ReleaseConfig(
        project_root=project_root,
        version=args.version or "0.0.0",
        language=language,
        dry_run=args.dry_run,
    )
    config.project_name = project_name
    config.project_url = project_url
    config.skip_stages = args.skip_stages

    print_info(f"Project: {project_name}")
    print_info(f"Language: {language.value}")
    print_info(f"Root: {project_root}")
    if args.skip_stages:
        print_info(f"Skipping: {', '.join(sorted(args.skip_stages))}")

    try:
        if args.action == 'prepare':
            success = prepare_release(config, adapter)
        elif args.action == 'release':
            success = create_release(config, adapter)
        elif args.action == 'rc-tag':
            success = create_rc_release(config, adapter, args)
        elif args.action == 'validate':
            # Future: add validation-only mode
            print_info("Validate action not yet implemented")
            success = True
        else:
            print_error(f"Unknown action: {args.action}")
            return 1

        return 0 if success else 1

    except KeyboardInterrupt:
        print("\n\nRelease process interrupted by user")
        return 1
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
