# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - Unreleased

### Added
- Local stdio MCP server with structured Google Health v4 responses, read-only defaults, and opt-in mutation tools.
- Browser OAuth setup with PKCE, live connection verification, shared local sign-in, and agent registration.
- Setup, client configuration, and privacy documentation for bring-your-own Google OAuth clients.

### Fixed
- Keep Windows setup, terminal commands, and MCP clients on the same local credential directory.
- Preserve successful token refreshes when Windows Credential Manager rejects the optional keyring copy.
- Report configuration-path problems without claiming the Google sign-in was never completed.

### Security
- Require patched AnyIO, cryptography, and certifi versions and refresh the dependency lockfile.
- Atomic private credential and agent-config writes, Google OAuth endpoint validation, and callback state checks.
- File-authoritative automatic token storage prevents stale keyring credentials selecting an old account.
- An empty local logout marker prevents unavailable keyring cleanup from restoring an older sign-in.
- Failed token revocation and deletion are reported, and existing agent registrations are preserved.

## [1.1.0] - 2026-06-27
### Changed
- Default token storage backend changed from `keyring` to `auto`. The `auto` backend dual-writes tokens to both the OS keyring (best-effort) and a local file with `0600` permissions. On read, it tries keyring first and falls back to the file, fixing `not_authenticated` errors in non-interactive and sandboxed environments.

### Added
- New `auto` option for `--token-storage` in `ghealth auth configure`.

## [1.0.0] - 2026-06-26
### Added
- Complete command line support for all Google Health REST API resources (Identity, Profile, Settings, Devices, Data Points, Webhook Subscribers, and Subscriptions).
- Secure local token storage using OS Credential Store / Keyring.
- Automatic silent refresh of Google Health access tokens.
- Native tabular formatting for humans and deterministic `--format json` output for AI agents.
- Convenient CLI shortcuts for common queries: `steps`, `sleep`, `calories`, `heart-rate`, `weight`, `nutrition`, and more.
- Static G Health data types registry with operation and scope discovery.
- Offline-first design and comprehensive mocked CLI integration test suite.
