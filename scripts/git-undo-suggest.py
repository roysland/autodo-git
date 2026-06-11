#!/usr/bin/env python3
"""
Description: Analyze the repository state and suggest/perform the safest undo operations.
"""
import os
import sys
import subprocess
import pathlib

class Colors:
    PURPLE = "\033[1;35m"
    CYAN = "\033[1;36m"
    GREEN = "\033[1;32m"
    YELLOW = "\033[1;33m"
    RED = "\033[1;31m"
    BLUE = "\033[1;34m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    @classmethod
    def disable(cls):
        cls.PURPLE = ""
        cls.CYAN = ""
        cls.GREEN = ""
        cls.YELLOW = ""
        cls.RED = ""
        cls.BLUE = ""
        cls.BOLD = ""
        cls.DIM = ""
        cls.RESET = ""

def run_cmd_capture(cmd):
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return res.returncode, res.stdout.strip(), res.stderr.strip()

def run_cmd_interactive(cmd):
    res = subprocess.run(cmd)
    return res.returncode

def ask_confirmation(warning_text):
    print(f"\n{Colors.RED}{Colors.BOLD}⚠️  WARNING: {warning_text}{Colors.RESET}")
    try:
        choice = input("Are you absolutely sure you want to proceed? (y/n): ").strip().lower()
        return choice == "y"
    except (KeyboardInterrupt, EOFError):
        return False

def get_git_status():
    # Verify in a git repository
    rc, _, _ = run_cmd_capture(["git", "rev-parse", "--is-inside-work-tree"])
    if rc != 0:
        print(f"{Colors.RED}Error: Not in a git repository.{Colors.RESET}")
        sys.exit(1)

    # Get repository root and actual git directory
    _, repo_root, _ = run_cmd_capture(["git", "rev-parse", "--show-toplevel"])
    _, git_dir, _ = run_cmd_capture(["git", "rev-parse", "--git-dir"])
    
    os.chdir(repo_root)
    git_dir_path = pathlib.Path(git_dir).resolve()

    # Get current branch
    _, branch, _ = run_cmd_capture(["git", "branch", "--show-current"])
    if not branch:
        _, branch, _ = run_cmd_capture(["git", "rev-parse", "--short", "HEAD"])
        branch = f"detached-HEAD-({branch})"

    # Check upstream
    _, upstream, _ = run_cmd_capture(["git", "rev-parse", "--abbrev-ref", "@{u}"])
    ahead = 0
    behind = 0
    if upstream:
        _, ahead_str, _ = run_cmd_capture(["git", "rev-list", "--count", f"{upstream}..HEAD"])
        _, behind_str, _ = run_cmd_capture(["git", "rev-list", "--count", f"HEAD..{upstream}"])
        try:
            ahead = int(ahead_str)
        except ValueError:
            pass
        try:
            behind = int(behind_str)
        except ValueError:
            pass

    # Files changed
    _, staged_out, _ = run_cmd_capture(["git", "diff", "--cached", "--name-only"])
    _, unstaged_out, _ = run_cmd_capture(["git", "diff", "--name-only"])
    
    staged_files = [l.strip() for l in staged_out.splitlines() if l.strip()]
    unstaged_files = [l.strip() for l in unstaged_out.splitlines() if l.strip()]

    # Untracked files
    _, porcelain, _ = run_cmd_capture(["git", "status", "--porcelain"])
    untracked_files = []
    for line in porcelain.splitlines():
        if line.startswith("?? "):
            untracked_files.append(line[3:])

    # Active states
    is_merge = (git_dir_path / "MERGE_HEAD").exists()
    is_rebase = (git_dir_path / "rebase-merge").exists() or (git_dir_path / "rebase-apply").exists()
    is_cherry_pick = (git_dir_path / "CHERRY_PICK_HEAD").exists()
    is_revert = (git_dir_path / "REVERT_HEAD").exists()
    is_bisect = (git_dir_path / "BISECT_LOG").exists()

    # Last 5 commits
    _, log_out, _ = run_cmd_capture(["git", "log", "-n", "5", "--oneline"])
    commits = []
    for line in log_out.splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2:
            commits.append({"hash": parts[0], "subject": parts[1]})

    return {
        "branch": branch,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "staged": staged_files,
        "unstaged": unstaged_files,
        "untracked": untracked_files,
        "is_merge": is_merge,
        "is_rebase": is_rebase,
        "is_cherry_pick": is_cherry_pick,
        "is_revert": is_revert,
        "is_bisect": is_bisect,
        "commits": commits
    }

def print_status_dashboard(status):
    print(f"\n{Colors.PURPLE}{Colors.BOLD}================================================================{Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}                    GIT-UNDO-SUGGEST STATUS                     {Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}================================================================{Colors.RESET}\n")

    print(f"Branch: {Colors.CYAN}{Colors.BOLD}{status['branch']}{Colors.RESET}")
    
    # In-progress actions
    active_modes = []
    if status["is_merge"]: active_modes.append(f"{Colors.RED}MERGE IN PROGRESS{Colors.RESET}")
    if status["is_rebase"]: active_modes.append(f"{Colors.RED}REBASE IN PROGRESS{Colors.RESET}")
    if status["is_cherry_pick"]: active_modes.append(f"{Colors.RED}CHERRY-PICK IN PROGRESS{Colors.RESET}")
    if status["is_revert"]: active_modes.append(f"{Colors.RED}REVERT IN PROGRESS{Colors.RESET}")
    if status["is_bisect"]: active_modes.append(f"{Colors.RED}BISECT IN PROGRESS{Colors.RESET}")
    
    if active_modes:
        print(f"Active Mode: {', '.join(active_modes)}")

    # Changes summary
    print(f"Staged changes: {Colors.GREEN}{len(status['staged'])} files{Colors.RESET}")
    print(f"Unstaged changes: {Colors.YELLOW}{len(status['unstaged'])} files{Colors.RESET}")
    print(f"Untracked changes: {Colors.BLUE}{len(status['untracked'])} files{Colors.RESET}")
    
    if status["upstream"]:
        print(f"Unpushed local commits: {Colors.GREEN}{status['ahead']}{Colors.RESET}")
    else:
        print(f"Unpushed local commits: {Colors.DIM}No upstream remote set{Colors.RESET}")

    if status["commits"]:
        print(f"\n{Colors.CYAN}{Colors.BOLD}Recent commits:{Colors.RESET}")
        for idx, c in enumerate(status["commits"][:3]):
            print(f"  {Colors.DIM}{c['hash']}{Colors.RESET} - {c['subject']}")

    print(f"\n{Colors.PURPLE}{Colors.BOLD}================================================================{Colors.RESET}\n")

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="git-undo-suggest: Safely revert git actions and commits."
    )
    parser.add_argument("--no-color", action="store_true", help="Disable colored terminal output.")
    args = parser.parse_args()

    if args.no_color:
        Colors.disable()

    status = get_git_status()
    print_status_dashboard(status)

    suggestions = []

    # 1. Active operations
    if status["is_merge"]:
        suggestions.append({
            "title": "Abort the active merge",
            "cmd": ["git", "merge", "--abort"],
            "desc": "Cancels the merge operation and restores the state before it started.",
            "destructive": False
        })
    if status["is_rebase"]:
        suggestions.append({
            "title": "Abort the active rebase",
            "cmd": ["git", "rebase", "--abort"],
            "desc": "Cancels the rebase process and returns you to the original branch state.",
            "destructive": False
        })
    if status["is_cherry_pick"]:
        suggestions.append({
            "title": "Abort the active cherry-pick",
            "cmd": ["git", "cherry-pick", "--abort"],
            "desc": "Aborts the cherry-pick and clears conflict states.",
            "destructive": False
        })
    if status["is_revert"]:
        suggestions.append({
            "title": "Abort the active revert",
            "cmd": ["git", "revert", "--abort"],
            "desc": "Aborts the revert operation.",
            "destructive": False
        })

    # 2. Staged files
    if status["staged"]:
        suggestions.append({
            "title": "Unstage staged changes (keep modifications in working tree)",
            "cmd": ["git", "restore", "--staged", "."],
            "desc": "Unstages all files so they become modified but unstaged.",
            "destructive": False
        })
        suggestions.append({
            "title": "Discard staged changes completely (destructive!)",
            "cmd": ["git", "reset", "--hard", "HEAD"],
            "desc": "Discards both staged and unstaged modifications to tracked files.",
            "destructive": True,
            "warning": "This will permanently delete all uncommitted modifications to tracked files."
        })

    # 3. Unstaged tracked modifications
    if status["unstaged"]:
        suggestions.append({
            "title": "Discard unstaged modifications to tracked files (destructive!)",
            "cmd": ["git", "restore", "."],
            "desc": "Discards changes in your working tree for tracked files.",
            "destructive": True,
            "warning": "This will permanently discard all unstaged changes to tracked files."
        })

    # 4. Untracked files
    if status["untracked"]:
        suggestions.append({
            "title": "Permanently delete all untracked files (destructive!)",
            "cmd": ["git", "clean", "-fd"],
            "desc": "Removes files and directories that are not tracked by Git.",
            "destructive": True,
            "warning": "This will permanently delete all untracked files and directories."
        })

    # 5. Local commits (ahead of remote)
    if status["ahead"] > 0:
        suggestions.append({
            "title": f"Undo last commit (keep files staged)",
            "cmd": ["git", "reset", "--soft", "HEAD~1"],
            "desc": "Moves HEAD back by one commit. Changes remain staged.",
            "destructive": False
        })
        suggestions.append({
            "title": f"Undo last commit (unstage changes, keep files modified)",
            "cmd": ["git", "reset", "HEAD~1"],
            "desc": "Moves HEAD back by one commit. Changes remain in working tree as unstaged.",
            "destructive": False
        })
        suggestions.append({
            "title": f"Undo last commit completely (destructive!)",
            "cmd": ["git", "reset", "--hard", "HEAD~1"],
            "desc": "Moves HEAD back by one commit and deletes all changes in that commit.",
            "destructive": True,
            "warning": "This will permanently delete the last commit and all modifications within it."
        })

    # 6. Reverting commits (for pushed history or older commits)
    if status["commits"]:
        # Revert the latest commit in log
        latest_hash = status["commits"][0]["hash"]
        latest_sub = status["commits"][0]["subject"]
        suggestions.append({
            "title": f"Revert commit '{latest_sub}' ({latest_hash}) via a new commit",
            "cmd": ["git", "revert", latest_hash, "--no-edit"],
            "desc": "Safe for pushed branches. Creates a new commit that undoes the changes of the selected commit.",
            "destructive": False
        })
        
        # If there are older commits, offer to choose one to revert
        if len(status["commits"]) > 1:
            suggestions.append({
                "title": "Select an older commit from history to revert",
                "cmd": "choose_revert",
                "desc": "Let you choose any of the last 5 commits to revert safely.",
                "destructive": False
            })

    # Append Exit option
    suggestions.append({
        "title": "Exit",
        "cmd": None,
        "desc": "Exit without performing any undo action.",
        "destructive": False
    })

    # Present options
    print("Recommended Undo Options:")
    for idx, s in enumerate(suggestions, 1):
        print(f"  {Colors.BOLD}{idx}. {s['title']}{Colors.RESET}")
        print(f"     {Colors.DIM}{s['desc']}{Colors.RESET}")
        if s["cmd"]:
            cmd_str = " ".join(s["cmd"]) if isinstance(s["cmd"], list) else s["cmd"]
            print(f"     Command: {Colors.CYAN}{cmd_str}{Colors.RESET}")
        print()

    # Get choice
    while True:
        try:
            choice = input(f"Select option (1-{len(suggestions)}): ").strip()
            if not choice:
                continue
            val = int(choice)
            if 1 <= val <= len(suggestions):
                selected = suggestions[val - 1]
                break
            print(f"Please enter a number between 1 and {len(suggestions)}.")
        except ValueError:
            print("Invalid input. Please enter a number.")
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            sys.exit(0)

    # Perform action
    cmd = selected["cmd"]
    if cmd is None:
        print("Goodbye!")
        sys.exit(0)

    if cmd == "choose_revert":
        print("\nSelect a commit to revert:")
        for idx, c in enumerate(status["commits"], 1):
            print(f"  {idx}. {Colors.CYAN}{c['hash']}{Colors.RESET} - {c['subject']}")
        
        while True:
            try:
                commit_choice = input(f"Select commit (1-{len(status['commits'])}): ").strip()
                c_val = int(commit_choice)
                if 1 <= c_val <= len(status["commits"]):
                    commit_to_revert = status["commits"][c_val - 1]
                    break
            except ValueError:
                pass
            print(f"Please enter a number between 1 and {len(status['commits'])}.")
            
        cmd = ["git", "revert", commit_to_revert["hash"], "--no-edit"]
        selected["destructive"] = False

    # Check destructive warning
    if selected["destructive"]:
        warning = selected.get("warning", "This action is destructive and irreversible!")
        if not ask_confirmation(warning):
            print("Action cancelled.")
            sys.exit(0)

    # Execute
    print(f"\nExecuting: {' '.join(cmd)}")
    rc = run_cmd_interactive(cmd)
    if rc == 0:
        print(f"{Colors.GREEN}Command completed successfully.{Colors.RESET}")
    else:
        print(f"{Colors.RED}Command exited with code {rc}.{Colors.RESET}")

if __name__ == "__main__":
    main()
