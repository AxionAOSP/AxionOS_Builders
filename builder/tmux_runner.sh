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

# Define Marker files early for trap safety
EXIT_CODE_FILE="/tmp/${SESSION_NAME}_exit"
DONE_FILE="/tmp/${SESSION_NAME}_done"

# --- SIGNAL TRAP (AUTO KILL) ---
# If this script (the runner) is killed by GitHub Actions (Cancel),
# we must ensure the background tmux session is also killed.
cleanup_trap() {
    echo "[TMUX] Signal received (Cancelled). Killing session: $SESSION_NAME"
    tmux kill-session -t "$SESSION_NAME" 2>/dev/null
    rm -f "$EXIT_CODE_FILE" "$DONE_FILE"
    exit 130
}
trap 'cleanup_trap' SIGINT SIGTERM

# Ensure no previous session exists
tmux kill-session -t "$SESSION_NAME" 2>/dev/null

# Create new detached session
echo "[TMUX] Creating session: $SESSION_NAME"
tmux new-session -d -s "$SESSION_NAME"

# Clean markers
rm -f "$EXIT_CODE_FILE" "$DONE_FILE"

# Prepare the command with environment variables:
# 1. Export variables
# 2. Run command
# 3. Save exit code
# 4. Touch done file
ENV_VARS=(
    "AOSP_MANIFEST_URL" "AOSP_MANIFEST_BRANCH" "DEVICE" "RELEASETYPE" 
    "INSTALLCLEAN" "FULLCLEAN" "GMS_VARIANT" "FSGEN" 
    "WORKSPACE" "GITHUB_REPO_NAME" "GITHUB_TOKEN" "AOSP_SOURCE_DIR"
)

ENV_EXPORT=""
for var in "${ENV_VARS[@]}"; do
    # Get value of variable by name
    val="${!var}"
    # Append to export string, escaping double quotes in value
    ENV_EXPORT+="export $var=\"${val//\"/\\\"}\"; "
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
            
            # Match: [ 1% 10/1000] Description...
            match($0, /^\[\s*([0-9]+)% ([0-9]+\/[0-9]+)([^]]*)\] (.*)/, arr);
            
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
echo "[TMUX] Process finished with exit code: $EXIT_CODE. Killing session."
tmux kill-session -t "$SESSION_NAME"
rm -f "$EXIT_CODE_FILE" "$DONE_FILE"

# Return the exit code to the caller (GitHub Actions)
exit $EXIT_CODE
