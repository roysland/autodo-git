#!/usr/bin/env python3
"""
Description: Splits a large diff into atomic commits at the hunk level.
Unlike git-split, this operates on individual diff hunks rather than whole
files, guaranteeing that unrelated edits in the same file land in separate commits.
"""
import os
import sys
import re
import json
import urllib.request
import subprocess
import pathlib
import tempfile


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
        for attr in ["PURPLE", "CYAN", "GREEN", "YELLOW", "RED", "BLUE", "BOLD", "DIM", "RESET"]:
            setattr(cls, attr, "")


def run_cmd_capture(cmd):
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return res.returncode, res.stdout, res.stderr.strip()


def run_cmd_interactive(cmd):
    return subprocess.run(cmd).returncode


def get_ollama_model():
    url = "http://localhost:11434/api/tags"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode())
            installed = [m["name"] for m in data.get("models", [])]
    except Exception:
        installed = []

    preferred = [
        "qwen2.5-coder:7b",
        "deepseek-coder:6.7b",
        "kimi-k2.7-code:cloud"
    ]
    for p in preferred:
        for m in installed:
            if m == p or m.startswith(p + ":") or p.startswith(m + ":"):
                return m
    for m in installed:
        if "embed" not in m:
            return m
    return "qwen2.5-coder:7b"


def query_ollama(model, prompt):
    url = "http://localhost:11434/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.1}}
    data = json.dumps(payload).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode()).get("response", "")
    except Exception as e:
        print(f"\n{Colors.RED}Error: Failed to connect to Ollama. Make sure Ollama is running.{Colors.RESET}")
        print(f"Details: {e}")
        sys.exit(1)


def strip_think_and_codeblocks(text):
    text = re.sub(r"(?is)<think>.*?</think>", "", text)
    text = re.sub(r"(?is)\bThinking\b.*?\bdone thinking\b\.?", "", text)
    text = re.sub(r"(?m)^```[a-zA-Z0-9_-]*\s*$", "", text)
    text = text.replace("```json", "").replace("```", "")
    return text.strip()


def extract_json(text):
    text = strip_think_and_codeblocks(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
    return None


# ---------------------------------------------------------------------------
# Hunk parsing
# ---------------------------------------------------------------------------

def parse_diff_into_hunks(diff_str):
    """Parse a unified diff string into a list of hunk dicts.

    Each hunk is:
      {id, file, file_header (str), hunk_lines (list[str])}

    file_header contains everything from 'diff --git' up to (not including)
    the first '@@' line. hunk_lines starts with the '@@' line.
    """
    hunks = []
    file_header_lines = []
    current_file = None
    current_hunk_lines = []
    in_hunk = False

    for line in diff_str.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if in_hunk and current_hunk_lines:
                hunks.append(_make_hunk(len(hunks), current_file, file_header_lines, current_hunk_lines))
                current_hunk_lines = []
                in_hunk = False
            m = re.search(r" b/(.+)$", line.rstrip())
            current_file = m.group(1) if m else "?"
            file_header_lines = [line]
        elif not in_hunk and (
            line.startswith("index ")
            or line.startswith("--- ")
            or line.startswith("+++ ")
            or line.startswith("new file mode")
            or line.startswith("deleted file mode")
            or line.startswith("old mode")
            or line.startswith("new mode")
            or line.startswith("Binary files")
        ):
            file_header_lines.append(line)
        elif line.startswith("@@ "):
            if in_hunk and current_hunk_lines:
                hunks.append(_make_hunk(len(hunks), current_file, file_header_lines, current_hunk_lines))
            current_hunk_lines = [line]
            in_hunk = True
        elif in_hunk:
            current_hunk_lines.append(line)

    if in_hunk and current_hunk_lines:
        hunks.append(_make_hunk(len(hunks), current_file, file_header_lines, current_hunk_lines))

    return hunks


def _make_hunk(hunk_id, file_path, file_header_lines, hunk_lines):
    return {
        "id": hunk_id,
        "file": file_path,
        "file_header": "".join(file_header_lines),
        "hunk_lines": list(hunk_lines),
    }


def get_hunk_preview(hunk_lines, max_changed=8):
    """Return a short preview of the changed lines in a hunk."""
    changed = []
    for line in hunk_lines[1:]:  # skip the @@ header
        if line.startswith("+") or line.startswith("-"):
            changed.append(line.rstrip("\n"))
            if len(changed) >= max_changed:
                changed.append("...")
                break
    return "\n".join(changed)


def build_patch_for_hunks(hunks):
    """Reconstruct a valid unified diff patch from a list of hunk dicts."""
    by_file = {}
    file_order = []
    for h in hunks:
        f = h["file"]
        if f not in by_file:
            by_file[f] = {"header": h["file_header"], "hunks": []}
            file_order.append(f)
        by_file[f]["hunks"].append("".join(h["hunk_lines"]))

    parts = []
    for f in file_order:
        parts.append(by_file[f]["header"])
        for hunk in by_file[f]["hunks"]:
            parts.append(hunk)
    return "".join(parts)


# ---------------------------------------------------------------------------
# AI clustering
# ---------------------------------------------------------------------------

def get_semantic_clusters(hunks, model):
    """Ask Ollama to group hunks into logical atomic commit clusters."""
    summaries = []
    for h in hunks:
        hunk_header = h["hunk_lines"][0].rstrip() if h["hunk_lines"] else ""
        summaries.append({
            "id": h["id"],
            "file": h["file"],
            "hunk_header": hunk_header,
            "changes": get_hunk_preview(h["hunk_lines"]),
        })

    summary_json = json.dumps(summaries, indent=2)
    if len(summary_json) > 14000:
        summary_json = summary_json[:14000] + "\n... [truncated]"

    prompt = f"""You are a Git assistant. Group these diff hunks into logical, atomic clusters — each cluster should represent a single coherent change that deserves its own commit.

Hunks:
{summary_json}

Respond with a single valid JSON object:
{{
  "clusters": [
    {{
      "title": "Short commit-worthy title (under 60 chars)",
      "hunk_ids": [0, 2, 5],
      "explanation": "One line: why these hunks belong together."
    }}
  ]
}}

Rules:
1. Every hunk id must appear in exactly one cluster.
2. If all hunks form a single coherent change, return one cluster.
3. Respond ONLY with the raw JSON object. No markdown fences, no think tags.
"""
    response = query_ollama(model, prompt)
    result = extract_json(response)

    all_ids = {h["id"] for h in hunks}

    if result and "clusters" in result:
        assigned = set()
        valid_clusters = []
        for c in result["clusters"]:
            c["hunk_ids"] = [i for i in c.get("hunk_ids", []) if i in all_ids]
            if c["hunk_ids"]:
                assigned.update(c["hunk_ids"])
                valid_clusters.append(c)
        result["clusters"] = valid_clusters
        unassigned = all_ids - assigned
        if unassigned:
            result["clusters"].append({
                "title": "Remaining changes",
                "hunk_ids": sorted(unassigned),
                "explanation": "Hunks not assigned by AI clustering.",
            })
        return result

    return {
        "clusters": [
            {
                "title": "All changes",
                "hunk_ids": sorted(all_ids),
                "explanation": "Single cluster fallback.",
            }
        ]
    }


def generate_commit_message(staged_diff, model):
    max_len = 8000
    if len(staged_diff) > max_len:
        staged_diff = staged_diff[:max_len] + "\n... [truncated]"

    prompt = f"""Generate a concise, professional git commit message for this diff.

Diff:
{staged_diff}

Return only the commit message text. Summary line under 72 chars, optionally followed by a blank line and a short body. No markdown, no think blocks.
"""
    response = query_ollama(model, prompt)
    response = strip_think_and_codeblocks(response)
    lines = [l.strip() for l in response.splitlines() if l.strip()]
    return "\n".join(lines) if lines else "update: changes"


# ---------------------------------------------------------------------------
# Interactive helpers
# ---------------------------------------------------------------------------

def ask_question(prompt_text, default=None):
    try:
        suffix = f" [{default}]" if default else ""
        inp = input(f"{prompt_text}{suffix}: ").strip()
        return inp if inp else (default or "")
    except (KeyboardInterrupt, EOFError):
        print("\nOperation cancelled.")
        sys.exit(0)


def display_cluster(cluster, hunk_by_id, idx, total):
    print(f"\n{Colors.BOLD}Cluster {idx}/{total}: {Colors.CYAN}{cluster['title']}{Colors.RESET}")
    print(f"  {Colors.DIM}{cluster['explanation']}{Colors.RESET}")
    print(f"  Hunks ({len(cluster['hunk_ids'])}):")
    for hid in cluster["hunk_ids"]:
        h = hunk_by_id[hid]
        hunk_header = h["hunk_lines"][0].rstrip() if h["hunk_lines"] else ""
        print(f"    {Colors.BLUE}[{hid}]{Colors.RESET} {h['file']}  {Colors.DIM}{hunk_header}{Colors.RESET}")
        preview = get_hunk_preview(h["hunk_lines"], max_changed=4)
        for pline in preview.splitlines():
            if pline.startswith("+"):
                print(f"         {Colors.GREEN}{pline}{Colors.RESET}")
            elif pline.startswith("-"):
                print(f"         {Colors.RED}{pline}{Colors.RESET}")
            else:
                print(f"         {Colors.DIM}{pline}{Colors.RESET}")


def edit_cluster_hunks(cluster, hunk_by_id):
    """Let the user adjust which hunk IDs are in this cluster."""
    print(f"\nCurrent hunk IDs: {cluster['hunk_ids']}")
    print("All available hunk IDs and their locations:")
    for hid, h in sorted(hunk_by_id.items()):
        marker = "*" if hid in cluster["hunk_ids"] else " "
        hunk_header = h["hunk_lines"][0].rstrip() if h["hunk_lines"] else ""
        print(f"  [{marker}] {hid}: {h['file']}  {Colors.DIM}{hunk_header}{Colors.RESET}")
    raw = ask_question("Enter hunk IDs to include (comma-separated)", ",".join(str(i) for i in cluster["hunk_ids"]))
    try:
        chosen = [int(x.strip()) for x in raw.split(",") if x.strip()]
        valid = [i for i in chosen if i in hunk_by_id]
        if valid:
            cluster["hunk_ids"] = valid
        else:
            print(f"{Colors.YELLOW}No valid IDs entered, keeping original selection.{Colors.RESET}")
    except ValueError:
        print(f"{Colors.YELLOW}Invalid input, keeping original selection.{Colors.RESET}")


# ---------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------

def stage_hunks(hunks):
    """Apply hunks to the index via git apply --cached. Returns (ok, error)."""
    patch = build_patch_for_hunks(hunks)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False, encoding="utf-8") as f:
        f.write(patch)
        patch_path = f.name
    try:
        rc, _, err = run_cmd_capture(["git", "apply", "--cached", patch_path])
        if rc != 0:
            # Retry with 3-way merge for robustness after prior partial commits
            rc, _, err = run_cmd_capture(["git", "apply", "--cached", "--3way", patch_path])
        return rc == 0, err
    finally:
        pathlib.Path(patch_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    rc, repo_root, _ = run_cmd_capture(["git", "rev-parse", "--show-toplevel"])
    if rc == 0 and repo_root.strip():
        os.chdir(repo_root.strip())

    if run_cmd_capture(["git", "rev-parse", "--is-inside-work-tree"])[0] != 0:
        print(f"{Colors.RED}Error: Not in a git repository.{Colors.RESET}")
        sys.exit(1)

    import argparse
    parser = argparse.ArgumentParser(
        description="git-atomic: Split a large diff into atomic commits at the hunk level."
    )
    parser.add_argument("--no-color", action="store_true", help="Disable colored output.")
    args = parser.parse_args()

    if args.no_color:
        Colors.disable()

    print(f"\n{Colors.PURPLE}{Colors.BOLD}{'=' * 64}{Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}{'GIT-ATOMIC WORKFLOW':^64}{Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}{'=' * 64}{Colors.RESET}\n")

    # Reset index so we see the full picture via git diff HEAD
    print("Clearing staged index...")
    run_cmd_capture(["git", "reset"])

    _, diff_str, _ = run_cmd_capture(["git", "diff", "HEAD"])

    # Also include untracked files as new-file hunks
    _, status_out, _ = run_cmd_capture(["git", "status", "--porcelain"])
    untracked = [l[3:] for l in status_out.splitlines() if l.startswith("?? ")]
    for uf in untracked:
        p = pathlib.Path(uf)
        if not p.is_file() or p.stat().st_size > 100_000:
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
            if "\x00" in content:
                continue
            lines = content.splitlines()
            mock = (
                f"diff --git a/{uf} b/{uf}\n"
                f"new file mode 100644\n"
                f"--- /dev/null\n"
                f"+++ b/{uf}\n"
                f"@@ -0,0 +1,{len(lines)} @@\n"
                + "\n".join(f"+{l}" for l in lines)
                + "\n"
            )
            diff_str = (diff_str or "") + mock
        except Exception:
            pass

    if not diff_str or not diff_str.strip():
        print(f"{Colors.GREEN}Workspace is clean. Nothing to split.{Colors.RESET}")
        sys.exit(0)

    hunks = parse_diff_into_hunks(diff_str)
    if not hunks:
        print(f"{Colors.YELLOW}No parseable hunks found in diff.{Colors.RESET}")
        sys.exit(0)

    hunk_by_id = {h["id"]: h for h in hunks}
    print(f"Found {Colors.CYAN}{len(hunks)}{Colors.RESET} hunk(s) across "
          f"{Colors.CYAN}{len({h['file'] for h in hunks})}{Colors.RESET} file(s).\n")

    print("Checking Ollama model...")
    model = get_ollama_model()
    print(f"Using model: {Colors.CYAN}{model}{Colors.RESET}\n")

    print("Calling Ollama to generate semantic clusters...")
    clusters_data = get_semantic_clusters(hunks, model)
    clusters = clusters_data.get("clusters", [])
    print(f"Suggested {Colors.CYAN}{len(clusters)}{Colors.RESET} cluster(s).\n")

    committed = []
    skipped_hunk_ids = set()

    for idx, cluster in enumerate(clusters, 1):
        display_cluster(cluster, hunk_by_id, idx, len(clusters))

        action = ask_question(
            "Stage and commit this cluster? (y=yes, n=skip, e=edit hunks, q=quit)", "y"
        )

        if action.lower() == "q":
            print("Exiting workflow.")
            break

        if action.lower() == "n":
            skipped_hunk_ids.update(cluster["hunk_ids"])
            print(f"  Skipped cluster '{cluster['title']}'.")
            continue

        if action.lower() == "e":
            edit_cluster_hunks(cluster, hunk_by_id)
            display_cluster(cluster, hunk_by_id, idx, len(clusters))
            confirm = ask_question("Stage and commit this edited cluster? (y/n)", "y")
            if confirm.lower() != "y":
                skipped_hunk_ids.update(cluster["hunk_ids"])
                print(f"  Skipped cluster '{cluster['title']}'.")
                continue

        # Stage selected hunks
        selected_hunks = [hunk_by_id[i] for i in cluster["hunk_ids"] if i in hunk_by_id]
        if not selected_hunks:
            print(f"  {Colors.YELLOW}No hunks to stage.{Colors.RESET}")
            continue

        print("  Staging hunks...")
        ok, err = stage_hunks(selected_hunks)
        if not ok:
            print(f"  {Colors.RED}Failed to stage hunks:{Colors.RESET} {err}")
            print(f"  {Colors.YELLOW}Skipping this cluster. You may need to handle these hunks manually.{Colors.RESET}")
            skipped_hunk_ids.update(cluster["hunk_ids"])
            continue

        _, staged_diff, _ = run_cmd_capture(["git", "diff", "--cached"])
        if not staged_diff.strip():
            print(f"  {Colors.YELLOW}Nothing staged (hunks may already be committed).{Colors.RESET}")
            continue

        print("  Generating commit message...")
        msg = generate_commit_message(staged_diff, model)
        print(f"\n  {Colors.CYAN}Suggested message:{Colors.RESET}\n  {msg.replace(chr(10), chr(10) + '  ')}\n")

        choice = ask_question("Use this message? (y=yes, e=edit, n=custom)", "y")
        if choice.lower() == "e":
            commit_msg = ask_question("Edit message", msg)
        elif choice.lower() == "n":
            commit_msg = ask_question("Enter commit message")
        else:
            commit_msg = msg

        if not commit_msg:
            print(f"  {Colors.YELLOW}Empty message, skipping commit.{Colors.RESET}")
            run_cmd_capture(["git", "reset"])
            skipped_hunk_ids.update(cluster["hunk_ids"])
            continue

        tmp = pathlib.Path(".git_atomic_msg")
        try:
            tmp.write_text(commit_msg, encoding="utf-8")
            rc_commit = run_cmd_interactive(["git", "commit", "-F", str(tmp)])
            if rc_commit == 0:
                short_hash = subprocess.check_output(
                    ["git", "rev-parse", "--short", "HEAD"]
                ).decode().strip()
                print(f"  {Colors.GREEN}Committed [{short_hash}] {cluster['title']}{Colors.RESET}")
                committed.append({"hash": short_hash, "title": cluster["title"]})
            else:
                print(f"  {Colors.RED}Commit failed.{Colors.RESET}")
                run_cmd_capture(["git", "reset"])
                skipped_hunk_ids.update(cluster["hunk_ids"])
        finally:
            if tmp.exists():
                tmp.unlink()

    print(f"\n{Colors.PURPLE}{Colors.BOLD}{'=' * 64}{Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}{'GIT-ATOMIC COMPLETED':^64}{Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}{'=' * 64}{Colors.RESET}\n")

    if committed:
        print(f"{Colors.BOLD}Commits made:{Colors.RESET}")
        for c in committed:
            print(f"  {Colors.GREEN}[{c['hash']}]{Colors.RESET} {c['title']}")
    else:
        print("No commits made.")

    if skipped_hunk_ids:
        skipped_files = sorted({hunk_by_id[i]["file"] for i in skipped_hunk_ids if i in hunk_by_id})
        print(f"\n{Colors.YELLOW}Skipped hunks remain in working tree:{Colors.RESET}")
        for f in skipped_files:
            print(f"  {f}")

    print()


if __name__ == "__main__":
    main()
