#!/usr/bin/env python3
"""
Description: Perform a local AI-powered code review on your git changes before committing or pushing.
"""
import os
import sys
import re
import json
import urllib.request
import subprocess
import pathlib
import argparse

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
    BG_RED = "\033[41;37m"
    BG_YELLOW = "\033[43;30m"
    BG_BLUE = "\033[44;37m"

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
        cls.BG_RED = ""
        cls.BG_YELLOW = ""
        cls.BG_BLUE = ""

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

def get_diff_from_args(args):
    rc, stdout, stderr = run_cmd_capture(["git", "diff"] + args)
    if rc != 0:
        print(f"{Colors.RED}Error running git diff: {stderr}{Colors.RESET}")
        sys.exit(1)
        
    rc_files, files_stdout, _ = run_cmd_capture(["git", "diff", "--name-only"] + args)
    changed_files = [line.strip() for line in files_stdout.splitlines() if line.strip()]
    
    return stdout, changed_files

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
        with urllib.request.urlopen(req, timeout=60) as response:
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

def perform_ai_review(diff_str, changed_files, model):
    max_len = 15000
    if len(diff_str) > max_len:
        diff_snippet = diff_str[:max_len] + f"\n\n... [Diff truncated. Total size: {len(diff_str)} chars] ..."
    else:
        diff_snippet = diff_str
        
    prompt = f"""You are a senior software engineer and security auditor. Perform a code review on the following git changes.

Changed Files:
{json.dumps(changed_files, indent=2)}

Git Diff:
{diff_snippet}

Please respond with a single, valid JSON object in the following format:
{{
  "summary": "High-level summary of the changes.",
  "issues": [
    {{
      "file": "file_name",
      "type": "Security" (e.g. secrets, vulnerabilities) or "Bug" (logic errors, edge cases) or "Leftover" (debug logs, TODOs) or "Quality" (bad practice, perf),
      "severity": "High" or "Medium" or "Low",
      "description": "Detailed description of what is wrong.",
      "suggestion": "How to fix it."
    }}
  ],
  "refactors": [
    {{
      "file": "file_name",
      "description": "Suggested structural or readability improvement.",
      "original_code": "code snippet to replace",
      "new_code": "improved code snippet"
    }}
  ]
}}

Rules:
1. Ensure the JSON is completely valid and properly formatted.
2. Only flag real issues. If there are no security bugs, logic errors, or refactor suggestions, return empty lists.
3. Respond ONLY with the raw JSON object. Do not include markdown code fences, think blocks, or conversational text.
"""
    response = query_ollama(model, prompt)
    result = extract_json(response)
    return result

def print_review_report(report_data, model_name):
    print(f"\n{Colors.PURPLE}{Colors.BOLD}================================================================{Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}                    LOCAL AI CODE REVIEW                        {Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}================================================================{Colors.RESET}")
    print(f"Model: {Colors.CYAN}{model_name}{Colors.RESET}\n")

    # Summary
    print(f"{Colors.BOLD}Summary of Changes:{Colors.RESET}")
    print(f"  {report_data.get('summary', 'No summary provided.')}\n")

    # Issues
    issues = report_data.get("issues", [])
    if issues:
        print(f"{Colors.RED}{Colors.BOLD}⚠️  Detected Issues ({len(issues)}):{Colors.RESET}")
        for idx, issue in enumerate(issues, 1):
            severity = issue.get("severity", "Low")
            sev_color = Colors.RED if severity == "High" else (Colors.YELLOW if severity == "Medium" else Colors.BLUE)
            sev_bg = Colors.BG_RED if severity == "High" else (Colors.BG_YELLOW if severity == "Medium" else Colors.BG_BLUE)
            
            print(f"  {Colors.BOLD}{idx}. [{issue.get('type', 'General')}] {issue.get('file', 'General')}{Colors.RESET}")
            print(f"     Severity: {sev_bg} {severity} {Colors.RESET}")
            print(f"     Description: {issue.get('description', '')}")
            print(f"     Suggestion:  {Colors.GREEN}{issue.get('suggestion', '')}{Colors.RESET}\n")
    else:
        print(f"{Colors.GREEN}{Colors.BOLD}✓ No critical issues, security bugs, or leftovers detected.{Colors.RESET}\n")

    # Refactors
    refactors = report_data.get("refactors", [])
    if refactors:
        print(f"{Colors.CYAN}{Colors.BOLD}💡 Suggested Refactors ({len(refactors)}):{Colors.RESET}")
        for idx, ref in enumerate(refactors, 1):
            print(f"  {Colors.BOLD}{idx}. File: {Colors.CYAN}{ref.get('file', '')}{Colors.RESET}")
            print(f"     Description: {Colors.DIM}{ref.get('description', '')}{Colors.RESET}")
            
            orig = ref.get("original_code", "")
            new_c = ref.get("new_code", "")
            
            if orig or new_c:
                print(f"     {Colors.RED}- Original:{Colors.RESET}")
                for line in orig.splitlines():
                    print(f"       {Colors.RED}{line}{Colors.RESET}")
                print(f"     {Colors.GREEN}+ Suggested:{Colors.RESET}")
                for line in new_c.splitlines():
                    print(f"       {Colors.GREEN}{line}{Colors.RESET}")
            print()
    else:
        print(f"{Colors.GREEN}{Colors.BOLD}✓ No refactoring recommendations.{Colors.RESET}\n")

    print(f"{Colors.PURPLE}{Colors.BOLD}================================================================{Colors.RESET}\n")

def main():
    rc, repo_root, _ = run_cmd_capture(["git", "rev-parse", "--show-toplevel"])
    if rc == 0 and repo_root:
        os.chdir(repo_root)
        
    parser = argparse.ArgumentParser(
        description="git-review: Local AI code review before committing or pushing."
    )
    parser.add_argument("diff_args", nargs="*", help="Arguments to pass to git diff (e.g. HEAD~1, origin/main..HEAD).")
    parser.add_argument("--model", help="Specify Ollama model to use.")
    parser.add_argument("--no-color", action="store_true", help="Disable colored terminal output.")
    args = parser.parse_args()
    
    if args.no_color:
        Colors.disable()
        
    # Verify in Git repo
    rc, _, _ = run_cmd_capture(["git", "rev-parse", "--is-inside-work-tree"])
    if rc != 0:
        print(f"{Colors.RED}Error: Not in a git repository.{Colors.RESET}")
        sys.exit(1)
        
    # Get Diff
    if args.diff_args:
        print(f"Analyzing git diff for: {' '.join(args.diff_args)}...")
        diff_str, changed_files = get_diff_from_args(args.diff_args)
    else:
        print("Analyzing local workspace changes (staged + unstaged)...")
        diff_str, changed_files = get_git_diff_with_untracked()
        
    if not changed_files or not diff_str.strip():
        print(f"{Colors.GREEN}✓ Workspace is clean (no changes detected to review).{Colors.RESET}")
        sys.exit(0)
        
    # Select Model
    if args.model:
        model = args.model
    else:
        print("Checking Ollama model...")
        model = get_ollama_model()
    
    print(f"Using model: {Colors.CYAN}{model}{Colors.RESET}")
    print("Calling Ollama to perform AI Code Review (this may take a moment)...")
    
    report_data = perform_ai_review(diff_str, changed_files, model)
    
    if not report_data:
        print(f"{Colors.RED}Error: Failed to parse review report from Ollama response.{Colors.RESET}")
        sys.exit(1)
        
    print_review_report(report_data, model)

if __name__ == "__main__":
    main()
