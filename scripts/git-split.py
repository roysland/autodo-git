#!/usr/bin/env python3
"""
Description: Automatically splits a large diff into multiple commits based on semantic clusters.
"""
import os
import sys
import re
import json
import urllib.request
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

def get_untracked_files():
    rc, stdout, _ = run_cmd_capture(["git", "status", "--porcelain"])
    files = []
    if rc == 0:
        for line in stdout.splitlines():
            if line.startswith("?? "):
                files.append(line[3:])
    return files

def get_git_diff_with_untracked():
    _, diff_tracked, _ = run_cmd_capture(["git", "diff", "HEAD"])
    
    untracked = get_untracked_files()
    diff_untracked = []
    
    for f in untracked:
        try:
            path = pathlib.Path(f)
            if not path.is_file():
                continue
            if path.stat().st_size > 50000:
                diff_untracked.append(f"\nDiff too large for untracked file: {f} ({path.stat().st_size} bytes)")
                continue
            with open(f, "r", encoding="utf-8", errors="ignore") as file_handle:
                content = file_handle.read()
                if "\x00" in content:
                    diff_untracked.append(f"\nBinary untracked file: {f}")
                    continue
                
                lines = content.splitlines()
                mock_lines = [f"+{line}" for line in lines]
                diff_untracked.append(
                    f"diff --git a/{f} b/{f}\n"
                    f"new file mode 100644\n"
                    f"--- /dev/null\n"
                    f"+++ b/{f}\n"
                    f"@@ -0,0 +1,{len(lines)} @@\n"
                    + "\n".join(mock_lines)
                )
        except Exception as e:
            diff_untracked.append(f"\nError reading untracked file {f}: {e}")
            
    full_diff = diff_tracked
    if diff_untracked:
        if full_diff:
            full_diff += "\n" + "\n".join(diff_untracked)
        else:
            full_diff = "\n".join(diff_untracked)
            
    _, tracked_files_out, _ = run_cmd_capture(["git", "diff", "HEAD", "--name-only"])
    changed_files = []
    if tracked_files_out:
        changed_files = [line.strip() for line in tracked_files_out.splitlines() if line.strip()]
    
    changed_files.extend(untracked)
    changed_files = sorted(list(set(changed_files)))
    
    return full_diff, changed_files

def get_ollama_model():
    url = "http://localhost:11434/api/tags"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode())
            installed_models = [m["name"] for m in data.get("models", [])]
    except Exception:
        installed_models = []

    preferred = [
        "qwen2.5-coder:7b",
        "deepseek-coder:6.7b",
        "kimi-k2.7-code:cloud"
    ]
    
    for p in preferred:
        for m in installed_models:
            if m == p or m.startswith(p + ":") or p.startswith(m + ":"):
                return m
                
    for m in installed_models:
        if "embed" not in m:
            return m
            
    return "qwen2.5-coder:7b"

def query_ollama(model, prompt):
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1
        }
    }
    
    headers = {"Content-Type": "application/json"}
    data = json.dumps(payload).encode("utf-8")
    
    try:
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=45) as response:
            res_data = json.loads(response.read().decode())
            return res_data.get("response", "")
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

def get_semantic_clusters(diff_str, changed_files, model):
    max_len = 12000
    if len(diff_str) > max_len:
        diff_snippet = diff_str[:max_len] + f"\n\n... [Diff truncated. Total size: {len(diff_str)} chars] ..."
    else:
        diff_snippet = diff_str
        
    prompt = f"""You are a Git assistant. Analyze the changed files and the diff below, and group them into logical, semantic clusters representing separate tasks (e.g. 'Backend Database Config', 'UI Styling', 'Documentation update').

Changed files list:
{json.dumps(changed_files, indent=2)}

Git Diff:
{diff_snippet}

Please respond with a single, valid JSON object in the following format:
{{
  "clusters": [
    {{
      "title": "Short descriptive title of the task",
      "files": ["file1.py", "file2.py"],
      "explanation": "One line explanation of why these files are grouped together and what changed."
    }}
  ]
}}

Rules:
1. Ensure the JSON is completely valid and properly formatted.
2. Group files that are closely related. If all files are part of a single unified change, return a single cluster.
3. Respond ONLY with the raw JSON object. Do not output markdown code fences, think tags, or introductory text.
"""
    response = query_ollama(model, prompt)
    result = extract_json(response)
    if not result:
        result = {
            "clusters": [
                {
                    "title": "Workspace changes",
                    "files": changed_files,
                    "explanation": "Detected changes in the workspace"
                }
            ]
        }
    return result

def generate_commit_message(diff_str, files, model):
    max_len = 8000
    if len(diff_str) > max_len:
        diff_snippet = diff_str[:max_len] + f"\n\n... [Diff truncated] ..."
    else:
        diff_snippet = diff_str
        
    prompt = f"""Generate a concise, professional git commit message based on the following diff and files.

Files:
{json.dumps(files, indent=2)}

Diff:
{diff_snippet}

Return only the commit message text. No explanations, no markdown blocks, no think blocks. Keep the commit message to a short summary line (under 50 chars) and an optional description body if necessary.
"""
    response = query_ollama(model, prompt)
    response = strip_think_and_codeblocks(response)
    lines = [l.strip() for l in response.splitlines() if l.strip()]
    if lines:
        return "\n".join(lines)
    return "update: workspace changes"

def ask_question(prompt_text, default=None):
    try:
        suffix = f" [{default}]" if default else ""
        inp = input(f"{prompt_text}{suffix}: ").strip()
        if not inp and default:
            return default
        return inp
    except (KeyboardInterrupt, EOFError):
        print("\nOperation cancelled.")
        sys.exit(0)

def main():
    rc, repo_root, _ = run_cmd_capture(["git", "rev-parse", "--show-toplevel"])
    if rc == 0 and repo_root:
        os.chdir(repo_root)
        
    rc_git, _, _ = run_cmd_capture(["git", "rev-parse", "--is-inside-work-tree"])
    if rc_git != 0:
        print(f"{Colors.RED}Error: Not in a git repository.{Colors.RESET}")
        sys.exit(1)
        
    import argparse
    parser = argparse.ArgumentParser(
        description="git-split: Automatically splits a large diff into multiple commits based on semantic clusters."
    )
    parser.add_argument("--no-color", action="store_true", help="Disable colored terminal output.")
    args = parser.parse_args()

    if args.no_color:
        Colors.disable()
        
    diff_str, changed_files = get_git_diff_with_untracked()
    if not changed_files or not diff_str.strip():
        print(f"{Colors.GREEN}✓ Workspace is clean. No changes to split!{Colors.RESET}")
        sys.exit(0)
        
    print("Checking Ollama model...")
    model = get_ollama_model()
    print(f"Using model: {Colors.CYAN}{model}{Colors.RESET}")
    
    print("Calling Ollama to generate semantic clusters...")
    clusters_data = get_semantic_clusters(diff_str, changed_files, model)
    clusters = clusters_data.get("clusters", [])
    
    print(f"\n{Colors.PURPLE}{Colors.BOLD}================================================================{Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}                    GIT-SPLIT WORKFLOW                          {Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}================================================================{Colors.RESET}\n")
    
    print(f"Found {Colors.CYAN}{len(clusters)}{Colors.RESET} semantic cluster(s).\n")
    
    # Reset any staged changes first to ensure split is clean
    print("Clearing staged index to start fresh...")
    run_cmd_capture(["git", "reset"])
    
    successful_commits = []
    
    for idx, c in enumerate(clusters, 1):
        print(f"\n{Colors.BOLD}Cluster {idx}/{len(clusters)}: {Colors.CYAN}{c['title']}{Colors.RESET}")
        print(f"Explanation: {Colors.DIM}{c['explanation']}{Colors.RESET}")
        print("Files:")
        for f in c["files"]:
            print(f"  - {f}")
            
        confirm = ask_question(f"Stage and commit this cluster? (y = yes, n = skip, q = quit workflow)", "y")
        if confirm.lower() == "q":
            print("Exiting split commit workflow.")
            break
        elif confirm.lower() == "y":
            # Stage only these files
            for f in c["files"]:
                run_cmd_capture(["git", "add", f])
                    
            # Check cached diff
            _, diff_staged, _ = run_cmd_capture(["git", "diff", "--cached"])
            if not diff_staged:
                print(f"{Colors.YELLOW}No staged changes found for this cluster (already committed?){Colors.RESET}")
                continue
                
            print("Generating commit message...")
            msg = generate_commit_message(diff_staged, c["files"], model)
            print(f"\n{Colors.CYAN}Suggested commit message:{Colors.RESET}\n{msg}\n")
            
            choice = ask_question("Use this message? (y = yes, n = enter custom message, e = edit)", "y")
            if choice.lower() == "y":
                commit_msg = msg
            elif choice.lower() == "e":
                commit_msg = ask_question("Edit commit message", msg)
            else:
                commit_msg = ask_question("Enter custom commit message")
                
            if commit_msg:
                temp_file = pathlib.Path(".git_suggest_commit_msg")
                try:
                    temp_file.write_text(commit_msg)
                    rc_commit = run_cmd_interactive(["git", "commit", "-F", str(temp_file)])
                    if rc_commit == 0:
                        commit_hash = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode().strip()
                        print(f"{Colors.GREEN}Cluster committed successfully! Hash: {commit_hash}{Colors.RESET}")
                        successful_commits.append({"hash": commit_hash, "title": c["title"]})
                    else:
                        print(f"{Colors.RED}Commit failed.{Colors.RESET}")
                finally:
                    if temp_file.exists():
                        temp_file.unlink()
        else:
            print(f"Skipping cluster '{c['title']}'.")
            
    print(f"\n{Colors.PURPLE}{Colors.BOLD}================================================================{Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}                    GIT-SPLIT COMPLETED                         {Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}================================================================{Colors.RESET}\n")
    
    if successful_commits:
        print("Successful Commits:")
        for c in successful_commits:
            print(f"  [{Colors.GREEN}{c['hash']}{Colors.RESET}] - {c['title']}")
    else:
        print("No commits made.")
    print()

if __name__ == "__main__":
    main()
