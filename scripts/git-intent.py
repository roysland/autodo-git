#!/usr/bin/env python3
"""
Description: AI-powered context recovery. Explains your current workspace changes in plain English and guesses your next steps.
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
        "qwen3.5:9b",
        "llama3.2:3b",
        "phi4-mini:latest",
        "smollm2:1.7b",
        "phi3:3.8b"
    ]
    
    for p in preferred:
        for m in installed_models:
            if m == p or m.startswith(p + ":") or p.startswith(m + ":"):
                return m
                
    for m in installed_models:
        if "embed" not in m:
            return m
            
    return "qwen3.5:9b"

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

def format_markdown(text):
    c_header = Colors.CYAN + Colors.BOLD
    c_bold = Colors.BOLD
    c_reset = Colors.RESET
    
    # Parse headers
    text = re.sub(r"^# (.*)", f"{Colors.PURPLE}{Colors.BOLD}\\1{c_reset}", text, flags=re.MULTILINE)
    text = re.sub(r"^## (.*)", f"{c_header}\\1{c_reset}", text, flags=re.MULTILINE)
    text = re.sub(r"^### (.*)", f"{Colors.YELLOW}{Colors.BOLD}\\1{c_reset}", text, flags=re.MULTILINE)
    
    # Bold text **text**
    text = re.sub(r"\*\*(.*?)\*\*", f"{c_bold}\\1{c_reset}", text)
    
    # Bullet points
    text = re.sub(r"^[-*] (.*)", f"  • \\1", text, flags=re.MULTILINE)
    
    return text

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
        description="git-intent: Explain what you were trying to do with local changes."
    )
    parser.add_argument("--no-color", action="store_true", help="Disable colored terminal output.")
    args = parser.parse_args()

    if args.no_color:
        Colors.disable()
        
    diff_str, changed_files = get_git_diff_with_untracked()
    if not changed_files or not diff_str.strip():
        print(f"{Colors.GREEN}✓ Workspace is clean. No changes to explain!{Colors.RESET}")
        sys.exit(0)
        
    print("Checking Ollama model...")
    model = get_ollama_model()
    print(f"Using model: {Colors.CYAN}{model}{Colors.RESET}")
    print("Analyzing workspace changes and extracting intent (this may take a moment)...")
    
    max_len = 15000
    if len(diff_str) > max_len:
        diff_snippet = diff_str[:max_len] + "\n\n... [Diff truncated. Total size: {len(diff_str)} chars] ..."
    else:
        diff_snippet = diff_str
        
    prompt = f"""You are a senior developer helping another developer recall what they were working on. 
Analyze the following git diff of their current work-in-progress modifications (which may be unstaged, staged, or untracked).

Git Diff:
{diff_snippet}

Please explain the developer's intent and goals in plain, friendly English. Structure your response into the following sections:
## Goal Summary
A short 2-3 sentence summary explaining the high-level intent/purpose of these changes.

## Key Changes
Bullet points explaining what was changed in each major file/area and why.

## Next Steps (Guesses)
What tasks seem unfinished or what should the developer work on next to complete this feature/fix? (e.g. missing tests, unfinished files, schema changes, etc.).

Format your output in clean Markdown. Do not include markdown code block markers for the whole response, think blocks, or introductory greetings. Just print the sections.
"""
    
    response = query_ollama(model, prompt)
    response = strip_think_and_codeblocks(response)
    
    print(f"\n{Colors.PURPLE}{Colors.BOLD}================================================================{Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}                    GIT-INTENT ANALYSIS                         {Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}================================================================{Colors.RESET}\n")
    
    print(format_markdown(response))
    
    print(f"\n{Colors.PURPLE}{Colors.BOLD}================================================================{Colors.RESET}\n")

if __name__ == "__main__":
    main()
