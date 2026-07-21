#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/speech-flow
STATE_DIR=/var/lib/speech-flow

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
    ffmpeg \
    fonts-liberation \
    fonts-noto-cjk \
    libgomp1 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    nginx \
    python3-pip \
    python3-venv

if ! id speechflow >/dev/null 2>&1; then
    useradd --system --home-dir "$STATE_DIR" --create-home --shell /usr/sbin/nologin speechflow
fi

install -d -o speechflow -g speechflow -m 0750 "$STATE_DIR/jobs" "$STATE_DIR/backups"

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

sed -i \
    -e "s|^SFA_JOBS_DIR=.*|SFA_JOBS_DIR=$STATE_DIR/jobs|" \
    -e "s|^SFA_AUTH_DB=.*|SFA_AUTH_DB=$STATE_DIR/auth.db|" \
    -e "s|^SFA_CHROME_NO_SANDBOX=.*|SFA_CHROME_NO_SANDBOX=false|" \
    "$APP_DIR/.env.production"

install -o root -g root -m 0644 "$APP_DIR/deploy/native/speech-flow.service" /etc/systemd/system/speech-flow.service
install -o root -g root -m 0644 "$APP_DIR/deploy/native/nginx.conf" /etc/nginx/sites-available/speech-flow
ln -sfn /etc/nginx/sites-available/speech-flow /etc/nginx/sites-enabled/speech-flow
rm -f /etc/nginx/sites-enabled/default

nginx -t
systemctl daemon-reload
systemctl enable --now speech-flow
systemctl enable --now nginx
