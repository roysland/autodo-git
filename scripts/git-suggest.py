#!/usr/bin/env python3
"""
Description: Analyze git workspace changes and suggest/perform actions (commit, branch, stash, split).
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

def get_git_status():
    # Check if in a git repo
    rc, _, _ = run_cmd_capture(["git", "rev-parse", "--is-inside-work-tree"])
    if rc != 0:
        print(f"{Colors.RED}Error: Not in a git repository.{Colors.RESET}")
        sys.exit(1)
        
    # Get current branch
    rc, branch, _ = run_cmd_capture(["git", "branch", "--show-current"])
    if not branch:
        # Detached HEAD?
        rc, branch, _ = run_cmd_capture(["git", "rev-parse", "--short", "HEAD"])
        branch = f"detached-HEAD-({branch})"
        
    # Check upstream
    rc, upstream, _ = run_cmd_capture(["git", "rev-parse", "--abbrev-ref", "@{u}"])
    ahead = 0
    behind = 0
    if rc == 0 and upstream:
        # Count ahead/behind
        _, ahead_str, _ = run_cmd_capture(["git", "rev-list", "--count", f"{upstream}..HEAD"])
        _, behind_str, _ = run_cmd_capture(["git", "rev-list", "--count", f"HEAD..{upstream}"])
        try:
            ahead = int(ahead_str)
        except ValueError:
            pass
        try:
            behind = int(behind_str)
        except ValueError:
            pass
    else:
        upstream = None
        
    return {
        "branch": branch,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind
    }

def get_untracked_files():
    rc, stdout, _ = run_cmd_capture(["git", "status", "--porcelain"])
    files = []
    if rc == 0:
        for line in stdout.splitlines():
            if line.startswith("?? "):
                files.append(line[3:])
    return files

def get_git_diff_with_untracked():
    # Tracked diff
    _, diff_tracked, _ = run_cmd_capture(["git", "diff", "HEAD"])
    
    untracked = get_untracked_files()
    diff_untracked = []
    
    for f in untracked:
        try:
            path = pathlib.Path(f)
            if not path.is_file():
                continue
            # Skip large files
            if path.stat().st_size > 50000:
                diff_untracked.append(f"\nDiff too large for untracked file: {f} ({path.stat().st_size} bytes)")
                continue
            # Try reading
            with open(f, "r", encoding="utf-8", errors="ignore") as file_handle:
                content = file_handle.read()
                # Simple check for binary content
                if "\x00" in content:
                    diff_untracked.append(f"\nBinary untracked file: {f}")
                    continue
                
                # Mock diff format
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
            
    # Also get list of changed files
    # Tracked changed files:
    _, tracked_files_out, _ = run_cmd_capture(["git", "diff", "HEAD", "--name-only"])
    changed_files = []
    if tracked_files_out:
        changed_files = [line.strip() for line in tracked_files_out.splitlines() if line.strip()]
    
    # Add untracked files
    changed_files.extend(untracked)
    # Deduplicate and sort
    changed_files = sorted(list(set(changed_files)))
    
    return full_diff, changed_files

def analyze_metrics(diff_str, changed_files):
    # Diff size
    added_lines = 0
    removed_lines = 0
    for line in diff_str.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added_lines += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed_lines += 1
            
    # File spread (directories)
    dirs = set()
    for f in changed_files:
        p = pathlib.Path(f)
        if len(p.parts) > 1:
            dirs.add(str(pathlib.Path(*p.parts[:-1])))
        else:
            dirs.add(".")
            
    # WIP signals
    wip_signals = {}
    keywords = {
        "TODO": ["TODO", "FIXME", "XXX"],
        "DEBUG": ["console.log", "print(", "debugger", "pdb.set_trace", "fmt.Println"]
    }
    
    current_file = "unknown"
    for line in diff_str.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
            continue
        if line.startswith("+") and not line.startswith("+++"):
            added_content = line[1:].strip()
            # Check keywords
            for category, words in keywords.items():
                for word in words:
                    if word in added_content:
                        if category not in wip_signals:
                            wip_signals[category] = []
                        wip_signals[category].append((current_file, added_content))
                        
    return {
        "added_lines": added_lines,
        "removed_lines": removed_lines,
        "directories": sorted(list(dirs)),
        "wip_signals": wip_signals
    }

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
        return ""

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
  ],
  "suggested_branch_name": "feature/short-kebab-case-name"
}}

Rules:
1. Ensure the JSON is completely valid and properly formatted.
2. Group files that are closely related. If all files are part of a single unified change, return a single cluster.
3. The "suggested_branch_name" should start with "feature/" or "bugfix/" or "refactor/" followed by a descriptive kebab-case name.
4. Respond ONLY with the raw JSON object. Do not output markdown code fences, think tags, or introductory text.
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
            ],
            "suggested_branch_name": "feature/workspace-changes"
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

def make_recommendations(status, metrics, clusters_data):
    recommendations = []
    actions = []
    
    branch = status["branch"]
    is_main = branch in ["main", "master"]
    
    added = metrics["added_lines"]
    removed = metrics["removed_lines"]
    total_lines = added + removed
    
    if is_main:
        recommendations.append(
            f"You are on {Colors.YELLOW}{branch}{Colors.RESET}. Committing directly to main is not recommended."
        )
        actions.append("branch")
    
    if total_lines > 150:
        recommendations.append(
            f"Large diff size ({Colors.YELLOW}{total_lines} lines{Colors.RESET}). Consider creating a feature branch."
        )
        if "branch" not in actions:
            actions.append("branch")
    elif total_lines > 0 and total_lines < 40 and not is_main:
        recommendations.append(
            f"Small fix ({Colors.GREEN}{total_lines} lines{Colors.RESET}) on a feature branch. Recommend direct commit."
        )
        actions.append("commit")
        
    clusters = clusters_data.get("clusters", [])
    if len(clusters) > 1:
        recommendations.append(
            f"Changes touch multiple unrelated areas ({Colors.YELLOW}{len(clusters)} semantic clusters{Colors.RESET}). "
            "Consider splitting into separate commits."
        )
        actions.append("split")
    
    if status["behind"] > 0:
        recommendations.append(
            f"Your branch is behind the remote upstream by {Colors.YELLOW}{status['behind']} commit(s){Colors.RESET}. "
            "Recommend rebasing/merging."
        )
        actions.append("rebase")
    if status["ahead"] > 0:
        recommendations.append(
            f"You have {Colors.GREEN}{status['ahead']} unpushed commit(s){Colors.RESET} on this branch. Suggest pushing."
        )
        actions.append("push")
        
    if not actions:
        if is_main:
            actions.append("branch")
        else:
            actions.append("commit")
            
    return recommendations, actions

def print_dashboard(status, metrics, clusters_data, recommendations, model_name):
    print(f"\n{Colors.PURPLE}{Colors.BOLD}================================================================{Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}                    GIT-SUGGEST REPORT                          {Colors.RESET}")
    print(f"{Colors.PURPLE}{Colors.BOLD}================================================================{Colors.RESET}\n")
    
    branch_info = f"Branch: {Colors.CYAN}{Colors.BOLD}{status['branch']}{Colors.RESET}"
    if status["upstream"]:
        branch_info += f"  (tracking {Colors.CYAN}{status['upstream']}{Colors.RESET})"
    print(branch_info)
    
    if status["ahead"] > 0 or status["behind"] > 0:
        status_line = []
        if status["ahead"] > 0:
            status_line.append(f"{Colors.GREEN}Ahead by {status['ahead']} commit(s){Colors.RESET}")
        if status["behind"] > 0:
            status_line.append(f"{Colors.YELLOW}Behind by {status['behind']} commit(s){Colors.RESET}")
        print(f"Status: {', '.join(status_line)}")
    else:
        print(f"Status: {Colors.GREEN}Up to date with remote{Colors.RESET}")
        
    added = metrics["added_lines"]
    removed = metrics["removed_lines"]
    total = added + removed
    print(f"Diff Size: {Colors.BOLD}{total}{Colors.RESET} lines changed "
          f"({Colors.GREEN}+{added}{Colors.RESET} / {Colors.RED}-{removed}{Colors.RESET})")
    print(f"File Spread: {Colors.BOLD}{len(metrics['directories'])}{Colors.RESET} directories affected")
    
    wip = metrics["wip_signals"]
    if wip:
        print(f"\n{Colors.YELLOW}{Colors.BOLD}⚠️  Work-In-Progress Signals Detected:{Colors.RESET}")
        for category, items in wip.items():
            print(f"  • {Colors.BOLD}{category}:{Colors.RESET}")
            for f, content in items[:3]:
                trunc_content = content[:60] + "..." if len(content) > 60 else content
                print(f"    - {Colors.CYAN}{f}{Colors.RESET}: {Colors.DIM}{trunc_content}{Colors.RESET}")
            if len(items) > 3:
                print(f"    - ... and {len(items) - 3} more occurrences")
                
    print(f"\n{Colors.CYAN}{Colors.BOLD}🤖 Semantic Clusters (Model: {model_name}):{Colors.RESET}")
    clusters = clusters_data.get("clusters", [])
    for idx, c in enumerate(clusters, 1):
        print(f"  {Colors.BOLD}{idx}. {c['title']}{Colors.RESET}")
        print(f"     Explanation: {Colors.DIM}{c['explanation']}{Colors.RESET}")
        print(f"     Files:")
        for f in c["files"]:
            print(f"       - {Colors.CYAN}{f}{Colors.RESET}")
            
    suggested_branch = clusters_data.get("suggested_branch_name", "feature/new-changes")
    print(f"\n{Colors.PURPLE}{Colors.BOLD}💡 Suggested Branch Name:{Colors.RESET} {suggested_branch}")
            
    print(f"\n{Colors.GREEN}{Colors.BOLD}📋 Recommendations:{Colors.RESET}")
    for rec in recommendations:
        print(f"  • {rec}")
    print(f"\n{Colors.PURPLE}{Colors.BOLD}================================================================{Colors.RESET}\n")

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

def choose_option(options, prompt_text):
    print(prompt_text)
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

def action_commit(model, status, changed_files, diff_str):
    rc, staged, _ = run_cmd_capture(["git", "diff", "--cached", "--name-only"])
    if not staged:
        confirm = ask_question("No changes are staged. Stage all changes now? (y/n)", "y")
        if confirm.lower() == "y":
            run_cmd_capture(["git", "add", "."])
            print(f"{Colors.GREEN}Staged all changes.{Colors.RESET}")
            _, diff_str, _ = run_cmd_capture(["git", "diff", "--cached"])
        else:
            print(f"{Colors.YELLOW}Cancelled commit since changes are not staged.{Colors.RESET}")
            return
            
    print(f"Generating commit message using LLM...")
    msg = generate_commit_message(diff_str, changed_files, model)
    print(f"\n{Colors.CYAN}Suggested commit message:{Colors.RESET}\n{msg}\n")
    
    choice = ask_question("Use this message? (y = yes, n = enter custom message, e = edit suggested)", "y")
    if choice.lower() == "y":
        commit_msg = msg
    elif choice.lower() == "e":
        commit_msg = ask_question("Edit commit message", msg)
    else:
        commit_msg = ask_question("Enter custom commit message")
        
    if not commit_msg:
        print(f"{Colors.RED}Commit message cannot be empty.{Colors.RESET}")
        return
        
    temp_file = pathlib.Path(".git_suggest_commit_msg")
    try:
        temp_file.write_text(commit_msg)
        rc = run_cmd_interactive(["git", "commit", "-F", str(temp_file)])
        if rc == 0:
            print(f"\n{Colors.GREEN}Successfully committed!{Colors.RESET}")
        else:
            print(f"\n{Colors.RED}Commit failed.{Colors.RESET}")
    finally:
        if temp_file.exists():
            temp_file.unlink()

def action_create_branch_and_commit(model, suggested_branch, changed_files, diff_str):
    branch_name = ask_question("Enter name for the new branch", suggested_branch)
    if not branch_name:
        print(f"{Colors.RED}Branch name cannot be empty.{Colors.RESET}")
        return
        
    print(f"Creating and checking out branch '{branch_name}'...")
    rc, _, stderr = run_cmd_capture(["git", "checkout", "-b", branch_name])
    if rc != 0:
        print(f"{Colors.RED}Failed to create branch: {stderr}{Colors.RESET}")
        return
        
    print(f"{Colors.GREEN}Switched to branch '{branch_name}'.{Colors.RESET}")
    action_commit(model, {"branch": branch_name}, changed_files, diff_str)

def action_split_changes(model, clusters):
    print(f"\n{Colors.CYAN}Starting split commit workflow...{Colors.RESET}")
    run_cmd_capture(["git", "reset"])
    
    for idx, c in enumerate(clusters, 1):
        print(f"\n{Colors.BOLD}Cluster {idx}/{len(clusters)}: {c['title']}{Colors.RESET}")
        print(f"Description: {Colors.DIM}{c['explanation']}{Colors.RESET}")
        print("Files:")
        for f in c["files"]:
            print(f"  - {f}")
            
        confirm = ask_question(f"Commit this cluster? (y = yes, n = skip, q = quit workflow)", "y")
        if confirm.lower() == "q":
            print("Exiting split commit workflow.")
            break
        elif confirm.lower() == "y":
            for f in c["files"]:
                run_cmd_capture(["git", "add", f])
                    
            _, diff_staged, _ = run_cmd_capture(["git", "diff", "--cached"])
            if not diff_staged:
                print(f"{Colors.YELLOW}No changes found for files in this cluster (perhaps already committed?){Colors.RESET}")
                continue
                
            print("Generating commit message for cluster...")
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
                    rc = run_cmd_interactive(["git", "commit", "-F", str(temp_file)])
                    if rc == 0:
                        print(f"{Colors.GREEN}Cluster committed successfully!{Colors.RESET}")
                    else:
                        print(f"{Colors.RED}Commit failed.{Colors.RESET}")
                finally:
                    if temp_file.exists():
                        temp_file.unlink()
        else:
            print(f"Skipping cluster '{c['title']}'.")
            
    print(f"\n{Colors.GREEN}Split commit workflow completed.{Colors.RESET}")

def action_stash():
    print("Stashing changes...")
    rc = run_cmd_interactive(["git", "stash"])
    if rc == 0:
        print(f"{Colors.GREEN}Changes stashed successfully.{Colors.RESET}")
    else:
        print(f"{Colors.RED}Failed to stash changes.{Colors.RESET}")

def action_push(status):
    print("Pushing commits to remote...")
    rc, stdout, stderr = run_cmd_capture(["git", "push"])
    if rc == 0:
        print(f"{Colors.GREEN}Pushed successfully.{Colors.RESET}")
    else:
        if "no upstream branch" in stderr or "has no upstream branch" in stderr:
            confirm = ask_question(f"No upstream branch set. Push and set upstream to origin/{status['branch']}? (y/n)", "y")
            if confirm.lower() == "y":
                run_cmd_interactive(["git", "push", "--set-upstream", "origin", status["branch"]])
        else:
            print(f"{Colors.RED}Push failed: {stderr}{Colors.RESET}")

def action_rebase_merge():
    rc_main, _, _ = run_cmd_capture(["git", "show-ref", "--verify", "refs/heads/main"])
    default_branch = "main" if rc_main == 0 else "master"
    
    choice = choose_option(
        [
            f"Git pull (fetch and merge from remote upstream)",
            f"Git pull --rebase (rebase current branch on upstream remote)",
            f"Git merge {default_branch} (merge local main/master into current branch)",
            f"Git rebase {default_branch} (rebase current branch on local main/master)",
            "Back"
        ],
        "Select integration strategy:"
    )
    if choice == 0:
        run_cmd_interactive(["git", "pull"])
    elif choice == 1:
        run_cmd_interactive(["git", "pull", "--rebase"])
    elif choice == 2:
        run_cmd_interactive(["git", "merge", default_branch])
    elif choice == 3:
        run_cmd_interactive(["git", "rebase", default_branch])

def run_auto_mode(model):
    status = get_git_status()
    diff_str, changed_files = get_git_diff_with_untracked()
    
    if not changed_files:
        if status["ahead"] > 0:
            print(f"{Colors.GREEN}No local changes, but you have {status['ahead']} unpushed commit(s).{Colors.RESET}")
            print("Pushing commits automatically...")
            run_cmd_interactive(["git", "push"])
        else:
            print(f"{Colors.GREEN}Workspace is clean. Nothing to do.{Colors.RESET}")
        return
        
    print("Analyzing changes for auto-actions...")
    clusters_data = get_semantic_clusters(diff_str, changed_files, model)
    suggested_branch = clusters_data.get("suggested_branch_name", "feature/auto-changes")
    
    branch = status["branch"]
    is_main = branch in ["main", "master"]
    
    target_branch = branch
    if is_main:
        print(f"{Colors.YELLOW}Warning: You are on main/master. Auto-creating branch '{suggested_branch}'...{Colors.RESET}")
        rc, _, stderr = run_cmd_capture(["git", "checkout", "-b", suggested_branch])
        if rc != 0:
            print(f"{Colors.RED}Failed to create branch: {stderr}. Aborting auto-commit.{Colors.RESET}")
            sys.exit(1)
        target_branch = suggested_branch
        
    print("Staging all changes...")
    run_cmd_capture(["git", "add", "."])
    
    _, staged_diff, _ = run_cmd_capture(["git", "diff", "--cached"])
    if not staged_diff:
        print(f"{Colors.RED}Failed to stage changes or diff is empty. Aborting.{Colors.RESET}")
        sys.exit(1)
        
    print("Generating commit message...")
    commit_msg = generate_commit_message(staged_diff, changed_files, model)
    print(f"{Colors.CYAN}Commit Message: {commit_msg}{Colors.RESET}")
    
    temp_file = pathlib.Path(".git_suggest_commit_msg")
    try:
        temp_file.write_text(commit_msg)
        rc = run_cmd_interactive(["git", "commit", "-F", str(temp_file)])
        if rc == 0:
            print(f"\n{Colors.GREEN}Successfully committed changes to '{target_branch}'!{Colors.RESET}")
        else:
            print(f"\n{Colors.RED}Commit failed.{Colors.RESET}")
    finally:
        if temp_file.exists():
            temp_file.unlink()

def main():
    rc, repo_root, _ = run_cmd_capture(["git", "rev-parse", "--show-toplevel"])
    if rc == 0 and repo_root:
        os.chdir(repo_root)
        
    import argparse
    parser = argparse.ArgumentParser(
        description="git-suggest: A tool to inspect git workspace and suggest actions."
    )
    parser.add_argument("--auto", action="store_true", help="Automatically decide, branch, and commit changes.")
    parser.add_argument("--no-color", action="store_true", help="Disable colored terminal output.")
    args = parser.parse_args()
    
    if args.no_color:
        Colors.disable()
        
    status = get_git_status()
    
    print("Checking Ollama model...")
    model = get_ollama_model()
    print(f"Using model: {Colors.CYAN}{model}{Colors.RESET}")
    
    if args.auto:
        run_auto_mode(model)
        return
        
    diff_str, changed_files = get_git_diff_with_untracked()
    
    if not changed_files:
        print(f"\n{Colors.GREEN}✓ Workspace is clean (no modified or untracked files).{Colors.RESET}")
        if status["ahead"] > 0:
            print(f"You have {Colors.GREEN}{status['ahead']}{Colors.RESET} unpushed commit(s) on branch '{status['branch']}'.")
            choice = ask_question("Would you like to push them now? (y/n)", "y")
            if choice.lower() == "y":
                action_push(status)
        else:
            print("Nothing to suggest. Workspace is up-to-date!")
        return
        
    print("Analyzing git diff and structure...")
    metrics = analyze_metrics(diff_str, changed_files)
    
    print("Calling Ollama to generate semantic clusters...")
    clusters_data = get_semantic_clusters(diff_str, changed_files, model)
    
    recs, actions = make_recommendations(status, metrics, clusters_data)
    
    print_dashboard(status, metrics, clusters_data, recs, model)
    
    while True:
        menu_options = [
            f"Commit changes directly to current branch '{status['branch']}'",
            f"Create a new branch and commit changes",
            f"Split changes (commit cluster-by-cluster)",
            "Stash changes",
            "Integration operations (Pull, Pull --rebase, Merge main, Rebase main)",
            "Push commits to remote",
            "Exit"
        ]
        
        if "split" in actions:
            menu_options[2] = f"{Colors.GREEN}{Colors.BOLD}(Recommended){Colors.RESET} " + menu_options[2]
        elif "branch" in actions:
            menu_options[1] = f"{Colors.GREEN}{Colors.BOLD}(Recommended){Colors.RESET} " + menu_options[1]
        elif "commit" in actions:
            menu_options[0] = f"{Colors.GREEN}{Colors.BOLD}(Recommended){Colors.RESET} " + menu_options[0]
            
        choice = choose_option(menu_options, "What would you like to do?")
        
        if choice == 0:
            action_commit(model, status, changed_files, diff_str)
            break
        elif choice == 1:
            suggested_branch = clusters_data.get("suggested_branch_name", "feature/new-changes")
            action_create_branch_and_commit(model, suggested_branch, changed_files, diff_str)
            break
        elif choice == 2:
            action_split_changes(model, clusters_data.get("clusters", []))
            break
        elif choice == 3:
            action_stash()
            break
        elif choice == 4:
            action_rebase_merge()
        elif choice == 5:
            action_push(status)
        elif choice == 6:
            print("Goodbye!")
            break

if __name__ == "__main__":
    main()
