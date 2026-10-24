#!/bin/bash
# Put a freshly built / downloaded frontend/dist live: restore the Root
# CA download, restart the system service, reload nginx.
#
# Shared by rebuild_ui.sh (newest commit, built on the board) and the
# release update in scripts/update.sh (prebuilt dist from GitHub).
set -e

# Never as root: cnc-root.crt would end up root-owned and the next
# (non-root) update could not replace it.
if [ "$EUID" -eq 0 ]; then
    if [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
        exec sudo -u "$SUDO_USER" -H bash "$0" "$@"
    fi
    echo "Error: do not run as root; run as the user that owns the project." >&2
    exit 1
fi

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UI_DIST_DIR="$PROJECT_DIR/frontend/dist"
BACKEND_SYSTEM_SERVICE="linuxcnc-ui-system.service"

echo "Restoring Root CA to the dist directory..."
CA_ROOT="$HOME/.local/share/mkcert/rootCA.pem"
if [ -f "$CA_ROOT" ]; then
    cp "$CA_ROOT" "$UI_DIST_DIR/cnc-root.crt"
    chmod 644 "$UI_DIST_DIR/cnc-root.crt"
    echo "Root CA restored successfully."
else
    echo "Warning: Root CA not found at $CA_ROOT. The download button may not work."
fi

echo "Restarting the backend system service..."
sudo /bin/systemctl restart "$BACKEND_SYSTEM_SERVICE"

echo "Reloading Nginx..."
sudo /bin/systemctl reload nginx
