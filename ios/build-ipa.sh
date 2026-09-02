#!/usr/bin/env bash
#
# Build an UNSIGNED MacRemote.ipa you can share (e.g. over WhatsApp/AirDrop).
# The recipient installs it with Sideloadly or AltStore, which re-sign it with
# their own Apple ID — no Apple Developer account or device UDID needed here.
#
# Requires: Xcode, and XcodeGen (`brew install xcodegen`).
set -euo pipefail
cd "$(dirname "$0")"

echo "▶︎ Generating Xcode project…"
xcodegen generate

echo "▶︎ Archiving (unsigned)…"
rm -rf build
xcodebuild -project MacRemote.xcodeproj -scheme MacRemote -configuration Release \
  -sdk iphoneos -archivePath build/MacRemote.xcarchive archive \
  CODE_SIGN_IDENTITY="" CODE_SIGNING_REQUIRED=NO CODE_SIGNING_ALLOWED=NO \
  -quiet

echo "▶︎ Packaging .ipa…"
APP="build/MacRemote.xcarchive/Products/Applications/MacRemote.app"
rm -rf build/Payload
mkdir -p build/Payload dist
cp -R "$APP" build/Payload/
( cd build && zip -qr ../dist/MacRemote.ipa Payload )
rm -rf build/Payload

echo "✓ Done → $(pwd)/dist/MacRemote.ipa"
