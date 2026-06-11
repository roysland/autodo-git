#!/usr/bin/env python3
"""
Description: Remove tracked files from git index that match .gitignore patterns — safely untrack files without deleting them from disk.
"""
import os
import sys
import subprocess
import pathlib
import fnmatch

# ─── Colors ────────────────────────────────────────────────────────────────────

class Colors:
    PURPLE = "\033[1;35m"
    CYAN   = "\033[1;36m"
    GREEN  = "\033[1;32m"
    YELLOW = "\033[1;33m"
    RED    = "\033[1;31m"
    BLUE   = "\033[1;34m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    RESET  = "\033[0m"

# ─── Helpers ───────────────────────────────────────────────────────────────────

def run_cmd(cmd, cwd=None):
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd)
    return res.returncode, res.stdout.strip(), res.stderr.strip()

def get_repo_root():
    rc, root, _ = run_cmd(["git", "rev-parse", "--show-toplevel"])
    return pathlib.Path(root) if rc == 0 and root else None

def get_tracked_files(root: pathlib.Path) -> list[str]:
    """Return all files currently tracked by git (relative paths)."""
    rc, stdout, _ = run_cmd(["git", "ls-files"], cwd=root)
    if rc != 0 or not stdout:
        return []
    return stdout.splitlines()

def get_gitignored_tracked(root: pathlib.Path) -> list[str]:
    """
    Use `git check-ignore` to find tracked files that are matched by .gitignore.
    git check-ignore --stdin -v reads paths from stdin and reports matches.
    """
    tracked = get_tracked_files(root)
    if not tracked:
        return []

    # Feed all tracked paths into git check-ignore
    proc = subprocess.run(
        ["git", "check-ignore", "--stdin", "-v", "--no-index"],
        input="\n".join(tracked),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=root,
    )

    # Output format: <source>:<linenum>:<pattern>\t<pathname>
    ignored = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            ignored.append(parts[1].strip())

    return ignored

def untrack_files(files: list[str], root: pathlib.Path, dry_run: bool = False) -> int:
    """
    Run `git rm --cached` on the given files.
    Returns count of successfully untracked files.
    """
    if not files:
        return 0

    cmd = ["git", "rm", "--cached", "-r", "--quiet"]
    if dry_run:
        cmd.append("--dry-run")
    cmd.extend(files)

    rc, stdout, stderr = run_cmd(cmd, cwd=root)

    if stdout:
        for line in stdout.splitlines():
            color = Colors.DIM if dry_run else Colors.GREEN
            print(f"  {color}{line}{Colors.RESET}")

    if stderr:
        for line in stderr.splitlines():
            print(f"  {Colors.RED}{line}{Colors.RESET}")

    return rc

def choose_option(options: list[str], prompt: str) -> int:
    print(f"\n{prompt}")
    for idx, opt in enumerate(options, 1):
        print(f"  {Colors.BOLD}{idx}. {opt}{Colors.RESET}")
    while True:
        try:
            choice = input(f"Select (1-{len(options)}): ").strip()
            if not choice:
                continue
            val = int(choice)
            if 1 <= val <= len(options):
                return val - 1
        except ValueError:
            pass
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            sys.exit(0)
        print(f"Please enter a number between 1 and {len(options)}.")

def format_file_list(files: list[str], max_show: int = 30) -> str:
    lines = [f"  {Colors.YELLOW}•{Colors.RESET} {f}" for f in files[:max_show]]
    if len(files) > max_show:
        lines.append(f"  {Colors.DIM}... and {len(files) - max_show} more{Colors.RESET}")
    return "\n".join(lines)

def group_by_pattern(files: list[str], root: pathlib.Path) -> dict[str, list[str]]:
    """
    Group files by which .gitignore pattern matched them.
    Uses `git check-ignore -v` output to get pattern info.
    """
    if not files:
        return {}

    proc = subprocess.run(
        ["git", "check-ignore", "--stdin", "-v", "--no-index"],
        input="\n".join(files),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=root,
    )

    groups: dict[str, list[str]] = {}
    for line in proc.stdout.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            meta   = parts[0]  # e.g. .gitignore:5:*.log
            fpath  = parts[1].strip()
            # Extract the pattern from the meta segment (last colon-delimited part)
            meta_parts = meta.rsplit(":", 1)
            pattern = meta_parts[-1] if meta_parts else "unknown"
            groups.setdefault(pattern, []).append(fpath)

    return groups

# ─── Main ───────────────────────────────────────────────────────────────────────

def main():
    root = get_repo_root()
    if root is None:
        print(f"{Colors.RED}Error: Not in a git repository.{Colors.RESET}")
        sys.exit(1)

    gitignore_path = root / ".gitignore"

    print(f"\n{Colors.PURPLE}{Colors.BOLD}{'=' * 64}{Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}          GIT UNTRACK — Remove Ignored Tracked Files{Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}{'=' * 64}{Colors.RESET}\n")

    if not gitignore_path.is_file():
        print(f"{Colors.YELLOW}Warning: No .gitignore found at {gitignore_path}{Colors.RESET}")
        print(f"Run {Colors.CYAN}git-gitignore{Colors.RESET} first to create one.")
        sys.exit(1)

    print(f"Repo root: {Colors.CYAN}{root}{Colors.RESET}")
    print(f"Scanning for tracked files that match .gitignore patterns…")

    ignored = get_gitignored_tracked(root)

    if not ignored:
        print(f"\n{Colors.GREEN}✔ No tracked files match any .gitignore pattern. Nothing to do!{Colors.RESET}")
        sys.exit(0)

    # Group by matching pattern for a clearer report
    groups = group_by_pattern(ignored, root)

    print(f"\n{Colors.RED}{Colors.BOLD}Found {len(ignored)} tracked file(s) that should be ignored:{Colors.RESET}\n")

    for pattern, files in sorted(groups.items()):
        print(f"  {Colors.CYAN}Pattern:{Colors.RESET} {Colors.BOLD}{pattern}{Colors.RESET}  ({len(files)} file(s))")
        for f in files[:10]:
            print(f"    {Colors.YELLOW}•{Colors.RESET} {f}")
        if len(files) > 10:
            print(f"    {Colors.DIM}... and {len(files) - 10} more{Colors.RESET}")

    print(f"\n{Colors.BOLD}These files will be REMOVED FROM GIT TRACKING only.{Colors.RESET}")
    print(f"{Colors.DIM}They will NOT be deleted from your disk. They will simply stop being versioned.{Colors.RESET}")
    print(f"{Colors.YELLOW}Note: You will need to commit the result to make the untracking permanent.{Colors.RESET}")

    choice = choose_option(
        [
            f"Dry-run — show what git rm --cached would do without applying",
            f"Untrack all {len(ignored)} file(s)",
            "Select files interactively",
            "Exit without changes",
        ],
        "What would you like to do?"
    )

    if choice == 0:
        # Dry run
        print(f"\n{Colors.DIM}Dry run (no changes will be made):{Colors.RESET}")
        rc = untrack_files(ignored, root, dry_run=True)
        print(f"\n{Colors.DIM}Dry run complete. Re-run and choose 'Untrack all' to apply.{Colors.RESET}")

    elif choice == 1:
        # Untrack all
        print(f"\n{Colors.BOLD}Untracking {len(ignored)} file(s)…{Colors.RESET}")
        rc = untrack_files(ignored, root)
        if rc == 0:
            print(f"\n{Colors.GREEN}✔ Done! {len(ignored)} file(s) removed from git index.{Colors.RESET}")
            print(f"\n{Colors.YELLOW}Next steps:{Colors.RESET}")
            print(f"  1. Review changes:  {Colors.CYAN}git status{Colors.RESET}")
            print(f"  2. Commit them:     {Colors.CYAN}git commit -m \"chore: untrack files now covered by .gitignore\"{Colors.RESET}")
        else:
            print(f"\n{Colors.RED}Some files could not be untracked. Review the output above.{Colors.RESET}")

    elif choice == 2:
        # Interactive selection
        print(f"\n{Colors.BOLD}Select files to untrack (enter numbers separated by spaces, 'all', or 'q'):{Colors.RESET}")
        for idx, f in enumerate(ignored, 1):
            print(f"  {Colors.DIM}{idx:>4}.{Colors.RESET} {f}")
        try:
            raw = input("\nSelection: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            sys.exit(0)

        if not raw or raw.lower() == "q":
            print("No changes made.")
            sys.exit(0)

        to_untrack: list[str] = []
        if raw.lower() == "all":
            to_untrack = ignored
        else:
            for tok in raw.split():
                try:
                    idx = int(tok) - 1
                    if 0 <= idx < len(ignored):
                        to_untrack.append(ignored[idx])
                except ValueError:
                    pass

        if not to_untrack:
            print("No valid selection. Nothing to do.")
            sys.exit(0)

        print(f"\n{Colors.BOLD}Untracking {len(to_untrack)} file(s)…{Colors.RESET}")
        rc = untrack_files(to_untrack, root)
        if rc == 0:
            print(f"\n{Colors.GREEN}✔ Done! {len(to_untrack)} file(s) removed from git index.{Colors.RESET}")
            print(f"\n{Colors.YELLOW}Next steps:{Colors.RESET}")
            print(f"  1. Review changes:  {Colors.CYAN}git status{Colors.RESET}")
            print(f"  2. Commit them:     {Colors.CYAN}git commit -m \"chore: untrack files now covered by .gitignore\"{Colors.RESET}")
        else:
            print(f"\n{Colors.RED}Some files could not be untracked. Review the output above.{Colors.RESET}")

    elif choice == 3:
        print("Exiting. No changes made.")

if __name__ == "__main__":
    main()
