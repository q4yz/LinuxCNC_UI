#!/bin/bash
set -e # Exit immediately if a command fails

# Ensure the script is run with sudo
if [ "$EUID" -ne 0 ]; then
  echo "Please run this script with sudo: sudo ./install.sh"
  exit 1
fi

# Get the original user who ran sudo (so we don't create venv as root)
REAL_USER=${SUDO_USER:-$USER}
PROJECT_DIR=$(pwd)
CERT_DIR="$PROJECT_DIR/frontend/.cert"
UI_DIST_DIR="$PROJECT_DIR/frontend/dist"

echo "=========================================="
echo " Starting LinuxCNC UI Installation"
echo " User: $REAL_USER"
echo " Project Dir: $PROJECT_DIR"
echo "=========================================="

# 1. Update and install core system packages
echo -e "\n---> Installing system dependencies..."
apt-get update
apt-get install -y curl wget git nginx python3-venv mkcert libnss3-tools ustreamer

# 2. Install Node.js (LTS version)
echo -e "\n---> Installing Node.js..."
if ! command -v node >/dev/null 2>&1; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
else
    echo "Node.js is already installed."
fi

# 3. Set up the Python Backend Virtual Environment
#
# One venv shared by both services (backend/machine and
# backend/system) — see .agent/context/ARCHITECTURE.md for why the
# backend is split into two processes. Each service's own
# requirements file (today identical; they'll diverge if a
# service-only dependency shows up) is installed into it.
echo -e "\n---> Setting up Python virtual environment (with system-site-packages)..."
cd "$PROJECT_DIR/backend"
sudo -u "$REAL_USER" python3 -m venv venv --system-site-packages
if [ -f "requirements-machine.txt" ] && [ -f "requirements-system.txt" ]; then
    sudo -u "$REAL_USER" ./venv/bin/pip install -r requirements-machine.txt -r requirements-system.txt
elif [ -f "requirements.txt" ]; then
    sudo -u "$REAL_USER" ./venv/bin/pip install -r requirements.txt
fi

# --- Temporary Backend Spin-up (both services, for OpenAPI codegen) ---
# The frontend's typed API client is generated from BOTH services'
# merged OpenAPI schema (frontend/scripts/generate-api.mjs +
# merge-openapi.mjs), so both need to be briefly reachable here.
echo -e "\n---> Temporarily starting both backends to generate API schemas..."
cd "$PROJECT_DIR/backend/machine"
sudo -u "$REAL_USER" "$PROJECT_DIR/backend/venv/bin/uvicorn" main:app --host 127.0.0.1 --port 8000 > "$PROJECT_DIR/backend-machine.log" 2>&1 &
MACHINE_BACKEND_PID=$!

cd "$PROJECT_DIR/backend/system"
sudo -u "$REAL_USER" "$PROJECT_DIR/backend/venv/bin/uvicorn" main:app --host 127.0.0.1 --port 8001 > "$PROJECT_DIR/backend-system.log" 2>&1 &
SYSTEM_BACKEND_PID=$!

echo "Waiting for both backends to expose their OpenAPI schemas..."
timeout 15 bash -c 'until curl -s http://127.0.0.1:8000/openapi.json > /dev/null; do sleep 1; done'
timeout 15 bash -c 'until curl -s http://127.0.0.1:8001/openapi.json > /dev/null; do sleep 1; done'

# 4. Set up the Frontend and Build
echo -e "\n---> Installing Frontend dependencies and building production app..."
cd "$PROJECT_DIR/frontend"
sudo -u "$REAL_USER" npm install

echo "Generating API client..."
sudo -u "$REAL_USER" npm run generate-api

echo "Building Vite application..."
sudo -u "$REAL_USER" npm run build

# --- CRITICAL: Clean up temporary backends ---
echo "Tearing down temporary backends..."
kill $MACHINE_BACKEND_PID $SYSTEM_BACKEND_PID >/dev/null 2>&1
wait $MACHINE_BACKEND_PID $SYSTEM_BACKEND_PID >/dev/null 2>&1 || true
# --------------------------------------------

# 5. Set up mkcert and the Root CA
echo -e "\n---> Configuring local Certificate Authority..."
sudo -u "$REAL_USER" mkcert -install

# Locate the generated Root CA
CA_ROOT="/home/$REAL_USER/.local/share/mkcert/rootCA.pem"

echo -e "\n---> Copying Root CA for the Vue frontend..."
# Copy it directly into the built Vue files so your popup can link to "/cnc-root.crt"
cp "$CA_ROOT" "$UI_DIST_DIR/cnc-root.crt"
chmod 644 "$UI_DIST_DIR/cnc-root.crt"

# 6. Generate the initial SSL Certificate
echo -e "\n---> Generating initial SSL certificate..."
sudo -u "$REAL_USER" mkdir -p "$CERT_DIR"
cd "$CERT_DIR"
ALL_IPS=$(hostname -I)
sudo -u "$REAL_USER" mkcert -cert-file localhost.pem -key-file localhost-key.pem localhost 127.0.0.1 $ALL_IPS

# 7. Configure Camera Service (ustreamer)
echo -e "\n---> Configuring uStreamer (USB Camera) service..."
USTREAMER_SERVICE="/etc/systemd/system/ustreamer.service"
cat << EOF > "$USTREAMER_SERVICE"
[Unit]
Description=uStreamer for CNC Camera
After=network.target

[Service]
Type=simple
User=$REAL_USER
ExecStart=/usr/bin/ustreamer --device /dev/video0 --host 127.0.0.1 --port 8081 --resolution 1280x720 --desired-fps 15
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ustreamer
systemctl restart ustreamer

# 7b. Configure the system backend service (machine + system split —
# see .agent/context/ARCHITECTURE.md). ONLY the system service (:8001)
# is a systemd unit: it owns every config/CRUD domain and must always
# be reachable, even while the machine backend or LinuxCNC itself is
# down. The machine backend (:8000) is deliberately NOT a unit — it is
# a program that gets started and shut off by the system service, like
# the LinuxCNC session it drives. Nginx (below) routes each path
# prefix to the service that owns it.
echo -e "\n---> Configuring backend services (system :8001 unit; machine :8000 is spawned by the system service)..."



SYSTEM_SERVICE="/etc/systemd/system/linuxcnc-ui-system.service"
cat << EOF > "$SYSTEM_SERVICE"
[Unit]
Description=LinuxCNC UI System Service (machine config, programs, macros, lifecycle — port 8001)
After=network.target

[Service]
Type=simple
User=$REAL_USER
WorkingDirectory=$PROJECT_DIR/backend/system
ExecStart=$PROJECT_DIR/backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8001
Restart=always
RestartSec=5
LimitMEMLOCK=infinity
# MachineLifecycleService spawns the LinuxCNC GUI, which needs a
# display; it already defaults to :0 if DISPLAY is unset, but a
# systemd unit has no environment of its own, so make it explicit.
Environment=DISPLAY=:0
KillMode=process

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable linuxcnc-ui-system
systemctl restart linuxcnc-ui-system

# 7c. Boot-time TLS certificate renewal.
#
# DHCP boxes get a new IP on every boot; an mkcert certificate that
# does not list the current IP makes browsers reject the HTTPS UI.
# start_network.sh re-mints the certificate for the current IPs and
# reloads nginx (passwordless via the sudoers rule in section 10), so
# run it as a oneshot on every boot once the network is up. Section 6
# already minted the initial certificate during this install — this
# unit keeps it fresh afterwards.
echo -e "\n---> Configuring boot-time certificate renewal (linuxcnc-ui-cert)..."
CERT_SERVICE="/etc/systemd/system/linuxcnc-ui-cert.service"
cat << EOF > "$CERT_SERVICE"
[Unit]
Description=LinuxCNC UI - re-mint TLS certificate for current IPs (start_network.sh)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$REAL_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/start_network.sh

[Install]
WantedBy=multi-user.target
EOF

chmod +x "$PROJECT_DIR/start_network.sh"
systemctl daemon-reload
systemctl enable linuxcnc-ui-cert

# 8. Fix Directory Permissions for Nginx
echo -e "\n---> Fixing directory permissions so Nginx can serve files..."
# Nginx (www-data user) needs traverse (execute) permissions up the entire directory tree
chmod 755 "/home/$REAL_USER"
chmod 755 "$PROJECT_DIR"
chmod -R 755 "$UI_DIST_DIR"

# 9. Configure Nginx
echo -e "\n---> Configuring Nginx..."
NGINX_CONF="/etc/nginx/sites-available/linuxcnc-ui"

cat << EOF > "$NGINX_CONF"
# HTTP Server (Port 80) - Used to show the Vue install popup
server {
    listen 80;
    server_name _;

    root $UI_DIST_DIR;
    index index.html;

    # Ensure the .crt file triggers a download with the correct MIME type
    location = /cnc-root.crt {
        types { application/x-x509-ca-cert crt; }
        default_type application/x-x509-ca-cert;
        add_header Content-Disposition 'attachment; filename="cnc-root.crt"';
    }

    location / {
        try_files \$uri \$uri/ /index.html;
    }

    # Proxy API and WebSockets so the app works on HTTP too
    # Two-backend routing (machine :8000 / system :8001 — see
    # .agent/context/ARCHITECTURE.md). A regex location always wins
    # over a prefix location in nginx regardless of file order, so
    # the macro-start exception is safe to declare anywhere; the
    # remaining plain-prefix locations are matched by longest prefix,
    # so the system-owned prefixes correctly win over the "/api/"
    # fallback without needing "^~".
    location ~ ^/api/v1/modules/macros/[^/]+/start\$ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
    location /api/v1/system/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
    location /api/v1/programs/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
    location /api/v1/modules/machineconfig/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
    location /api/v1/modules/macros/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "Upgrade";
        proxy_set_header Host \$host;
    }
}

# Application Server (Port 443 - HTTPS)
server {
    listen 443 ssl http2;
    server_name _;

    keepalive_timeout 75s;
    keepalive_requests 1000;

    ssl_certificate $CERT_DIR/localhost.pem;
    ssl_certificate_key $CERT_DIR/localhost-key.pem;

    root $UI_DIST_DIR;
    index index.html;

    location / {
        try_files \$uri \$uri/ /index.html;
    }
    # Two-backend routing (machine :8000 / system :8001 — see
    # .agent/context/ARCHITECTURE.md). A regex location always wins
    # over a prefix location in nginx regardless of file order, so
    # the macro-start exception is safe to declare anywhere; the
    # remaining plain-prefix locations are matched by longest prefix,
    # so the system-owned prefixes correctly win over the "/api/"
    # fallback without needing "^~".
    location ~ ^/api/v1/modules/macros/[^/]+/start\$ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
    location /api/v1/system/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
    location /api/v1/programs/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
    location /api/v1/modules/machineconfig/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
    location /api/v1/modules/macros/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "Upgrade";
        proxy_set_header Host \$host;
    }
}
EOF

# Enable the site and restart Nginx
ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
systemctl restart nginx

# 10. Configure sudoers for passwordless service management
#
# scripts/update.sh runs as $REAL_USER (not root) and needs to
# restart the system unit after pulling new code; start_network.sh
# (boot-time cert renewal) needs the nginx reload.
echo -e "\n---> Configuring passwordless service management for $REAL_USER..."
SUDOERS_FILE="/etc/sudoers.d/linuxcnc-ui"
# Superseded by the consolidated rule below (re-running install.sh
# on an already-installed machine would otherwise leave this stale).
rm -f "/etc/sudoers.d/linuxcnc-nginx-reload"

cat << EOF > "$SUDOERS_FILE"
$REAL_USER ALL=(ALL) NOPASSWD: /bin/systemctl reload nginx
$REAL_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart linuxcnc-ui-system
EOF

# Sudoers files must have strict permissions or the system will ignore them
chmod 0440 "$SUDOERS_FILE"

# Grab just the first IP address for a clean display output
DISPLAY_IP=$(echo $ALL_IPS | awk '{print $1}')

echo "=========================================="
echo " Installation Complete!"
echo " "
echo " App (HTTP Popup):   http://$DISPLAY_IP"
echo " App (HTTPS Secure): https://$DISPLAY_IP"
echo "=========================================="