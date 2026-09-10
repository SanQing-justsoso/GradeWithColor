#!/usr/bin/env bash
# BiggerSpeed 一键编译：edge840/edge540 的 .prg + 上架用 .iq
# 自动探测 macOS / Windows(Git Bash/MSYS) 的 Connect IQ SDK
#
# 用法：
#   bash build.sh
#
# 密钥查找顺序（取第一个存在者）：
#   1) 项目根目录 developer_key.der
#   2) ~/Garmin/developer_key
#
# 产物：
#   bin/BiggerSpeed-edge840.prg   侧载到 Edge 840
#   bin/BiggerSpeed-edge540.prg   侧载到 Edge 540
#   BiggerSpeed.iq                上传 Garmin 商店
set -e

# 1) 探测 SDK 目录与平台
SDK_DIR=""
PLATFORM=""
if [ -d "$HOME/Library/Application Support/Garmin/ConnectIQ/Sdks" ]; then
    SDK_DIR=$(ls -d "$HOME/Library/Application Support/Garmin/ConnectIQ/Sdks/connectiq-sdk-mac-"* 2>/dev/null | sort -V | tail -1)
    PLATFORM="mac"
elif [ -d "$HOME/AppData/Roaming/Garmin/ConnectIQ/Sdks" ]; then
    SDK_DIR=$(ls -d "$HOME/AppData/Roaming/Garmin/ConnectIQ/Sdks/connectiq-sdk-win-"* 2>/dev/null | sort -V | tail -1)
    PLATFORM="win"
fi

if [ -z "$SDK_DIR" ]; then
    echo "错误：找不到 Connect IQ SDK" >&2
    echo "  macOS 期望路径: ~/Library/Application Support/Garmin/ConnectIQ/Sdks/connectiq-sdk-mac-*" >&2
    echo "  Windows 期望路径: %APPDATA%/Garmin/ConnectIQ/Sdks/connectiq-sdk-win-*" >&2
    exit 1
fi

# 2) 定位 developer key
KEY=""
if [ -f "$(pwd)/developer_key.der" ]; then
    KEY="$(pwd)/developer_key.der"
elif [ -f "$HOME/Garmin/developer_key" ]; then
    KEY="$HOME/Garmin/developer_key"
fi

if [ -z "$KEY" ]; then
    echo "错误：找不到 developer key" >&2
    echo "请把当初上架用的 developer_key.der 复制到项目根目录，或放到 ~/Garmin/developer_key" >&2
    exit 1
fi

echo "SDK : $SDK_DIR"
echo "平台: $PLATFORM"
echo "密钥: $KEY"
echo ""
mkdir -p bin

# 3) 编译函数：mac 用 monkeyc 脚本，win 用 monkeybrains.jar + cygpath
compile_one() {
    local out="$1"
    shift
    if [ "$PLATFORM" = "mac" ]; then
        MSYS_NO_PATHCONV=1 "$SDK_DIR/bin/monkeyc" -o "$out" "$@"
    else
        local JAR="$SDK_DIR/bin/monkeybrains.jar"
        local APIDB="$SDK_DIR/bin/api.db"
        local APIMIR="$SDK_DIR/bin/api.mir"
        MSYS_NO_PATHCONV=1 java -Xms1g -Dfile.encoding=UTF-8 \
            -jar "$(cygpath -w "$JAR")" \
            -a "$(cygpath -w "$APIDB")" \
            -b "$(cygpath -w "$APIMIR")" \
            -o "$(cygpath -w "$out")" \
            "$@"
    fi
}

# 4) 两个设备的 .prg（USB 侧载用）
for DEV in edge840 edge540; do
    echo "===== 编译 .prg : $DEV ====="
    compile_one "bin/BiggerSpeed-$DEV.prg" -f monkey.jungle -d "$DEV" -y "$KEY" -w
done

# 5) 上架用 .iq（不带 -d，自动打包 manifest 里所有设备）
echo "===== 编译 .iq（含全部设备 + 签名）====="
compile_one "BiggerSpeed.iq" -f monkey.jungle -y "$KEY" -e -w

echo ""
echo "完成："
echo "  bin/BiggerSpeed-edge840.prg   (侧载到 840)"
echo "  bin/BiggerSpeed-edge540.prg   (侧载到 540)"
echo "  BiggerSpeed.iq                (上传 Garmin 商店)"
