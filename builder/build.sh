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

ax -br || { 
    echo "Build failed"; exit 1; 
}

echo "Building stage complete."
