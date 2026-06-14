#!/usr/bin/env python3
"""
Description: Generate a kebab-case branch name based on current changes and print only the string to stdout (ideal for shell piping).
"""
import os
import sys
import re
import json
import urllib.request
import subprocess
import pathlib

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
        with urllib.request.urlopen(req, timeout=40) as response:
            res_data = json.loads(response.read().decode())
            return res_data.get("response", "")
    except Exception as e:
        print(f"Error: Failed to connect to Ollama ({e})", file=sys.stderr)
        sys.exit(1)

def strip_think_and_codeblocks(text):
    text = re.sub(r"(?is)<think>.*?</think>", "", text)
    text = re.sub(r"(?is)\bThinking\b.*?\bdone thinking\b\.?", "", text)
    text = re.sub(r"(?m)^```[a-zA-Z0-9_-]*\s*$", "", text)
    text = text.replace("```json", "").replace("```", "")
    return text.strip()

def clean_branch_name(name):
    # Remove think blocks and formatting
    name = strip_think_and_codeblocks(name)
    
    # Strip quotes
    name = name.strip("'\"` \n\r\t")
    
    lines = [l.strip() for l in name.splitlines() if l.strip()]
    if not lines:
        return "feature/workspace-changes"
        
    valid_prefixes = ("feature/", "bugfix/", "refactor/", "fix/")
    
    # 1. Search for a line starting with or containing a valid prefix
    matched_line = None
    for line in lines:
        for prefix in valid_prefixes:
            if line.startswith(prefix):
                matched_line = line
                break
            elif prefix in line:
                # E.g. "Branch: feature/my-branch" -> take "feature/my-branch"
                match = re.search(r"(" + prefix + r"[\w-]+)", line)
                if match:
                    matched_line = match.group(1)
                    break
        if matched_line:
            break
            
    # 2. Search for any line with a slash
    if not matched_line:
        for line in lines:
            if "/" in line:
                match = re.search(r"([\w-]+/[\w-]+)", line)
                if match:
                    matched_line = match.group(1)
                    break

    # 3. Fallback: take the first line
    if not matched_line:
        matched_line = lines[0]
        # Force prefix if fallback doesn't have it
        if not matched_line.startswith(valid_prefixes):
            # Clean it up: keep only alphanumeric and hyphens
            clean_str = re.sub(r"[^\w\s-]", "", matched_line)
            clean_str = re.sub(r"\s+", "-", clean_str).lower()
            matched_line = f"feature/{clean_str}"
            
    # Final cleanup on the matched line
    matched_line = matched_line.lower()
    matched_line = re.sub(r"[~^:?*\[\\]", "", matched_line)
    matched_line = re.sub(r"\s+", "-", matched_line)
    matched_line = re.sub(r"-+", "-", matched_line)
    matched_line = re.sub(r"\.+", ".", matched_line)
    
    # Ensure prefix
    if not matched_line.startswith(valid_prefixes):
        matched_line = "feature/" + matched_line
        
    return matched_line


def main():
    rc, repo_root, _ = run_cmd_capture(["git", "rev-parse", "--show-toplevel"])
    if rc == 0 and repo_root:
        os.chdir(repo_root)
        
    rc_git, _, _ = run_cmd_capture(["git", "rev-parse", "--is-inside-work-tree"])
    if rc_git != 0:
        print("Error: Not in a git repository.", file=sys.stderr)
        sys.exit(1)
        
    diff_str, changed_files = get_git_diff_with_untracked()
    if not changed_files or not diff_str.strip():
        print("Error: No changes detected to generate a branch name.", file=sys.stderr)
        sys.exit(1)
        
    model = get_ollama_model()
    print(f"Using model: {model}", file=sys.stderr)
    
    max_len = 12000
    if len(diff_str) > max_len:
        diff_snippet = diff_str[:max_len] + "\n\n... [Diff truncated] ..."
    else:
        diff_snippet = diff_str
        
    prompt = f"""You are a Git assistant. Generate a descriptive, kebab-case branch name based on the following git diff.

Git Diff:
{diff_snippet}

Rules:
1. The branch name should start with 'feature/', 'fix/', 'bugfix/', or 'refactor/' followed by a descriptive kebab-case name.
2. Respond ONLY with the raw branch name string (e.g. 'feature/add-login').
3. Do not include quotes, markdown code fences, think blocks, or introductory/conversational text.
"""
    
    response = query_ollama(model, prompt)
    branch_name = clean_branch_name(response)
    
    # Output ONLY the branch name to stdout
    print(branch_name)

if __name__ == "__main__":
    main()
