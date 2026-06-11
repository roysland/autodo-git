#!/bin/bash
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

# If no changes are staged/staged, we don't need to generate a commit message
if [ -z "$DIFF" ]; then
    echo "No changes to commit"
    exit 0
fi

# Prepare prompt
prompt=$(cat <<EOF
Generate a raw text commit message for the following diff.
Keep commit message concise and to the point. Make the first line the title (100 characters or less), and the rest 
the body (if necessary). Do not include any extra information or formatting, just the raw commit message
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

# Get the generated commit message and use it to commit the changes (git commit -m "generated commit message")
git commit -m "$commit_message"


