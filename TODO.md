# Git Automation Tools Roadmap & TODO List

Track the implementation status and priorities of the Git helper utilities. Run commands using `autodo <command>` or `autodo run <command>`.

---

## Completed

- [x] **`git-suggest`** (Core suggestion engine)
  - *Description*: Inspects diff size, directories, branch name, remote sync state, and WIP signals to suggest the best course of action.
  - *Testing*: Run `./autodo git-suggest` (interactive TUI) or `./autodo git-suggest --auto` (auto-branch & commit).

---

## High Priority

- [x] **`git-review`** (AI Code Review)
  - *Description*: Runs local AI analysis on the current diff to inspect code quality, detect security risks/secrets, find debug leftovers, and suggest refactors.
  - *Testing*: Run `./autodo git-review` or `./autodo git-review <diff-arguments>`

- [x] **`git-undo-suggest`** (Risk-Free Git Undo)
  - *Description*: Analyzes repository state (unstaged, staged, local commits, pushed commits) and suggests the safest command to revert the last actions.
  - *Testing*: Run `./autodo git-undo-suggest`

- [ ] **`git-continue`** (Resume Conflict Resolution)
  - *Description*: Detects if you are in the middle of a rebase, merge, or cherry-pick conflict, reads the state, and tells you exactly what step to run next.
  - *Proposed Testing*: `./autodo git-continue`

---

## Medium Priority

- [ ] **`git-intent`** (Context / Goal Recovery)
  - *Description*: Queries the local LLM to describe what you were trying to accomplish with the current changes based on the diff.
  - *Proposed Testing*: `./autodo git-intent`

- [ ] **`git-split`** (Standalone Splitter)
  - *Description*: Standalone command to run the cluster-by-cluster staging and committing workflow directly from the shell.
  - *Proposed Testing*: `./autodo git-split`

- [ ] **`git-branch-name`** (Pipelineable Branch Name Generator)
  - *Description*: Generates a kebab-case branch name based on current changes and prints only the string to stdout (ideal for shell piping).
  - *Proposed Testing*: `git checkout -b $(autodo git-branch-name)`

- [ ] **`git-cleanup`** (Housekeeping Assistant)
  - *Description*: Interactively prunes merged local branches, old stashes, untracked garbage, and conflict leftover files.
  - *Proposed Testing*: `./autodo git-cleanup`

---

## Low Priority / Skipped

- [ ] **`git-scope`** (Conventional Commit Helper)
  - *Description*: Analyzes changes to suggest conventional commit scopes/types (e.g. `feat`, `fix`, `docs`).
  - *Proposed Testing*: `./autodo git-scope`
