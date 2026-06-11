#!/usr/bin/env python3
"""
Description: AI-assisted cleanup of merged branches, stale branches, local stashes, untracked files, and merge conflict markers.
"""
import os
import sys
import time
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

def get_default_branch():
    rc, stdout, _ = run_cmd_capture(["git", "symbolic-ref", "refs/remotes/origin/HEAD"])
    if rc == 0 and stdout:
        return stdout.split("/")[-1]
    
    rc_main, _, _ = run_cmd_capture(["git", "show-ref", "--verify", "refs/heads/main"])
    if rc_main == 0:
        return "main"
    return "master"

def get_current_branch():
    rc, branch, _ = run_cmd_capture(["git", "branch", "--show-current"])
    return branch.strip()

def get_merged_branches(default_branch):
    # Get local branches merged into default_branch
    rc, stdout, _ = run_cmd_capture(["git", "branch", "--merged", default_branch])
    if rc != 0:
        return []
    
    current = get_current_branch()
    merged = []
    for line in stdout.splitlines():
        name = line.replace("*", "").strip()
        # Exclude default branch and current branch from deletion candidates
        if name and name != default_branch and name != current:
            merged.append(name)
    return merged

def get_stale_branches(default_branch, stale_days=30):
    # Get all branches and their committer dates
    rc, stdout, _ = run_cmd_capture([
        "git", "for-each-ref", 
        "--format=%(refname:short) %(committerdate:raw)", 
        "refs/heads/"
    ])
    if rc != 0:
        return []
        
    current = get_current_branch()
    current_time = time.time()
    stale = []
    
    for line in stdout.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            name = parts[0]
            if name == default_branch or name == current:
                continue
            timestamp_str = parts[1]
            try:
                timestamp = float(timestamp_str)
                age_days = int((current_time - timestamp) / 86400)
                if age_days >= stale_days:
                    # Also check if it's already merged
                    rc_merged, _, _ = run_cmd_capture(["git", "merge-base", "--is-ancestor", name, default_branch])
                    is_merged = (rc_merged == 0)
                    stale.append({
                        "name": name,
                        "age_days": age_days,
                        "is_merged": is_merged
                    })
            except ValueError:
                pass
    return stale

def get_stashes():
    rc, stdout, _ = run_cmd_capture(["git", "stash", "list"])
    stashes = []
    if rc == 0 and stdout:
        for line in stdout.splitlines():
            line = line.strip()
            if line:
                stashes.append(line)
    return stashes

def get_untracked_files():
    rc, stdout, _ = run_cmd_capture(["git", "status", "--porcelain"])
    untracked = []
    if rc == 0:
        for line in stdout.splitlines():
            if line.startswith("?? "):
                untracked.append(line[3:])
    return untracked

def scan_conflict_markers():
    # Scan tracked files for conflict markers
    rc, stdout, _ = run_cmd_capture([
        "git", "grep", "-nI", "-E", 
        "^(<<<<<<< |=======|>>>>>>> )"
    ])
    markers = []
    if rc == 0 and stdout:
        for line in stdout.splitlines():
            parts = line.strip().split(":", 2)
            if len(parts) >= 3:
                markers.append({
                    "file": parts[0],
                    "line": parts[1],
                    "content": parts[2]
                })
    return markers

def ask_confirmation(warning):
    print(f"\n{Colors.RED}{Colors.BOLD}⚠️  WARNING: {warning}{Colors.RESET}")
    try:
        choice = input("Proceed? (y/n): ").strip().lower()
        return choice == "y"
    except (KeyboardInterrupt, EOFError):
        return False

def clean_merged(merged):
    print(f"\n{Colors.CYAN}Found {len(merged)} merged branch(es) to clean:{Colors.RESET}")
    for b in merged:
        print(f"  - {b}")
    confirm = input("\nDelete these branches? (y/n): ").strip().lower()
    if confirm == "y":
        for b in merged:
            rc = run_cmd_interactive(["git", "branch", "-d", b])
            if rc == 0:
                print(f"Deleted merged branch {Colors.GREEN}{b}{Colors.RESET}")
            else:
                print(f"Failed to delete branch {Colors.RED}{b}{Colors.RESET}")
    else:
        print("Skipped branch cleanup.")

def clean_stale(stale):
    print(f"\n{Colors.CYAN}Found {len(stale)} stale branch(es) (untouched for 30+ days):{Colors.RESET}")
    for idx, b in enumerate(stale, 1):
        status = "merged" if b["is_merged"] else "NOT merged"
        color = Colors.GREEN if b["is_merged"] else Colors.RED
        print(f"  {idx}. {Colors.BOLD}{b['name']}{Colors.RESET} ({b['age_days']} days old, {color}{status}{Colors.RESET})")
        
    choice = input("\nEnter numbers of branches to delete (separated by spaces, e.g. 1 3), 'all' to delete all, or 'q' to quit: ").strip().lower()
    if choice == 'q' or not choice:
        return
        
    to_delete = []
    if choice == 'all':
        to_delete = stale
    else:
        try:
            indices = [int(i) - 1 for i in choice.split()]
            to_delete = [stale[i] for i in indices if 0 <= i < len(stale)]
        except ValueError:
            print("Invalid input.")
            return

    if not to_delete:
        return

    # Check if force delete is needed for unmerged branches
    for b in to_delete:
        cmd = ["git", "branch", "-d" if b["is_merged"] else "-D", b["name"]]
        if not b["is_merged"]:
            print(f"\nBranch '{b['name']}' has unmerged changes.")
            if not ask_confirmation(f"Force delete branch '{b['name']}'? This cannot be undone."):
                print(f"Skipped {b['name']}.")
                continue
        rc = run_cmd_interactive(cmd)
        if rc == 0:
            print(f"Deleted stale branch {Colors.GREEN}{b['name']}{Colors.RESET}")

def clean_stashes(stashes):
    print(f"\n{Colors.CYAN}Found {len(stashes)} stash(es):{Colors.RESET}")
    for idx, s in enumerate(stashes):
        print(f"  {idx}. {s}")
        
    choice = input("\nEnter stash index to drop (e.g. 0), 'clear' to clear ALL stashes, or 'q' to quit: ").strip().lower()
    if choice == 'q' or not choice:
        return
    if choice == 'clear':
        if ask_confirmation("Delete ALL stashes permanently?"):
            rc = run_cmd_interactive(["git", "stash", "clear"])
            if rc == 0:
                print(f"{Colors.GREEN}All stashes cleared.{Colors.RESET}")
    else:
        try:
            idx = int(choice)
            if 0 <= idx < len(stashes):
                if ask_confirmation(f"Drop stash@{idx}?"):
                    rc = run_cmd_interactive(["git", "stash", "drop", f"stash@{{{idx}}}"])
                    if rc == 0:
                        print(f"{Colors.GREEN}Stash dropped successfully.{Colors.RESET}")
            else:
                print("Index out of range.")
        except ValueError:
            print("Invalid input.")

def clean_untracked(untracked):
    print(f"\n{Colors.CYAN}Found {len(untracked)} untracked files/folders:{Colors.RESET}")
    # Group and preview
    for f in untracked[:15]:
        print(f"  - {f}")
    if len(untracked) > 15:
        print(f"  ... and {len(untracked) - 15} more files.")
        
    choice = choose_option([
        "Dry-run clean (see what git clean would delete)",
        "Clean untracked files (removes files permanently!)",
        "Clean untracked files and directories (removes files + folders permanently!)",
        "Back"
    ], "Select cleanup action:")
    
    if choice == 0:
        run_cmd_interactive(["git", "clean", "-nd"])
    elif choice == 1:
        if ask_confirmation("Permanently delete untracked files in working tree?"):
            run_cmd_interactive(["git", "clean", "-f"])
    elif choice == 2:
        if ask_confirmation("Permanently delete untracked files and directories in working tree?"):
            run_cmd_interactive(["git", "clean", "-fd"])

def choose_option(options, prompt):
    print(f"\n{prompt}")
    for idx, opt in enumerate(options, 1):
        print(f"  {Colors.BOLD}{idx}. {opt}{Colors.RESET}")
    while True:
        try:
            choice = input(f"Select option (1-{len(options)}): ").strip()
            if not choice:
                continue
            val = int(choice)
            if 1 <= val <= len(options):
                return val - 1
            print(f"Please enter a number between 1 and {len(options)}.")
        except ValueError:
            print("Invalid input. Please enter a number.")
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            sys.exit(0)

def main():
    rc, repo_root, _ = run_cmd_capture(["git", "rev-parse", "--show-toplevel"])
    if rc == 0 and repo_root:
        os.chdir(repo_root)
        
    # Verify in Git repo
    rc_git, _, _ = run_cmd_capture(["git", "rev-parse", "--is-inside-work-tree"])
    if rc_git != 0:
        print(f"{Colors.RED}Error: Not in a git repository.{Colors.RESET}")
        sys.exit(1)
        
    default_branch = get_default_branch()
    
    while True:
        status = get_current_branch()
        merged = get_merged_branches(default_branch)
        stale = get_stale_branches(default_branch)
        stashes = get_stashes()
        untracked = get_untracked_files()
        markers = scan_conflict_markers()
        
        print(f"\n{Colors.PURPLE}{Colors.BOLD}================================================================{Colors.RESET}")
        print(f"{Colors.PURPLE}{Colors.BOLD}                    GIT-CLEANUP ASSISTANT                       {Colors.RESET}")
        print(f"{Colors.PURPLE}{Colors.BOLD}================================================================{Colors.RESET}\n")
        
        print(f"Current Branch: {Colors.CYAN}{status}{Colors.RESET}  (Default: {Colors.CYAN}{default_branch}{Colors.RESET})")
        print(f"Merged local branches: {Colors.GREEN if merged else Colors.DIM}{len(merged)}{Colors.RESET}")
        print(f"Stale local branches (>30d): {Colors.YELLOW if stale else Colors.DIM}{len(stale)}{Colors.RESET}")
        print(f"Stashes saved: {Colors.BLUE if stashes else Colors.DIM}{len(stashes)}{Colors.RESET}")
        print(f"Untracked files/folders: {Colors.YELLOW if untracked else Colors.DIM}{len(untracked)}{Colors.RESET}")
        
        if markers:
            print(f"Conflict markers found: {Colors.RED}{Colors.BOLD}{len(markers)} marker(s){Colors.RESET} in files:")
            files = sorted(list(set(m["file"] for m in markers)))
            for f in files:
                print(f"  • {Colors.RED}{f}{Colors.RESET}")
        else:
            print(f"Conflict markers found: {Colors.GREEN}None{Colors.RESET}")
            
        print(f"\n{Colors.PURPLE}{Colors.BOLD}================================================================{Colors.RESET}")
        
        menu = [
            f"Prune Merged Branches ({len(merged)})",
            f"Prune Stale Branches ({len(stale)})",
            f"Manage Stashes ({len(stashes)})",
            f"Clean Untracked Files ({len(untracked)})",
            "Show conflict marker lines" if markers else "Scan conflict markers (None)",
            "Exit"
        ]
        
        choice = choose_option(menu, "Select cleanup task:")
        
        if choice == 0:
            if merged:
                clean_merged(merged)
            else:
                print("\nNo merged branches to clean.")
        elif choice == 1:
            if stale:
                clean_stale(stale)
            else:
                print("\nNo stale branches to clean.")
        elif choice == 2:
            if stashes:
                clean_stashes(stashes)
            else:
                print("\nNo stashes to manage.")
        elif choice == 3:
            if untracked:
                clean_untracked(untracked)
            else:
                print("\nNo untracked files to clean.")
        elif choice == 4:
            if markers:
                print(f"\n{Colors.RED}Found Conflict Marker Lines:{Colors.RESET}")
                for m in markers[:20]:
                    print(f"  {Colors.BOLD}{m['file']}:{m['line']}{Colors.RESET} - {Colors.DIM}{m['content']}{Colors.RESET}")
                if len(markers) > 20:
                    print(f"  ... and {len(markers) - 20} more conflict markers.")
            else:
                print("\nNo conflict markers found.")
        elif choice == 5:
            print("Goodbye!")
            break

if __name__ == "__main__":
    main()
