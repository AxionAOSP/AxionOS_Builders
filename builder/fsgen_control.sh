#!/bin/bash

# This script controls the modification and restoration of build/soong/fsgen/Android.bp
# to enable or disable the soong_filesystem_creator.

# Arguments:
# 1: ACTION - "modify" or "restore"

ACTION="$1"
TARGET_FILE="build/soong/fsgen/Android.bp"
BACKUP_FILE="build/soong/fsgen/Android.bp.bak"

modify_file() {
    echo "Modifying $TARGET_FILE..."
    if [ ! -f "$TARGET_FILE" ]; then
        echo "Error: Target file $TARGET_FILE does not exist."
        exit 1
    fi

    # 1. Create a backup
    echo "Backing up original file to $BACKUP_FILE"
    cp "$TARGET_FILE" "$BACKUP_FILE" || { echo "Failed to create backup."; exit 1; }

    # 2. Modify the file
    # This sed command finds the block and adds 'enabled: false,'
    sed -i '/name: "soong_filesystem_creator",/a \    enabled: false,' "$TARGET_FILE"
    
    echo "File modification complete."
}

restore_file() {
    echo "Restoring $TARGET_FILE from backup..."
    if [ ! -f "$BACKUP_FILE" ]; then
        echo "Warning: Backup file $BACKUP_FILE not found. Nothing to restore."
        return
    fi

    mv "$BACKUP_FILE" "$TARGET_FILE" || { echo "Failed to restore from backup."; exit 1; }
    echo "File restored successfully."
}

# --- Main Logic ---
case "$ACTION" in
    "modify")
        modify_file
        ;;
    "restore")
        restore_file
        ;;
    *)
        echo "Error: Invalid action specified. Use 'modify' or 'restore'."
        exit 1
        ;;
esac

exit 0
