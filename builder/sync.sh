#!/bin/bash
set -o pipefail
LOCAL_MANIFEST_URL="$1"
LOCAL_MANIFEST_PATH=".repo/local_manifests/jenkins_custom_manifest.xml"

KEY_BACKUP_DIR="$HOME/android_keys"

# Auto-backup keys if they exist in source but not in backup yet
if [ -d "vendor/lineage-priv/keys" ] && [ "$(ls -A vendor/lineage-priv/keys 2>/dev/null)" ]; then
    if [ ! -d "$KEY_BACKUP_DIR" ] || [ ! "$(ls -A "$KEY_BACKUP_DIR" 2>/dev/null)" ]; then
        echo "🔑 Auto-backing up keys from vendor/lineage-priv/keys to $KEY_BACKUP_DIR..."
        mkdir -p "$KEY_BACKUP_DIR"
        cp -r vendor/lineage-priv/keys/* "$KEY_BACKUP_DIR/"
    fi
fi

# Fast lock file cleanup (inside .repo only to avoid slow deep tree traversal)
find .repo/ -name "*.lock" -delete 2>/dev/null
find .repo/projects .repo/project-objects -name "index.lock" -o -name "config.lock" -o -name "shallow.lock" -delete 2>/dev/null

# Discard uncommitted changes and untracked garbage in all active repositories to prevent sync failures
if [ -d ".repo" ]; then
    echo "Cleaning uncommitted or dirty changes in all repositories..."
    repo forall -c "git reset --hard HEAD && git clean -qdf"
fi

rm -rf .repo/local_manifests/*
mkdir -p ".repo/local_manifests"

# Ensure required variables are set
AOSP_URL="${AOSP_MANIFEST_URL:-https://github.com/AxionAOSP/android.git}"
AOSP_BRANCH="${AOSP_MANIFEST_BRANCH:-lineage-23.2}"

echo "Initializing repo with: $AOSP_URL -b $AOSP_BRANCH"
repo init -u "$AOSP_URL" -b "$AOSP_BRANCH" --depth=1 --git-lfs --no-repo-verify < /dev/null || exit 1

if [ -n "$LOCAL_MANIFEST_URL" ]; then
    curl -L -o "$LOCAL_MANIFEST_PATH" "$LOCAL_MANIFEST_URL" || exit 1
fi

repo sync -c --no-clone-bundle --no-tags --optimized-fetch --prune --force-sync -j$(nproc --all) || exit 1

. build/envsetup.sh || exit 1
axionSync || exit 1

# Restore keys if backup exists
if [ -d "$KEY_BACKUP_DIR" ] && [ "$(ls -A "$KEY_BACKUP_DIR" 2>/dev/null)" ]; then
    echo "🔑 Restoring keys from $KEY_BACKUP_DIR to vendor/lineage-priv/keys..."
    mkdir -p "vendor/lineage-priv/keys"
    cp -r "$KEY_BACKUP_DIR/"* "vendor/lineage-priv/keys/"
fi
