#!/usr/bin/env bash
# Attach directly to the live AxionOS build tmux session (syncing, building, uploading)

SESSION_NAME="axion_build"

if ! TMUX= tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "⏳ Waiting for live '$SESSION_NAME' session to start (Ctrl+C to cancel)..."
    while ! TMUX= tmux has-session -t "$SESSION_NAME" 2>/dev/null; do
        sleep 1
    done
fi

TMUX= exec tmux attach-session -t "$SESSION_NAME"
