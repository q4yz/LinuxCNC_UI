#!/bin/bash

# Never mint certificates as root: they would be root-owned (the next
# boot-time run as the normal user could not replace them) and mkcert
# would use root's CA instead of the user's. Re-run as the invoking user.
if [ "$EUID" -eq 0 ]; then
    if [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
        exec sudo -u "$SUDO_USER" -H bash "$0" "$@"
    fi
    echo "Error: do not run as root; run as the user that owns the project." >&2
    exit 1
fi

# Give the system a moment to settle
sleep 2

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR/frontend/.cert" || exit 1

# Detect current IPs
ALL_IPS=$(hostname -I)
echo "Minting certificate for localhost and IPs: $ALL_IPS"

# Generate fresh certificates
mkcert -cert-file localhost.pem -key-file localhost-key.pem localhost 127.0.0.1 $ALL_IPS

# Reload Nginx to use the new certificate
sudo systemctl reload nginx

# Keep script alive silently if LinuxCNC expects it, or just exit.
# Since no frontend node process is running, we can just exit clean.
exit 0