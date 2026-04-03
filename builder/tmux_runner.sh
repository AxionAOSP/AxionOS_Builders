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
    tmux send-keys -t "$SESSION_NAME" "clear" C-m
fi

# --- PERFORMANCE OPTIMIZATION: LOG STREAMING ---
# Instead of capturing the whole pane every 3s (High I/O), we pipe the output directly to the log file.
# We use 'cat -u' for unbuffered output to the log file.
tmux pipe-pane -t "$SESSION_NAME" "cat -u >> \"$LOG_FILE\""

# Clean markers for this execution
rm -f "$EXIT_CODE_FILE" "$DONE_FILE"

# ... (Env Var preparation remains the same) ...
TMUX_CMD="set +e; $ENV_EXPORT $COMMAND; echo \$? > $EXIT_CODE_FILE; touch $DONE_FILE"

# Send command to tmux
tmux send-keys -t "$SESSION_NAME" "$TMUX_CMD" C-m

echo "[TMUX] Command sent. Streaming logs to $LOG_FILE..."

# Monitoring Loop (Reduced I/O)
while [ ! -f "$DONE_FILE" ]; do
    # Only capture the LAST 50 lines for progress parsing (Saves CPU/Disk)
    if [ -n "$PROGRESS_FILE" ]; then
        tmux capture-pane -p -S -50 -t "$SESSION_NAME" | \
        awk -v logfile="$PROGRESS_FILE" '{ 
            gsub(/\x1b\[[0-9;]*m/, "");
            match($0, /^\[\s*([0-9]+)%\s+([0-9]+\/[0-9]+)([^]]*)\]\s*(.*)/, arr);
            if (arr[1] != "" && arr[2] != "") {
                 print arr[1] "," arr[2] "," arr[4] > logfile;
                 fflush(logfile);
            }
        }'
    fi
    sleep 5 # Increased sleep for performance
done

# Stop piping when done
tmux pipe-pane -t "$SESSION_NAME"

# Retrieve Exit Code
# ... (rest of cleanup remains same) ...

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
