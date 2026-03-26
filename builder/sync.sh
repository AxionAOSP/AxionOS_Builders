#!/bin/bash

# Arguments:
# 1: LOCAL_MANIFEST_URL (optional)
# AOSP_MANIFEST_URL and AOSP_MANIFEST_BRANCH are read from environment variables

set -o pipefail

LOCAL_MANIFEST_URL="$1"
MANIFEST_FILENAME="jenkins_custom_manifest.xml"
LOCAL_MANIFEST_PATH=".repo/local_manifests/$MANIFEST_FILENAME"

echo "Starting Syncing Source stage..."

# --- 1. CLEANUP PREVIOUS CUSTOM MANIFEST (Before Repo Init) ---
if [ -f "$LOCAL_MANIFEST_PATH" ]; then
    echo "Found previous custom manifest ($MANIFEST_FILENAME). Starting cleanup..."
    rm -f "$LOCAL_MANIFEST_PATH"
fi

# --- 2. REPO INIT ---
echo "Ensuring local manifests directory exists..."
mkdir -p ".repo/local_manifests" || { echo "Failed to create .repo/local_manifests"; exit 1; }

echo "Initializing repo with AOSP main manifest from $AOSP_MANIFEST_URL on branch $AOSP_MANIFEST_BRANCH"
repo init -u "$AOSP_MANIFEST_URL" -b "$AOSP_MANIFEST_BRANCH" --depth=1 --git-lfs || { echo "Repo init failed"; exit 1; }

# --- 3. APPLY NEW CUSTOM MANIFEST ---
if [ -n "$LOCAL_MANIFEST_URL" ]; then
    echo "Fetching new local manifest from: $LOCAL_MANIFEST_URL"
    if curl -L -o "$LOCAL_MANIFEST_PATH" "$LOCAL_MANIFEST_URL"; then
        echo "Local manifest successfully downloaded."
    else
        echo "Failed to download local manifest."
        exit 1
    fi
fi

# --- 4. REPO SYNC ---
if [ ! -f "build/envsetup.sh" ]; then
    echo "First sync detected or build/ folder missing. Running initial repo sync..."
    repo sync -c --no-clone-bundle --no-tags --optimized-fetch --prune --force-sync -j$(nproc --all) || { echo "Initial repo sync failed"; exit 1; }
fi

echo "Sourcing build/envsetup.sh..."
. build/envsetup.sh || { echo "Failed to source build/envsetup.sh"; exit 1; }

echo "Running axionSync..."
# We run it again in case the local manifest added new repos or updates are needed
axionSync || { echo "axionSync failed"; exit 1; }

echo "Syncing Source stage complete."
