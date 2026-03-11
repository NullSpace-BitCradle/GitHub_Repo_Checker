# GitHub Repository Batch Checker

A Python tool to quickly validate large collections of GitHub repository bookmarks. Checks if repos exist, are accessible, or have been deleted/made private using GitHub's API with concurrent processing.

## Features

- **Fast concurrent checking** - Process hundreds of URLs quickly
- **Rate limiting protection** - Respects GitHub's API limits
- **Detailed status reporting** - Know if repos are deleted, private, archived, etc.
- **Progress tracking** - Real-time updates with final summary
- **Token support** - Optional GitHub token for higher rate limits
- **Dead link identification** - Easily spot URLs that need removal or fixing

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

### With GitHub Token (Recommended)

Using a token increases the rate limit from 60 to 5,000 requests per hour.

**Option 1 - Environment variable (recommended):**

```bash
export GITHUB_TOKEN="your_token_here"
python github_checker.py urls.txt
```

**Option 2 - Command line argument:**

```bash
python github_checker.py urls.txt YOUR_GITHUB_TOKEN
```

### Getting a GitHub Token

1. Go to [GitHub Settings > Developer settings > Personal access tokens](https://github.com/settings/tokens)
2. Click "Generate new token (classic)"
3. Select the `public_repo` scope
4. Copy the generated token

## Sample Output

```text
Found 150 GitHub URLs to check...
[1/150] OK SecureAuthCorp/impacket
[2/150] FAIL someuser/deleted-repo - Repository not found
[3/150] WARN private-org/secret-tool - Access denied (private or rate limited)
[4/150] OK danielmiessler/SecLists

==================================================
SUMMARY
==================================================
EXISTS: 142
NOT_FOUND: 6
FORBIDDEN: 2

Dead/Problematic Links (8):
  https://github.com/someuser/deleted-repo
  https://github.com/another/missing-tool
```

## Status Codes

| Status | Meaning |
|--------|---------|
| **EXISTS** | Repository is accessible |
| **NOT_FOUND** | Repository deleted or never existed |
| **FORBIDDEN** | Private repository or rate limited |
| **ERROR** | Network error or other issue |
| **INVALID_URL** | Malformed GitHub URL |

## Use Cases

- **Offensive security collections** - Validate pentesting tool repositories
- **Research bookmarks** - Check academic and research repo collections
- **Development tools** - Maintain curated lists of useful repositories
- **Documentation links** - Verify tutorial and guide repositories
- **Organization audits** - Check if team repositories are still accessible

## Tips

- **Large collections**: The script includes per-request rate limiting to avoid hitting GitHub's API limits
- **Private repos**: Will show as FORBIDDEN -- this is normal for private repositories
- **Archived repos**: Still show as EXISTS but are marked as archived in detailed output
- **Redirected repos**: GitHub redirects are followed automatically
- **Environment variable**: Set `GITHUB_TOKEN` to avoid passing the token on the command line

## Requirements

- Python 3.9+
- `requests` library

## License

MIT License -- see LICENSE file for details.
