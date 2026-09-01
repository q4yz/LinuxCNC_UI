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
echo -e "\n---> Setting up Python virtual environment (with system-site-packages)..."
cd "$PROJECT_DIR/backend"
sudo -u "$REAL_USER" python3 -m venv venv --system-site-packages
if [ -f "requirements.txt" ]; then
    sudo -u "$REAL_USER" ./venv/bin/pip install -r requirements.txt
fi

# --- Temporary Backend Spin-up ---
echo -e "\n---> Temporarily starting backend to generate API schema..."
sudo -u "$REAL_USER" ./venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

echo "Waiting for backend to expose OpenAPI schema..."
timeout 15 bash -c 'until curl -s http://127.0.0.1:8000/openapi.json > /dev/null; do sleep 1; done'

# 4. Set up the Frontend and Build
echo -e "\n---> Installing Frontend dependencies and building production app..."
cd "$PROJECT_DIR/frontend"
sudo -u "$REAL_USER" npm install

echo "Generating API client..."
sudo -u "$REAL_USER" npm run generate-api

echo "Building Vite application..."
sudo -u "$REAL_USER" npm run build

# --- CRITICAL: Clean up temporary Backend ---
echo "Tearing down temporary backend..."
kill $BACKEND_PID 2>/dev/null
wait $BACKEND_PID 2>/dev/null || true
# --------------------------------------------

# 5. Set up mkcert and the Root CA
echo -e "\n---> Configuring local Certificate Authority..."
sudo -u "$REAL_USER" mkcert -install

# Locate the generated Root CA
CA_ROOT=$(sudo -u "$REAL_USER" mkcert -CARoot)/rootCA.pem

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

# 8. Configure Nginx
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

# Application Server (Port 8080 - HTTPS)
server {
    listen 8080 ssl;
    server_name _;

    ssl_certificate $CERT_DIR/localhost.pem;
    ssl_certificate_key $CERT_DIR/localhost-key.pem;

    root $UI_DIST_DIR;
    index index.html;

    location / {
        try_files \$uri \$uri/ /index.html;
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



# 9. Configure sudoers for passwordless Nginx reload
echo -e "\n---> Configuring passwordless Nginx reloads for $REAL_USER..."
SUDOERS_FILE="/etc/sudoers.d/linuxcnc-nginx-reload"

# Write the rule dynamically using the detected user
echo "$REAL_USER ALL=(ALL) NOPASSWD: /bin/systemctl reload nginx" > "$SUDOERS_FILE"

# Sudoers files must have strict permissions or the system will ignore them
chmod 0440 "$SUDOERS_FILE"


echo "=========================================="
echo " Installation Complete!"
echo " "
echo " App (HTTP Popup):   http://$CURRENT_IP"
echo " App (HTTPS Secure): https://$CURRENT_IP:8080"
echo "=========================================="