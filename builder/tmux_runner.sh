#!/bin/bash

# Arguments:
# 1: Session Name
# 2: Command to run
# 3: Log File Path
# 4: Progress File Path (Optional)

SESSION_NAME="$1"
COMMAND="$2"
LOG_FILE="$3"
PROGRESS_FILE="$4"

# Create a unique ID for this specific execution to avoid marker clashes
EXEC_ID=$(date +%s%N | cut -b1-13)
EXIT_CODE_FILE="/tmp/${SESSION_NAME}_${EXEC_ID}_exit"
DONE_FILE="/tmp/${SESSION_NAME}_${EXEC_ID}_done"

# --- SIGNAL TRAP (AUTO KILL) ---
cleanup_trap() {
    echo "[TMUX] Signal received (Cancelled). Marker: $EXEC_ID"
    # We DON'T kill the session anymore to allow user to stay attached, 
    # but we send a Ctrl+C to stop the current command.
    tmux send-keys -t "$SESSION_NAME" C-c
    rm -f "$EXIT_CODE_FILE" "$DONE_FILE"
    exit 130
}
trap 'cleanup_trap' SIGINT SIGTERM

# Ensure session exists
if ! tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "[TMUX] Creating new session: $SESSION_NAME"
    tmux new-session -d -s "$SESSION_NAME"
else
    echo "[TMUX] Reusing existing session: $SESSION_NAME"
    # Optional: Clear the screen for a fresh look
    tmux send-keys -t "$SESSION_NAME" "clear" C-m
fi

# Clean markers for this execution
rm -f "$EXIT_CODE_FILE" "$DONE_FILE"

# Prepare the command with environment variables:
# 1. Export variables
# 2. Run command
# 3. Save exit code
# 4. Touch done file
ENV_VARS=(
    "AOSP_MANIFEST_URL" "AOSP_MANIFEST_BRANCH" "DEVICE" "RELEASETYPE" 
    "FULLCLEAN" "GMS_VARIANT" 
    "WORKSPACE" "GITHUB_REPO_NAME" "GITHUB_TOKEN" "AOSP_SOURCE_DIR"
)

ENV_EXPORT=""
for var in "${ENV_VARS[@]}"; do
    # Get value of variable by name
    val="${!var}"
    if [ -n "$val" ]; then
        # Append to export string, escaping double quotes in value
        ENV_EXPORT+="export $var=\"${val//\"/\\\"}\"; "
    fi
done

TMUX_CMD="set +e; $ENV_EXPORT $COMMAND; echo \$? > $EXIT_CODE_FILE; touch $DONE_FILE"

# Send command to tmux
tmux send-keys -t "$SESSION_NAME" "$TMUX_CMD" C-m

echo "[TMUX] Command sent. Monitoring output..."

# Monitoring Loop
while [ ! -f "$DONE_FILE" ]; do
    # 1. Capture Pane to Log File (Preserve ANSI colors for potential future use, or strip if needed)
    # Using -e to include escape sequences (colors), -J to join wrapped lines
    tmux capture-pane -p -e -J -t "$SESSION_NAME" > "$LOG_FILE"

    # 2. Progress Parsing (If Progress File provided)
    # We parse the LAST few lines of the captured log to update progress
    if [ -n "$PROGRESS_FILE" ]; then
        tail -n 20 "$LOG_FILE" 2>/dev/null | \
        awk -v logfile="$PROGRESS_FILE" '{ 
            # Remove ANSI colors for parsing
            gsub(/\x1b\[[0-9;]*m/, "");
            
            # Match: [ 1% 10/1000] Description... (Handle variable whitespace)
            match($0, /^\[\s*([0-9]+)%\s+([0-9]+\/[0-9]+)([^]]*)\]\s*(.*)/, arr);
            
            if (arr[1] != "" && arr[2] != "") {
                 print arr[1] "," arr[2] "," arr[4] > logfile;
                 fflush(logfile);
            }
        }'
    fi

    sleep 3
done

# Final Capture to ensure we have everything
tmux capture-pane -p -e -J -t "$SESSION_NAME" > "$LOG_FILE"

# Retrieve Exit Code
EXIT_CODE=0
if [ -f "$EXIT_CODE_FILE" ]; then
    EXIT_CODE=$(cat "$EXIT_CODE_FILE")
else
    echo "Warning: Exit code file not found. Assuming failure."
    EXIT_CODE=1
fi

# Cleanup
echo "[TMUX] Process finished with exit code: $EXIT_CODE. Marker: $EXEC_ID"
rm -f "$EXIT_CODE_FILE" "$DONE_FILE"

# Return the exit code to the caller (GitHub Actions)
exit $EXIT_CODE
