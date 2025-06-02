#!/usr/bin/env python3
"""
GitHub File Pusher
Simple script to push files from current directory to a GitHub repository
"""

import os
import sys
import json
import base64
import getpass
from pathlib import Path
from typing import List, Dict, Optional
import requests
from datetime import datetime

class GitHubPusher:
    def __init__(self, token: str = None):
        self.token = token
        self.base_url = "https://api.github.com"
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "GitHub-File-Pusher"
        }
        if self.token:
            self.headers["Authorization"] = f"token {self.token}"
    
    def authenticate(self) -> bool:
        """Test authentication with GitHub"""
        try:
            response = requests.get(f"{self.base_url}/user", headers=self.headers)
            if response.status_code == 200:
                user_data = response.json()
                print(f"✅ Successfully authenticated as: {user_data['login']}")
                return True
            else:
                print(f"❌ Authentication failed: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Authentication error: {e}")
            return False
    
    def get_repositories(self) -> List[Dict]:
        """Get list of user repositories"""
        try:
            repos = []
            page = 1
            per_page = 100
            
            while True:
                response = requests.get(
                    f"{self.base_url}/user/repos",
                    headers=self.headers,
                    params={
                        "page": page,
                        "per_page": per_page,
                        "sort": "updated",
                        "type": "all"
                    }
                )
                
                if response.status_code != 200:
                    print(f"❌ Failed to get repositories: {response.status_code}")
                    return []
                
                page_repos = response.json()
                if not page_repos:
                    break
                
                repos.extend(page_repos)
                page += 1
            
            return repos
        except Exception as e:
            print(f"❌ Error getting repositories: {e}")
            return []
    
    def select_repository(self, repos: List[Dict]) -> Optional[Dict]:
        """Let user select a repository"""
        if not repos:
            print("❌ No repositories found")
            return None
        
        print("\n📁 Available Repositories:")
        print("-" * 50)
        
        for i, repo in enumerate(repos, 1):
            visibility = "🔒 Private" if repo['private'] else "🌐 Public"
            updated = repo['updated_at'][:10]  # Just the date
            print(f"{i:2d}. {repo['name']} ({visibility}) - Updated: {updated}")
            if repo['description']:
                print(f"    📝 {repo['description'][:60]}...")
        
        print("-" * 50)
        
        while True:
            try:
                choice = input(f"\nSelect repository (1-{len(repos)}) or 'q' to quit: ").strip()
                if choice.lower() == 'q':
                    return None
                
                index = int(choice) - 1
                if 0 <= index < len(repos):
                    return repos[index]
                else:
                    print(f"❌ Please enter a number between 1 and {len(repos)}")
            except ValueError:
                print("❌ Please enter a valid number")
    
    def get_local_files(self, exclude_patterns: List[str] = None) -> List[Path]:
        """Get list of files in current directory"""
        if exclude_patterns is None:
            exclude_patterns = [
                '.git', '__pycache__', '.pyc', '.pyo', '.pyd',
                '.DS_Store', 'Thumbs.db', '*.log', '*.tmp',
                'node_modules', '.env', '.venv', 'venv',
                '*.db', '*.sqlite', '*.sqlite3'
            ]
        
        current_dir = Path.cwd()
        files = []
        
        for file_path in current_dir.rglob('*'):
            if file_path.is_file():
                # Check if file should be excluded
                should_exclude = False
                for pattern in exclude_patterns:
                    if pattern in str(file_path) or file_path.name.endswith(pattern.replace('*', '')):
                        should_exclude = True
                        break
                
                if not should_exclude:
                    files.append(file_path.relative_to(current_dir))
        
        return sorted(files)
    
    def file_exists_in_repo(self, repo_name: str, file_path: str, branch: str = "main") -> Optional[Dict]:
        """Check if file exists in repository and get its SHA"""
        try:
            url = f"{self.base_url}/repos/{repo_name}/contents/{file_path}"
            response = requests.get(url, headers=self.headers, params={"ref": branch})
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                return None
            else:
                print(f"⚠️ Warning: Could not check file {file_path}: {response.status_code}")
                return None
        except Exception as e:
            print(f"⚠️ Warning: Error checking file {file_path}: {e}")
            return None
    
    def upload_file(self, repo_name: str, file_path: Path, commit_message: str = None, branch: str = "main") -> bool:
        """Upload a single file to repository"""
        try:
            # Read file content
            try:
                with open(file_path, 'rb') as f:
                    content = f.read()
            except Exception as e:
                print(f"❌ Could not read file {file_path}: {e}")
                return False
            
            # Encode content
            encoded_content = base64.b64encode(content).decode('utf-8')
            
            # Check if file already exists
            file_path_str = str(file_path).replace('\\', '/')  # Ensure forward slashes
            existing_file = self.file_exists_in_repo(repo_name, file_path_str, branch)
            
            # Prepare commit message
            if not commit_message:
                action = "Update" if existing_file else "Add"
                commit_message = f"{action} {file_path_str}"
            
            # Prepare request data
            data = {
                "message": commit_message,
                "content": encoded_content,
                "branch": branch
            }
            
            # If file exists, include its SHA for update
            if existing_file:
                data["sha"] = existing_file["sha"]
            
            # Upload file
            url = f"{self.base_url}/repos/{repo_name}/contents/{file_path_str}"
            response = requests.put(url, headers=self.headers, json=data)
            
            if response.status_code in [200, 201]:
                action = "Updated" if existing_file else "Added"
                print(f"✅ {action}: {file_path_str}")
                return True
            else:
                print(f"❌ Failed to upload {file_path_str}: {response.status_code}")
                try:
                    error_info = response.json()
                    print(f"   Error: {error_info.get('message', 'Unknown error')}")
                except:
                    pass
                return False
                
        except Exception as e:
            print(f"❌ Error uploading {file_path}: {e}")
            return False
    
    def push_files(self, repo: Dict, files: List[Path], custom_message: str = None) -> Dict:
        """Push all files to the repository"""
        repo_name = repo['full_name']
        branch = repo.get('default_branch', 'main')
        
        print(f"\n🚀 Pushing files to {repo_name} (branch: {branch})")
        print("=" * 60)
        
        results = {
            'success': 0,
            'failed': 0,
            'skipped': 0,
            'total': len(files)
        }
        
        # Group commit message
        if custom_message:
            commit_message = custom_message
        else:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            commit_message = f"Bulk upload - {timestamp}"
        
        for file_path in files:
            # Skip very large files (>25MB - GitHub limit is 100MB but let's be safe)
            try:
                file_size = file_path.stat().st_size
                if file_size > 25 * 1024 * 1024:  # 25MB
                    print(f"⚠️ Skipping large file: {file_path} ({file_size / 1024 / 1024:.1f}MB)")
                    results['skipped'] += 1
                    continue
            except:
                pass
            
            # Upload file
            if self.upload_file(repo_name, file_path, commit_message, branch):
                results['success'] += 1
            else:
                results['failed'] += 1
        
        return results

def get_token() -> str:
    """Get GitHub Personal Access Token from user"""
    print("🔑 GitHub Authentication")
    print("-" * 30)
    print("You need a Personal Access Token (PAT) to push files.")
    print("Create one at: https://github.com/settings/tokens")
    print("Required permissions: repo (Full control of private repositories)")
    print()
    
    token = getpass.getpass("Enter your GitHub Personal Access Token: ").strip()
    
    if not token:
        print("❌ No token provided")
        return None
    
    return token

def main():
    print("🐙 GitHub File Pusher")
    print("=" * 40)
    
    # Get token
    token = get_token()
    if not token:
        sys.exit(1)
    
    # Initialize pusher
    pusher = GitHubPusher(token)
    
    # Test authentication
    if not pusher.authenticate():
        sys.exit(1)
    
    # Get repositories
    print("\n📁 Loading repositories...")
    repos = pusher.get_repositories()
    
    if not repos:
        print("❌ No repositories found or accessible")
        sys.exit(1)
    
    # Select repository
    selected_repo = pusher.select_repository(repos)
    if not selected_repo:
        print("👋 Goodbye!")
        sys.exit(0)
    
    print(f"\n✅ Selected repository: {selected_repo['name']}")
    
    # Get local files
    print("\n📂 Scanning local files...")
    local_files = pusher.get_local_files()
    
    if not local_files:
        print("❌ No files found in current directory")
        sys.exit(1)
    
    print(f"📋 Found {len(local_files)} files:")
    for file in local_files[:10]:  # Show first 10
        print(f"   • {file}")
    
    if len(local_files) > 10:
        print(f"   ... and {len(local_files) - 10} more files")
    
    # Confirm upload
    print(f"\n⚠️  This will upload {len(local_files)} files to {selected_repo['full_name']}")
    confirm = input("Continue? (y/N): ").strip().lower()
    
    if confirm != 'y':
        print("👋 Upload cancelled")
        sys.exit(0)
    
    # Optional custom commit message
    custom_message = input("\nCustom commit message (optional): ").strip()
    if not custom_message:
        custom_message = None
    
    # Push files
    results = pusher.push_files(selected_repo, local_files, custom_message)
    
    # Show results
    print("\n" + "=" * 60)
    print("📊 Upload Results:")
    print(f"✅ Success: {results['success']}")
    print(f"❌ Failed:  {results['failed']}")
    print(f"⚠️ Skipped: {results['skipped']}")
    print(f"📁 Total:   {results['total']}")
    
    if results['success'] > 0:
        repo_url = selected_repo['html_url']
        print(f"\n🌐 View repository: {repo_url}")
    
    print("\n🎉 Done!")

if __name__ == "__main__":
    # Check if requests is installed
    try:
        import requests
    except ImportError:
        print("❌ Missing required module: requests")
        print("Install with: pip install requests")
        sys.exit(1)
    
    main()
