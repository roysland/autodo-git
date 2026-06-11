#!/usr/bin/env python3
"""
Description: Generate an AI-powered git commit message using Ollama, with interactive review and editing before committing.
"""
import os
import sys
import re
import json
import shutil
import subprocess
import tempfile
import pathlib
import urllib.request
import urllib.error

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
    ITALIC = "\033[3m"
    RESET  = "\033[0m"

    @classmethod
    def disable(cls):
        for attr in ["PURPLE","CYAN","GREEN","YELLOW","RED","BLUE","BOLD","DIM","ITALIC","RESET"]:
            setattr(cls, attr, "")

# ─── Git helpers ───────────────────────────────────────────────────────────────

def run(cmd, **kwargs):
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kwargs)
    return res.returncode, res.stdout.strip(), res.stderr.strip()

def ensure_git_repo():
    rc, _, _ = run(["git", "rev-parse", "--is-inside-work-tree"])
    if rc != 0:
        print(f"{Colors.RED}Error: Not in a git repository.{Colors.RESET}")
        sys.exit(1)

def repo_root():
    _, root, _ = run(["git", "rev-parse", "--show-toplevel"])
    return pathlib.Path(root) if root else pathlib.Path.cwd()

def current_branch():
    _, branch, _ = run(["git", "branch", "--show-current"])
    return branch or "HEAD"

def stage_all():
    run(["git", "add", "."])

def get_staged_diff():
    _, diff, _ = run(["git", "diff", "--cached"])
    return diff

def get_staged_name_status():
    _, out, _ = run(["git", "diff", "--cached", "--name-status"])
    return out

def has_staged_changes():
    _, out, _ = run(["git", "diff", "--cached", "--name-only"])
    return bool(out.strip())

# ─── Ollama ────────────────────────────────────────────────────────────────────

OLLAMA_BASE = "http://localhost:11434"

def pick_model(preferred="qwen3.5:9b"):
    """Return the best available Ollama model, falling back to preferred."""
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE}/api/tags")
        with urllib.request.urlopen(req, timeout=3) as r:
            models = [m["name"] for m in json.loads(r.read())["models"]]
    except Exception:
        return preferred

    priority = [
        "qwen2.5-coder:7b",
        "qwen3.5:9b",
        "llama3.2:3b",
        "phi4-mini:latest",
        "smollm2:1.7b",
        "phi3:3.8b",
    ]
    for p in priority:
        for m in models:
            if m == p or m.startswith(p.split(":")[0]):
                return m
    return next((m for m in models if "embed" not in m), preferred)

def query_ollama(model, prompt, timeout=60):
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2},
    }).encode()
    try:
        req = urllib.request.Request(
            f"{OLLAMA_BASE}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()).get("response", "")
    except urllib.error.URLError:
        print(f"\n{Colors.RED}Error: Cannot reach Ollama at {OLLAMA_BASE}. Is it running?{Colors.RESET}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{Colors.RED}Ollama error: {e}{Colors.RESET}")
        sys.exit(1)

def clean_response(text):
    """Strip think blocks, markdown fences, and leading/trailing whitespace."""
    text = re.sub(r"(?is)<think>.*?</think>", "", text)
    text = re.sub(r"(?is)\bThinking\b.*?\bdone thinking\b\.?", "", text)
    text = re.sub(r"(?m)^```[a-zA-Z0-9_-]*\s*$", "", text)
    text = text.replace("```", "")
    return text.strip()

COMMIT_PROMPT = """\
You are an expert software engineer writing a git commit message.
Analyze the diff below and produce a commit message following these rules:

1. First line: imperative mood, max 72 chars (e.g. "Add user authentication")
2. Blank line after the first line if adding a body
3. Optional body: explain *what* changed and *why*, not *how*
4. Do NOT include the diff itself, file names as a list, or any markdown
5. Output ONLY the raw commit message text — no preamble, no code fences, no think tags

Git diff:
{diff}
"""

def generate_message(model, diff):
    diff_snippet = diff[:12000] + "\n\n[... diff truncated ...]" if len(diff) > 12000 else diff
    prompt = COMMIT_PROMPT.format(diff=diff_snippet)
    raw = query_ollama(model, prompt)
    return clean_response(raw)

# ─── UI helpers ────────────────────────────────────────────────────────────────

def print_header():
    print(f"\n{Colors.PURPLE}{Colors.BOLD}{'═' * 60}{Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}        CREATE COMMIT MESSAGE{Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}{'═' * 60}{Colors.RESET}\n")

def print_staged_files(name_status):
    if not name_status:
        return
    status_colors = {
        "A": Colors.GREEN,
        "M": Colors.YELLOW,
        "D": Colors.RED,
        "R": Colors.CYAN,
        "C": Colors.CYAN,
    }
    print(f"{Colors.BOLD}Staged changes:{Colors.RESET}")
    for line in name_status.splitlines():
        parts = line.split(None, 1)
        if not parts:
            continue
        code   = parts[0][0]          # first char of status code
        fname  = parts[1] if len(parts) > 1 else ""
        color  = status_colors.get(code, Colors.DIM)
        labels = {"A": "added", "M": "modified", "D": "deleted", "R": "renamed", "C": "copied"}
        label  = labels.get(code, code)
        print(f"  {color}{label:<10}{Colors.RESET} {fname}")
    print()

def print_message_box(msg):
    width = 58
    print(f"\n{Colors.CYAN}{Colors.BOLD}┌{'─' * width}┐{Colors.RESET}")
    for line in msg.splitlines():
        # Wrap long lines
        while len(line) > width - 2:
            print(f"{Colors.CYAN}{Colors.BOLD}│{Colors.RESET} {line[:width-2]} {Colors.CYAN}{Colors.BOLD}│{Colors.RESET}")
            line = "  " + line[width-2:]
        padding = width - 2 - len(line)
        print(f"{Colors.CYAN}{Colors.BOLD}│{Colors.RESET} {line}{' ' * padding} {Colors.CYAN}{Colors.BOLD}│{Colors.RESET}")
    print(f"{Colors.CYAN}{Colors.BOLD}└{'─' * width}┘{Colors.RESET}\n")

def ask(prompt_text, default=None):
    suffix = f" [{Colors.DIM}{default}{Colors.RESET}]" if default else ""
    try:
        val = input(f"{prompt_text}{suffix}: ").strip()
        return val if val else (default or "")
    except (KeyboardInterrupt, EOFError):
        print(f"\n{Colors.YELLOW}Cancelled.{Colors.RESET}")
        sys.exit(0)

def open_in_editor(initial_text):
    """Open $EDITOR (or nano/vi) with initial_text, return edited content."""
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or shutil.which("nano") or "vi"
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", prefix="commit_msg_", delete=False
    ) as f:
        f.write(initial_text)
        tmp_path = f.name
    try:
        subprocess.run([editor, tmp_path])
        return pathlib.Path(tmp_path).read_text().strip()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

def inline_edit(current_msg):
    """Let the user edit the message line-by-line in the terminal."""
    print(f"{Colors.DIM}Current message (press Enter to keep a line, or type a replacement):{Colors.RESET}")
    lines = current_msg.splitlines()
    new_lines = []
    for line in lines:
        try:
            edited = input(f"  {Colors.CYAN}{line}{Colors.RESET}\n> ").strip()
            new_lines.append(edited if edited else line)
        except (KeyboardInterrupt, EOFError):
            print(f"\n{Colors.YELLOW}Edit cancelled — keeping original.{Colors.RESET}")
            return current_msg
    return "\n".join(new_lines)

def do_commit(message):
    """Commit using a temp file so multi-line messages work correctly."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", prefix="commit_msg_", delete=False
    ) as f:
        f.write(message)
        tmp_path = f.name
    try:
        rc = subprocess.run(["git", "commit", "-F", tmp_path]).returncode
        return rc
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Generate an AI commit message with interactive review."
    )
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")
    parser.add_argument("--no-stage", action="store_true", help="Skip 'git add .' — only use already-staged changes")
    parser.add_argument("--model", default=None, help="Ollama model to use (auto-detected if omitted)")
    args = parser.parse_args()

    if args.no_color:
        Colors.disable()

    ensure_git_repo()
    os.chdir(repo_root())

    print_header()

    # ── Stage ──────────────────────────────────────────────────────────────────
    if not args.no_stage:
        stage_all()

    if not has_staged_changes():
        print(f"{Colors.YELLOW}No staged changes found. Nothing to commit.{Colors.RESET}")
        sys.exit(0)

    name_status = get_staged_name_status()
    print_staged_files(name_status)

    diff = get_staged_diff()

    # ── Model ──────────────────────────────────────────────────────────────────
    model = args.model or pick_model()
    branch = current_branch()
    print(f"Branch : {Colors.CYAN}{branch}{Colors.RESET}")
    print(f"Model  : {Colors.CYAN}{model}{Colors.RESET}\n")

    # ── Generate ───────────────────────────────────────────────────────────────
    print(f"{Colors.DIM}Generating commit message…{Colors.RESET}", end="", flush=True)
    message = generate_message(model, diff)
    print(f"\r{' ' * 35}\r", end="")  # clear the spinner line

    # ── Review loop ────────────────────────────────────────────────────────────
    while True:
        print(f"{Colors.BOLD}Suggested commit message:{Colors.RESET}")
        print_message_box(message)

        print(f"  {Colors.BOLD}[y]{Colors.RESET} Accept and commit")
        print(f"  {Colors.BOLD}[e]{Colors.RESET} Edit in {Colors.DIM}$EDITOR{Colors.RESET} ({os.environ.get('EDITOR', 'default editor')})")
        print(f"  {Colors.BOLD}[i]{Colors.RESET} Edit inline (line by line)")
        print(f"  {Colors.BOLD}[t]{Colors.RESET} Type a custom message from scratch")
        print(f"  {Colors.BOLD}[r]{Colors.RESET} Regenerate (ask the model again)")
        print(f"  {Colors.BOLD}[q]{Colors.RESET} Quit without committing")

        choice = ask(f"\n{Colors.BOLD}Choice{Colors.RESET}", default="y").lower()

        if choice == "y":
            break

        elif choice == "e":
            edited = open_in_editor(message)
            if not edited:
                print(f"{Colors.YELLOW}Editor returned empty message — keeping previous.{Colors.RESET}")
            else:
                message = edited

        elif choice == "i":
            message = inline_edit(message)

        elif choice == "t":
            custom = ask("Enter your commit message (first line = subject)")
            if custom:
                message = custom
            else:
                print(f"{Colors.YELLOW}Empty message — keeping previous.{Colors.RESET}")

        elif choice == "r":
            print(f"{Colors.DIM}Regenerating…{Colors.RESET}", end="", flush=True)
            message = generate_message(model, diff)
            print(f"\r{' ' * 20}\r", end="")

        elif choice == "q":
            print(f"{Colors.YELLOW}Aborted. No commit was made.{Colors.RESET}")
            sys.exit(0)

        else:
            print(f"{Colors.RED}Unknown choice '{choice}'. Please enter y/e/i/t/r/q.{Colors.RESET}")

    # ── Commit ─────────────────────────────────────────────────────────────────
    if not message.strip():
        print(f"{Colors.RED}Commit message is empty. Aborting.{Colors.RESET}")
        sys.exit(1)

    rc = do_commit(message)

    if rc == 0:
        _, short_hash, _ = run(["git", "rev-parse", "--short", "HEAD"])
        print(f"\n{Colors.GREEN}{Colors.BOLD}✔ Committed successfully!{Colors.RESET}")
        print(f"  Hash    : {Colors.CYAN}{short_hash}{Colors.RESET}")
        print(f"  Branch  : {Colors.CYAN}{branch}{Colors.RESET}")
        print(f"  Message :")
        print_message_box(message)
    else:
        print(f"\n{Colors.RED}Commit failed (exit code {rc}).{Colors.RESET}")
        sys.exit(rc)

if __name__ == "__main__":
    main()
