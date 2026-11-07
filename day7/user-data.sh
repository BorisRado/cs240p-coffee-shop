#!/bin/bash
# Lab 7 launch-template user data. Runs reviews.py as a service on port 80,
# under the instance's coffee-app role. Amazon Linux 2023 (python3 and the
# aws CLI are already there). TAG is replaced by the release tag.
set -xe
TAG=day7-v1
REPO=https://raw.githubusercontent.com/BorisRado/cs240p-coffee-shop/$TAG/day7
cd /opt
curl -sSfO $REPO/reviews.py

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
cat > /etc/coffee.env <<EOF
ORDERS_BUCKET=cs240p-orders-$ACCOUNT
COFFEE_ADMIN_PASSWORD=barista2019
PORT=80
EOF

id coffee >/dev/null 2>&1 || useradd --system --no-create-home coffee
cat > /etc/systemd/system/coffee.service <<'EOF'
[Unit]
Description=Coffee shop reviews (Lab 7)
After=network-online.target

[Service]
EnvironmentFile=/etc/coffee.env
ExecStart=/usr/bin/python3 /opt/reviews.py
User=coffee
AmbientCapabilities=CAP_NET_BIND_SERVICE
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now coffee.service
