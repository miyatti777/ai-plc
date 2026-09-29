#!/bin/bash
# AI-PLC Registry のメニューバーアプリをビルドする。Xcode 不要（Command Line Tools の swiftc）。
#   ./build.sh [出力先フォルダ]   既定: このフォルダの build/
# リポジトリの場所と python3（pyyaml 入り）の場所を Info.plist に埋め込む。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"
OUT="${1:-$HERE/build}"
APP="$OUT/AI-PLC Registry.app"

# pyyaml の入った python3 を探す。環境変数 AIPLC_PYTHON → PATH 上の python3（pyenv・conda・venv を含む）→ 定番の場所。
# pyenv の shim などは実体のパス（sys.executable）に解決して埋め込む（GUI アプリはシェルの PATH を引き継がないため）
PY=""
for c in ${AIPLC_PYTHON:-} $(type -ap python3) /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  [ -x "$c" ] || continue
  real="$("$c" -c "import sys, yaml; print(sys.executable)" 2>/dev/null)" || continue
  if [ -n "$real" ] && [ -x "$real" ]; then PY="$real"; break; fi
done
if [ -z "$PY" ]; then echo "pyyaml の入った python3 が見つかりません（AIPLC_PYTHON=/path/to/python3 で指定できます）" >&2; exit 2; fi

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O -framework AppKit -framework WebKit "$HERE/RegistryViewer.swift" -o "$APP/Contents/MacOS/RegistryViewer"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>AI-PLC Registry</string>
  <key>CFBundleDisplayName</key><string>AI-PLC Registry</string>
  <key>CFBundleIdentifier</key><string>local.aiplc.registry-viewer</string>
  <key>CFBundleExecutable</key><string>RegistryViewer</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
  <key>AIPLCRepo</key><string>$REPO</string>
  <key>AIPLCPython</key><string>$PY</string>
</dict>
</plist>
PLIST

codesign --force --sign - "$APP" >/dev/null 2>&1 || true
echo "ビルドしました: $APP"
echo "  repo:   $REPO"
echo "  python: $PY"
