#!/bin/bash -l
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
if [ -n "${CUSTOM_NINJA_BIN:-}" ] && [ -f "build/soong/ui/build/config.go" ] && ! grep -q "CUSTOM_NINJA_BIN" "build/soong/ui/build/sandbox_linux.go"; then
    python3 -c '
p1 = "build/soong/ui/build/config.go"
s1 = open(p1).read()
t1 = "func (c *configImpl) NinjaBin() string {\n"
r1 = t1 + "\tif custom, ok := c.environ.Get(\"CUSTOM_NINJA_BIN\"); ok && custom != \"\" {\n\t\treturn custom\n\t}\n"
if t1 in s1 and "CUSTOM_NINJA_BIN" not in s1:
    open(p1, "w").write(s1.replace(t1, r1, 1))
p2 = "build/soong/ui/build/ninja.go"
s2 = open(p2).read()
t2 = "\tcmd.Sandbox = ninjaSandbox\n"
r2 = "\tif custom, ok := config.Environment().Get(\"CUSTOM_NINJA_BIN\"); ok && custom != \"\" {\n\t\tcmd.Sandbox = noSandbox\n\t} else {\n\t\tcmd.Sandbox = ninjaSandbox\n\t}\n"
if t2 in s2 and "CUSTOM_NINJA_BIN" not in s2:
    s2 = s2.replace(t2, r2, 1).replace("\"SOONG_NINJA\",\n", "\"SOONG_NINJA\",\n\t\t\t\"CUSTOM_NINJA_BIN\",\n", 1)
    open(p2, "w").write(s2)
p3 = "build/soong/ui/build/sandbox_linux.go"
s3 = open(p3).read()
t3 = "func (c *Cmd) sandboxSupported() bool {\n"
r3 = t3 + "\tif custom := os.Getenv(\"CUSTOM_NINJA_BIN\"); custom != \"\" {\n\t\treturn false\n\t}\n"
if t3 in s3 and "CUSTOM_NINJA_BIN" not in s3:
    open(p3, "w").write(s3.replace(t3, r3, 1))
'
    rm -f out/soong_ui out/.soong_ui_hash
fi

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
export BUILD_HOSTNAME="AxionCI"
ax -br || exit 1

echo "Waiting for ZIP in out/target/product/$DEVICE..."
ROM_ZIP=""
for i in {1..1200}; do
    ROM_ZIP=$(find "out/target/product/$DEVICE" -maxdepth 1 -name "*.zip" -size +500M -print -quit 2>/dev/null)
    if [ -n "$ROM_ZIP" ]; then
        echo "✅ ZIP: $ROM_ZIP"
        break
    fi
    if ! pgrep -u "$(id -u)" -f "soong_ui|ninja" > /dev/null && [ $i -ge 2 ]; then
        echo "❌ Stopped. No ZIP."
        exit 1
    fi
    [ $((i % 10)) -eq 0 ] && echo "[$(date +%H:%M:%S)] Building..."
    sleep 30
done

if [ -z "$ROM_ZIP" ]; then
    echo "❌ Timeout."
    exit 1
fi
