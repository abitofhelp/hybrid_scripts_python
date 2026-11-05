# Changelog

All notable changes to this repo are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed (breaking)

- `makefile/container_run.py` always passes `HOST_USER`, `HOST_UID`, and
  `HOST_GID`, for every container CLI, as required by dev_containers
  v2.0.0 and later. It refuses to launch on native Windows (no POSIX UID or
  GID; use a WSL2 shell) and when the user name is not valid inside the
  container. Podman now runs with `--userns=keep-id --user 0:0`. The
  `--root` diagnostic option is removed (dev_containers#6).

### Added

- `tests/test_container_run.py`: host identity and command-assembly tests
  for the launcher.


### Changed

- `arch_guard` now enforces `Library_Standalone = "standard"` on Ada
  root library GPRs.
- `namespace_layers` no longer upgrades libraries to `"encapsulated"`.

### Rationale

- Prevents duplicate Ada runtime (RTS) conflicts when multiple
  encapsulated SALs appear in the same final link.
- Aligns GPR build configuration with the existing architecture rules:
  public-API enforcement is the role of `Library_Interface`, not of
  `Library_Standalone`.

### Migration

- No API changes.
- Consumer repositories whose root GPR currently declares
  `Library_Standalone use "encapsulated"` will see `make check-arch`
  fail after bumping the `scripts/python/shared` submodule to this
  release. Fix in each consumer by flipping the root GPR to
  `Library_Standalone use "standard"` and picking up the new submodule
  + dependencies:
    - If consuming via git submodule: `git submodule update --remote`
    - If consuming via Alire:          `alr update`
    - Then rebuild.
