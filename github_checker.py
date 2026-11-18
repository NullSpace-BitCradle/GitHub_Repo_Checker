#!/usr/bin/env python3
"""
GitHub Repository Batch Checker
Checks if GitHub repositories exist and are accessible.
"""

import argparse
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_BASE = 'https://api.github.com'

# First path segments on github.com that are not user or organization names.
RESERVED_OWNERS = {
    'about', 'apps', 'collections', 'customer-stories', 'enterprise', 'events',
    'explore', 'features', 'issues', 'login', 'logout', 'marketplace',
    'new', 'notifications', 'orgs', 'pricing', 'pulls', 'readme', 'search',
    'security', 'settings', 'signup', 'sponsors', 'stars', 'team', 'topics',
    'trending', 'users', 'watching',
}

# A GitHub URL as it appears in bookmark files, markdown lists and notes.
# Requires github.com itself (not gist.github.com or a lookalike host).
_CANDIDATE_RE = re.compile(
    r'(?<![\w.@-])(?:(?:https?://)?(?:www\.)?|git@)github\.com[/:][^\s<>()\[\]"\']*',
    re.IGNORECASE,
)
_REPO_RE = re.compile(r'(?<![\w.-])(?:www\.)?github\.com[/:]([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+)', re.IGNORECASE)

# Statuses that mean the URL was not actually checked.
UNCHECKED_STATUSES = ('ERROR', 'RATE_LIMITED')


class GitHubRepoChecker:
    def __init__(self, token=None, max_workers=10, max_wait=120, retries=3,
                 backoff=0.5, max_rate_retries=3, api_base=None, log=None):
        """
        max_wait: the longest, in seconds, to sleep for a rate limit. A limit
            that resets later than this stops the run and the rest of the
            URLs are reported as RATE_LIMITED (not checked).
        retries/backoff: transient failures (connection errors, 5xx) are
            retried with exponential backoff before a URL is reported ERROR.
        """
        self.session = requests.Session()
        self.max_workers = max_workers
        self.max_wait = max_wait
        self.max_rate_retries = max_rate_retries
        self.api_base = (api_base or API_BASE).rstrip('/')
        self._log = log or (lambda message: print(message, file=sys.stderr))
        self._time = time.time
        self._sleep = time.sleep

        self._lock = threading.Lock()
        self._resume_at = 0.0       # no request is sent before this time
        self._stop_until = None     # set when the limit resets too far away
        self.rate_limit_reset = None

        self.session.headers.update({
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
        })
        # Add GitHub token if provided (increases rate limits)
        if token:
            self.session.headers.update({'Authorization': f'Bearer {token}'})

        retry = Retry(
            total=retries,
            connect=retries,
            read=retries,
            status=retries,
            backoff_factor=backoff,
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=('GET',),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)

    def extract_repo_info(self, url):
        """Extract (owner, repo) from a GitHub URL, or (None, None) if it is not a repository URL"""
        match = _REPO_RE.search(url)
        if not match:
            return None, None
        owner, repo = match.groups()
        # Clean up repo name (remove .git suffix and sentence punctuation)
        repo = repo.removesuffix('.git').rstrip('.')
        if owner.lower() in RESERVED_OWNERS or repo in ('', '.', '..'):
            return None, None
        return owner, repo

    # --- rate limiting -------------------------------------------------

    @staticmethod
    def _header_int(response, name):
        try:
            return int(response.headers.get(name))
        except (TypeError, ValueError):
            return None

    def _is_rate_limited(self, response):
        if response.status_code == 429:
            return True
        if response.status_code != 403:
            return False
        if self._header_int(response, 'X-RateLimit-Remaining') == 0:
            return True
        if 'Retry-After' in response.headers:
            return True
        try:
            return 'rate limit' in response.text[:1000].lower()
        except Exception:
            return False

    def _wait_seconds(self, response):
        """Seconds until a rate limited request may be retried."""
        retry_after = self._header_int(response, 'Retry-After')
        if retry_after is not None:
            return max(retry_after, 1)
        reset = self._header_int(response, 'X-RateLimit-Reset')
        if reset is not None:
            return max(reset - self._time() + 1, 1)
        return 60  # GitHub's advice for secondary limits that carry no header

    def _pause(self, wait):
        """Hold every worker until the limit clears, or stop the run if that is too far off."""
        resume = self._time() + wait
        with self._lock:
            if wait > self.max_wait:
                if self._stop_until is None:
                    self._stop_until = resume
                    self.rate_limit_reset = resume
                    self._log(
                        f"Rate limited: GitHub resets in about {int(wait // 60)} min, "
                        f"longer than --max-wait ({self.max_wait}s). "
                        "Stopping; remaining URLs will be reported as not checked."
                    )
                return
            if resume > self._resume_at:
                if self._resume_at <= self._time():
                    self._log(f"Rate limited: waiting {int(wait)}s before continuing...")
                self._resume_at = resume

    def _wait_for_pause(self):
        while True:
            with self._lock:
                delay = self._resume_at - self._time()
            if delay <= 0:
                return
            self._sleep(min(delay, 5))

    def _note_remaining(self, response):
        """If the quota just ran out, pause or stop before the next request is wasted."""
        if self._header_int(response, 'X-RateLimit-Remaining') == 0:
            reset = self._header_int(response, 'X-RateLimit-Reset')
            if reset is not None:
                self._pause(max(reset - self._time() + 1, 1))

    def _rate_limited_result(self, url, owner, repo):
        when = ''
        if self.rate_limit_reset:
            when = ' Limit resets at ' + time.strftime('%H:%M:%S', time.localtime(self.rate_limit_reset)) + '.'
        return {
            'url': url,
            'status': 'RATE_LIMITED',
            'message': f"UNCHECKED {owner}/{repo} - GitHub rate limit reached, not checked.{when}",
        }

    # --- checks --------------------------------------------------------

    def check_repo(self, url):
        """Check if a single repository exists"""
        owner, repo = self.extract_repo_info(url)

        if not owner or not repo:
            return {
                'url': url,
                'status': 'INVALID_URL',
                'message': f'SKIP {url} - not a GitHub repository URL'
            }

        api_url = f'{self.api_base}/repos/{owner}/{repo}'

        try:
            for _ in range(self.max_rate_retries + 1):
                if self._stop_until is not None:
                    return self._rate_limited_result(url, owner, repo)
                self._wait_for_pause()

                response = self.session.get(api_url, timeout=10)

                if self._is_rate_limited(response):
                    self._pause(self._wait_seconds(response))
                    continue
                self._note_remaining(response)
                break
            else:
                return self._rate_limited_result(url, owner, repo)

            if response.status_code == 200:
                repo_data = response.json()
                private = repo_data.get('private', False)
                archived = repo_data.get('archived', False)
                tags = (' [archived]' if archived else '') + (' [private]' if private else '')
                return {
                    'url': url,
                    'status': 'EXISTS',
                    'message': f"OK {owner}/{repo}{tags}",
                    'private': private,
                    'archived': archived,
                    'stars': repo_data.get('stargazers_count', 0)
                }
            elif response.status_code == 404:
                # GitHub answers 404, not 403, for a private repo you cannot see.
                return {
                    'url': url,
                    'status': 'NOT_FOUND',
                    'message': f"FAIL {owner}/{repo} - Repository not found (deleted, or private to you)"
                }
            elif response.status_code == 403:
                return {
                    'url': url,
                    'status': 'FORBIDDEN',
                    'message': f"WARN {owner}/{repo} - HTTP 403, access denied (not a rate limit)"
                }
            else:
                return {
                    'url': url,
                    'status': 'ERROR',
                    'message': f"ERROR {owner}/{repo} - HTTP {response.status_code}, not checked"
                }

        except requests.exceptions.RequestException as e:
            return {
                'url': url,
                'status': 'ERROR',
                'message': f"ERROR {owner}/{repo} - Network error, not checked: {str(e)}"
            }

    def check_repos_batch(self, urls, progress_callback=None):
        """Check multiple repositories concurrently. Results are in input order."""
        results = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            for i, result in enumerate(executor.map(self.check_repo, urls)):
                results.append(result)

                if progress_callback:
                    progress_callback(i + 1, len(urls), result)

        return results


def find_github_urls(line):
    """Return every github.com URL candidate in a line of text."""
    return [m.group(0) for m in _CANDIDATE_RE.finditer(line)]


def load_urls(filename):
    """
    Read GitHub URLs from a text file.

    Returns (urls, skipped, duplicates): the repository URLs in file order with
    repeats removed, the lines that mention github.com but are not a
    repository, and the number of repeats dropped. Accepts plain URLs,
    markdown links and list items, and ssh-style git@github.com:owner/repo.
    """
    parser = GitHubRepoChecker()
    urls, skipped, seen, duplicates = [], [], set(), 0

    # utf-8-sig drops a BOM; errors='replace' keeps a stray byte from aborting the run
    with open(filename, 'r', encoding='utf-8-sig', errors='replace') as f:
        for number, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or 'github.com' not in line.lower():
                continue
            candidates = find_github_urls(line)
            if not candidates:
                skipped.append((number, line, 'no github.com repository URL found'))
                continue
            for candidate in candidates:
                owner, repo = parser.extract_repo_info(candidate)
                if not owner:
                    skipped.append((number, candidate, 'not a repository URL (profile, gist or site page)'))
                    continue
                key = f'{owner}/{repo}'.lower()
                if key in seen:
                    duplicates += 1
                    continue
                seen.add(key)
                urls.append(candidate)
    return urls, skipped, duplicates


def progress_callback(completed, total, result):
    """Print progress updates"""
    print(f"[{completed}/{total}] {result['message']}")


def print_summary(results, skipped, duplicates, rate_limit_reset=None):
    """Print the summary and return the exit code (0 clean, 1 if anything needs attention)."""
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)

    status_counts = {}
    for result in results:
        status_counts[result['status']] = status_counts.get(result['status'], 0) + 1
    for status, count in status_counts.items():
        print(f"{status}: {count}")

    archived = [r['url'] for r in results if r.get('archived')]
    if archived:
        print(f"ARCHIVED (included in EXISTS): {len(archived)}")
    if duplicates:
        print(f"Duplicate URLs skipped: {duplicates}")

    dead = [r['url'] for r in results if r['status'] == 'NOT_FOUND']
    forbidden = [r['url'] for r in results if r['status'] == 'FORBIDDEN']
    unchecked = [r['url'] for r in results if r['status'] in UNCHECKED_STATUSES]

    if dead:
        print(f"\nDead Links ({len(dead)}):")
        for url in dead:
            print(f"  {url}")
    if forbidden:
        print(f"\nForbidden ({len(forbidden)}):")
        for url in forbidden:
            print(f"  {url}")
    if archived:
        print(f"\nArchived Repositories ({len(archived)}):")
        for url in archived:
            print(f"  {url}")
    if unchecked:
        print(f"\nNot Checked, retry later ({len(unchecked)}):")
        for url in unchecked:
            print(f"  {url}")
        if any(r['status'] == 'RATE_LIMITED' for r in results):
            when = ''
            if rate_limit_reset:
                when = ' The limit resets at ' + time.strftime('%H:%M:%S', time.localtime(rate_limit_reset)) + '.'
            print(f"GitHub's rate limit stopped the run.{when} Set GITHUB_TOKEN for a higher limit.")
    if skipped:
        print(f"\nSkipped Lines ({len(skipped)}):")
        for number, text, reason in skipped:
            print(f"  line {number}: {text} ({reason})")

    return 1 if (dead or forbidden or unchecked) else 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check whether the GitHub repositories listed in a file exist. "
        "Exits 0 if every repository was checked and found, 1 if any is dead, "
        "forbidden or could not be checked, 2 for a usage or input error."
    )
    parser.add_argument('file', help='text file with one GitHub URL per line')
    parser.add_argument('token', nargs='?', help=argparse.SUPPRESS)  # deprecated: use GITHUB_TOKEN
    parser.add_argument('--max-wait', type=int, default=120, metavar='SECONDS',
                        help='longest to sleep for a rate limit before stopping (default 120)')
    parser.add_argument('--workers', type=int, default=10,
                        help='concurrent requests (default 10)')
    args = parser.parse_args(argv)

    token = os.environ.get('GITHUB_TOKEN')
    if args.token:
        print("Warning: a token on the command line shows up in shell history and process lists. "
              "Set the GITHUB_TOKEN environment variable instead.", file=sys.stderr)
        token = args.token

    # Keep an unusual terminal encoding from aborting the run mid-output
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='replace')

    try:
        urls, skipped, duplicates = load_urls(args.file)
    except FileNotFoundError:
        print(f"Error: File '{args.file}' not found", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"Error: cannot read '{args.file}': {e}", file=sys.stderr)
        return 2

    if not urls:
        print("No GitHub repository URLs found in the file", file=sys.stderr)
        return 2

    print(f"Found {len(urls)} GitHub URLs to check...")
    if not token and len(urls) > 60:
        print("Note: without GITHUB_TOKEN GitHub allows 60 requests per hour, "
              f"so {len(urls)} URLs will probably hit the limit.", file=sys.stderr)

    checker = GitHubRepoChecker(token=token, max_workers=args.workers, max_wait=args.max_wait)
    results = checker.check_repos_batch(urls, progress_callback)

    return print_summary(results, skipped, duplicates, checker.rate_limit_reset)


if __name__ == "__main__":
    sys.exit(main())
