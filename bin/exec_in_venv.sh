#!/bin/bash

# Ensure the script is executed with bash
if [ -z "$BASH_VERSION" ]; then
    echo "Please run this script with bash."
    exit 1
fi

# Determine the directory of the current script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Navigate to the project root (assuming this script will be in scripts/ or tests/ or similar)
# Adjust this path if the exec_in_venv.sh script is placed elsewhere
PROJECT_ROOT="$SCRIPT_DIR/.."
if [ ! -d "$PROJECT_ROOT/venv" ]; then
    # Try one level up if not found
    PROJECT_ROOT="$SCRIPT_DIR/../.."
    if [ ! -d "$PROJECT_ROOT/venv" ]; then
        echo "Error: Virtual environment 'venv' not found in project root."
        exit 1
    fi
fi

# Activate the virtual environment
source "$PROJECT_ROOT/venv/bin/activate"

# Execute the command passed to this script
exec "$@"