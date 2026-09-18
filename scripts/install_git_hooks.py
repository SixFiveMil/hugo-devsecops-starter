#!/usr/bin/env python3
"""
Configures local git repository to use .githooks for automated pre-push verification.
"""
import subprocess
import sys
from pathlib import Path

# Safe UTF-8 stdout on Windows
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent

def main():
    print("[*] Installing DevSecOps Git Hooks...")
    try:
        res = subprocess.run(
            ["git", "config", "core.hooksPath", ".githooks"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True
        )
        print("[OK] Configured git 'core.hooksPath' -> '.githooks'")
        
        # Also copy into .git/hooks if .git directory exists
        git_hooks_dir = REPO_ROOT / ".git" / "hooks"
        if git_hooks_dir.exists():
            pre_push_source = REPO_ROOT / ".githooks" / "pre-push"
            pre_push_dest = git_hooks_dir / "pre-push"
            if pre_push_source.exists():
                pre_push_dest.write_bytes(pre_push_source.read_bytes())
                print("[OK] Copied .githooks/pre-push -> .git/hooks/pre-push")

        print("[SUCCESS] Pre-push DevSecOps hook installed successfully!")
        return 0
    except Exception as e:
        print(f"[ERROR] Failed to configure git hooks: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
