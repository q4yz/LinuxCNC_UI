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
GATEWAY_DIR="/var/www/cnc-gateway"
UI_DIST_DIR="$PROJECT_DIR/frontend/dist"

echo "=========================================="
echo " Starting LinuxCNC UI Installation"
echo " User: $REAL_USER"
echo " Project Dir: $PROJECT_DIR"
echo "=========================================="

# 1. Update and install core system packages
echo -e "\n---> Installing system dependencies (Nginx, Python venv, mkcert)..."
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
# Run as the real user to prevent permission issues
sudo -u "$REAL_USER" python3 -m venv venv --system-site-packages
# Install python requirements if a requirements file exists
if [ -f "requirements.txt" ]; then
    sudo -u "$REAL_USER" ./venv/bin/pip install -r requirements.txt
fi

# 4. Set up the Frontend and Build
echo -e "\n---> Installing Frontend dependencies and building production app..."
cd "$PROJECT_DIR/frontend"
sudo -u "$REAL_USER" npm install
# (Assuming you want Nginx to serve the built static files rather than the dev server)
sudo -u "$REAL_USER" npm run build

# 5. Set up mkcert and the Gateway Page
echo -e "\n---> Configuring local Certificate Authority..."
# Install mkcert into the real user's trust store
sudo -u "$REAL_USER" mkcert -install

# Locate the generated Root CA
CA_ROOT=$(sudo -u "$REAL_USER" mkcert -CARoot)/rootCA.pem

echo -e "\n---> Setting up the Port 80 Download Gateway..."
mkdir -p "$GATEWAY_DIR"
# Copy and rename the Root CA so mobile devices recognize it
cp "$CA_ROOT" "$GATEWAY_DIR/cnc-root.crt"


# 6. Generate the initial SSL Certificate (so Nginx doesn't crash on boot)
echo -e "\n---> Generating initial SSL certificate..."
sudo -u "$REAL_USER" mkdir -p "$CERT_DIR"
cd "$CERT_DIR"
CURRENT_IP=$(hostname -I | awk '{print $1}')
sudo -u "$REAL_USER" mkcert -cert-file localhost.pem -key-file localhost-key.pem localhost 127.0.0.1 "$CURRENT_IP"

# 7. Configure Nginx
echo -e "\n---> Configuring Nginx..."
NGINX_CONF="/etc/nginx/sites-available/linuxcnc-ui"

cat << EOF > "$NGINX_CONF"
# Gateway Server (Port 80)
server {
    listen 80;
    server_name _;

    root $GATEWAY_DIR;
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
}

# Application Server (Port 8080 - HTTPS)
server {
    listen 8080 ssl;
    server_name _;

    ssl_certificate $CERT_DIR/localhost.pem;
    ssl_certificate_key $CERT_DIR/localhost-key.pem;

    # Serve the built Vue frontend
    root $UI_DIST_DIR;
    index index.html;

    location / {
        try_files \$uri \$uri/ /index.html;
    }

    # Proxy API calls to FastAPI (Port 8000)
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }

    # Proxy WebSockets to FastAPI
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

echo "=========================================="
echo " Installation Complete!"
echo " "
echo " Gateway is live at: http://$CURRENT_IP"
echo " App is live at:     https://$CURRENT_IP:8080"
echo "=========================================="