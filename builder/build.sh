#!/bin/bash
DEVICE="$1"
RELEASETYPE="$2"
FULLCLEAN="$3"

case "$GMS_VARIANT" in
    "GMS") AXION_VARIANT="gms" ;;
    "PICO") AXION_VARIANT="pico" ;;
    "CORE") AXION_VARIANT="core" ;;
    "VANILLA") AXION_VARIANT="va" ;;
    *) AXION_VARIANT="" ;;
esac

echo "Building $DEVICE ($GMS_VARIANT -> $AXION_VARIANT)..."
. build/envsetup.sh || exit 1

KEY_BACKUP_DIR="$HOME/android_keys"
if [ -d "$KEY_BACKUP_DIR" ] && [ "$(ls -A "$KEY_BACKUP_DIR" 2>/dev/null)" ]; then
    echo "🔑 Ensuring keys are restored to vendor/lineage-priv/keys..."
    mkdir -p "vendor/lineage-priv/keys"
    cp -r "$KEY_BACKUP_DIR/"* "vendor/lineage-priv/keys/"
fi

if [ "$FULLCLEAN" == "Yes" ]; then
    echo "Cleaning out/..."
    rm -rf out || exit 1
fi

axion "$DEVICE" $AXION_VARIANT || exit 1
ax -br || exit 1

echo "Waiting for ZIP in out/target/product/$DEVICE..."
for i in {1..1200}; do
    ROM_ZIP=$(find "out/target/product/$DEVICE" -maxdepth 1 -name "*.zip" -size +500M | head -n 1)
    if [ -n "$ROM_ZIP" ]; then
        echo "✅ ZIP: $ROM_ZIP"
        sleep 10
        break
    fi
    if ! pgrep -u $(whoami) -f "soong_ui|ninja" > /dev/null && [ $i -gt 10 ]; then
         echo "❌ Stopped. No ZIP."
         exit 1
    fi
    [ $((i % 10)) -eq 0 ] && echo "[$(date +%H:%M:%S)] Building..."
    sleep 30
done

if ! find "out/target/product/$DEVICE" -maxdepth 1 -name "*.zip" -size +500M | grep -q "."; then
    echo "❌ Timeout."
    exit 1
fi
