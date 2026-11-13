#!/usr/bin/env bash
# qBittorrent completion hook -> one Shoko ImportNewFiles request 5 minutes
# after the most recent Anime-tagged completion (trailing-edge debounce).
# qBittorrent MUST invoke: /usr/local/bin/notify-shoko.sh "%G"
set -Eeuo pipefail
umask 077

# qBittorrent %G is a comma-separated list of tags. Fail closed when omitted.
# Filter *before* touching state so unrelated torrents cannot reset the timer.
if [[ "${1:-}" != '--worker' || "${SHOKO_NOTIFY_INTERNAL_WORKER:-}" != '1' ]]; then
    [[ $# -eq 1 ]] || exit 0
    matched=0
    IFS=',' read -r -a tags <<< "$1"
    for tag in "${tags[@]}"; do
        # Whitespace is not significant around comma-separated tag names.
        tag="${tag#"${tag%%[![:space:]]*}"}"
        tag="${tag%"${tag##*[![:space:]]}"}"
        if [[ "$tag" == 'Anime' ]]; then
            matched=1
            break
        fi
    done
    (( matched )) || exit 0
fi

STATE_DIR="${SHOKO_NOTIFY_STATE_DIR:-/var/lib/torrenya/shoko-notify}"
KEY_FILE="${SHOKO_NOTIFY_KEY_FILE:-/etc/torrenya/shoko-api-key}"
SHOKO_URL="${SHOKO_NOTIFY_URL:-http://10.169.2.151:8111/api/v3/Action/ImportNewFiles}"
DEBOUNCE_SECONDS="${SHOKO_NOTIFY_DEBOUNCE_SECONDS:-300}"
RETRY_SECONDS="${SHOKO_NOTIFY_RETRY_SECONDS:-60}"
SCRIPT="$(readlink -f -- "$0")"
STATE="$STATE_DIR/pending"
PID_FILE="$STATE_DIR/worker.pid"
LOCK="$STATE_DIR/state.lock"
LOG="$STATE_DIR/worker.log"

if [[ ! -d "$STATE_DIR" || ! -w "$STATE_DIR" ]]; then
    echo "notify-shoko: $STATE_DIR must exist and be writable by $(id -un)" >&2
    exit 1
fi
if [[ ! "$DEBOUNCE_SECONDS" =~ ^[1-9][0-9]*$ || ! "$RETRY_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
    echo 'notify-shoko: debounce/retry interval must be a positive integer' >&2
    exit 1
fi

# Both entry points share the same state lock. State format: epoch_seconds event_id.
read_state() {
    last=0
    seq=0
    if [[ -s "$STATE" ]]; then
        read -r last seq < "$STATE" || true
        [[ "$last" =~ ^[0-9]+$ && "$seq" =~ ^[0-9]+$ ]] || {
            echo 'notify-shoko: corrupt state file' >&2
            exit 1
        }
    fi
}
log() { printf '%s %s\n' "$(date -Is)" "$*"; }

if [[ "${1:-}" == '--worker' && "${SHOKO_NOTIFY_INTERNAL_WORKER:-}" == '1' ]]; then
    exec 9>"$LOCK"
    while true; do
        flock -x 9
        read_state
        if (( last == 0 )); then
            rm -f -- "$PID_FILE"
            flock -u 9
            exit 0
        fi
        remaining=$((last + DEBOUNCE_SECONDS - $(date +%s)))
        if (( remaining > 0 )); then
            flock -u 9
            sleep "$remaining"
            continue
        fi
        processing_seq="$seq"
        flock -u 9

        if [[ ! -r "$KEY_FILE" ]]; then
            log "ERROR: API key unreadable: $KEY_FILE"
            sleep "$RETRY_SECONDS"
            continue
        fi
        key="$(<"$KEY_FILE")"
        if [[ -z "$key" ]]; then
            log 'ERROR: API key empty'
            sleep "$RETRY_SECONDS"
            continue
        fi
        log "Requesting Shoko ImportNewFiles (event $processing_seq)"
        if curl -fsS --retry 3 --retry-delay 3 --connect-timeout 10 --max-time 60 \
            -H "apikey: $key" "$SHOKO_URL" >/dev/null; then
            flock -x 9
            read_state
            # If completions arrived during the API call, keep their new timer.
            if (( seq == processing_seq )); then
                printf '0 %s\n' "$seq" > "$STATE"
            fi
            flock -u 9
            log "Shoko scan requested successfully (event $processing_seq)"
        else
            log "ERROR: Shoko request failed; retrying after $RETRY_SECONDS seconds"
            # Preserve the pending request so the next run can also recover it.
            sleep "$RETRY_SECONDS"
        fi
    done
elif [[ $# -eq 1 ]]; then
    exec 9>"$LOCK"
    flock -x 9
    read_state
    printf '%s %s\n' "$(date +%s)" "$((seq + 1))" > "$STATE"
    if [[ ! -s "$PID_FILE" ]] || ! kill -0 "$(<"$PID_FILE")" 2>/dev/null; then
        # Never block qBittorrent for five minutes. The worker survives its shell.
        SHOKO_NOTIFY_INTERNAL_WORKER=1 nohup "$SCRIPT" --worker 9>&- </dev/null >>"$LOG" 2>&1 &
        printf '%s\n' "$!" > "$PID_FILE"
    fi
    flock -u 9
else
    echo 'Usage: notify-shoko.sh "%G" (qBittorrent tags argument)' >&2
    exit 2
fi
