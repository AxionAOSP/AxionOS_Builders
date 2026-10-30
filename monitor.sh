#!/usr/bin/env bash
# Attach directly to the live AxionOS build tmux session (syncing, building, uploading)

TMUX_DIR="${TMUX_TMPDIR:-$HOME/.tmux_tmp}"
SESSION_NAME="axion_build"

if ! TMUX= TMUX_TMPDIR="$TMUX_DIR" tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "⏳ Waiting for live '$SESSION_NAME' session to start (Ctrl+C to cancel)..."
    while ! TMUX= TMUX_TMPDIR="$TMUX_DIR" tmux has-session -t "$SESSION_NAME" 2>/dev/null; do
        sleep 1
    done
fi

TMUX= TMUX_TMPDIR="$TMUX_DIR" exec tmux attach-session -t "$SESSION_NAME"
