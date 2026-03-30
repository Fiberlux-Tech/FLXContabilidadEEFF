#!/bin/bash
# Run this script with: sudo bash setup_infrastructure.sh
# Optional: pass APP_ROOT as first argument (default: directory containing this script)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT="${1:-$SCRIPT_DIR}"
APP_USER="${APP_USER:-administrator}"

echo "=== 1. Updating nginx config ==="
cat > /etc/nginx/sites-enabled/myapp << NGINXEOF
server {
    listen 80;
    server_name 10.100.50.4 10.100.23.164;

    root ${APP_ROOT}/frontend/dist;
    index index.html;

    location / {
        try_files \$uri \$uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Cookie \$http_cookie;
        proxy_pass_header Set-Cookie;
    }

    location /auth/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Cookie \$http_cookie;
        proxy_pass_header Set-Cookie;
    }
}
NGINXEOF

echo "=== 2. Testing nginx config ==="
nginx -t

echo "=== 3. Updating systemd service ==="
cat > /etc/systemd/system/flxcontabilidad.service << SERVICEEOF
[Unit]
Description=Gunicorn instance to serve FLXContabilidad
After=network.target

[Service]
Type=notify
User=${APP_USER}
Group=www-data
WorkingDirectory=${APP_ROOT}/backend
Environment="PATH=${APP_ROOT}/venv/bin"
EnvironmentFile=${APP_ROOT}/.env
ExecStart=${APP_ROOT}/venv/bin/gunicorn --config gunicorn.conf.py app:app
ExecReload=/bin/kill -s HUP \$MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SERVICEEOF

echo "=== 4. Stopping old service ==="
systemctl stop plantillaapi 2>/dev/null || true
systemctl disable plantillaapi 2>/dev/null || true

echo "=== 5. Starting new service ==="
systemctl daemon-reload
systemctl enable flxcontabilidad
systemctl start flxcontabilidad

echo "=== 6. Reloading nginx ==="
systemctl reload nginx

echo "=== 7. Checking status ==="
systemctl status flxcontabilidad --no-pager
echo ""
echo "=== DONE! ==="
echo "Visit http://10.100.50.4 to verify"
