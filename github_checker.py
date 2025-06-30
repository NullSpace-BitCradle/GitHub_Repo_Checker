#!/usr/bin/env python3
"""
GitHub Repository Batch Checker
Checks if GitHub repositories exist and are accessible.
"""

import requests
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

class GitHubRepoChecker:
    def __init__(self, token=None, max_workers=10):
        self.session = requests.Session()
        self.max_workers = max_workers
        
        # Add GitHub token if provided (increases rate limits)
        if token:
            self.session.headers.update({'Authorization': f'token {token}'})
    
    def extract_repo_info(self, url):
        """Extract owner/repo from GitHub URL"""
        # Handle various GitHub URL formats
        patterns = [
            r'github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$',
            r'github\.com/([^/]+)/([^/]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                owner, repo = match.groups()
                # Clean up repo name (remove .git, etc.)
                repo = repo.rstrip('.git')
                return owner, repo
        return None, None
    
    def check_repo(self, url):
        """Check if a single repository exists"""
        owner, repo = self.extract_repo_info(url)
        
        if not owner or not repo:
            return {
                'url': url,
                'status': 'INVALID_URL',
                'message': 'Could not parse GitHub URL'
            }
        
        api_url = f'https://api.github.com/repos/{owner}/{repo}'
        
        try:
            response = self.session.get(api_url, timeout=10)
            
            if response.status_code == 200:
                repo_data = response.json()
                return {
                    'url': url,
                    'status': 'EXISTS',
                    'message': f"✓ {owner}/{repo}",
                    'private': repo_data.get('private', False),
                    'archived': repo_data.get('archived', False),
                    'stars': repo_data.get('stargazers_count', 0)
                }
            elif response.status_code == 404:
                return {
                    'url': url,
                    'status': 'NOT_FOUND',
                    'message': f"✗ {owner}/{repo} - Repository not found"
                }
            elif response.status_code == 403:
                return {
                    'url': url,
                    'status': 'FORBIDDEN',
                    'message': f"⚠ {owner}/{repo} - Access denied (private or rate limited)"
                }
            else:
                return {
                    'url': url,
                    'status': 'ERROR',
                    'message': f"? {owner}/{repo} - HTTP {response.status_code}"
                }
                
        except requests.exceptions.RequestException as e:
            return {
                'url': url,
                'status': 'ERROR',
                'message': f"✗ {owner}/{repo} - Network error: {str(e)}"
            }
    
    def check_repos_batch(self, urls, progress_callback=None):
        """Check multiple repositories concurrently"""
        results = []
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_url = {executor.submit(self.check_repo, url): url for url in urls}
            
            # Process completed tasks
            for i, future in enumerate(as_completed(future_to_url)):
                result = future.result()
                results.append(result)
                
                if progress_callback:
                    progress_callback(i + 1, len(urls), result)
                
                # Small delay to be nice to GitHub's API
                time.sleep(0.1)
        
        return results

def progress_callback(completed, total, result):
    """Print progress updates"""
    print(f"[{completed}/{total}] {result['message']}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python github_checker.py <file_with_urls.txt> [github_token]")
        print("\nFile should contain one GitHub URL per line")
        print("GitHub token is optional but recommended for higher rate limits")
        sys.exit(1)
    
    filename = sys.argv[1]
    token = sys.argv[2] if len(sys.argv) > 2 else None
    
    try:
        with open(filename, 'r') as f:
            urls = [line.strip() for line in f if line.strip() and 'github.com' in line]
    except FileNotFoundError:
        print(f"Error: File '{filename}' not found")
        sys.exit(1)
    
    if not urls:
        print("No GitHub URLs found in the file")
        sys.exit(1)
    
    print(f"Found {len(urls)} GitHub URLs to check...")
    
    checker = GitHubRepoChecker(token=token)
    results = checker.check_repos_batch(urls, progress_callback)
    
    # Summary
    print("\n" + "="*50)
    print("SUMMARY")
    print("="*50)
    
    status_counts = {}
    dead_links = []
    
    for result in results:
        status = result['status']
        status_counts[status] = status_counts.get(status, 0) + 1
        
        if status in ['NOT_FOUND', 'ERROR']:
            dead_links.append(result['url'])
    
    for status, count in status_counts.items():
        print(f"{status}: {count}")
    
    if dead_links:
        print(f"\nDead/Problematic Links ({len(dead_links)}):")
        for url in dead_links:
            print(f"  {url}")

if __name__ == "__main__":
    main()
