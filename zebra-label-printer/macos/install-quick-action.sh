#!/bin/bash
# install-quick-action.sh — Install the "Print to Zebra" macOS Quick Action.
#
# Usage:
#   ./install-quick-action.sh [SERVER_URL]
#
# Examples:
#   ./install-quick-action.sh                          # defaults to http://homeassistant.local:8099
#   ./install-quick-action.sh http://192.168.1.50:8099
#
# The installed Quick Action appears in Finder's right-click menu
# under Quick Actions > "Print to Zebra" for PDFs and images.

set -euo pipefail

SERVER="${1:-http://homeassistant.local:8099}"
WORKFLOW_NAME="Print to Zebra"
SERVICES_DIR="$HOME/Library/Services"
WORKFLOW_DIR="${SERVICES_DIR}/${WORKFLOW_NAME}.workflow"

echo "Installing '${WORKFLOW_NAME}' Quick Action..."
echo "  Server: ${SERVER}"
echo "  Target: ${WORKFLOW_DIR}"

mkdir -p "${WORKFLOW_DIR}/Contents"

# --- Info.plist ---
cat > "${WORKFLOW_DIR}/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>NSServices</key>
	<array>
		<dict>
			<key>NSMenuItem</key>
			<dict>
				<key>default</key>
				<string>Print to Zebra</string>
			</dict>
			<key>NSMessage</key>
			<string>runWorkflowAsService</string>
		</dict>
	</array>
</dict>
</plist>
PLIST

# --- document.wflow (Automator workflow definition) ---
# This defines a Quick Action that receives files in Finder and runs a shell script.
cat > "${WORKFLOW_DIR}/Contents/document.wflow" << WFLOW
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>AMApplicationBuild</key>
	<string>523</string>
	<key>AMApplicationVersion</key>
	<string>2.10</string>
	<key>AMDocumentVersion</key>
	<integer>2</integer>
	<key>actions</key>
	<array>
		<dict>
			<key>action</key>
			<dict>
				<key>AMAccepts</key>
				<dict>
					<key>Container</key>
					<string>List</string>
					<key>Optional</key>
					<false/>
					<key>Types</key>
					<array>
						<string>com.apple.cocoa.path</string>
					</array>
				</dict>
				<key>AMActionVersion</key>
				<string>1.0.2</string>
				<key>AMApplication</key>
				<array>
					<string>Automator</string>
				</array>
				<key>AMBundleIdentifier</key>
				<string>com.apple.RunShellScript</string>
				<key>AMCategory</key>
				<array>
					<string>AMCategoryUtilities</string>
				</array>
				<key>AMIconName</key>
				<string>RunShellScript</string>
				<key>AMKeywords</key>
				<array>
					<string>Shell</string>
					<string>Script</string>
					<string>Command</string>
					<string>Run</string>
					<string>Unix</string>
				</array>
				<key>AMName</key>
				<string>Run Shell Script</string>
				<key>AMProvides</key>
				<dict>
					<key>Container</key>
					<string>List</string>
					<key>Types</key>
					<array>
						<string>com.apple.cocoa.path</string>
					</array>
				</dict>
				<key>ActionBundlePath</key>
				<string>/System/Library/Automator/Run Shell Script.action</string>
				<key>ActionName</key>
				<string>Run Shell Script</string>
				<key>ActionParameters</key>
				<dict>
					<key>COMMAND_STRING</key>
					<string>SERVER="${SERVER}"

for f in "\$@"; do
    FILENAME=\$(basename "\$f")
    EXT="\${FILENAME##*.}"
    EXT_LOWER=\$(echo "\$EXT" | tr '[:upper:]' '[:lower:]')

    case "\$EXT_LOWER" in
        pdf) CT="application/pdf" ;;
        png) CT="image/png" ;;
        jpg|jpeg) CT="image/jpeg" ;;
        tif|tiff) CT="image/tiff" ;;
        bmp) CT="image/bmp" ;;
        gif) CT="image/gif" ;;
        webp) CT="image/webp" ;;
        *) CT="application/octet-stream" ;;
    esac

    RESPONSE=\$(curl -s -w "\\n%{http_code}" \\
        --connect-timeout 5 \\
        --max-time 30 \\
        -X POST \\
        -F "file=@\${f};type=\${CT}" \\
        "\${SERVER}/api/labels/print" 2>&amp;1)

    HTTP_CODE=\$(echo "\$RESPONSE" | tail -1)
    BODY=\$(echo "\$RESPONSE" | sed '\$d')

    if [ "\$HTTP_CODE" -ge 200 ] 2>/dev/null &amp;&amp; [ "\$HTTP_CODE" -lt 300 ] 2>/dev/null; then
        osascript -e "display notification \"\${FILENAME} sent to printer\" with title \"Zebra Label Printer\" sound name \"Glass\""
    else
        osascript -e "display notification \"Error: \${BODY}\" with title \"Print Failed\" sound name \"Basso\""
    fi
done</string>
					<key>CheckedForUserDefaultShell</key>
					<true/>
					<key>inputMethod</key>
					<integer>1</integer>
					<key>shell</key>
					<string>/bin/bash</string>
					<key>source</key>
					<string></string>
				</dict>
				<key>BundleIdentifier</key>
				<string>com.apple.RunShellScript</string>
				<key>CFBundleVersion</key>
				<string>1.0.2</string>
				<key>CanShowSelectedItemsWhenRun</key>
				<false/>
				<key>CanShowWhenRun</key>
				<true/>
				<key>Category</key>
				<array>
					<string>AMCategoryUtilities</string>
				</array>
				<key>Class Name</key>
				<string>RunShellScriptAction</string>
				<key>InputUUID</key>
				<string>A1A2B3C4-D5E6-F7A8-B9C0-D1E2F3A4B5C6</string>
				<key>Keywords</key>
				<array>
					<string>Shell</string>
					<string>Script</string>
					<string>Command</string>
					<string>Run</string>
					<string>Unix</string>
				</array>
				<key>Name</key>
				<string>Run Shell Script</string>
				<key>OutputUUID</key>
				<string>B2C3D4E5-F6A7-B8C9-D0E1-F2A3B4C5D6E7</string>
				<key>ShowWhenRun</key>
				<false/>
				<key>UUID</key>
				<string>C3D4E5F6-A7B8-C9D0-E1F2-A3B4C5D6E7F8</string>
			</dict>
		</dict>
	</array>
	<key>connectors</key>
	<dict/>
	<key>workflowMetaData</key>
	<dict>
		<key>applicationBundleIDsByPath</key>
		<dict/>
		<key>applicationPaths</key>
		<array/>
		<key>inputTypeIdentifier</key>
		<string>com.apple.Automator.fileSystemObject</string>
		<key>outputTypeIdentifier</key>
		<string>com.apple.Automator.nothing</string>
		<key>presentationMode</key>
		<integer>15</integer>
		<key>processesInput</key>
		<integer>0</integer>
		<key>serviceApplicationBundleID</key>
		<string>com.apple.finder</string>
		<key>serviceApplicationPath</key>
		<string>/System/Library/CoreServices/Finder.app</string>
		<key>serviceInputTypeIdentifier</key>
		<string>com.apple.Automator.fileSystemObject</string>
		<key>serviceOutputTypeIdentifier</key>
		<string>com.apple.Automator.nothing</string>
		<key>serviceProcessesInput</key>
		<integer>0</integer>
		<key>systemImageName</key>
		<string>NSActionTemplate</string>
		<key>useAutomaticInputType</key>
		<integer>0</integer>
		<key>workflowTypeIdentifier</key>
		<string>com.apple.Automator.servicesMenu</string>
	</dict>
</dict>
</plist>
WFLOW

echo ""
echo "Quick Action installed successfully!"
echo ""
echo "Usage:"
echo "  1. Right-click any PDF or image in Finder"
echo "  2. Select Quick Actions > Print to Zebra"
echo "  3. A notification confirms success or failure"
echo ""
echo "To uninstall:"
echo "  rm -rf \"${WORKFLOW_DIR}\""
