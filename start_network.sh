#!/bin/bash

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