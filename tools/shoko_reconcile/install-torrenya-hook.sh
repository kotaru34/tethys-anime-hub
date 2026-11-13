#!/usr/bin/env bash
# One-time root-side repair/install of the existing qBittorrent -> Shoko hook.
# Does not restart or change the qBittorrent process, torrents or Shoko.
set -Eeuo pipefail
umask 077

if (( EUID != 0 )); then
  echo "Run this installer as root inside Torrenya CT 540" >&2
  exit 1
fi

QB_USER="kotaru"
KEY="/etc/torrenya/shoko-api-key"
HOOK="/usr/local/bin/notify-shoko.sh"
STATE="/var/lib/torrenya/shoko-notify"
WATCHDOG="/usr/local/libexec/torrenya-qbt-vfork-watchdog.sh"
WATCH_SOURCE="https://raw.githubusercontent.com/kotaru34/tethys-anime-hub/main/tools/shoko_reconcile/torrenya-qbt-vfork-watchdog.sh"
SOURCE="https://raw.githubusercontent.com/kotaru34/tethys-anime-hub/8507ca7dd1593b5bd589ce3f0cf3a636c996ec84/tools/shoko_reconcile/notify-shoko.sh"

id "$QB_USER" >/dev/null
[[ -s "$KEY" ]] || { echo "Missing or empty Shoko API key at $KEY" >&2; exit 1; }
command -v setfacl >/dev/null || { echo "setfacl is required (package: acl)" >&2; exit 1; }
command -v curl >/dev/null || { echo "curl is required" >&2; exit 1; }

# Restrict the existing secret to exactly the qBittorrent service account.
setfacl -m "u:$QB_USER:--x" /etc/torrenya
setfacl -m "u:$QB_USER:r--" "$KEY"

install -d -o "$QB_USER" -g "$(id -gn "$QB_USER")" -m 0700 "$STATE"
runuser -u "$QB_USER" -- test -r "$KEY"
runuser -u "$QB_USER" -- test -w "$STATE"

tmp="$(mktemp)"
watchtmp="$(mktemp)"
trap 'rm -f "$tmp" "$watchtmp"' EXIT
curl -fsSL --connect-timeout 10 --max-time 45 "$SOURCE" -o "$tmp"
bash -n "$tmp"
# Prevent accidentally installing an older or unrelated hook.
grep -q 'SHOKO_NOTIFY_DEBOUNCE_SECONDS:-300' "$tmp"
grep -q 'SHOKO_NOTIFY_INTERNAL_WORKER' "$tmp"
grep -q 'Anime' "$tmp"
curl -fsSL --connect-timeout 10 --max-time 45 "$WATCH_SOURCE" -o "$watchtmp"
bash -n "$watchtmp"
grep -q 'kernel_clone' "$watchtmp"

if [[ -f "$HOOK" ]]; then
  backup="$HOOK.backup-$(date +%Y%m%d-%H%M%S)"
  cp -a "$HOOK" "$backup"
  echo "Backed up previous hook: $backup"
fi
install -o root -g root -m 0755 "$tmp" "$HOOK"
install -d -o root -g root -m 0755 /usr/local/libexec
install -o root -g root -m 0755 "$watchtmp" "$WATCHDOG"

# Watchdog does NOT request Shoko scans. It only recovers an observed Qt helper stall.
cat > /etc/systemd/system/torrenya-qbt-vfork-watchdog.service <<EOF
[Unit]
Description=Recover stuck qBittorrent Qt double-vfork launch without restarting torrents
[Service]
Type=oneshot
ExecStart=$WATCHDOG
TimeoutStartSec=20
EOF
cat > /etc/systemd/system/torrenya-qbt-vfork-watchdog.timer <<'EOF'
[Unit]
Description=Check qBittorrent for the known Qt helper stall (no Shoko scans)
[Timer]
OnBootSec=90s
OnUnitActiveSec=30s
AccuracySec=10s
Unit=torrenya-qbt-vfork-watchdog.service
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now torrenya-qbt-vfork-watchdog.timer

# A non-Anime event must not create or update debounce state.
runuser -u "$QB_USER" -- "$HOOK" "Games"
echo "Installed: $HOOK"
echo "State directory: $STATE (owned by $QB_USER, mode 0700)"
echo "qBittorrent UI: Settings -> Downloads -> Run external program on torrent completion"
echo 'Use exactly: /usr/local/bin/notify-shoko.sh "%G"'
echo 'Tag must be exactly: Anime'
echo 'No torrent process was restarted. The qBittorrent recovery watchdog timer is active.'
echo
echo "Potential *additional* automated Shoko import callers on this CT:"
if grep -RIlE '(/Action/ImportNewFiles|/ImportFolder/[0-9]+/Scan)' /etc/systemd/system /etc/cron.d /etc/crontab /etc/cron.hourly /etc/cron.daily /etc/cron.weekly /etc/cron.monthly 2>/dev/null; then
  echo "Review the listed units/jobs: they may trigger duplicate scans."
else
  echo "None found in the checked systemd/cron paths."
fi
