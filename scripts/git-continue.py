#!/usr/bin/env python3
"""
Description: Resume where you left off. Detect active rebases, merges, cherry-picks, stashes, or WIP commits and suggest next steps.
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

    # Unresolved conflict files
    _, conflict_out, _ = run_cmd_capture(["git", "diff", "--name-only", "--diff-filter=U"])
    conflict_files = [l.strip() for l in conflict_out.splitlines() if l.strip()]

    # Staged changes
    _, staged_out, _ = run_cmd_capture(["git", "diff", "--cached", "--name-only"])
    staged_files = [l.strip() for l in staged_out.splitlines() if l.strip()]

    # Unstaged changes
    _, unstaged_out, _ = run_cmd_capture(["git", "diff", "--name-only"])
    unstaged_files = [l.strip() for l in unstaged_out.splitlines() if l.strip()]

    # Active states
    is_merge = (git_dir_path / "MERGE_HEAD").exists()
    is_rebase = (git_dir_path / "rebase-merge").exists() or (git_dir_path / "rebase-apply").exists()
    is_cherry_pick = (git_dir_path / "CHERRY_PICK_HEAD").exists()
    is_revert = (git_dir_path / "REVERT_HEAD").exists()
    is_bisect = (git_dir_path / "BISECT_LOG").exists()

    # Stash count
    _, stash_out, _ = run_cmd_capture(["git", "stash", "list"])
    stashes = [l.strip() for l in stash_out.splitlines() if l.strip()]

    # Last commit (WIP check)
    last_hash = ""
    last_subject = ""
    _, log_out, _ = run_cmd_capture(["git", "log", "-1", "--format=%h %s"])
    if log_out:
        parts = log_out.split(" ", 1)
        if len(parts) == 2:
            last_hash = parts[0]
            last_subject = parts[1]

    return {
        "branch": branch,
        "conflict_files": conflict_files,
        "staged": staged_files,
        "unstaged": unstaged_files,
        "is_merge": is_merge,
        "is_rebase": is_rebase,
        "is_cherry_pick": is_cherry_pick,
        "is_revert": is_revert,
        "is_bisect": is_bisect,
        "stashes": stashes,
        "last_hash": last_hash,
        "last_subject": last_subject
    }

def print_dashboard(status):
    print(f"\n{Colors.PURPLE}{Colors.BOLD}================================================================{Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}                       GIT-CONTINUE STATUS                      {Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}================================================================{Colors.RESET}\n")

    print(f"Branch: {Colors.CYAN}{Colors.BOLD}{status['branch']}{Colors.RESET}")
    
    # Mode details
    modes = []
    if status["is_merge"]: modes.append(f"{Colors.RED}Merge in Progress{Colors.RESET}")
    if status["is_rebase"]: modes.append(f"{Colors.RED}Rebase in Progress{Colors.RESET}")
    if status["is_cherry_pick"]: modes.append(f"{Colors.RED}Cherry-Pick in Progress{Colors.RESET}")
    if status["is_revert"]: modes.append(f"{Colors.RED}Revert in Progress{Colors.RESET}")
    if status["is_bisect"]: modes.append(f"{Colors.RED}Bisect in Progress{Colors.RESET}")
    
    if modes:
        print(f"Active State: {', '.join(modes)}")
    else:
        print(f"Active State: {Colors.GREEN}Normal Development{Colors.RESET}")

    # Conflict status
    if status["conflict_files"]:
        print(f"Conflicts: {Colors.RED}{Colors.BOLD}{len(status['conflict_files'])} unresolved conflict(s){Colors.RESET}")
        for f in status["conflict_files"]:
            print(f"  • {Colors.RED}{f}{Colors.RESET}")
    else:
        print(f"Conflicts: {Colors.GREEN}None{Colors.RESET}")

    # Staged / Unstaged
    print(f"Staged changes: {Colors.GREEN}{len(status['staged'])} files{Colors.RESET}")
    print(f"Unstaged changes: {Colors.YELLOW}{len(status['unstaged'])} files{Colors.RESET}")
    
    # Stash
    if status["stashes"]:
        print(f"Stashes: {Colors.BLUE}{len(status['stashes'])} stash(es) found{Colors.RESET} (Latest: {status['stashes'][0]})")
    else:
        print(f"Stashes: {Colors.DIM}None{Colors.RESET}")

    # WIP Commit Check
    is_wip = "WIP" in status["last_subject"].upper() or "WORK IN PROGRESS" in status["last_subject"].upper()
    if is_wip:
        print(f"Last Commit: {Colors.YELLOW}{Colors.BOLD}WIP detected{Colors.RESET} ({status['last_hash']} - {status['last_subject']})")

    print(f"\n{Colors.PURPLE}{Colors.BOLD}================================================================{Colors.RESET}\n")

def ask_option(options):
    for idx, opt in enumerate(options, 1):
        print(f"  {Colors.BOLD}{idx}. {opt['title']}{Colors.RESET}")
        print(f"     {Colors.DIM}{opt['desc']}{Colors.RESET}")
        if opt.get("cmd"):
            print(f"     Command: {Colors.CYAN}{' '.join(opt['cmd'])}{Colors.RESET}")
        print()

    while True:
        try:
            choice = input(f"Select next step (1-{len(options)}): ").strip()
            if not choice:
                continue
            val = int(choice)
            if 1 <= val <= len(options):
                return options[val - 1]
            print(f"Please enter a number between 1 and {len(options)}.")
        except ValueError:
            print("Invalid input. Please enter a number.")
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            sys.exit(0)

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="git-continue: Resumes pending rebases, merges, or conflict resolution."
    )
    parser.add_argument("--no-color", action="store_true", help="Disable colored terminal output.")
    args = parser.parse_args()

    if args.no_color:
        Colors.disable()

    status = get_git_status()
    print_dashboard(status)

    options = []
    
    is_wip = "WIP" in status["last_subject"].upper() or "WORK IN PROGRESS" in status["last_subject"].upper()

    # Case 1: Active Rebase
    if status["is_rebase"]:
        if status["conflict_files"]:
            options.append({
                "title": "Unresolved Conflicts Checklist",
                "cmd": None,
                "desc": "Please open the conflict files listed above, resolve conflict markers, stage them with 'git add <files>', and then rerun git-continue.",
                "action": "info"
            })
            options.append({
                "title": "Skip current commit",
                "cmd": ["git", "rebase", "--skip"],
                "desc": "Skips applying the current commit of the rebase (and discards its changes).",
                "action": "run"
            })
        else:
            options.append({
                "title": "Continue Rebase",
                "cmd": ["git", "rebase", "--continue"],
                "desc": "Resumes the rebase now that conflicts are resolved or changes are staged.",
                "action": "run"
            })
        options.append({
            "title": "Abort Rebase",
            "cmd": ["git", "rebase", "--abort"],
            "desc": "Cancels the rebase entirely and restores original branch state.",
            "action": "run"
        })

    # Case 2: Active Merge
    elif status["is_merge"]:
        if status["conflict_files"]:
            options.append({
                "title": "Unresolved Conflicts Checklist",
                "cmd": None,
                "desc": "Please resolve conflict markers in the listed files, stage them with 'git add', and run 'git commit'.",
                "action": "info"
            })
        else:
            options.append({
                "title": "Complete Merge",
                "cmd": ["git", "commit"],
                "desc": "Saves the merge commit now that conflicts are resolved.",
                "action": "run"
            })
        options.append({
            "title": "Abort Merge",
            "cmd": ["git", "merge", "--abort"],
            "desc": "Cancels the merge and restores pre-merge state.",
            "action": "run"
        })

    # Case 3: Active Cherry-Pick
    elif status["is_cherry_pick"]:
        if status["conflict_files"]:
            options.append({
                "title": "Unresolved Conflicts Checklist",
                "cmd": None,
                "desc": "Resolve conflicts, stage the files, and run 'git cherry-pick --continue'.",
                "action": "info"
            })
        else:
            options.append({
                "title": "Continue Cherry-Pick",
                "cmd": ["git", "cherry-pick", "--continue"],
                "desc": "Completes the cherry-pick with current staged changes.",
                "action": "run"
            })
        options.append({
            "title": "Abort Cherry-Pick",
            "cmd": ["git", "cherry-pick", "--abort"],
            "desc": "Cancels the cherry-pick and clears conflict state.",
            "action": "run"
        })

    # Case 4: Active Revert
    elif status["is_revert"]:
        if status["conflict_files"]:
            options.append({
                "title": "Resolve conflicts and continue",
                "cmd": None,
                "desc": "Resolve conflicts, stage the files, and run 'git revert --continue'.",
                "action": "info"
            })
        else:
            options.append({
                "title": "Continue Revert",
                "cmd": ["git", "revert", "--continue"],
                "desc": "Resumes the revert commit.",
                "action": "run"
            })
        options.append({
            "title": "Abort Revert",
            "cmd": ["git", "revert", "--abort"],
            "desc": "Cancels the revert.",
            "action": "run"
        })

    # Case 5: Normal state but has stashes
    elif status["stashes"]:
        options.append({
            "title": "Apply latest stash (keep stash saved)",
            "cmd": ["git", "stash", "apply"],
            "desc": "Applies the changes from the latest stash to your working directory.",
            "action": "run"
        })
        options.append({
            "title": "Pop latest stash (apply and delete stash)",
            "cmd": ["git", "stash", "pop"],
            "desc": "Applies changes and deletes the latest stash from history.",
            "action": "run"
        })

    # Case 6: WIP Commit
    if is_wip and not status["is_rebase"] and not status["is_merge"] and not status["is_cherry_pick"]:
        options.append({
            "title": "Un-commit last WIP commit (keep modifications)",
            "cmd": ["git", "reset", "HEAD~1"],
            "desc": "Resets HEAD back by one commit. Moves modifications back into working tree as unstaged changes so you can resume coding.",
            "action": "run"
        })
        options.append({
            "title": "Amend WIP commit",
            "cmd": ["git", "commit", "--amend"],
            "desc": "Allows you to add new modifications and update the WIP commit message to a proper description.",
            "action": "run"
        })

    # Default fallback
    if not options:
        if status["staged"] or status["unstaged"]:
            options.append({
                "title": "Commit current changes",
                "cmd": ["autodo", "run", "create-commit-message"],
                "desc": "Runs commit assistant to save your work.",
                "action": "run"
            })
        else:
            print(f"{Colors.GREEN}✓ No active conflicts, merges, stashes, or WIP commits detected.{Colors.RESET}")
            print("Your workspace is completely up to date. Start coding!")
            sys.exit(0)

    # Append Exit option
    options.append({
        "title": "Exit",
        "cmd": None,
        "desc": "Do nothing and exit.",
        "action": "exit"
    })

    print("Next Recommended Steps:")
    selected = ask_option(options)

    if selected["action"] == "exit":
        print("Goodbye!")
        sys.exit(0)
    elif selected["action"] == "info":
        print(f"\n{Colors.YELLOW}Instruction:{Colors.RESET}")
        print(f"  {selected['desc']}")
        sys.exit(0)
    elif selected["action"] == "run":
        cmd = selected["cmd"]
        print(f"\nExecuting: {' '.join(cmd)}")
        rc = run_cmd_interactive(cmd)
        if rc == 0:
            print(f"{Colors.GREEN}Command completed successfully.{Colors.RESET}")
        else:
            print(f"{Colors.RED}Command exited with code {rc}.{Colors.RESET}")

if __name__ == "__main__":
    main()
