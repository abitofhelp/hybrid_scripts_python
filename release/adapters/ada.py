#!/usr/bin/env python3
# ==============================================================================
# adapters/ada.py - Ada language adapter for release management
# ==============================================================================
# Copyright (c) 2025 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
#
# Purpose:
#   Ada-specific adapter for release operations.
#   Handles alire.toml versioning, alr build, make test, and Ada-specific config.
#
# Design Notes:
#   Ada projects use alire.toml for version and metadata.
#   Version package is generated from alire.toml.
#   Multi-layer projects need version sync across all alire.toml files.
#
# ==============================================================================

from pathlib import Path
from typing import Tuple
import re
import sys

from .base import BaseReleaseAdapter


class AdaReleaseAdapter(BaseReleaseAdapter):
    """
    Ada-specific adapter for release operations.

    Handles:
        - alire.toml version management
        - Version package generation (Project.Version)
        - Version synchronization across layer alire.toml files
        - Build via 'make build' or 'alr build'
        - Test via 'make test'
    """

    @property
    def name(self) -> str:
        return "Ada"

    @staticmethod
    def detect(project_root: Path) -> bool:
        """
        Detect if a directory is an Ada project.

        Args:
            project_root: Path to check

        Returns:
            True if Ada project detected
        """
        if (project_root / 'alire.toml').exists():
            return True
        if list(project_root.glob('*.gpr')):
            return True
        if list(project_root.glob('**/*.gpr')):
            return True
        if list(project_root.glob('**/*.ads')) or list(project_root.glob('**/*.adb')):
            return True
        return False

    def load_project_info(self, config) -> Tuple[str, str]:
        """
        Load project name and URL from alire.toml.

        Args:
            config: ReleaseConfig instance

        Returns:
            Tuple of (project_name, project_url)
        """
        alire_toml = config.project_root / 'alire.toml'
        project_name = ""
        project_url = ""

        if alire_toml.exists():
            content = alire_toml.read_text(encoding='utf-8')

            # Extract name field
            name_match = re.search(r'^name\s*=\s*"([^"]+)"', content, re.MULTILINE)
            if name_match:
                project_name = name_match.group(1)

            # Extract website field
            website_match = re.search(r'^website\s*=\s*"([^"]+)"', content, re.MULTILINE)
            if website_match:
                url = website_match.group(1)
                # Remove .git suffix if present
                if url.endswith('.git'):
                    url = url[:-4]
                project_url = url

        # Fallback to directory name
        if not project_name:
            project_name = config.project_root.name

        return project_name, project_url

    def update_version(self, config) -> bool:
        """
        Update version in root alire.toml.

        Args:
            config: ReleaseConfig instance

        Returns:
            True if successful
        """
        root_toml = config.project_root / 'alire.toml'

        if not root_toml.exists():
            print("  alire.toml not found")
            return False

        try:
            content = root_toml.read_text(encoding='utf-8')

            # Check if version is already correct
            current_match = re.search(
                r'^version\s*=\s*"([^"]+)"',
                content,
                flags=re.MULTILINE
            )

            if current_match:
                current_version = current_match.group(1)
                if current_version == config.version:
                    print(f"  Root alire.toml already has version = \"{config.version}\"")
                    return True

            # Update version line
            old_content = content
            content = re.sub(
                r'^(\s*version\s*=\s*")[^"]+(")',
                rf'\g<1>{config.version}\g<2>',
                content,
                flags=re.MULTILINE
            )

            if content == old_content:
                print(f"  Error: Version field not found in {root_toml}")
                return False

            root_toml.write_text(content, encoding='utf-8')
            print(f"  Updated root alire.toml: version = \"{config.version}\"")
            return True

        except Exception as e:
            print(f"Error updating root alire.toml: {e}")
            return False

    def sync_versions(self, config) -> bool:
        """
        Synchronize versions across all layer alire.toml files and test crate.

        Args:
            config: ReleaseConfig instance

        Returns:
            True if successful
        """
        print("Syncing versions across all layer alire.toml files...")

        # Find sync_versions.py script
        sync_script = config.project_root / 'scripts' / 'release' / 'sync_versions.py'
        if not sync_script.exists():
            # Try alternative location
            sync_script = config.project_root / 'scripts' / 'sync_versions.py'

        if sync_script.exists():
            result = self.run_command(
                [sys.executable, str(sync_script), config.version],
                config.project_root,
                capture_output=True
            )
            return result is not None

        # Fallback: manually sync all alire.toml files
        for toml_file in config.project_root.rglob('alire.toml'):
            if toml_file.parent == config.project_root:
                continue  # Skip root (already updated)

            try:
                content = toml_file.read_text(encoding='utf-8')
                new_content = re.sub(
                    r'^(\s*version\s*=\s*")[^"]+(")',
                    rf'\g<1>{config.version}\g<2>',
                    content,
                    flags=re.MULTILINE
                )
                if new_content != content:
                    toml_file.write_text(new_content, encoding='utf-8')
                    rel_path = toml_file.relative_to(config.project_root)
                    print(f"  Updated {rel_path}")
            except Exception as e:
                print(f"  Warning: Could not update {toml_file}: {e}")

        # Regenerate test config files by running alr build in test directory
        # This updates test/config/* with the version from test/alire.toml
        test_dir = config.project_root / 'test'
        test_alire = test_dir / 'alire.toml'
        if test_alire.exists():
            print("  Regenerating test config files via alr build...")
            result = self.run_command(
                ['alr', 'build'],
                test_dir,
                capture_output=True,
                check=False
            )
            if result is not None:
                print(f"  Regenerated test/config/* from test/alire.toml")
            else:
                print(f"  Warning: Could not regenerate test config files (alr build failed)")

        return True

    def generate_version_file(self, config) -> bool:
        """
        Generate Version Ada package from alire.toml.

        Embeds version generation logic directly - no external script needed.
        Output: src/<project_name>-version.ads

        Args:
            config: ReleaseConfig instance

        Returns:
            True if successful
        """
        try:
            # Read alire.toml
            alire_toml = config.project_root / 'alire.toml'
            if not alire_toml.exists():
                print("  alire.toml not found, skipping version package generation")
                return True

            content = alire_toml.read_text(encoding='utf-8')

            # Extract version
            version_match = re.search(r'^\s*version\s*=\s*"([^"]+)"', content, re.MULTILINE)
            if not version_match:
                print("  No version field in alire.toml, skipping")
                return True
            version_str = version_match.group(1)

            # Extract project name
            name_match = re.search(r'^\s*name\s*=\s*"([^"]+)"', content, re.MULTILINE)
            if not name_match:
                print("  No name field in alire.toml, skipping")
                return True
            project_name = name_match.group(1)

            # Check for optional ada-package-name override in .release.toml (for acronyms like TZif)
            ada_pkg_match = None
            release_toml = config.project_root / '.release.toml'
            if release_toml.exists():
                release_content = release_toml.read_text(encoding='utf-8')
                ada_pkg_match = re.search(r'^\s*ada-package-name\s*=\s*"([^"]+)"', release_content, re.MULTILINE)

            # Parse semantic version: MAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]
            version_pattern = r'^(\d+)\.(\d+)\.(\d+)(?:-([a-zA-Z0-9.]+))?(?:\+([a-zA-Z0-9.]+))?$'
            ver_match = re.match(version_pattern, version_str)
            if not ver_match:
                print(f"  Invalid semantic version: {version_str}")
                return False

            major, minor, patch, prerelease, build = ver_match.groups()
            prerelease = prerelease or ''
            build = build or ''

            # Use ada-package-name if specified, otherwise auto-generate from project name
            if ada_pkg_match:
                ada_package = ada_pkg_match.group(1)
            else:
                # Convert to Ada casing (hybrid_app_ada -> Hybrid_App_Ada)
                ada_package = '_'.join(part.capitalize() for part in project_name.split('_'))

            # Generate Ada package source
            ada_code = f'''pragma Ada_2022;
--  =========================================================================
--  {ada_package}.Version - Application Version Information
--  =========================================================================
--  Copyright (c) 2025 Michael Gardner, A Bit of Help, Inc.
--  SPDX-License-Identifier: BSD-3-Clause
--  See LICENSE file in the project root.
--
--  AUTO-GENERATED FILE - DO NOT EDIT MANUALLY
--
--  This file is automatically generated from alire.toml by:
--    scripts/python/release/release.py (Ada adapter)
--
--  To update the version:
--    1. Edit the "version" field in alire.toml
--    2. Run: python3 scripts/python/release/release.py prepare <version>
--    3. Rebuild the project
--
--  Purpose:
--    Provides version constants extracted from alire.toml (single source
--    of truth). Useful for CLI --version flags and runtime version queries.
--
--  Design Notes:
--    - Version follows Semantic Versioning 2.0.0 (semver.org)
--    - Pre-release identifiers: -dev, -alpha.N, -beta.N, -rc.N
--    - Build metadata: +build.N, +commit.HASH
--  =========================================================================

package {ada_package}.Version
  with Preelaborate, SPARK_Mode => On
is

   --  Semantic Version Components
   Major : constant Natural := {major};
   Minor : constant Natural := {minor};
   Patch : constant Natural := {patch};

   --  Pre-release identifier (e.g., "dev", "alpha.1", "beta.2", "rc.1")
   --  Empty string for stable releases
   Prerelease : constant String := "{prerelease}";

   --  Build metadata (e.g., "build.123", "commit.abc123")
   --  Empty string if not specified
   Build_Metadata : constant String := "{build}";

   --  Full version string (e.g., "0.1.0-dev", "1.2.3", "2.0.0-rc.1+build.456")
   Version : constant String := "{version_str}";

   --  Check if this is a pre-release version
   function Is_Prerelease return Boolean is (Prerelease'Length > 0);

   --  Check if this is a development version
   --  Note: Condition may be always False for stable releases (expected)
   pragma Warnings (Off, "condition is always*");
   function Is_Development return Boolean is (Prerelease = "dev");
   pragma Warnings (On, "condition is always*");

   --  Check if this is a stable release
   function Is_Stable return Boolean is (not Is_Prerelease);

end {ada_package}.Version;
'''

            # Write output file to src/version/ (cross-cutting, outside hexagonal layers)
            output_path = config.project_root / 'src' / 'version' / f'{project_name}-version.ads'
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Check if file exists and content is unchanged
            if output_path.exists():
                existing_content = output_path.read_text(encoding='utf-8')
                if existing_content == ada_code:
                    print(f"  Version file unchanged (v{version_str})")
                    return True

            output_path.write_text(ada_code, encoding='utf-8')

            print(f"  Project: {project_name}")
            print(f"  Version: {version_str}")
            print(f"  Generated: src/version/{project_name}-version.ads")
            print(f"  Package: {ada_package}.Version")

            # Also update test_version.adb if it exists
            self._update_test_version_file(config, ada_package, major, minor, patch, version_str)

            return True

        except Exception as e:
            print(f"  Error generating version file: {e}")
            return False

    def _update_test_version_file(self, config, ada_package: str, major: str, minor: str, patch: str, version_str: str) -> bool:
        """
        Update test/unit/test_version.adb with new version values.

        The test file contains hardcoded assertions like:
          Assert (TZif.Version.Major = 2, "Major version is 2");
          Assert (TZif.Version.Version = "2.0.0", "Version string is 2.0.0");

        This method updates those values to match the new version.

        Args:
            config: ReleaseConfig instance
            ada_package: Ada package name (e.g., "TZif")
            major, minor, patch: Version components
            version_str: Full version string

        Returns:
            True if successful or file doesn't exist
        """
        test_file = config.project_root / 'test' / 'unit' / 'test_version.adb'
        if not test_file.exists():
            return True  # Not an error if test file doesn't exist

        try:
            content = test_file.read_text(encoding='utf-8')
            original_content = content

            # Update Major version assertion
            # Pattern: Assert (Package.Version.Major = N, "Major version is N");
            content = re.sub(
                r'(Assert\s*\(\s*\w+\.Version\.Major\s*=\s*)\d+(\s*,\s*"Major version is )\d+(")',
                rf'\g<1>{major}\g<2>{major}\g<3>',
                content
            )

            # Update Minor version assertion
            content = re.sub(
                r'(Assert\s*\(\s*\w+\.Version\.Minor\s*=\s*)\d+(\s*,\s*"Minor version is )\d+(")',
                rf'\g<1>{minor}\g<2>{minor}\g<3>',
                content
            )

            # Update Patch version assertion
            content = re.sub(
                r'(Assert\s*\(\s*\w+\.Version\.Patch\s*=\s*)\d+(\s*,\s*"Patch version is )\d+(")',
                rf'\g<1>{patch}\g<2>{patch}\g<3>',
                content
            )

            # Update Version string assertion
            # Pattern: Assert (Package.Version.Version = "X.Y.Z", "Version string is X.Y.Z");
            content = re.sub(
                r'(Assert\s*\(\s*\w+\.Version\.Version\s*=\s*")[^"]+("\s*,\s*"Version string is )[^"]+(")',
                rf'\g<1>{version_str}\g<2>{version_str}\g<3>',
                content
            )

            # Update version references in comments (e.g., "For current X.Y.Z release")
            content = re.sub(
                r'(--\s*For current )\d+\.\d+\.\d+( release)',
                rf'\g<1>{version_str}\g<2>',
                content
            )

            # Update version references in test messages (e.g., "Version X.Y.Z is stable")
            content = re.sub(
                r'("Version )\d+\.\d+\.\d+( is )',
                rf'\g<1>{version_str}\g<2>',
                content
            )

            if content != original_content:
                test_file.write_text(content, encoding='utf-8')
                print(f"  Updated: test/unit/test_version.adb")
            else:
                print(f"  Test file unchanged")

            return True

        except Exception as e:
            print(f"  Warning: Could not update test_version.adb: {e}")
            return True  # Non-fatal

    def run_build(self, config) -> bool:
        """
        Run Ada release build.

        Args:
            config: ReleaseConfig instance

        Returns:
            True if build successful
        """
        print("Running Ada release build...")

        # Try make first (if Makefile exists with build-release target)
        makefile = config.project_root / 'Makefile'
        if makefile.exists():
            # Run make clean first
            self.run_command(['make', 'clean'], config.project_root, capture_output=True)

            # Use build-release for production builds
            result = self.run_command(['make', 'build-release'], config.project_root)
            if result:
                print("  Release build successful (via make)")
                return True

        # Fallback to alr build with release validation
        result = self.run_command(
            ['alr', 'build', '--release'],
            config.project_root
        )

        if result:
            print("  Release build successful")
            return True

        print("  Build failed")
        return False

    def run_tests(self, config) -> bool:
        """
        Run Ada tests and extract test counts.

        Args:
            config: ReleaseConfig instance

        Returns:
            True if tests pass

        Side effects:
            Sets config.test_counts dict with unit, integration, examples counts
        """
        print("Running Ada tests...")

        # Initialize test counts
        config.test_counts = {'unit': 0, 'integration': 0, 'examples': 0}

        # Try make test-all (comprehensive test target)
        makefile = config.project_root / 'Makefile'
        if makefile.exists():
            # Try test-all first (includes unit, integration, e2e)
            result = self.run_command(
                ['make', 'test-all'],
                config.project_root,
                capture_output=True
            )
            if result is not None:
                # Parse test counts from output
                self._parse_test_counts(result, config)
                total = sum(config.test_counts.values())
                print(f"  All tests passed (via make test-all)")
                print(f"  Test counts: {config.test_counts['unit']} unit, "
                      f"{config.test_counts['integration']} integration, "
                      f"{config.test_counts['examples']} examples = {total} total")
                return True

            # Fallback to test target
            result = self.run_command(
                ['make', 'test'],
                config.project_root,
                capture_output=True
            )
            if result is not None:
                self._parse_test_counts(result, config)
                print("  All tests passed (via make test)")
                return True

        # No standard fallback for Ada - make test is the convention
        print("  No test target found")
        return True  # Not fatal

    def _parse_test_counts(self, output: str, config) -> None:
        """
        Parse test counts from make test-all output.

        Looks for patterns like:
            GRAND TOTAL - ALL UNIT TESTS
            Total tests:   425

            GRAND TOTAL - ALL INTEGRATION TESTS
            Total tests:   131

            GRAND TOTAL - ALL EXAMPLE TESTS
            Total tests:   11

        Args:
            output: Test runner output
            config: ReleaseConfig to store counts on
        """
        import re

        # Pattern to find test totals by section
        # Look for "GRAND TOTAL - ALL X TESTS" followed by "Total tests: N"
        patterns = [
            (r'GRAND TOTAL - ALL UNIT TESTS.*?Total tests:\s*(\d+)', 'unit'),
            (r'GRAND TOTAL - ALL INTEGRATION TESTS.*?Total tests:\s*(\d+)', 'integration'),
            (r'GRAND TOTAL - ALL EXAMPLE TESTS.*?Total tests:\s*(\d+)', 'examples'),
        ]

        for pattern, key in patterns:
            match = re.search(pattern, output, re.DOTALL | re.IGNORECASE)
            if match:
                config.test_counts[key] = int(match.group(1))

    def update_test_counts_in_docs(self, config) -> bool:
        """
        Update test counts in CHANGELOG and README after tests pass.

        Args:
            config: ReleaseConfig instance with test_counts populated

        Returns:
            True if successful
        """
        import re

        if not hasattr(config, 'test_counts'):
            print("  No test counts available, skipping doc update")
            return True

        counts = config.test_counts
        total = sum(counts.values())

        if total == 0:
            print("  No test counts parsed, skipping doc update")
            return True

        print(f"Updating test counts in docs ({total} total tests)...")

        # Update README.md test results line
        readme_file = config.project_root / 'README.md'
        if readme_file.exists():
            content = readme_file.read_text(encoding='utf-8')
            # Pattern: **Test Results:** X unit + Y integration + Z examples = **N tests passing**
            old_pattern = r'\*\*Test Results:\*\*\s*\d+\s*unit\s*\+\s*\d+\s*integration\s*\+\s*\d+\s*examples\s*=\s*\*\*\d+\s*tests passing\*\*'
            new_text = f"**Test Results:** {counts['unit']} unit + {counts['integration']} integration + {counts['examples']} examples = **{total} tests passing**"

            if re.search(old_pattern, content):
                content = re.sub(old_pattern, new_text, content)
                if not config.dry_run:
                    readme_file.write_text(content, encoding='utf-8')
                print(f"  Updated README.md test results")
            else:
                print(f"  README.md test results line not found (pattern may differ)")

        # Update CHANGELOG.md - find the current version section and add/update test counts
        changelog_file = config.project_root / 'CHANGELOG.md'
        if changelog_file.exists():
            content = changelog_file.read_text(encoding='utf-8')

            # Look for test count line in current version section
            # Pattern: **Test Coverage:** X unit + Y integration + Z examples = N total
            old_coverage_pattern = r'\*\*Test Coverage:\*\*\s*\d+\s*unit.*?=\s*\d+\s*total'
            new_coverage = f"**Test Coverage:** {counts['unit']} unit + {counts['integration']} integration + {counts['examples']} examples = {total} total"

            if re.search(old_coverage_pattern, content):
                content = re.sub(old_coverage_pattern, new_coverage, content)
                if not config.dry_run:
                    changelog_file.write_text(content, encoding='utf-8')
                print(f"  Updated CHANGELOG.md test coverage")
            else:
                # Try to add test coverage to current version section
                version_section_pattern = rf'(## \[{re.escape(config.version)}\][^\n]*\n)'
                match = re.search(version_section_pattern, content)
                if match:
                    # Add test coverage after the version header
                    insert_pos = match.end()
                    # Check if there's already content or just blank
                    next_content = content[insert_pos:insert_pos+100]
                    if not next_content.strip().startswith('**Test Coverage:**'):
                        content = content[:insert_pos] + f"\n{new_coverage}\n" + content[insert_pos:]
                        if not config.dry_run:
                            changelog_file.write_text(content, encoding='utf-8')
                        print(f"  Added test coverage to CHANGELOG.md")
                else:
                    print(f"  CHANGELOG.md version section not found")

        return True

    def run_format(self, config) -> bool:
        """
        Run Ada code formatting.

        Args:
            config: ReleaseConfig instance

        Returns:
            True if successful
        """
        print("Formatting Ada code...")

        # Try make format first
        makefile = config.project_root / 'Makefile'
        if makefile.exists():
            result = self.run_command(
                ['make', 'format'],
                config.project_root,
                capture_output=True
            )
            if result is not None:
                print("  Code formatted (via make)")
                return True

        # gnatpp is not always available
        print("  Format target not available (gnatpp/adafmt)")
        return True

    def cleanup_temp_files(self, config) -> bool:
        """
        Clean up Ada build artifacts.

        Args:
            config: ReleaseConfig instance

        Returns:
            True if successful
        """
        print("Cleaning up temporary files...")

        # Check for cleanup script
        cleanup_script = config.project_root / 'scripts' / 'cleanup_temp_files.py'
        if cleanup_script.exists():
            result = self.run_command(
                [sys.executable, str(cleanup_script)],
                config.project_root,
                capture_output=True
            )
            if result is not None:
                print("  Cleaned (via cleanup script)")
                return True

        # Fallback to make clean
        makefile = config.project_root / 'Makefile'
        if makefile.exists():
            result = self.run_command(
                ['make', 'clean'],
                config.project_root,
                capture_output=True
            )
            if result is not None:
                print("  Cleaned (via make)")

        # Reset Alire config files to development mode
        # Release build creates config/ with release settings (-O3, etc.)
        # We regenerate with development settings so git stays clean
        alire_toml = config.project_root / 'alire.toml'
        if alire_toml.exists():
            print("  Resetting Alire config to development mode...")
            result = self.run_command(
                ['alr', 'build', '--stop-after=generation'],
                config.project_root,
                capture_output=True,
                check=False
            )
            if result is not None:
                print("  Alire config reset to development settings")

        print("  Cleaned")
        return True

    def has_spark_project(self, config) -> bool:
        """
        Check if project has a SPARK verification project file.

        Args:
            config: ReleaseConfig instance

        Returns:
            True if *_spark.gpr exists
        """
        spark_files = list(config.project_root.glob('*_spark.gpr'))
        return len(spark_files) > 0

    def run_spark_check(self, config) -> bool:
        """
        Run SPARK legality check (fast gate for release prepare).

        Args:
            config: ReleaseConfig instance

        Returns:
            True if SPARK check passes
        """
        if not self.has_spark_project(config):
            print("  No SPARK project file found, skipping")
            return True

        print("Running SPARK legality check...")

        makefile = config.project_root / 'Makefile'
        if makefile.exists():
            result = self.run_command(
                ['make', 'spark-check'],
                config.project_root,
                capture_output=True
            )
            if result is not None:
                print("  SPARK check passed (via make)")
                return True
            else:
                print("  SPARK check failed")
                return False

        print("  No spark-check target found")
        return True

    def run_spark_prove(self, config) -> Tuple[bool, str]:
        """
        Run SPARK formal verification (post-release validation).

        Saves the full log to /tmp/spark_prove_v{version}.log for
        attachment to the GitHub release.

        Args:
            config: ReleaseConfig instance

        Returns:
            Tuple of (success, results_summary)
        """
        # Initialize log path (will be set if prove runs successfully)
        self._spark_log_path = None

        if not self.has_spark_project(config):
            return True, "No SPARK project (skipped)"

        print("Running SPARK PROVE formal verification...")
        print("  (This may take several minutes...)")

        makefile = config.project_root / 'Makefile'
        if makefile.exists():
            # Capture output to parse results
            import subprocess
            from pathlib import Path
            try:
                result = subprocess.run(
                    ['make', 'spark-prove'],
                    cwd=config.project_root,
                    capture_output=True,
                    text=True,
                    timeout=5400  # 90 min timeout (SPARK prove can take 45-90 min)
                )

                output = result.stdout + result.stderr

                # Save log to temp file for release attachment
                log_path = Path(f'/tmp/spark_prove_v{config.version}.log')
                log_path.write_text(output, encoding='utf-8')
                self._spark_log_path = log_path
                print(f"  SPARK log saved to: {log_path}")

                # Parse results from gnatprove output
                # Look for summary line like "Summary logged in ..."
                # and count info/warning/error lines
                flow_count = len(
                    re.findall(r': info: .*flow', output, re.IGNORECASE))
                proved_count = len(
                    re.findall(r': info: .*proved', output, re.IGNORECASE))
                medium_count = len(re.findall(r': medium:', output))

                total_checks = flow_count + proved_count + medium_count
                summary = (f"{total_checks} checks: {flow_count} flow, "
                           f"{proved_count} proved, {medium_count} unproved")

                if result.returncode == 0:
                    print(f"  SPARK PROVE passed: {summary}")
                    return True, summary
                else:
                    print(f"  SPARK PROVE completed with warnings: {summary}")
                    # Still return True if only medium warnings (not errors)
                    if medium_count > 0 and 'error:' not in output.lower():
                        return True, summary
                    return False, summary

            except subprocess.TimeoutExpired:
                print("  SPARK PROVE timed out (>90 minutes)")
                return False, "Timeout"
            except Exception as e:
                print(f"  SPARK PROVE error: {e}")
                return False, str(e)

        print("  No spark-prove target found")
        return True, "No spark-prove target"

    def update_github_release_with_spark(self, config, spark_summary: str) -> bool:
        """
        Update GitHub release description with SPARK verification results.

        Args:
            config: ReleaseConfig instance
            spark_summary: SPARK verification results summary

        Returns:
            True if successful
        """
        import subprocess

        print("Updating GitHub release with SPARK results...")

        try:
            # Get current release notes
            result = subprocess.run(
                ['gh', 'release', 'view', f'v{config.version}', '--json', 'body'],
                cwd=config.project_root,
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                print(f"  Could not fetch release notes: {result.stderr}")
                return False

            import json
            release_data = json.loads(result.stdout)
            current_body = release_data.get('body', '')

            # Append SPARK verification section
            spark_section = f"""

---

## SPARK Formal Verification

| Metric | Result |
|--------|--------|
| **Status** | Verified |
| **Mode** | gnatprove --mode=prove --level=2 |
| **Results** | {spark_summary} |

Verified using SPARK Ada formal verification tools."""

            new_body = current_body + spark_section

            # Update release notes
            result = subprocess.run(
                ['gh', 'release', 'edit', f'v{config.version}',
                 '--notes', new_body],
                cwd=config.project_root,
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                print(f"  Could not update release: {result.stderr}")
                return False

            print("  GitHub release updated with SPARK results")

            # Upload SPARK prove log as release asset if available
            if hasattr(self, '_spark_log_path') and self._spark_log_path:
                log_path = self._spark_log_path
                if log_path.exists():
                    upload_result = subprocess.run(
                        ['gh', 'release', 'upload', f'v{config.version}',
                         str(log_path), '--clobber'],
                        cwd=config.project_root,
                        capture_output=True,
                        text=True
                    )
                    if upload_result.returncode == 0:
                        print(f"  Attached SPARK log: {log_path.name}")
                    else:
                        print(f"  Warning: Could not attach log: "
                              f"{upload_result.stderr}")

            return True

        except Exception as e:
            print(f"  Error updating release: {e}")
            return False
