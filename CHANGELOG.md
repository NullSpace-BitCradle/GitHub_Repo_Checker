# Changelog

## Unreleased (branch fix/audit-2026-11-18)

### Changed: exit codes (may break scripts)

- A run that finds a dead link, a forbidden repository, a repository it could not check, or that was stopped by the rate limit now exits **1**. It always exited 0 before.
- A missing or unreadable URL file, or a file with no repository URLs, now exits **2**. It exited 1 before.
- A clean run still exits 0.

### Changed: behaviour

- Rate limits are read from GitHub's headers. A wait up to `--max-wait` seconds (default 120) is slept through once for all workers; a longer one stops the run and the remaining URLs are reported as `RATE_LIMITED` (not checked). The tool no longer sleeps for a `Retry-After` on its own inside the HTTP client.
- Connection errors and 5xx responses are retried with backoff. `ERROR` and `RATE_LIMITED` mean "not checked" and are listed apart from dead links.
- Output uses ASCII tags (`OK`, `FAIL`, `WARN`, `ERROR`, `UNCHECKED`, `SKIP`) in place of the check marks, and follows the order of the input file.
- URL parsing handles markdown links, list items, `git@` addresses and upper-case hosts, and skips gists, profiles and site pages (listed as skipped lines). Repeated repositories are checked once.
- A token passed as a command-line argument prints a warning; use `GITHUB_TOKEN`. Authorization uses `Bearer`.

### Added

- Archived and private markers on result lines and an archived list in the summary.
- `--max-wait` and `--workers` options.
- `tests/` (unittest, local mock HTTP server).

### Requirements

- `requests>=2.32.0`, `urllib3>=1.26.0`.
