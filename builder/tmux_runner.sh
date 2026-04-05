#!/bin/bash
SESSION_NAME="$1"
COMMAND="$2"
LOG_FILE="$3"
PROGRESS_FILE="$4"

EXEC_ID=$(date +%s%N | cut -b1-13)
EXIT_CODE_FILE="/tmp/${SESSION_NAME}_${EXEC_ID}_exit"
DONE_FILE="/tmp/${SESSION_NAME}_${EXEC_ID}_done"

cleanup() {
    tmux send-keys -t "$SESSION_NAME" C-c
    rm -f "$EXIT_CODE_FILE" "$DONE_FILE"
    exit 130
}
trap 'cleanup' SIGINT SIGTERM

if ! tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    tmux new-session -d -s "$SESSION_NAME"
else
    tmux send-keys -t "$SESSION_NAME" "clear" C-m
fi

tmux pipe-pane -t "$SESSION_NAME" "cat -u >> \"$LOG_FILE\""
rm -f "$EXIT_CODE_FILE" "$DONE_FILE"

TMUX_CMD="set +e; $COMMAND; echo \$? > $EXIT_CODE_FILE; touch $DONE_FILE"
tmux send-keys -t "$SESSION_NAME" "$TMUX_CMD" C-m

while [ ! -f "$DONE_FILE" ]; do
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
    sleep 5
done

tmux pipe-pane -t "$SESSION_NAME"
EXIT_CODE=$(cat "$EXIT_CODE_FILE" 2>/dev/null || echo 1)
rm -f "$EXIT_CODE_FILE" "$DONE_FILE"
exit $EXIT_CODE
