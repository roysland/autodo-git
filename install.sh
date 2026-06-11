#!/bin/bash
set -e

# Target directory
BIN_DIR="$HOME/.local/bin"
AUTODO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_PATH="$AUTODO_ROOT/autodo-git"
TARGET_PATH="$BIN_DIR/autodo-git"

echo -e "\033[1;35mInstalling autodo-git...\033[0m"

# Ensure bin directory exists
if [ ! -d "$BIN_DIR" ]; then
    echo "Creating directory $BIN_DIR..."
    mkdir -p "$BIN_DIR"
fi

# Ensure source file is executable
chmod +x "$SOURCE_PATH"

# Create symlink
if [ -f "$TARGET_PATH" ] || [ -L "$TARGET_PATH" ]; then
    echo "Removing existing symlink or file at $TARGET_PATH..."
    rm "$TARGET_PATH"
fi

echo "Creating symlink from $SOURCE_PATH to $TARGET_PATH..."
ln -s "$SOURCE_PATH" "$TARGET_PATH"

echo -e "\n\033[1;32mInstallation successful!\033[0m"

# Check if BIN_DIR is in PATH
if [[ ":$PATH:" == *":$BIN_DIR:"* ]]; then
    echo -e "You can now run \033[1;36mautodo-git\033[0m from any terminal directory!"
else
    echo -e "\033[1;33mWarning:\033[0m $BIN_DIR is not in your PATH."
    echo "Please add the following line to your shell configuration file (e.g. ~/.bashrc, ~/.zshrc):"
    echo -e "\n    export PATH=\"\$HOME/.local/bin:\$PATH\"\n"
fi
