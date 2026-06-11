# autodo-git — AI-Powered Git Automation Suite

`autodo-git` is a modular, AI-assisted Git workflow automation utility. It runs standalone script components to inspect, review, split, and undo git changes in your working tree using local Ollama models.

The suite is designed for:
1. **Developer context recovery** (recalling goals and next steps).
2. **Local AI security and logic code review** (gatekeeping commits).
3. **Automating branching & staging workflows**.
4. **Resuming conflict resolutions** (merge, rebase, cherry-pick help).

---

## Architecture & Design

Each script in the `scripts/` directory is designed to be **100% standalone** and **portable**, making them simple for AI agents to analyze or refactor in isolation.

The parent CLI `autodo-git` acts as:
- An **interactive TUI menu** to navigate and execute the scripts.
- A **non-interactive runner** to invoke individual tools directly (perfect for integration into other CLI utilities or IDE extensions).

---

## Commands Included

### 1. `git-suggest`
* **Purpose**: Inspects diff size, files affected, branch state, and WIP signals to suggest whether you should commit directly, create a feature branch, stash, or split your changes.
* **TUI Option / CLI**: `./autodo-git git-suggest`
* **Auto Mode**: `./autodo-git git-suggest --auto` (runs automatic branching, staging, and committing).

### 2. `git-review`
* **Purpose**: Performs a security, bug, and quality code audit on your diff locally before committing/pushing. Supports custom diff arguments.
* **CLI**: `./autodo-git git-review` or `./autodo-git git-review origin/main..HEAD`

### 3. `git-undo-suggest`
* **Purpose**: Diagnoses your workspace status (unstaged, staged, unpushed commits, pushed commits) and guides you safely through aborting merges/rebases or running resets/reverts.
* **CLI**: `./autodo-git git-undo-suggest`

### 4. `git-continue`
* **Purpose**: Resumes conflict resolutions (rebases, merges, cherry-picks) by listing conflict files, staging instructions, and popping stashes or WIP commits.
* **CLI**: `./autodo-git git-continue`

### 5. `git-intent`
* **Purpose**: Queries local LLMs (like `qwen2.5-coder`) to write a plain-English explanation of your workspace diff and predict your unfinished next steps.
* **CLI**: `./autodo-git git-intent`

### 6. `git-split`
* **Purpose**: Interactively splits a dirty working tree into multiple commits by clustering changed files semantically and generating localized commit messages.
* **CLI**: `./autodo-git git-split`

### 7. `git-branch-name`
* **Purpose**: Generates a kebab-case branch name from the current diff and prints **only** the string to `stdout` (ideal for shell piping).
* **CLI**: `git checkout -b $(autodo-git git-branch-name)`

### 8. `create-commit-message`
* **Purpose**: Stages changes, prints status, and commits with an AI-generated commit message.
* **CLI**: `./autodo-git create-commit-message`

---

## Installation

Run the provided installation script to symlink `autodo-git` into your user binaries:

```bash
chmod +x install.sh
./install.sh
```

Ensure `~/.local/bin` is in your `PATH` environment variable.

---

## Integration: Calling from other CLIs

Because `autodo-git` forwards exit codes and supports non-interactive arguments, you can easily invoke it as a subtask or daemon subprocess from Go, Rust, Node, or shell scripts.

### Non-Interactive CLI Invocation
To bypass the interactive TUI menu, pass the script name and any extra arguments directly:

```bash
autodo-git run <script-name> [args...]
# Example:
autodo-git run git-suggest --auto
```

### Exit Codes
* **`0`**: The script ran and completed successfully.
* **`1`**: General failure (connection issues, not in git repo, git command errors).
* **`130`**: Interrupted by user (Ctrl+C).
