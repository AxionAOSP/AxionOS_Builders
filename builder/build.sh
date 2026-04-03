#!/bin/bash

# Arguments:
# 1: DEVICE
# 2: RELEASETYPE (Unused now as axion script handles it or uses defaults)
# 3: FULLCLEAN

DEVICE="$1"
RELEASETYPE="$2"
FULLCLEAN="$3"

# Mapping GMS_VARIANT to axion command arguments
# Core    -> "gms core"
# Pico    -> "gms pico"
# Vanilla -> "va"
case "$GMS_VARIANT" in
    "Core")
        AXION_VARIANT="gms core"
        ;;
    "Pico")
        AXION_VARIANT="gms pico"
        ;;
    "Vanilla")
        AXION_VARIANT="va"
        ;;
    *)
        # Default to gms core if unknown
        AXION_VARIANT="gms core"
        ;;
esac

echo "Starting Building stage for $DEVICE with variant: $AXION_VARIANT"

# Source build environment
echo "Sourcing build/envsetup.sh..."
. build/envsetup.sh || { echo "Failed to source build/envsetup.sh"; exit 1; }

# Handle Full Clean step (cleans the entire 'out' directory)
if [ "$FULLCLEAN" == "Yes" ]; then
    echo "FULLCLEAN is Yes, running 'make clean'..."
    make clean || { echo "Make clean failed"; exit 1; }
fi

# Run Axion Configure command
# Usage: axion <device_codename> [variant]
echo "Running axion command: axion $DEVICE $AXION_VARIANT"
axion "$DEVICE" $AXION_VARIANT || { echo "Axion configuration failed"; exit 1; }

# Start building
# Usage: ax -br -j<count>
echo "Starting Axion build process (ax -br)..."

# Initial build command. 
# Note: If this command exits after installclean, we handle it below.
ax -br

# --- AXION BUILD SYSTEM WORKAROUND ---
# ax -br might exit after 'installclean'. We must block until the REAL build finishes.
# We verify this by looking for the ROM ZIP in the out directory.
echo "Waiting for ROM package to be ready in out/target/product/$DEVICE..."

# Wait up to 10 hours (AOSP builds are long)
# 1200 iterations * 30 seconds = 600 minutes = 10 hours
for i in {1..1200}; do
    # Search for ROM ZIP (larger than 500MB to ensure it's the actual ROM and not a small package)
    ROM_ZIP=$(find "out/target/product/$DEVICE" -maxdepth 1 -name "*.zip" -size +500M | head -n 1)
    
    if [ -n "$ROM_ZIP" ]; then
        echo "✅ ROM ZIP found: $ROM_ZIP"
        # Wait an extra 10 seconds to ensure the filesystem has finished writing the file
        sleep 10
        break
    fi
    
    # Check if build processes are still active
    # If no ninja/soong processes are running, and no ZIP exists after a few minutes, the build failed.
    if ! pgrep -u $(whoami) -f "soong_ui|ninja" > /dev/null; then
        # Give it 5 minutes (10 iterations) to start up or transition
        if [ $i -gt 10 ]; then
             echo "❌ Build processes (ninja/soong) stopped but no ROM ZIP was found."
             echo "This likely means the build failed or was aborted."
             exit 1
        fi
    fi
    
    # Heartbeat every 5 minutes
    if [ $((i % 10)) -eq 0 ]; then
        echo "[$(date +%H:%M:%S)] Still building... (Waiting for ZIP in out/target/product/$DEVICE)"
    fi
    
    sleep 30
done

if ! find "out/target/product/$DEVICE" -maxdepth 1 -name "*.zip" -size +500M | grep -q "."; then
    echo "❌ Timeout: Build took too long or failed to produce a ZIP."
    exit 1
fi

echo "Building stage complete."
