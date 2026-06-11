#!/bin/bash
# Description: Generate AI-powered git commit messages using Ollama.
ollama_executable="ollama"
ollama_model="qwen3.5:9b"


# Figure out the current working directory, if it has a .git directory, then we are in the root of the repository
# If not, just fail and exit with "Not in a git repository" error message
if [ ! -d ".git" ]; then
    echo "Not in a git repository" >&2
    exit 1
fi

# Check if the ollama executable is installed
if ! command -v "$ollama_executable" &> /dev/null; then
    echo "Error: '$ollama_executable' is not installed or not in PATH." >&2
    exit 1
fi

# Stage all files that have been changed (git add .)
git add .

# Get diff of the staged changes, and pass it to the ollama model to generate a commit message
DIFF=$(git diff --cached)

# If no changes are staged, we don't need to generate a commit message
if [ -z "$DIFF" ]; then
    echo "No changes to commit"
    exit 0
fi

# Output the staged files
echo -e "\033[1;35mStaged files:\033[0m"
git diff --cached --name-status | sed 's/^/  /'
echo ""

# Prepare prompt
prompt=$(cat <<EOF
Briefly summarize this git diff as a git commit message. No conversational text.

$DIFF
EOF
)

# Run the ollama model with the prompt
commit_message=$("$ollama_executable" run "$ollama_model" "$prompt")

# Validate the generated commit message
if [ -z "$commit_message" ]; then
    echo "Error: Failed to generate commit message from ollama." >&2
    exit 1
fi

# Improvement: Strip thinking/reasoning chains and markdown code blocks
if command -v python3 &> /dev/null; then
    commit_message=$(echo "$commit_message" | python3 -c '
import sys, re
text = sys.stdin.read()
# Strip <think>...</think> blocks
text = re.sub(r"(?is)<think>.*?</think>", "", text)
# Strip Thinking... done thinking blocks
text = re.sub(r"(?is)\bThinking\b.*?\bdone thinking\b\.?", "", text)
# Strip markdown code block markers
text = re.sub(r"(?m)^```[a-zA-Z0-9_-]*\s*$", "", text)
print(text.strip())
')
else
    # Fallback to simple sed/awk if python3 is not present
    commit_message=$(echo "$commit_message" | sed -E '/^```[a-zA-Z0-9_-]*$/d' | sed -E 's/^```//' | sed -E 's/```$//')
    commit_message=$(echo "$commit_message" | awk 'NF {p=1} p')
fi

# Perform the commit
commit_output=$(git commit -m "$commit_message" 2>&1)
commit_status=$?

if [ $commit_status -ne 0 ]; then
    echo -e "\033[1;31mError: Commit failed.\033[0m" >&2
    echo "$commit_output" >&2
    exit $commit_status
fi

# Get the new commit hash
commit_hash=$(git rev-parse --short HEAD)

echo -e "\033[1;32mCommit successful!\033[0m"
echo -e "\033[1;36mHash:\033[0m $commit_hash"
echo -e "\033[1;36mMessage:\033[0m\n$commit_message"


