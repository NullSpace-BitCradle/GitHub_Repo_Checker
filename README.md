# GitHub Repository Batch Checker

A Python tool to quickly validate large collections of GitHub repository bookmarks. Checks if repos exist, are accessible, or have been deleted/made private using GitHub's API with concurrent processing.

## Features

- ⚡ **Fast concurrent checking** - Process hundreds of URLs quickly
- 🛡️ **Rate limiting protection** - Respects GitHub's API limits
- 📊 **Detailed status reporting** - Know if repos are deleted, private, archived, etc.
- 📈 **Progress tracking** - Real-time updates with final summary
- 🔑 **Token support** - Optional GitHub token for higher rate limits
- 🎯 **Dead link identification** - Easily spot URLs that need removal/fixing

## Installation

```bash
git clone https://github.com/NullSpace-BitCradle/GitHub_Repo_Checker.git
cd GitHub_Repo_Checker
pip install requests
```

## Usage

### Basic Usage

1. Create a text file with your GitHub URLs (one per line):
```
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

For higher rate limits (5000/hour vs 60/hour):

```bash
python github_checker.py urls.txt YOUR_GITHUB_TOKEN
```

## Getting a GitHub Token

1. Go to [GitHub Settings → Developer settings → Personal access tokens](https://github.com/settings/tokens)
2. Click "Generate new token (classic)"
3. Select the `public_repo` scope
4. Copy the generated token

## Sample Output

```
Found 150 GitHub URLs to check...
[1/150] ✓ SecureAuthCorp/impacket
[2/150] ✗ someuser/deleted-repo - Repository not found
[3/150] ⚠ private-org/secret-tool - Access denied (private or rate limited)
[4/150] ✓ danielmiessler/SecLists

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

- ✅ **EXISTS** - Repository is accessible
- ❌ **NOT_FOUND** - Repository deleted or never existed
- ⚠️ **FORBIDDEN** - Private repository or rate limited
- ❓ **ERROR** - Network error or other issue
- 🚫 **INVALID_URL** - Malformed GitHub URL

## Use Cases

- 🔐 **Offensive Security Collections** - Validate pentesting tool repositories
- 📚 **Research Bookmarks** - Check academic/research repo collections  
- 🛠️ **Development Tools** - Maintain curated lists of useful repositories
- 📖 **Documentation Links** - Verify tutorial and guide repositories
- 🏢 **Organization Audits** - Check if team repositories are still accessible

## Tips

- **Large collections**: The script includes rate limiting to avoid hitting GitHub's API limits
- **Private repos**: Will show as FORBIDDEN - this is normal for private repositories
- **Archived repos**: Still show as EXISTS but are marked as archived in detailed output
- **Redirected repos**: GitHub redirects are followed automatically

## Requirements

- Python 3.6+
- `requests` library

## License

MIT License - see LICENSE file for details
