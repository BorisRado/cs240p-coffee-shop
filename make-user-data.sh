#!/bin/bash
# Print the EC2 user data that installs the shop, for one release tag.
# Usage: ./make-user-data.sh v1.0 [github-owner]
#
# For TAs. Run it after you tag a release, and paste the output into the
# Lab 3.1 handout (Step 2.5). The sums pin the exact files: if anyone
# changes them on GitHub, the server refuses to install them.
set -euo pipefail
TAG=${1:?usage: $0 TAG [OWNER]}
OWNER=${2:-BorisRado}
cd "$(dirname "$0")"
if [ "$(git tag --list "$TAG" 2>/dev/null)" = "$TAG" ]; then
  SUMS=$(for f in shop.py coffee.service; do
    git show "$TAG:$f" | shasum -a 256 | sed "s/ .*/  $f/"; done)
else
  echo "warning: no tag $TAG yet; using the files on disk" >&2
  SUMS=$(shasum -a 256 shop.py coffee.service)
fi
cat <<EOF
#!/bin/bash
# Coffee shop $TAG. cloud-init runs this once, as root, at first boot.
set -euxo pipefail
REPO=https://raw.githubusercontent.com/$OWNER/cs240p-coffee-shop/$TAG
mkdir -p /opt/coffee
cd /opt/coffee
curl -fsSLO "\$REPO/shop.py"
curl -fsSLO "\$REPO/coffee.service"
sha256sum -c <<'SUMS'
$SUMS
SUMS
echo "COFFEE_MANAGER_PIN=CHANGE-ME" > /etc/coffee.env
chmod 600 /etc/coffee.env
cp coffee.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now coffee
EOF
