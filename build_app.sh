#!/usr/bin/env bash
# Baut ein minimalistisches macOS-App-Bundle für murml.
#
# Das Bundle ist im Grunde ein Wrapper, der run.sh startet. Es ist klein,
# läuft im Hintergrund (LSUIElement) und ist doppelklickbar.
#
# Aufruf:   ./build_app.sh
# Ergebnis: dist/murml.app

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
APP="$ROOT/dist/murml.app"
LOG_DIR="$HOME/Library/Logs"

VERSION="$(grep -E '^__version__' murml/__init__.py | cut -d'"' -f2 || echo "0.1.0")"

echo "→ Erstelle dist/murml.app (Version $VERSION)"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
mkdir -p "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>murml</string>
    <key>CFBundleDisplayName</key>
    <string>murml</string>
    <key>CFBundleExecutable</key>
    <string>murml</string>
    <key>CFBundleIdentifier</key>
    <string>com.durhat.murml</string>
    <key>CFBundleVersion</key>
    <string>$VERSION</string>
    <key>CFBundleShortVersionString</key>
    <string>$VERSION</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>

    <!-- Background-App ohne Dock-Symbol; lebt nur in der Menüleiste. -->
    <key>LSUIElement</key>
    <true/>

    <!-- Begründungen, die macOS in den Berechtigungs-Dialogen anzeigt. -->
    <key>NSMicrophoneUsageDescription</key>
    <string>murml braucht das Mikrofon, um deine Sprache aufzunehmen und zu transkribieren.</string>
    <key>NSAppleEventsUsageDescription</key>
    <string>murml öffnet den Emoji-Picker und sendet Cmd+V, um den transkribierten Text einzufügen.</string>
</dict>
</plist>
EOF

# Launcher: ruft run.sh auf, schreibt Logs in ~/Library/Logs/murml.log
mkdir -p "$LOG_DIR"
cat > "$APP/Contents/MacOS/murml" <<EOF
#!/usr/bin/env bash
exec "$ROOT/run.sh" >> "$LOG_DIR/murml.log" 2>&1
EOF
chmod +x "$APP/Contents/MacOS/murml"

# Ad-hoc Code-Signing: macht das Öffnen auf Sequoia/Tahoe deutlich angenehmer.
# Ohne Apple-Developer-Account ist das die kostenlose Variante.
if codesign --sign - --force --deep "$APP" >/dev/null 2>&1; then
    echo "→ Ad-hoc-signiert."
else
    echo "→ codesign nicht verfügbar – das Bundle ist trotzdem startbar."
fi

echo ""
echo "Fertig:"
echo "  $APP"
echo ""
echo "Doppelklick zum Starten — oder ins Programme-Verzeichnis ziehen:"
echo "  cp -R \"$APP\" /Applications/"
echo ""
echo "Logs landen unter: $LOG_DIR/murml.log"
