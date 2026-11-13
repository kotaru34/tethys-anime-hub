# Native Shoko 5.3.3 event-driven Reconciler (no periodic timer)

Shoko **5.3.3** has a real-time SignalR endpoint at `/signalr/aggregate?feeds=shoko,queue`, authenticated with the `apikey` header. Read the exact v5.3.3 C# implementations: `API/SignalR/Aggregate/{AggregateHub,ShokoEventEmitter,QueueEmitter}.cs`.

- `Shoko:FileNotMatched`: emitted when Shoko has processed a file but not identified an AniDB match.
- `Queue:QueueStateChanged`: emitted when the Shoko job queue changes; wait for **idle**.
- `Queue:OnConnected`: initial status sent upon subscription.
- The service also inspects existing Unrecognized files on startup or reconnect to catch missed events. It never runs an unconditional recurring scan.
- After event and a grace period for files to finish writing, the fallback revalidates on disk, Shoko API, series identity and episode type. Low-confidence matches are excluded. An exact, publisher-verified release override resolves the 2024 Go-Toubun specials without excluding valid 2023 specials or Tensura OVA.
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
python3 relink_go_toubun_2024.py --diagnose      # inspect episode type/number and Shoko job queue
python3 relink_go_toubun_2024.py --refresh       # if episodes have not appeared after initial refresh
python3 relink_go_toubun_2024.py --force-refresh # optional if cached AniDB episode list stays incomplete
python3 relink_go_toubun_2024.py --apply --confirm RELINK # only after dry-run success
```

`LinkFromSeries` removes old manual cross-references and queues new manual links through Shoko's own API. Do not call delete-file endpoints; MKVs and torrents must remain untouched.

The matching rule no longer rejects all franchise specials/OVA; a regression analysis of 83 archived release groups found that broad rule suppressed 9 valid links (981 -> 972). The precise verified-release override preserves 981 potential links (57 deferred) while correcting IDs 778 and 779 from 17968 to 18603. **An explicit public source confirming a release's year is stronger than filename punctuation.** For future verified one-off corrections, use user-curated private overrides instead of global fuzzy title normalization.

## 2024 AniDB episode-type discrepancy

AniDB 18603 was observed on the live Shoko 5.3.3 instance as E01, O01 and O02, **not E01/E02**, even after force refresh. The theatrical edit and 2-part TV edit may be different representations. This must be verified from actual AniDB episode titles before linking. `relink_go_toubun_2024.py --diagnose` prints episode type, number, title, date and duration. If and only if O01/O02 correspond to the two downloaded 2024 broadcast halves, run `--target-type Other` as dry-run, then `--target-type Other --apply --confirm RELINK_OTHER` to update the two manual links. Never map O01/O02 solely because E02 is absent. Shoko API `LinkFromSeries` supports the `O` prefix for Other. No repeated AniDB force refresh is necessary after metadata appears.
