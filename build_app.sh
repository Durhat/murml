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
ICON_SRC="$ROOT/assets/icon-source.png"
ICON_NAME="murml"

VERSION="$(grep -E '^__version__' murml/__init__.py | cut -d'"' -f2 || echo "0.1.0")"
AUTHOR="Durhat Eser"
YEAR="$(date +%Y)"
COPYRIGHT="Copyright © ${YEAR} ${AUTHOR}. Veröffentlicht unter MIT-Lizenz."

echo "→ Erstelle dist/murml.app (Version $VERSION)"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
mkdir -p "$APP/Contents/Resources"

# ── Icon (.icns) aus assets/icon-source.png bauen ──────────────────────────
ICONFILE_KEY=""
if [ -f "$ICON_SRC" ]; then
    echo "→ Generiere App-Icon aus $ICON_SRC"
    ICONSET="$(mktemp -d)/${ICON_NAME}.iconset"
    mkdir -p "$ICONSET"

    # Apple erwartet diese acht Größen-Stufen.
    sips -z 16 16     "$ICON_SRC" --out "$ICONSET/icon_16x16.png"        >/dev/null
    sips -z 32 32     "$ICON_SRC" --out "$ICONSET/icon_16x16@2x.png"     >/dev/null
    sips -z 32 32     "$ICON_SRC" --out "$ICONSET/icon_32x32.png"        >/dev/null
    sips -z 64 64     "$ICON_SRC" --out "$ICONSET/icon_32x32@2x.png"     >/dev/null
    sips -z 128 128   "$ICON_SRC" --out "$ICONSET/icon_128x128.png"      >/dev/null
    sips -z 256 256   "$ICON_SRC" --out "$ICONSET/icon_128x128@2x.png"   >/dev/null
    sips -z 256 256   "$ICON_SRC" --out "$ICONSET/icon_256x256.png"      >/dev/null
    sips -z 512 512   "$ICON_SRC" --out "$ICONSET/icon_256x256@2x.png"   >/dev/null
    sips -z 512 512   "$ICON_SRC" --out "$ICONSET/icon_512x512.png"      >/dev/null
    sips -z 1024 1024 "$ICON_SRC" --out "$ICONSET/icon_512x512@2x.png"   >/dev/null

    iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/${ICON_NAME}.icns"
    rm -rf "$(dirname "$ICONSET")"
    ICONFILE_KEY="    <key>CFBundleIconFile</key>
    <string>${ICON_NAME}</string>"
    echo "→ Icon gebaut: ${ICON_NAME}.icns"
else
    echo "→ Kein Icon-Quellbild gefunden (assets/icon-source.png) — überspringe."
fi

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

    <!-- Author + Copyright erscheinen im Finder-Info-Dialog. -->
    <key>NSHumanReadableCopyright</key>
    <string>${COPYRIGHT}</string>
    <key>CFBundleGetInfoString</key>
    <string>murml ${VERSION} — Push-to-talk Diktieren von ${AUTHOR}</string>

    <!-- Background-App ohne Dock-Symbol; lebt nur in der Menüleiste. -->
    <key>LSUIElement</key>
    <true/>

    <!-- Begründungen, die macOS in den Berechtigungs-Dialogen anzeigt. -->
    <key>NSMicrophoneUsageDescription</key>
    <string>murml braucht das Mikrofon, um deine Sprache aufzunehmen und zu transkribieren.</string>
    <key>NSAppleEventsUsageDescription</key>
    <string>murml öffnet den Emoji-Picker und sendet Cmd+V, um den transkribierten Text einzufügen.</string>
${ICONFILE_KEY}
</dict>
</plist>
EOF

# Launcher: kompiliert ein winziges C-Binary, das run.sh per posix_spawn
# startet und am Leben bleibt. Damit ist das Bundle-Executable ein echter
# Mach-O-Prozess (kein Skript), und macOS kann TCC-Berechtigungen sauber
# der App-Identität zuordnen statt sie als "python3.11" zu labeln.
mkdir -p "$LOG_DIR"

# run.sh schreibt selbst nicht ins Log — wir lassen die Shell das via
# Wrapper-Stub umlenken, der dann run.sh exec'd.
RUN_WRAPPER="$APP/Contents/Resources/run-wrapped.sh"
cat > "$RUN_WRAPPER" <<EOF
#!/usr/bin/env bash
exec "$ROOT/run.sh" >> "$LOG_DIR/murml.log" 2>&1
EOF
chmod +x "$RUN_WRAPPER"

LAUNCHER_C="$ROOT/launcher.c"
if [ ! -f "$LAUNCHER_C" ]; then
    echo "✗ launcher.c fehlt – kann das Bundle-Executable nicht bauen." >&2
    exit 1
fi

# @@RUN_SH@@ im Quelltext durch den vollen Pfad zum Wrapper-Skript ersetzen.
LAUNCHER_TMP="$(mktemp -t murml_launcher.XXXX).c"
sed "s|@@RUN_SH@@|${RUN_WRAPPER}|g" "$LAUNCHER_C" > "$LAUNCHER_TMP"

if ! cc -O2 -arch arm64 -arch x86_64 -o "$APP/Contents/MacOS/murml" "$LAUNCHER_TMP" 2>/dev/null; then
    # Fallback: nur native arch.
    cc -O2 -o "$APP/Contents/MacOS/murml" "$LAUNCHER_TMP"
fi
rm -f "$LAUNCHER_TMP"
chmod +x "$APP/Contents/MacOS/murml"

# Ad-hoc Code-Signing: macht das Öffnen auf neueren macOS-Versionen
# deutlich angenehmer. Ohne Apple-Developer-Account ist das die kostenlose Variante.
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
