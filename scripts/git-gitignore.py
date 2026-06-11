#!/usr/bin/env python3
"""
Description: Interactive .gitignore creator/editor — ensures agentic folders, SQLite databases, comments/thoughts, and sensitive files are properly ignored.
"""
import os
import sys
import re
import subprocess
import pathlib

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

# ─── Recommended ignore groups ─────────────────────────────────────────────────

IGNORE_GROUPS = [
    {
        "id":      "agentic",
        "label":   "Agentic / AI tool folders",
        "desc":    "Folders created by AI coding assistants and agentic tools",
        "entries": [
            ".antigravitycli/",
            ".gemini/",
            ".aider/",
            ".aider.tags.cache.v*/",
            ".aider.chat.history.md",
            ".cursor/",
            ".continue/",
            ".copilot/",
            ".github/copilot-instructions.md",
            ".codeium/",
            ".sourcegraph/",
            ".tabnine/",
            ".cody/",
            ".mentat/",
            ".sweep/",
            ".gpt-engineer/",
            ".smol-developer/",
            ".devin/",
            ".agent/",
            ".claude/",
            "agent_workspace/",
        ],
    },
    {
        "id":      "databases",
        "label":   "SQLite & database files",
        "desc":    "SQLite and other embedded database files",
        "entries": [
            "*.sqlite",
            "*.sqlite3",
            "*.sqlite3-shm",
            "*.sqlite3-wal",
            "*.db",
            "*.db-shm",
            "*.db-wal",
            "*.mdb",
        ],
    },
    {
        "id":      "thoughts",
        "label":   "Comments, thoughts & scratch notes",
        "desc":    "Personal notes, AI reasoning traces, scratch pads, and ephemeral thought files",
        "entries": [
            "thoughts/",
            "scratch/",
            "notes/",
            "scratchpad/",
            "NOTES.md",
            "SCRATCH.md",
            "THOUGHTS.md",
            "TODO.local.md",
            "*.thoughts.md",
            "*.notes.md",
            "*.scratch.md",
            ".brain/",
            "brain/",
        ],
    },
    {
        "id":      "secrets",
        "label":   "Secrets & credentials",
        "desc":    "API keys, tokens, environment files, and credentials",
        "entries": [
            ".env",
            ".env.*",
            "!.env.example",
            "!.env.template",
            "*.pem",
            "*.key",
            "*.p12",
            "*.pfx",
            "secrets.json",
            "secrets.yaml",
            "secrets.yml",
            "credentials.json",
            ".secrets/",
        ],
    },
    {
        "id":      "os",
        "label":   "OS-generated files",
        "desc":    "macOS, Windows, and Linux system-generated metadata files",
        "entries": [
            ".DS_Store",
            ".DS_Store?",
            "._*",
            ".Spotlight-V100",
            ".Trashes",
            "Thumbs.db",
            "ehthumbs.db",
            "Desktop.ini",
            "$RECYCLE.BIN/",
            ".directory",
        ],
    },
    {
        "id":      "editors",
        "label":   "Editor & IDE files",
        "desc":    "VS Code, JetBrains, Vim, Emacs, and other editor metadata",
        "entries": [
            ".vscode/",
            "!.vscode/extensions.json",
            "!.vscode/settings.json",
            ".idea/",
            "*.swp",
            "*.swo",
            "*~",
            "*.orig",
            ".project",
            ".classpath",
            ".settings/",
            "*.iml",
        ],
    },
    {
        "id":      "build",
        "label":   "Build artifacts & dependencies",
        "desc":    "Compiled output, caches, and dependency directories",
        "entries": [
            "__pycache__/",
            "*.py[cod]",
            "*.pyo",
            ".pytest_cache/",
            ".mypy_cache/",
            ".ruff_cache/",
            "*.egg-info/",
            "dist/",
            "build/",
            "node_modules/",
            ".npm/",
            ".pnpm-store/",
            ".yarn/",
            "target/",
            ".cargo/",
        ],
    },
    {
        "id":      "logs",
        "label":   "Log files",
        "desc":    "Application and system log files",
        "entries": [
            "*.log",
            "logs/",
            "*.log.*",
            "npm-debug.log*",
            "yarn-debug.log*",
            "yarn-error.log*",
        ],
    },
]

# ─── Helpers ───────────────────────────────────────────────────────────────────

def run_cmd(cmd):
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return res.returncode, res.stdout.strip(), res.stderr.strip()

def get_repo_root():
    rc, root, _ = run_cmd(["git", "rev-parse", "--show-toplevel"])
    return pathlib.Path(root) if rc == 0 and root else None

def read_gitignore(path: pathlib.Path):
    """Return a list of raw lines (preserving comments/blanks)."""
    if path.is_file():
        return path.read_text(errors="replace").splitlines()
    return []

def write_gitignore(path: pathlib.Path, lines: list[str]):
    path.write_text("\n".join(lines) + "\n")

def active_patterns(lines: list[str]):
    """Return a set of non-comment, non-blank patterns currently in the file."""
    patterns = set()
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            patterns.add(stripped)
    return patterns

def section_header(label: str):
    return [f"", f"# ── {label} ─────────────────────────────────────────"]

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

# ─── Status display ─────────────────────────────────────────────────────────────

def print_header(gitignore_path: pathlib.Path, lines: list[str]):
    exists = gitignore_path.is_file()
    patterns = active_patterns(lines)

    print(f"\n{Colors.PURPLE}{Colors.BOLD}{'=' * 64}{Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}              .GITIGNORE MANAGER{Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}{'=' * 64}{Colors.RESET}\n")

    status = f"{Colors.GREEN}exists{Colors.RESET}" if exists else f"{Colors.YELLOW}not found (will be created){Colors.RESET}"
    print(f"File: {Colors.CYAN}{gitignore_path}{Colors.RESET}  [{status}]")
    print(f"Active patterns: {Colors.BOLD}{len(patterns)}{Colors.RESET}")

    # Coverage summary per group
    print(f"\n{Colors.BOLD}Group coverage:{Colors.RESET}")
    for group in IGNORE_GROUPS:
        group_patterns  = set(group["entries"])
        covered         = group_patterns & patterns
        pct             = int(100 * len(covered) / len(group_patterns))
        if pct == 100:
            bar_color = Colors.GREEN
        elif pct >= 50:
            bar_color = Colors.YELLOW
        else:
            bar_color = Colors.RED
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        print(f"  {group['label']:<35} {bar_color}{bar} {pct:>3}%{Colors.RESET}")

    print(f"\n{Colors.PURPLE}{Colors.BOLD}{'=' * 64}{Colors.RESET}")

# ─── Actions ───────────────────────────────────────────────────────────────────

def apply_all_recommended(lines: list[str], gitignore_path: pathlib.Path):
    """Merge all recommended groups into the .gitignore."""
    patterns = active_patterns(lines)
    added_total = 0

    for group in IGNORE_GROUPS:
        missing = [e for e in group["entries"] if e not in patterns]
        if not missing:
            continue
        lines += section_header(group["label"])
        for entry in missing:
            lines.append(entry)
        added_total += len(missing)

    write_gitignore(gitignore_path, lines)
    print(f"\n{Colors.GREEN}✔ Added {added_total} new pattern(s) across all groups.{Colors.RESET}")
    return lines

def pick_groups_interactive(lines: list[str], gitignore_path: pathlib.Path):
    """Let the user select which groups to add."""
    patterns = active_patterns(lines)
    added_total = 0

    for group in IGNORE_GROUPS:
        missing = [e for e in group["entries"] if e not in patterns]
        if not missing:
            print(f"\n{Colors.DIM}[{group['label']}] — all patterns already present, skipping.{Colors.RESET}")
            continue

        print(f"\n{Colors.CYAN}{Colors.BOLD}[{group['label']}]{Colors.RESET}")
        print(f"  {Colors.DIM}{group['desc']}{Colors.RESET}")
        print(f"  Missing patterns ({len(missing)}):")
        for e in missing:
            print(f"    {Colors.YELLOW}+{Colors.RESET} {e}")

        try:
            choice = input("  Add these patterns? (y/n/q): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            break

        if choice == "q":
            break
        if choice == "y":
            lines += section_header(group["label"])
            for entry in missing:
                lines.append(entry)
            added_total += len(missing)

    if added_total:
        write_gitignore(gitignore_path, lines)
        print(f"\n{Colors.GREEN}✔ Added {added_total} new pattern(s).{Colors.RESET}")
    else:
        print(f"\n{Colors.DIM}No changes made.{Colors.RESET}")

    return lines

def add_custom_entry(lines: list[str], gitignore_path: pathlib.Path):
    """Prompt the user to type a custom pattern."""
    patterns = active_patterns(lines)
    try:
        entry = input("\nEnter pattern to add (e.g. *.log or secrets/): ").strip()
    except (KeyboardInterrupt, EOFError):
        return lines

    if not entry:
        print("No entry given.")
        return lines

    if entry in patterns:
        print(f"{Colors.YELLOW}Pattern already exists in .gitignore.{Colors.RESET}")
        return lines

    lines.append(entry)
    write_gitignore(gitignore_path, lines)
    print(f"{Colors.GREEN}✔ Added: {entry}{Colors.RESET}")
    return lines

def show_current(lines: list[str]):
    """Pretty-print the current .gitignore contents."""
    if not lines:
        print(f"\n{Colors.DIM}(empty){Colors.RESET}")
        return
    print(f"\n{Colors.BOLD}Current .gitignore:{Colors.RESET}")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            print()
        elif stripped.startswith("#"):
            print(f"  {Colors.DIM}{line}{Colors.RESET}")
        else:
            print(f"  {Colors.CYAN}{line}{Colors.RESET}")

def check_missing(lines: list[str]):
    """Report recommended patterns not yet present."""
    patterns = active_patterns(lines)
    any_missing = False
    for group in IGNORE_GROUPS:
        missing = [e for e in group["entries"] if e not in patterns]
        if missing:
            any_missing = True
            print(f"\n{Colors.YELLOW}{Colors.BOLD}[{group['label']}]{Colors.RESET}  {Colors.DIM}{group['desc']}{Colors.RESET}")
            for e in missing:
                print(f"  {Colors.RED}-{Colors.RESET} {e}")
    if not any_missing:
        print(f"\n{Colors.GREEN}✔ All recommended patterns are already covered!{Colors.RESET}")

def remove_entry(lines: list[str], gitignore_path: pathlib.Path):
    """Remove a specific pattern from .gitignore."""
    patterns = sorted(active_patterns(lines))
    if not patterns:
        print("No patterns to remove.")
        return lines

    print(f"\n{Colors.BOLD}Active patterns:{Colors.RESET}")
    for idx, p in enumerate(patterns, 1):
        print(f"  {idx}. {Colors.CYAN}{p}{Colors.RESET}")

    try:
        raw = input("\nEnter pattern number(s) to remove (space-separated), or 'q' to cancel: ").strip()
    except (KeyboardInterrupt, EOFError):
        return lines

    if not raw or raw.lower() == "q":
        return lines

    to_remove = set()
    for tok in raw.split():
        try:
            idx = int(tok) - 1
            if 0 <= idx < len(patterns):
                to_remove.add(patterns[idx])
        except ValueError:
            pass

    if not to_remove:
        print("Nothing to remove.")
        return lines

    new_lines = [l for l in lines if l.strip() not in to_remove]
    write_gitignore(gitignore_path, new_lines)
    print(f"{Colors.GREEN}✔ Removed {len(to_remove)} pattern(s).{Colors.RESET}")
    return new_lines

# ─── Main ───────────────────────────────────────────────────────────────────────

def main():
    root = get_repo_root()
    if root is None:
        print(f"{Colors.RED}Error: Not in a git repository.{Colors.RESET}")
        sys.exit(1)

    gitignore_path = root / ".gitignore"
    lines = read_gitignore(gitignore_path)

    while True:
        print_header(gitignore_path, lines)

        menu = [
            "Apply ALL recommended patterns (auto-merge)",
            "Review and pick groups interactively",
            "Add a custom pattern",
            "Remove a pattern",
            "Show current .gitignore",
            "Show missing recommended patterns",
            "Exit",
        ]
        choice = choose_option(menu, "What would you like to do?")

        if choice == 0:
            lines = apply_all_recommended(lines, gitignore_path)
        elif choice == 1:
            lines = pick_groups_interactive(lines, gitignore_path)
        elif choice == 2:
            lines = add_custom_entry(lines, gitignore_path)
        elif choice == 3:
            lines = remove_entry(lines, gitignore_path)
        elif choice == 4:
            show_current(lines)
        elif choice == 5:
            check_missing(lines)
        elif choice == 6:
            print("Goodbye!")
            break

if __name__ == "__main__":
    main()
