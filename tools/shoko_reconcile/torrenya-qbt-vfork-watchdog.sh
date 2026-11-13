#!/usr/bin/env bash
# Recover the specific qBittorrent Qt double-vfork helper hang observed in Torrenya.
# Never restarts/kills the main qBittorrent process and never triggers Shoko scans.
set -Eeuo pipefail
main="$(systemctl show --property=MainPID --value qbittorrent.service)"
[[ "$main" =~ ^[1-9][0-9]*$ ]] || exit 0
[[ -r "/proc/$main/task/$main/wchan" ]] || exit 0

# Running qBittorrent is not a problem; only inspect the observed blocked-vfork state.
# procfs wchan generally has no trailing newline: Bash `read` would return 1
# and `set -e` would silently terminate this watchdog before detecting a hang.
wchan="$(cat "/proc/$main/task/$main/wchan" 2>/dev/null || true)"
[[ "$wchan" == 'kernel_clone' ]] || exit 0
main_stat="$(ps -p "$main" -o stat= || true)"
[[ "$main_stat" == D* ]] || exit 0

# Do not gate on an HTTP probe: a WebUI worker may answer 403 while the
# qBittorrent main event loop is deadlocked. Require the exact process
# signature and a helper age >= 45s before terminating anything.

# QProcess::startDetached() uses a double-fork. Don't touch any unrelated child.
parent="$(pgrep -P "$main" -x qbittorrent-nox | head -n1 || true)"
[[ "$parent" =~ ^[1-9][0-9]*$ ]] || exit 0
leaf="$(pgrep -P "$parent" -x qbittorrent-nox | head -n1 || true)"
[[ "$leaf" =~ ^[1-9][0-9]*$ ]] || exit 0

parent_stat="$(ps -p "$parent" -o stat= || true)"
parent_wchan="$(cat "/proc/$parent/wchan" 2>/dev/null || true)"
leaf_age="$(ps -p "$leaf" -o etimes= | tr -d ' ' || true)"
[[ "$parent_stat" == D* && "$parent_wchan" == 'kernel_clone' ]] || exit 0
[[ "$leaf_age" =~ ^[0-9]+$ ]] || exit 0
(( leaf_age >= 45 )) || exit 0

# Check PID parentage once more before acting, avoiding a PID reuse race.
[[ "$(ps -p "$parent" -o ppid= | tr -d ' ')" == "$main" ]] || exit 0
[[ "$(ps -p "$leaf" -o ppid= | tr -d ' ')" == "$parent" ]] || exit 0
[[ "$(ps -p "$leaf" -o comm= | tr -d ' ')" == "qbittorrent-nox" ]] || exit 0
logger -t qbt-vfork-watchdog "WebUI stalled; main PID $main blocked in vfork; terminating stuck Qt helper PID $leaf (age ${leaf_age}s)"
kill -KILL "$leaf"
