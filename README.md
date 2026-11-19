# GitHub Repository Batch Checker

A Python tool to quickly validate large collections of GitHub repository bookmarks. Checks if repos exist, are archived, or have been deleted using GitHub's API with concurrent processing.

## Features

- **Fast concurrent checking** - Process hundreds of URLs quickly
- **Rate limit handling** - Reads GitHub's rate limit headers. A short limit is waited out; a long one stops the run, and every URL it did not reach is reported as not checked instead of being given a wrong status
- **Retries** - Connection errors and 5xx responses are retried with backoff before a URL is reported
- **Detailed status reporting** - Shows deleted (or private to you), archived and private repos
- **Progress tracking** - Real-time updates in input order with a final summary
- **Token support** - Optional GitHub token for higher rate limits
- **Dead link identification** - Easily spot URLs that need removal or fixing
- **Exit codes** - 0 when everything checked out, 1 when anything needs attention, so it can gate a script

## Installation

```bash
git clone https://github.com/NullSpace-BitCradle/GitHub_Repo_Checker.git
cd GitHub_Repo_Checker
pip install -r requirements.txt
```

## Usage

### Basic Usage

1. Create a text file with your GitHub URLs (one per line):

```text
https://github.com/SecureAuthCorp/impacket
https://github.com/danielmiessler/SecLists
https://github.com/carlospolop/PEASS-ng
https://github.com/rebootuser/LinEnum
```

2. Run the checker:

```bash
python github_checker.py urls.txt
```

Lines can also be markdown list items or links (`- https://github.com/o/r - notes`, `[name](https://github.com/o/r)`), `git@github.com:o/r.git` addresses, or URLs with a `/tree/main/...`, `?tab=` or `#` suffix. The host is matched without regard to case. Each repository is checked once however many times it is listed. Lines that mention github.com but are not a repository (gists, profiles, `topics/`, `sponsors/` and similar pages) are listed under "Skipped Lines" and not checked.

### Options

| Option | Meaning |
|--------|---------|
| `--max-wait SECONDS` | The longest to sleep for a rate limit before stopping the run (default 120) |
| `--workers N` | Concurrent requests (default 10) |

### With GitHub Token (Recommended)

Without a token GitHub allows 60 requests per hour from your IP address, so a file with more than about 60 URLs will hit the limit. A token raises that to 5,000 per hour.

Set the token in the environment so it never appears on the command line:

```bash
export GITHUB_TOKEN="your_token_here"
python github_checker.py urls.txt
```

On Windows PowerShell:

```powershell
$env:GITHUB_TOKEN = "your_token_here"
python github_checker.py urls.txt
```

Passing the token as a second argument still works but prints a warning, because it ends up in shell history and in the process list.

### Getting a GitHub Token

Reading public repository data needs no permissions, so give the token none.

1. Go to [GitHub Settings > Developer settings > Personal access tokens](https://github.com/settings/tokens)
2. Click "Generate new token" and choose a fine-grained token with no extra permissions (or a classic token with no scopes ticked)
3. Copy the generated token

## Sample Output

```text
Found 4 GitHub URLs to check...
[1/4] OK SecureAuthCorp/impacket
[2/4] FAIL someuser/deleted-repo - Repository not found (deleted, or private to you)
[3/4] OK danielmiessler/SecLists
[4/4] OK atom/atom [archived]

==================================================
SUMMARY
==================================================
EXISTS: 3
NOT_FOUND: 1
ARCHIVED (included in EXISTS): 1

Dead Links (1):
  https://github.com/someuser/deleted-repo

Archived Repositories (1):
  https://github.com/atom/atom
```

When GitHub's rate limit stops the run, the remaining URLs are reported like this instead of as dead links:

```text
Rate limited: GitHub resets in about 52 min, longer than --max-wait (120s). Stopping; remaining URLs will be reported as not checked.
...
RATE_LIMITED: 40

Not Checked, retry later (40):
  https://github.com/example/one
  ...
GitHub's rate limit stopped the run. The limit resets at 14:07:31. Set GITHUB_TOKEN for a higher limit.
```

## Status Codes

| Status | Meaning |
|--------|---------|
| **EXISTS** | Repository is accessible. `[archived]` and `[private]` (private repos your token can see) are shown on the line |
| **NOT_FOUND** | Repository deleted, never existed, or private to you |
| **FORBIDDEN** | GitHub answered 403 for a reason other than a rate limit, for example a blocked repository |
| **RATE_LIMITED** | Not checked: GitHub's rate limit was reached |
| **ERROR** | Not checked: network failure or an unexpected HTTP status, after retries |
| **INVALID_URL** | Not a repository URL (only reached when calling `check_repo` directly; the command line lists these as skipped lines) |

NOT_FOUND, FORBIDDEN, RATE_LIMITED and ERROR each get their own section in the summary. Only NOT_FOUND is a dead link. RATE_LIMITED and ERROR mean the repository was not checked, so run the file again later.

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Every repository was checked and exists |
| 1 | At least one is NOT_FOUND, FORBIDDEN, RATE_LIMITED or ERROR |
| 2 | Usage or input error: file missing or unreadable, no repository URLs in it, or an invalid option |

Earlier versions always exited 0 and used 1 for a missing file, so a script that relied on those needs updating. See [CHANGELOG.md](CHANGELOG.md).

## Use Cases

- **Offensive security collections** - Validate pentesting tool repositories
- **Research bookmarks** - Check academic and research repo collections
- **Development tools** - Maintain curated lists of useful repositories
- **Documentation links** - Verify tutorial and guide repositories
- **Organization audits** - Check if team repositories are still accessible

## Tips

- **Large collections**: Set `GITHUB_TOKEN`. The tool waits out short rate limits and stops on long ones, but a token is what keeps a big file from hitting the limit at all
- **Private repos**: GitHub answers 404 for a private repo you cannot see, so these show as NOT_FOUND. Use a token that can see the repo to tell the difference
- **Archived repos**: Shown as EXISTS with `[archived]` and listed in the summary
- **Redirected repos**: GitHub redirects are followed automatically, so a renamed repo is reported as EXISTS
- **Results order**: Output follows the order of your file

## Testing

```bash
python -m unittest discover -s tests -v
```

The tests run against a local mock HTTP server. They do not contact GitHub or use any of its rate limit.

## Requirements

- Python 3.11+
- `requests` 2.32 or newer (see `requirements.txt`)

## License

MIT License -- see LICENSE file for details.
