#!/bin/bash
# Development environment setup script

echo "Setting up development environment..."

# Use default .venv directory
echo "Using default .venv directory"

# Sync dependencies
echo "Syncing dependencies..."
uv sync --dev

if [ $? -eq 0 ]; then
    echo "✅ Environment setup complete!"
    echo ""
    echo "Virtual environment: .venv"
    echo "To run the application: uv run tag-db"
    echo "To run tests: uv run pytest"
else
    echo "❌ Setup failed!"
    exit 1
fi
