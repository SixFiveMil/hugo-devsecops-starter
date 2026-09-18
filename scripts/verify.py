#!/usr/bin/env python3
"""
Unified Shift-Left DevSecOps & Quality Gate Runner for Hugo.
Executes Hugo build and runs 100% of functional, security, and agent rules tests.
"""
import os
import sys
import subprocess
import unittest
import time
from pathlib import Path

# Safe UTF-8 stdout on Windows
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent

# ANSI colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def log(msg, color=""):
    try:
        print(f"{color}{msg}{RESET}")
    except UnicodeEncodeError:
        safe_msg = msg.encode("ascii", "replace").decode("ascii")
        print(f"{color}{safe_msg}{RESET}")


def run_command(cmd, cwd=REPO_ROOT):
    cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
    log(f"[EXEC] {cmd_str}", CYAN)
    res = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True)
    return res


def main():
    start_time = time.time()
    log(f"\n===============================================================", BOLD)
    log(f"[*] HUGO DEVSECOPS & QUALITY GATES HARNESS", BOLD)
    log(f"===============================================================\n", BOLD)

    # Step 1: Check Hugo binary
    log("[1/3] Compiling Hugo static site...", YELLOW)
    hugo_res = run_command(["hugo", "--minify", "--gc", "--cleanDestinationDir"])
    if hugo_res.returncode != 0:
        log("[ERROR] Hugo compilation failed!", RED)
        print(hugo_res.stderr or hugo_res.stdout)
        return 1
    log("[OK] Hugo compilation succeeded.", GREEN)

    # Step 2: Run Python Test Suite
    log("\n[2/3] Executing automated DevSecOps & AGENTS.md test suite...", YELLOW)
    os.chdir(REPO_ROOT)
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    
    # Use unittest test discovery
    suite = unittest.defaultTestLoader.discover(str(REPO_ROOT / "tests"), pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Step 3: Report Summary
    elapsed = time.time() - start_time
    log(f"\n---------------------------------------------------------------", BOLD)
    if result.wasSuccessful():
        log(f"[SUCCESS] ALL QUALITY & DEVSECOPS GATES PASSED in {elapsed:.2f}s!", GREEN + BOLD)
        log(f"   Total tests executed: {result.testsRun}", GREEN)
        log(f"   Failures: 0 | Errors: 0\n", GREEN)
        return 0
    else:
        log(f"[FAILURE] QUALITY GATES FAILED with {len(result.failures)} failure(s) and {len(result.errors)} error(s)!", RED + BOLD)
        log("   Review test errors above and fix violations before pushing.\n", RED)
        return 1


if __name__ == "__main__":
    sys.exit(main())
