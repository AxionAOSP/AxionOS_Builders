#!/bin/bash
set -o pipefail
LOCAL_MANIFEST_URL="$1"
LOCAL_MANIFEST_PATH=".repo/local_manifests/jenkins_custom_manifest.xml"

[ -f "$LOCAL_MANIFEST_PATH" ] && rm -f "$LOCAL_MANIFEST_PATH"
mkdir -p ".repo/local_manifests"

# Ensure required variables are set
AOSP_URL="${AOSP_MANIFEST_URL:-https://github.com/AxionAOSP/android.git}"
AOSP_BRANCH="${AOSP_MANIFEST_BRANCH:-lineage-23.2}"

echo "Initializing repo with: $AOSP_URL -b $AOSP_BRANCH"
repo init -u "$AOSP_URL" -b "$AOSP_BRANCH" --depth=1 --git-lfs || exit 1

if [ -n "$LOCAL_MANIFEST_URL" ]; then
    curl -L -o "$LOCAL_MANIFEST_PATH" "$LOCAL_MANIFEST_URL" || exit 1
fi

if [ ! -f "build/envsetup.sh" ]; then
    repo sync -c --no-clone-bundle --no-tags --optimized-fetch --prune --force-sync -j$(nproc --all) || exit 1
fi

. build/envsetup.sh || exit 1
axionSync || exit 1
