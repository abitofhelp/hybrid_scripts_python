#!/usr/bin/env python3
# ==============================================================================
# brand_project.py - Unified Project Branding Script
# ==============================================================================
# Copyright (c) 2025 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
#
# Purpose:
#   Instantiate new projects from hybrid_app/hybrid_lib templates.
#   Supports Go, Ada, and Rust (future) languages.
#
# Usage:
#   python3 brand_project.py --git-repo https://github.com/user/my_app.git
#   python3 brand_project.py --git-repo github.com/user/my_app
#   python3 brand_project.py --git-repo github.com/user/my_app --dry-run
#
# ==============================================================================

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional, List, Tuple

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from common import (
    print_success, print_error, print_warning, print_info, print_section,
    configure_xmlada_dependency, detect_project_type
)

# Support both direct script execution and module import
try:
    from .models import GitRepoUrl, ProjectConfig, Language, to_snake_case
    from .adapters import GoAdapter, AdaAdapter
except ImportError:
    from models import GitRepoUrl, ProjectConfig, Language, to_snake_case
    from adapters import GoAdapter, AdaAdapter


def detect_language(source_dir: Path) -> Optional[Language]:
    """
    Detect the template language from source directory.

    Args:
        source_dir: Path to template directory

    Returns:
        Detected Language or None
    """
    if GoAdapter.detect(source_dir):
        return Language.GO
    if AdaAdapter.detect(source_dir):
        return Language.ADA
    # Future: RustAdapter.detect(source_dir)
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
        Language.GO: GoAdapter(),
        Language.ADA: AdaAdapter(),
    }
    return adapters.get(language)


def detect_template_name(source_dir: Path, language: Language) -> str:
    """
    Detect the template project name from source directory.

    Args:
        source_dir: Path to template directory
        language: Detected language

    Returns:
        Template name in snake_case
    """
    if language == Language.GO:
        # Try to get from go.mod
        go_mod = source_dir / 'go.mod'
        if go_mod.exists():
            import re
            content = go_mod.read_text(encoding='utf-8')
            match = re.search(r'^module\s+\S+/(\S+)$', content, re.MULTILINE)
            if match:
                return to_snake_case(match.group(1))

    elif language == Language.ADA:
        # Try to get from alire.toml
        alire_toml = source_dir / 'alire.toml'
        if alire_toml.exists():
            import re
            content = alire_toml.read_text(encoding='utf-8')
            match = re.search(r'^name\s*=\s*"([^"]+)"', content, re.MULTILINE)
            if match:
                return match.group(1)

        # Try from .gpr file
        gpr_files = list(source_dir.glob('*.gpr'))
        if gpr_files:
            return to_snake_case(gpr_files[0].stem)

    # Fallback: use directory name
    return to_snake_case(source_dir.name)


def detect_example_app_names(template_name: str, language: Language) -> list:
    """
    Detect the example application names for a template.

    Application templates include sample applications (e.g., "greeter", "greet"
    in hybrid_app_ada) that should be renamed to the new project name.
    Library templates do not have example apps.

    Args:
        template_name: Name of the template (e.g., "hybrid_app_ada")
        language: Detected language

    Returns:
        List of example app names (e.g., ["greeter", "greet"]) or empty list
    """
    if language == Language.ADA:
        return AdaAdapter.get_example_app_names(template_name)
    # Future: add GoAdapter.get_example_app_names, RustAdapter.get_example_app_names
    return []


def validate_generated_project(target_dir: Path, language: Language) -> Tuple[bool, List[str]]:
    """
    Validate the generated project structure.

    Args:
        target_dir: Path to generated project
        language: Project language

    Returns:
        Tuple of (all_passed, list of failure messages)
    """
    failures = []

    # Check submodules
    submodules = [
        ("docs/common", "Shared documentation"),
        ("scripts/python", "Python build/test scripts"),
        ("test/python", "Python test utilities"),
    ]
    for submodule_path, description in submodules:
        full_path = target_dir / submodule_path
        git_file = full_path / ".git"
        if not full_path.exists():
            failures.append(f"Missing submodule directory: {submodule_path}")
        elif not git_file.exists():
            failures.append(f"Not a submodule (no .git): {submodule_path}")

    # Check required directories
    common_dirs = ["docs", "docs/common", "docs/diagrams", "docs/guides",
                   "scripts/python", "test", "test/python"]
    if language == Language.ADA:
        # Use detect_project_type to determine library vs application structure
        is_library = detect_project_type(target_dir)
        if is_library:
            # Library: 4-layer (domain, application, infrastructure, api)
            common_dirs.extend(["src/api", "src/application", "src/domain",
                               "src/infrastructure", "test/unit", "test/integration", "test/common"])
        else:
            # Application: 5-layer (domain, application, infrastructure, presentation, bootstrap)
            common_dirs.extend(["src/bootstrap", "src/presentation", "src/application", "src/domain",
                               "src/infrastructure", "test/unit", "test/integration", "test/common"])
    elif language == Language.GO:
        common_dirs.extend(["internal/domain", "internal/application", "internal/infrastructure"])

    for dir_path in common_dirs:
        if not (target_dir / dir_path).is_dir():
            failures.append(f"Missing directory: {dir_path}")

    # Check required files
    common_files = ["README.md", "CHANGELOG.md", "LICENSE", ".gitignore", ".gitmodules", "Makefile"]
    if language == Language.ADA:
        common_files.extend(["alire.toml", "test/alire.toml"])
    elif language == Language.GO:
        common_files.append("go.mod")

    for file_path in common_files:
        if not (target_dir / file_path).is_file():
            failures.append(f"Missing file: {file_path}")

    # Check no cache files at root
    cache_files = [".als-alire", ".DS_Store"]
    for cache_file in cache_files:
        if (target_dir / cache_file).exists():
            failures.append(f"Cache file should not exist: {cache_file}")

    # Ada-specific checks
    if language == Language.ADA:
        # Check main alire.toml does NOT have gnatcov
        main_alire = target_dir / "alire.toml"
        if main_alire.exists():
            content = main_alire.read_text()
            if "gnatcov" in content.lower():
                failures.append("Main alire.toml should NOT contain gnatcov")

        # Check test/alire.toml HAS gnatcov
        test_alire = target_dir / "test" / "alire.toml"
        if test_alire.exists():
            content = test_alire.read_text()
            if "gnatcov" not in content.lower():
                failures.append("test/alire.toml should contain gnatcov")

        # Check Makefile has coverage support via Python script
        makefile = target_dir / "Makefile"
        if makefile.exists():
            content = makefile.read_text()
            if "coverage_ada.py" not in content:
                failures.append("Makefile should have coverage support (scripts/python/makefile/coverage_ada.py)")

        # Check GPR file exists
        if not list(target_dir.glob("*.gpr")):
            failures.append("Missing GPR project file")

    return (len(failures) == 0, failures)


def brand_project(config: ProjectConfig, verbose: bool = False) -> bool:
    """
    Execute the complete project branding process.

    Args:
        config: ProjectConfig instance
        verbose: Print detailed progress

    Returns:
        True if successful, False otherwise
    """
    adapter = get_adapter(config.language)
    if not adapter:
        print_error(f"No adapter available for language: {config.language.value}")
        return False

    dry_run_prefix = "[DRY RUN] " if config.dry_run else ""

    # Print header
    print_section("=" * 70)
    print_section(f"{dry_run_prefix}Project Branding")
    print_section("=" * 70)
    print_info(f"Source:   {config.source_dir}")
    print_info(f"Target:   {config.target_dir}")
    print_info(f"Language: {config.language.value}")
    print_info(f"Old name: {config.old_name}")
    print_info(f"New name: {config.new_name}")
    if config.example_app_names:
        for app_name in config.example_app_names:
            print_info(f"Example app: {app_name} -> {config.new_name}")
    print_info(f"New repo: {config.new_repo.https_url}")
    print()

    # Step 0: Update REF submodules to latest
    print_section(f"\n{dry_run_prefix}Step 0: Updating REF template submodules...")
    if not config.dry_run:
        try:
            result = subprocess.run(
                ["git", "-C", str(config.source_dir), "submodule", "update", "--remote", "--merge"],
                capture_output=True,
                text=True,
                timeout=60
            )
            if result.returncode == 0:
                print_success("REF submodules updated to latest")
            else:
                print_warning(f"Could not update REF submodules: {result.stderr.strip()}")
        except subprocess.TimeoutExpired:
            print_warning("Submodule update timed out - continuing with current state")
        except Exception as e:
            print_warning(f"Could not update REF submodules: {e}")
    else:
        print_info("[DRY RUN] Would update REF submodules")

    # Step 1: Copy template
    print_section(f"\n{dry_run_prefix}Step 1: Copying template files...")
    file_count = adapter.copy_template(config, verbose)
    if file_count == 0 and not config.dry_run:
        print_error("No files copied. Check if target directory already exists.")
        return False
    print_success(f"Copied {file_count} files")

    # Step 2: Set up docs structure
    print_section(f"\n{dry_run_prefix}Step 2: Setting up docs structure...")
    if adapter.setup_docs_structure(config, verbose):
        print_success("Set up docs structure (common/, diagrams/, guides/, formal/, index.md, quick_start.md)")
    else:
        print_warning("Could not set up docs structure")

    # Step 3: Rename files
    print_section(f"\n{dry_run_prefix}Step 3: Renaming files...")
    renamed = adapter.rename_files(config, verbose)
    print_success(f"Renamed {len(renamed)} files")
    if verbose and renamed:
        for f in renamed:
            print_info(f"  - {f}")

    # Step 4: Replace in file contents
    print_section(f"\n{dry_run_prefix}Step 4: Replacing text in files...")
    modified = adapter.replace_in_files(config, verbose)
    print_success(f"Modified {modified} files")

    # Step 5: Update language-specific config
    print_section(f"\n{dry_run_prefix}Step 5: Updating config files...")
    updated = adapter.update_config_files(config)
    print_success(f"Updated {len(updated)} config files")
    if verbose and updated:
        for f in updated:
            print_info(f"  - {f}")

    # Step 6: Reset CHANGELOG.md to fresh state
    print_section(f"\n{dry_run_prefix}Step 6: Resetting CHANGELOG.md...")
    if adapter.reset_changelog(config, verbose):
        print_success("Reset CHANGELOG.md to fresh state")
    else:
        print_warning("Could not reset CHANGELOG.md")

    # Step 7: Verify no old references remain
    print_section(f"\n{dry_run_prefix}Step 7: Verifying no old references...")
    if not config.dry_run:
        remaining = adapter.verify_no_old_references(config)
        if remaining:
            print_warning(f"Found {len(remaining)} files with old references:")
            for f in remaining[:10]:  # Show first 10
                print_warning(f"  - {f}")
            if len(remaining) > 10:
                print_warning(f"  ... and {len(remaining) - 10} more")
        else:
            print_success("No old references found")
    else:
        print_info("[DRY RUN] Skipping verification")

    # Step 8: Initialize git and submodules
    print_section(f"\n{dry_run_prefix}Step 8: Initializing git and submodules...")
    if adapter.initialize_git_and_submodules(config, verbose):
        print_success("Initialized git repository and submodules")
    else:
        print_warning("Could not initialize git/submodules (manual setup required)")

    # Step 9: Validate generated project
    print_section(f"\n{dry_run_prefix}Step 9: Validating generated project...")
    if not config.dry_run:
        valid, failures = validate_generated_project(config.target_dir, config.language)
        if valid:
            print_success("All structure validation checks passed")
        else:
            print_warning(f"Structure validation found {len(failures)} issue(s):")
            for failure in failures:
                print_warning(f"  - {failure}")
    else:
        print_info("[DRY RUN] Skipping validation")

    # Step 10: Configure xmlada (Ada projects only)
    if config.language == Language.ADA:
        print_section(f"\n{dry_run_prefix}Step 10: Configuring xmlada dependency...")
        if not config.dry_run:
            if configure_xmlada_dependency(config.target_dir, verbose):
                print_success("xmlada dependency configured (if present)")
            else:
                print_warning("Some xmlada directories could not be configured")
        else:
            print_info("[DRY RUN] Would configure xmlada dependency if present")

    # Summary
    print_section("\n" + "=" * 70)
    if config.dry_run:
        print_success("[DRY RUN] Branding simulation complete")
        print_info("Run without --dry-run to apply changes")
    else:
        print_success("Project branding complete!")
        print_info(f"\nNext steps:")
        print_info(f"  cd {config.target_dir}")
        print_info(f"  git add .")
        print_info(f'  git commit -m "Initial commit from template"')
        print_info(f"  git remote add origin {config.new_repo.clone_url}")
        print_info(f"  git push -u origin main")
    print_section("=" * 70)

    return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Instantiate a new project from hybrid_app/hybrid_lib template',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --git-repo https://github.com/account/my_app.git
  %(prog)s --git-repo github.com/account/my_app
  %(prog)s --git-repo github.com/account/my_app --dry-run
  %(prog)s --git-repo github.com/account/my_app -o ~/projects
  %(prog)s --git-repo github.com/account/my_app --source ../hybrid_lib_go -o /tmp

The script will:
  1. Detect the template language (Go/Ada/Rust)
  2. Copy template files (excluding build artifacts, docs handled separately)
  3. Set up docs structure (docs/common submodule, diagrams/, guides/, formal/)
  4. Rename files containing template name
  5. Replace template name in file contents
  6. Update language-specific config (go.mod, alire.toml, etc.)
  7. Reset CHANGELOG.md to fresh state (before any release)
  8. Verify no old references remain
        """
    )

    parser.add_argument(
        '--git-repo',
        required=True,
        help='Git repository URL for new project (e.g., github.com/account/my_app)'
    )

    parser.add_argument(
        '--source',
        type=Path,
        default=Path.cwd(),
        help='Source template directory (default: current directory)'
    )

    parser.add_argument(
        '--output', '-o',
        type=Path,
        default=Path.cwd(),
        help='Output directory where new project will be created (default: current directory)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed progress'
    )

    args = parser.parse_args()

    # Parse git repo URL
    try:
        new_repo = GitRepoUrl.parse(args.git_repo)
    except ValueError as e:
        print_error(f"Invalid git repo URL: {e}")
        return 1

    # Resolve source directory
    source_dir = args.source.resolve()
    if not source_dir.exists():
        print_error(f"Source directory does not exist: {source_dir}")
        return 1

    # Detect language
    language = detect_language(source_dir)
    if not language:
        print_error(f"Could not detect language in: {source_dir}")
        print_info("Supported languages: Go, Ada")
        return 1

    # Detect template name
    old_name = detect_template_name(source_dir, language)

    # Detect example app names (for application templates like hybrid_app_ada)
    example_app_names = detect_example_app_names(old_name, language)

    # Determine target directory (output_dir / project_name)
    output_dir = args.output.resolve()

    # In dry-run mode, we don't require the output directory to exist
    if not args.dry_run and not output_dir.exists():
        # Try to create it
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            print_info(f"Created output directory: {output_dir}")
        except Exception as e:
            print_error(f"Could not create output directory: {output_dir}")
            print_error(f"  {e}")
            return 1

    target_dir = output_dir / new_repo.project_name

    # Warn if target would be nested (common mistake: -o ../my_proj instead of -o ..)
    if output_dir.name == new_repo.project_name:
        print_warning(f"Output directory name matches project name.")
        print_warning(f"  Target will be: {target_dir}")
        print_warning(f"  Did you mean: -o {output_dir.parent}?")

    # Create config
    config = ProjectConfig(
        source_dir=source_dir,
        target_dir=target_dir,
        old_name=old_name,
        new_repo=new_repo,
        language=language,
        dry_run=args.dry_run,
        example_app_names=example_app_names,
    )

    # Execute branding
    success = brand_project(config, verbose=args.verbose)
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
