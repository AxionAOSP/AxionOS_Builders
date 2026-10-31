#!/bin/bash
SESSION_NAME="$1"
COMMAND="$2"
LOG_FILE="$3"
PROGRESS_FILE="$4"

EXEC_ID=$(date +%s%N | cut -b1-13)
STATE_DIR="${HOME}/.cache/axion_ci"
mkdir -p "$STATE_DIR" 2>/dev/null || STATE_DIR="/tmp"
EXIT_CODE_FILE="${STATE_DIR}/${SESSION_NAME}_${EXEC_ID}_exit"
DONE_FILE="${STATE_DIR}/${SESSION_NAME}_${EXEC_ID}_done"

cleanup() {
    tmux send-keys -t "$SESSION_NAME" C-c
    rm -f "$EXIT_CODE_FILE" "$DONE_FILE"
    exit 130
}
trap 'cleanup' SIGINT SIGTERM

# Unset outer TMUX variable so nested/sandboxed tmux uses TMUX_TMPDIR cleanly
unset TMUX
export TERM="${TERM:-xterm-256color}"
export LC_BYOBU=0
export DISABLE_BYOBU=true
if [ -n "$TMUX_TMPDIR" ]; then
    mkdir -p "$TMUX_TMPDIR" 2>/dev/null || true
fi

# Check if session already exists; create with a fresh login shell (bash -l) so all server profiles load
if ! tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    tmux new-session -d -s "$SESSION_NAME" "/bin/bash -l" || exit 1
    sleep 1
fi

if [ -n "$LOG_FILE" ]; then
    tmux pipe-pane -t "$SESSION_NAME" "cat -u >> \"$LOG_FILE\""
fi
rm -f "$EXIT_CODE_FILE" "$DONE_FILE"

TMUX_CMD="set +e; $COMMAND; echo \$? > $EXIT_CODE_FILE; touch $DONE_FILE"
tmux send-keys -t "$SESSION_NAME" "$TMUX_CMD" C-m || exit 1

while [ ! -f "$DONE_FILE" ]; do
    if ! tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
        echo "❌ tmux session '$SESSION_NAME' terminated unexpectedly."
        exit 1
    fi
    if [ -n "$PROGRESS_FILE" ]; then
        tmux capture-pane -p -S -50 -t "$SESSION_NAME" | \
        awk -v logfile="$PROGRESS_FILE" '{
            gsub(/\x1b\[[0-9;]*m/, "");
            if (match($0, /^\[\s*([0-9]+)%\s+([0-9]+\/[0-9]+)([^]]*)\]\s*(.*)/, arr) && arr[1] != "" && arr[2] != "") {
                last_line = arr[1] "," arr[2] "," arr[4];
            } else if (match($0, /Syncing:\s*([0-9]+)%\s*\(([^)]+)\)/, sarr) && sarr[1] != "" && sarr[2] != "") {
                last_line = sarr[1] "," sarr[2];
            }
        }
        END {
            if (last_line != "") {
                print last_line > logfile;
                close(logfile);
            }
        }'
    fi
    sleep 2
done

tmux pipe-pane -t "$SESSION_NAME"
EXIT_CODE=$(cat "$EXIT_CODE_FILE" 2>/dev/null || echo 1)
rm -f "$EXIT_CODE_FILE" "$DONE_FILE"
exit $EXIT_CODE
