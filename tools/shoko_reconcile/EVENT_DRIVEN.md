# Native Shoko 5.3.3 event-driven Reconciler (no periodic timer)

Shoko **5.3.3** has a real-time SignalR endpoint at `/signalr/aggregate?feeds=shoko,queue`, authenticated with the `apikey` header. Read the exact v5.3.3 C# implementations: `API/SignalR/Aggregate/{AggregateHub,ShokoEventEmitter,QueueEmitter}.cs`.

- `Shoko:FileNotMatched`: emitted when Shoko has processed a file but not identified an AniDB match.
- `Queue:QueueStateChanged`: emitted when the Shoko job queue changes; wait for **idle**.
- `Queue:OnConnected`: initial status sent upon subscription.
- The service also inspects existing Unrecognized files on startup or reconnect to catch missed events. It never runs an unconditional recurring scan.
- After event and a grace period for files to finish writing, the fallback revalidates on disk, Shoko API, series identity and episode type. Files with ambiguous sequels/specials are **excluded**.
- The downloader still invokes `GET /api/v3/Action/ImportNewFiles` upon torrent completion. This is separate from the fallback and is required because Shoko's FileSystemWatcher is disabled after its known crash.

## Shoko CT installation

```sh
cd /opt/tethys-anime-hub
git pull --ff-only
apt-get install -y python3-venv
python3 -m venv /opt/tethys-anime-hub/.venv-shoko
/opt/tethys-anime-hub/.venv-shoko/bin/pip install 'websocket-client>=1.8,<2'
install -d -o shoko -g anime -m 0700 /var/lib/shoko-reconcile
install -o root -g anime -m 0640 /dev/null /etc/shoko-reconcile.env
# Edit it to set SHOKO_API_KEY and SHOKO_URL=http://127.0.0.1:8111.
```

First, use read-only mode; do not enable automatic writes before verifying the observed websocket event log:

```ini
# /etc/systemd/system/shoko-reconcile-events.service
[Unit]
Description=Shoko SignalR Reconciler (event-driven)
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=shoko
Group=anime
WorkingDirectory=/opt/tethys-anime-hub/tools/shoko_reconcile
EnvironmentFile=/etc/shoko-reconcile.env
ExecStart=/opt/tethys-anime-hub/.venv-shoko/bin/python event_bridge.py
Restart=always
RestartSec=5
UMask=0077

[Install]
WantedBy=multi-user.target
```

```sh
systemctl daemon-reload
systemctl disable --now shoko-reconcile.timer 2>/dev/null || true
systemctl enable --now shoko-reconcile-events.service
journalctl -u shoko-reconcile-events.service -f
```

Once **tested on the real Shoko CT**, add `--apply --confirm LINK` to `ExecStart` and restart the service. The listener stays connected and subscribes to events; it does not poll with systemd timers. Reconnects on socket errors.

**Safety:** always leave Shoko `Watch For New Files = Off` in this installation; this SignalR stream is a downstream notification channel, not an inotify replacement for triggering initial detection.

## Repair Go-Toubun 2024 mislinks safely

An older offline plan wrongly selected 2023 AniDB 17968 for two 2024 special MKVs (Shoko File IDs 778 and 779). The target is AniDB 18603, normal episodes 1 and 2. Evidence:
- https://anilibria.tv/release/go-toubun-no-hanayome.html (2023)
- https://anilibria.tv/release/5-toubun-no-hanayome-specials2.html (2024)

```sh
cd /opt/tethys-anime-hub
git pull --ff-only
cd tools/shoko_reconcile
# With SHOKO_API_KEY exported:
python3 relink_go_toubun_2024.py                 # dry-run, strict file ID/path/old link checks
python3 relink_go_toubun_2024.py --refresh       # only if new AniDB series not loaded
python3 relink_go_toubun_2024.py --apply --confirm RELINK # only after dry-run success
```

`LinkFromSeries` removes old manual cross-references and queues new manual links through Shoko's own API. Do not call delete-file endpoints; MKVs and torrents must remain untouched.

The matching rule treats franchise specials/OVA plus nearby alternative titles as ambiguous, regardless of a perfect title similarity score. **An explicit public source confirming a release's year is stronger than filename punctuation.** For future verified one-off corrections, use user-curated private overrides instead of global fuzzy title normalization.
