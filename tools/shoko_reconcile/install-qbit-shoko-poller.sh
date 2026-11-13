#!/usr/bin/env bash
# Migrate Torrenya from qBittorrent QProcess completion hook to independent API polling.
# Run as root in CT 540. Does not restart qBittorrent or modify torrent data.
set -Eeuo pipefail
umask 077

(( EUID == 0 )) || { echo "Run as root inside Torrenya CT 540" >&2; exit 1; }
id kotaru >/dev/null
command -v python3 >/dev/null
command -v curl >/dev/null
command -v setfacl >/dev/null || { echo "Missing setfacl (install package acl)" >&2; exit 1; }

SOURCE="https://raw.githubusercontent.com/kotaru34/tethys-anime-hub/main/tools/shoko_reconcile/qbit_shoko_poller.py"
DEST="/usr/local/libexec/qbit_shoko_poller.py"
CONFIG="/etc/torrenya/qbit-shoko-poller.json"
STATE_DIR="/var/lib/torrenya/shoko-poller"

# One-shot recovery of the already-observed double-vfork hang if qBittorrent
# happens to be stuck *right now*. Do not keep the old watchdog enabled.
main="$(systemctl show -P MainPID qbittorrent.service 2>/dev/null || true)"
if [[ "$main" =~ ^[1-9][0-9]*$ ]] &&
   [[ "$(cat "/proc/$main/task/$main/wchan" 2>/dev/null || true)" == kernel_clone ]] &&
   [[ "$(ps -p "$main" -o stat= 2>/dev/null || true)" == D* ]]; then
    parent="$(pgrep -P "$main" -x qbittorrent-nox | head -n1 || true)"
    leaf=""
    if [[ "$parent" =~ ^[1-9][0-9]*$ ]]; then
        leaf="$(pgrep -P "$parent" -x qbittorrent-nox | head -n1 || true)"
    fi
    if [[ "$leaf" =~ ^[1-9][0-9]*$ ]] &&
       [[ "$(cat "/proc/$parent/wchan" 2>/dev/null || true)" == kernel_clone ]] &&
       [[ "$(ps -p "$parent" -o stat= 2>/dev/null || true)" == D* ]] &&
       [[ "$(ps -p "$leaf" -o ppid= | tr -d ' ')" == "$parent" ]]; then
        echo "Releasing known Qt fork hang via stuck grandchild PID $leaf (main $main preserved)"
        kill -KILL "$leaf"
        sleep 2
    fi
fi

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
curl -fsSL --connect-timeout 10 --max-time 45 "$SOURCE" -o "$tmp"
python3 -m py_compile "$tmp"
install -d -o root -g root -m 0755 /usr/local/libexec
install -o root -g root -m 0755 "$tmp" "$DEST"

# Existing Shoko key ACL, now restricted to the same local qBittorrent account.
setfacl -m u:kotaru:--x /etc/torrenya
setfacl -m u:kotaru:r-- /etc/torrenya/shoko-api-key
install -d -o kotaru -g "$(id -gn kotaru)" -m 0700 "$STATE_DIR"

echo "Setting up qBittorrent read-only API access and disabling the old completion command."
python3 "$DEST" --config "$CONFIG" --configure
chown kotaru:"$(id -gn kotaru)" "$CONFIG"
chmod 0600 "$CONFIG"

# Disable obsolete watchdog before activating the new design.
systemctl disable --now torrenya-qbt-vfork-watchdog.timer 2>/dev/null || true
systemctl stop torrenya-qbt-vfork-watchdog.service 2>/dev/null || true

cat >/etc/systemd/system/qbit-shoko-poller.service <<'EOF'
[Unit]
Description=Independent qBittorrent Anime completion observer to Shoko
Wants=network-online.target
After=network-online.target qbittorrent.service

[Service]
Type=simple
User=kotaru
Group=kotaru
ExecStart=/usr/bin/python3 /usr/local/libexec/qbit_shoko_poller.py
Restart=always
RestartSec=30
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/lib/torrenya/shoko-poller
UMask=0077

[Install]
WantedBy=multi-user.target
EOF

# Verify qBittorrent authentication and initialize the snapshot WITHOUT
# requesting a Shoko scan (existing completed Anime are merely baselined).
runuser -u kotaru -- python3 "$DEST" --once
systemctl daemon-reload
systemctl enable --now qbit-shoko-poller.service
systemctl is-active --quiet qbit-shoko-poller.service

echo
echo "SUCCESS. qBittorrent completion hook DISABLED; no qBittorrent restarts."
echo "Independent observer: qbit-shoko-poller.service (every 30s, Anime only)"
echo "Shoko scan: only after 300s without another Anime completion"
echo "Obsolete vfork watchdog timer disabled."
echo "Logs: journalctl -u qbit-shoko-poller.service -f"
