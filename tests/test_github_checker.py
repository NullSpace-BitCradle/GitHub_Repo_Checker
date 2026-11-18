"""Tests for github_checker.

The API is a local mock HTTP server, so nothing here talks to GitHub or uses
any of its rate limit.
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import github_checker
from github_checker import GitHubRepoChecker, find_github_urls, load_urls


def repo_json(full_name, **extra):
    data = {'full_name': full_name, 'private': False, 'archived': False, 'stargazers_count': 1}
    data.update(extra)
    return json.dumps(data)


class MockGitHub:
    """A tiny stand-in for api.github.com.

    `script` maps a request path to a list of (status, headers, body) replies,
    served in order; the last one repeats. A path with no entry returns 404.
    """

    def __init__(self):
        self.script = {}
        self.hits = []
        self.auth_headers = []
        self.delays = {}
        self._lock = threading.Lock()
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                with mock._lock:
                    mock.hits.append(self.path)
                    mock.auth_headers.append(self.headers.get('Authorization'))
                    replies = mock.script.get(self.path)
                    if replies:
                        reply = replies.pop(0) if len(replies) > 1 else replies[0]
                    else:
                        reply = (404, {}, json.dumps({'message': 'Not Found'}))
                time.sleep(mock.delays.get(self.path, 0))
                status, headers, body = reply
                data = body.encode()
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, str(value))
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}'
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': 0.01}, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def ok(self, owner, repo, **extra):
        self.script[f'/repos/{owner}/{repo}'] = [(200, {}, repo_json(f'{owner}/{repo}', **extra))]


class FakeClock:
    """Replaces time.time and time.sleep so a rate limit wait costs no real time."""

    def __init__(self):
        self.now = 1_000_000.0
        self.slept = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def make_checker(mock, **kwargs):
    kwargs.setdefault('retries', 0)
    kwargs.setdefault('backoff', 0)
    kwargs.setdefault('max_workers', 1)
    return GitHubRepoChecker(api_base=mock.url, log=lambda message: None, **kwargs)


class MockedTestCase(unittest.TestCase):
    def setUp(self):
        self.mock = MockGitHub()
        self.addCleanup(self.mock.close)


class TestExtractRepoInfo(unittest.TestCase):
    def setUp(self):
        self.checker = GitHubRepoChecker()

    def test_plain_urls(self):
        cases = {
            'https://github.com/octo/repo': ('octo', 'repo'),
            'https://github.com/octo/repo/': ('octo', 'repo'),
            'https://github.com/octo/repo.git': ('octo', 'repo'),
            'https://github.com/octo/repo/tree/main/src': ('octo', 'repo'),
            'https://github.com/octo/repo?tab=readme': ('octo', 'repo'),
            'https://github.com/octo/repo#readme': ('octo', 'repo'),
            'https://www.github.com/octo/repo': ('octo', 'repo'),
            'https://GitHub.com/octo/Upper-Case': ('octo', 'Upper-Case'),
            'github.com/octo/schemeless': ('octo', 'schemeless'),
            'git@github.com:octo/sshstyle.git': ('octo', 'sshstyle'),
            'https://github.com/octo/dotted.name.js': ('octo', 'dotted.name.js'),
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(self.checker.extract_repo_info(url), expected)

    def test_trailing_text_is_not_part_of_the_name(self):
        for url in ('https://github.com/octo/markdown)', 'https://github.com/octo/repo.',
                    'https://github.com/octo/repo,'):
            with self.subTest(url=url):
                self.assertEqual(self.checker.extract_repo_info(url)[0], 'octo')
                self.assertNotIn(')', self.checker.extract_repo_info(url)[1])

    def test_non_repository_urls_are_rejected(self):
        for url in ('https://github.com/octo',
                    'https://github.com/topics/security',
                    'https://github.com/sponsors/octo',
                    'https://github.com/orgs/acme/people',
                    'https://github.com/settings/tokens',
                    'https://gist.github.com/someone/abcdef0123',
                    'https://example.com/octo/repo'):
            with self.subTest(url=url):
                self.assertEqual(self.checker.extract_repo_info(url), (None, None))


class TestFindAndLoadUrls(unittest.TestCase):
    def _load(self, text=None, raw=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'urls.txt')
            with open(path, 'wb') as f:
                f.write(raw if raw is not None else text.encode('utf-8'))
            return load_urls(path)

    def test_find_github_urls_in_markdown_and_notes(self):
        self.assertEqual(find_github_urls('- https://github.com/octo/bullet - nice tool'),
                         ['https://github.com/octo/bullet'])
        self.assertEqual(find_github_urls('[label](https://github.com/octo/markdown)'),
                         ['https://github.com/octo/markdown'])
        self.assertEqual(find_github_urls('see https://gist.github.com/a/b'), [])

    def test_bookmark_file_formats(self):
        text = '\n'.join([
            'https://github.com/octo/plain',
            '- https://github.com/octo/bullet - nice tool',
            '[label](https://github.com/octo/markdown)',
            'https://gist.github.com/someone/abcdef0123',
            'https://github.com/topics/security',
            'git@github.com:octo/sshstyle.git',
            'https://github.com/octo',
            'https://GitHub.com/octo/uppercase',
            'https://github.com/octo/readme?tab=readme',
            '',
            'a line with no link',
        ])
        urls, skipped, duplicates = self._load(text)
        self.assertEqual([GitHubRepoChecker().extract_repo_info(u)[1] for u in urls],
                         ['plain', 'bullet', 'markdown', 'sshstyle', 'uppercase', 'readme'])
        self.assertEqual(duplicates, 0)
        skipped_lines = {number for number, _, _ in skipped}
        self.assertEqual(skipped_lines, {4, 5, 7})  # gist, topics, bare profile

    def test_duplicates_are_dropped_case_insensitively(self):
        urls, _, duplicates = self._load(
            'https://github.com/octo/plain\nhttps://github.com/OCTO/Plain\nhttps://github.com/octo/plain.git\n')
        self.assertEqual(len(urls), 1)
        self.assertEqual(duplicates, 2)

    def test_input_order_is_kept(self):
        urls, _, _ = self._load('https://github.com/b/b\nhttps://github.com/a/a\n')
        self.assertEqual(urls, ['https://github.com/b/b', 'https://github.com/a/a'])

    def test_bom_and_non_utf8_bytes_do_not_crash(self):
        urls, _, _ = self._load(raw=b'\xef\xbb\xbfhttps://github.com/octo/bom\n')
        self.assertEqual(len(urls), 1)
        self.assertTrue(urls[0].startswith('https://github.com/octo/bom'))
        urls, _, _ = self._load(raw=b'caf\xe9 https://github.com/octo/latin1\n')
        self.assertEqual(len(urls), 1)


class TestStatusHandling(MockedTestCase):
    def test_exists_archived_private_and_not_found(self):
        self.mock.ok('octo', 'live')
        self.mock.ok('octo', 'old', archived=True)
        self.mock.ok('octo', 'secret', private=True)
        checker = make_checker(self.mock)
        results = checker.check_repos_batch([
            'https://github.com/octo/live',
            'https://github.com/octo/old',
            'https://github.com/octo/secret',
            'https://github.com/octo/gone',
        ])
        self.assertEqual([r['status'] for r in results], ['EXISTS', 'EXISTS', 'EXISTS', 'NOT_FOUND'])
        self.assertNotIn('[archived]', results[0]['message'])
        self.assertIn('[archived]', results[1]['message'])
        self.assertTrue(results[1]['archived'])
        self.assertIn('[private]', results[2]['message'])
        self.assertIn('not found', results[3]['message'])

    def test_plain_403_is_forbidden_not_rate_limited(self):
        self.mock.script['/repos/octo/blocked'] = [(403, {}, json.dumps({'message': 'Repository access blocked'}))]
        result = make_checker(self.mock).check_repo('https://github.com/octo/blocked')
        self.assertEqual(result['status'], 'FORBIDDEN')
        self.assertEqual(len(self.mock.hits), 1)

    def test_invalid_url_makes_no_request(self):
        result = make_checker(self.mock).check_repo('https://github.com/topics/security')
        self.assertEqual(result['status'], 'INVALID_URL')
        self.assertEqual(self.mock.hits, [])

    def test_messages_are_ascii(self):
        self.mock.ok('octo', 'old', archived=True, private=True)
        results = make_checker(self.mock).check_repos_batch([
            'https://github.com/octo/old', 'https://github.com/octo/gone', 'https://github.com/topics/x'])
        for result in results:
            self.assertTrue(result['message'].isascii(), result['message'])

    def test_results_keep_input_order(self):
        for name in ('first', 'second', 'third'):
            self.mock.ok('octo', name)
        self.mock.delays['/repos/octo/first'] = 0.3
        urls = [f'https://github.com/octo/{n}' for n in ('first', 'second', 'third')]
        results = make_checker(self.mock, max_workers=3).check_repos_batch(urls)
        self.assertEqual([r['url'] for r in results], urls)

    def test_token_is_sent_as_bearer_header(self):
        self.mock.ok('octo', 'live')
        checker = GitHubRepoChecker(token='tok-123', api_base=self.mock.url, retries=0)
        checker.check_repo('https://github.com/octo/live')
        self.assertEqual(self.mock.auth_headers, ['Bearer tok-123'])


class TestRateLimit(MockedTestCase):
    def _limited(self, reset_in=3600):
        return (403, {'X-RateLimit-Limit': 60, 'X-RateLimit-Remaining': 0,
                      'X-RateLimit-Reset': int(time.time()) + reset_in},
                json.dumps({'message': 'API rate limit exceeded for 1.2.3.4.'}))

    def test_long_rate_limit_stops_the_run_and_reports_unchecked(self):
        """Once the quota is gone for an hour, no more requests are sent and the rest are RATE_LIMITED."""
        self.mock.ok('octo', 'a')
        self.mock.ok('octo', 'b')
        for name in ('c', 'd', 'e'):
            self.mock.script[f'/repos/octo/{name}'] = [self._limited()]
        urls = [f'https://github.com/octo/{n}' for n in 'abcde']
        results = make_checker(self.mock).check_repos_batch(urls)
        self.assertEqual([r['status'] for r in results],
                         ['EXISTS', 'EXISTS', 'RATE_LIMITED', 'RATE_LIMITED', 'RATE_LIMITED'])
        # a, b, then the c request that was refused; d and e were never sent
        self.assertEqual(self.mock.hits, ['/repos/octo/a', '/repos/octo/b', '/repos/octo/c'])
        self.assertIn('not checked', results[2]['message'])

    def test_concurrent_workers_stop_sending_once_limited(self):
        """With 10 workers and 60 URLs, the limit stops the run within one worker batch."""
        for i in range(3):
            self.mock.ok('octo', f'r{i}')
        for i in range(3, 60):
            self.mock.script[f'/repos/octo/r{i}'] = [self._limited()]
        urls = [f'https://github.com/octo/r{i}' for i in range(60)]
        checker = make_checker(self.mock, max_workers=10)
        results = checker.check_repos_batch(urls)
        statuses = [r['status'] for r in results]
        self.assertEqual(statuses[:3], ['EXISTS'] * 3)
        self.assertEqual(statuses[3:], ['RATE_LIMITED'] * 57)
        self.assertLessEqual(len(self.mock.hits), 3 + 10)

    def test_quota_running_out_on_a_success_stops_before_a_wasted_request(self):
        remaining_zero = (200, {'X-RateLimit-Remaining': 0, 'X-RateLimit-Reset': int(time.time()) + 3600},
                          repo_json('octo/a'))
        self.mock.script['/repos/octo/a'] = [remaining_zero]
        self.mock.ok('octo', 'b')
        results = make_checker(self.mock).check_repos_batch(
            ['https://github.com/octo/a', 'https://github.com/octo/b'])
        self.assertEqual([r['status'] for r in results], ['EXISTS', 'RATE_LIMITED'])
        self.assertEqual(self.mock.hits, ['/repos/octo/a'])

    def test_short_429_with_retry_after_waits_and_retries(self):
        self.mock.script['/repos/octo/a'] = [
            (429, {'Retry-After': 2}, json.dumps({'message': 'slow down'})),
            (200, {}, repo_json('octo/a')),
        ]
        checker = make_checker(self.mock)
        clock = FakeClock()
        checker._time, checker._sleep = clock.time, clock.sleep
        result = checker.check_repo('https://github.com/octo/a')
        self.assertEqual(result['status'], 'EXISTS')
        self.assertEqual(len(self.mock.hits), 2)
        self.assertGreaterEqual(sum(clock.slept), 2)

    def test_secondary_limit_without_headers_waits_a_minute(self):
        self.mock.script['/repos/octo/a'] = [
            (403, {}, json.dumps({'message': 'You have exceeded a secondary rate limit.'})),
            (200, {}, repo_json('octo/a')),
        ]
        checker = make_checker(self.mock)
        clock = FakeClock()
        checker._time, checker._sleep = clock.time, clock.sleep
        result = checker.check_repo('https://github.com/octo/a')
        self.assertEqual(result['status'], 'EXISTS')
        self.assertGreaterEqual(sum(clock.slept), 60)

    def test_rate_limit_longer_than_max_wait_is_not_slept_through(self):
        self.mock.script['/repos/octo/a'] = [(429, {'Retry-After': 500}, '{}')]
        checker = make_checker(self.mock, max_wait=120)
        clock = FakeClock()
        checker._time, checker._sleep = clock.time, clock.sleep
        result = checker.check_repo('https://github.com/octo/a')
        self.assertEqual(result['status'], 'RATE_LIMITED')
        self.assertEqual(clock.slept, [])

    def test_a_rate_limit_that_never_clears_gives_up(self):
        self.mock.script['/repos/octo/a'] = [(429, {'Retry-After': 1}, '{}')]
        checker = make_checker(self.mock, max_rate_retries=2)
        clock = FakeClock()
        checker._time, checker._sleep = clock.time, clock.sleep
        result = checker.check_repo('https://github.com/octo/a')
        self.assertEqual(result['status'], 'RATE_LIMITED')
        self.assertEqual(len(self.mock.hits), 3)  # first try plus two retries


class TestTransientFailures(MockedTestCase):
    def test_5xx_is_retried_then_succeeds(self):
        self.mock.script['/repos/octo/a'] = [(502, {}, '{}'), (200, {}, repo_json('octo/a'))]
        result = make_checker(self.mock, retries=2).check_repo('https://github.com/octo/a')
        self.assertEqual(result['status'], 'EXISTS')
        self.assertEqual(len(self.mock.hits), 2)

    def test_persistent_5xx_is_reported_as_unchecked_error_not_dead(self):
        self.mock.script['/repos/octo/a'] = [(503, {}, '{}')]
        result = make_checker(self.mock, retries=2).check_repo('https://github.com/octo/a')
        self.assertEqual(result['status'], 'ERROR')
        self.assertIn('not checked', result['message'])
        self.assertEqual(len(self.mock.hits), 3)

    def test_connection_failure_is_error(self):
        checker = make_checker(self.mock)
        with patch.object(checker.session, 'get',
                          side_effect=requests.exceptions.ConnectionError('connection refused')):
            result = checker.check_repo('https://github.com/octo/a')
        self.assertEqual(result['status'], 'ERROR')
        self.assertIn('Network error', result['message'])
        self.assertIn('not checked', result['message'])


class TestCommandLine(MockedTestCase):
    def _run(self, text=None, token=None, extra=(), raw=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'urls.txt')
            with open(path, 'wb') as f:
                f.write(raw if raw is not None else text.encode('utf-8'))
            env = {'GITHUB_TOKEN': token} if token else {}
            out, err = io.StringIO(), io.StringIO()
            with patch.object(github_checker, 'API_BASE', self.mock.url), \
                    patch.dict(os.environ, env, clear=False), \
                    patch.object(GitHubRepoChecker, '__init__', _patched_init), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                if not token:
                    os.environ.pop('GITHUB_TOKEN', None)
                code = github_checker.main([path, *extra])
            return code, out.getvalue(), err.getvalue()

    def test_clean_run_exits_zero(self):
        self.mock.ok('octo', 'a')
        code, out, _ = self._run('https://github.com/octo/a\n')
        self.assertEqual(code, 0)
        self.assertIn('EXISTS: 1', out)

    def test_dead_link_exits_one_and_is_listed(self):
        self.mock.ok('octo', 'a')
        code, out, _ = self._run('https://github.com/octo/a\nhttps://github.com/octo/gone\n')
        self.assertEqual(code, 1)
        self.assertIn('Dead Links (1)', out)
        self.assertIn('https://github.com/octo/gone', out)

    def test_archived_repos_are_shown_and_counted(self):
        self.mock.ok('octo', 'old', archived=True)
        code, out, _ = self._run('https://github.com/octo/old\n')
        self.assertIn('[archived]', out)
        self.assertIn('Archived Repositories (1)', out)

    def test_rate_limit_is_reported_as_not_checked_and_exits_one(self):
        limited = (403, {'X-RateLimit-Remaining': 0, 'X-RateLimit-Reset': int(time.time()) + 3600},
                   json.dumps({'message': 'API rate limit exceeded'}))
        self.mock.script['/repos/octo/a'] = [limited]
        text = 'https://github.com/octo/a\nhttps://github.com/octo/b\nhttps://github.com/octo/c\n'
        code, out, err = self._run(text, extra=['--workers', '1'])
        self.assertEqual(code, 1)
        self.assertIn('RATE_LIMITED: 3', out)
        self.assertIn('Not Checked, retry later (3)', out)
        self.assertNotIn('Dead Links', out)
        self.assertIn('Rate limited', err)

    def test_skipped_lines_and_duplicates_are_reported(self):
        self.mock.ok('octo', 'a')
        text = 'https://github.com/octo/a\nhttps://github.com/octo/a\nhttps://github.com/topics/security\n'
        code, out, _ = self._run(text)
        self.assertEqual(code, 0)
        self.assertIn('Found 1 GitHub URLs', out)
        self.assertIn('Duplicate URLs skipped: 1', out)
        self.assertIn('line 3', out)
        self.assertEqual(self.mock.hits, ['/repos/octo/a'])

    def test_token_from_env_is_used_and_never_printed(self):
        self.mock.ok('octo', 'a')
        code, out, err = self._run('https://github.com/octo/a\n', token='secret-token-value')
        self.assertEqual(self.mock.auth_headers, ['Bearer secret-token-value'])
        self.assertNotIn('secret-token-value', out + err)

    def test_token_on_the_command_line_still_works_but_warns(self):
        self.mock.ok('octo', 'a')
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'urls.txt')
            with open(path, 'w') as f:
                f.write('https://github.com/octo/a\n')
            out, err = io.StringIO(), io.StringIO()
            with patch.object(github_checker, 'API_BASE', self.mock.url), \
                    patch.object(GitHubRepoChecker, '__init__', _patched_init), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = github_checker.main([path, 'argv-token-value'])
        self.assertEqual(code, 0)
        self.assertEqual(self.mock.auth_headers, ['Bearer argv-token-value'])
        self.assertIn('GITHUB_TOKEN', err.getvalue())
        self.assertNotIn('argv-token-value', out.getvalue() + err.getvalue())

    def test_missing_file_and_empty_file_exit_two(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(github_checker.main([os.path.join(tempfile.gettempdir(), 'no-such-urls-file.txt')]), 2)
        code, _, err = self._run('nothing useful here\n')
        self.assertEqual(code, 2)
        self.assertIn('No GitHub repository URLs', err)

    def test_latin1_input_does_not_crash(self):
        self.mock.ok('octo', 'a')
        code, out, _ = self._run(raw=b'caf\xe9 https://github.com/octo/a\n')
        self.assertEqual(code, 0)


_real_init = GitHubRepoChecker.__init__


def _patched_init(self, *args, **kwargs):
    """CLI tests: no retries or backoff so failures return at once."""
    kwargs.setdefault('retries', 0)
    kwargs.setdefault('backoff', 0)
    _real_init(self, *args, **kwargs)


if __name__ == '__main__':
    unittest.main()
