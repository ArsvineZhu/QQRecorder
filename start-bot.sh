#!/bin/bash

# Start QQContextBot
# Usage: ./start-bot.sh

# Exit on error
set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_PATH="$SCRIPT_DIR"

# Check if directory exists
if [ ! -d "$PROJECT_PATH" ]; then
    echo "Error: Project directory not found: $PROJECT_PATH" >&2
    exit 1
fi

# Change to project directory
cd "$PROJECT_PATH" || {
    echo "Error: Failed to change directory to: $PROJECT_PATH" >&2
    exit 1
}

# Check if uv is available
if ! command -v uv &> /dev/null; then
    echo "Error: uv command not found. Please install uv first." >&2
    exit 1
fi

# Start the bot
echo -e "\033[32mStarting QQContextBot...\033[0m"
uv run ncatbot run
