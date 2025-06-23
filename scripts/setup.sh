#!/bin/bash
# クロスプラットフォーム環境セットアップスクリプト

echo "Setting up development environment..."

# OS判別と環境変数設定
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    export UV_PROJECT_ENVIRONMENT=.venv_linux
    echo "Detected Linux environment - using .venv_linux"
elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    export UV_PROJECT_ENVIRONMENT=.venv_windows
    echo "Detected Windows environment - using .venv_windows"
else
    echo "Unknown OS type: $OSTYPE - using default .venv"
fi

echo "UV_PROJECT_ENVIRONMENT = $UV_PROJECT_ENVIRONMENT"

# 依存関係の同期
echo "Syncing dependencies..."
uv sync --dev

if [ $? -eq 0 ]; then
    echo "Environment setup complete!"
    echo "To run the application: uv run tag-db"
else
    echo "Setup failed!"
    exit 1
fi