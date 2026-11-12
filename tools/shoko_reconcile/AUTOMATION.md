# Shoko ongoing indexing and conservative Reconciler fallback

Current target: Shoko 5.3.3 in Debian 13 LXC 2601 at 10.169.2.151, local read-only bind \`/Anime\` backed by \`/mnt/neko/Anime\` on mainserver. Never activate the known-failing FileSystemWatcher. No deletion or writes to torrent media by this tooling.

## Ensure new files remain readable

On **mainserver host**, newly created folders inherit GID 3000 (parent is setgid 2770). To give any group-3000 reader a stable read/traverse policy for future children:

\`\`\`sh
apt-get install -y acl
setfacl -m g:3000:r-X,d:g:3000:r-X /mnt/neko/Anime
getfacl /mnt/neko/Anime
\`\`\`

The torrent client's file-creation/chmod mode may override the ACL mask, so confirm its umask (recommend \`002\` or \`007\`) and check a **new** release. Existing release trees are **not recursively modified** by the commands above. In Shoko CT run \`runuser -u shoko -g anime -- find /Anime/NEW_RELEASE -maxdepth 2 -type f -readable -print\` and compare against \`find /Anime/NEW_RELEASE -type f\`. Shoko must have traversal on each directory, not just the root.

## Completion event: qBittorrent example (only if Torrenya is qBittorrent)

From Shoko CT (local API, protect key):
\`\`\`sh
export SHOKO_API_KEY='YOUR_PRIVATE_KEY'
curl -fsS -H "apikey: $SHOKO_API_KEY" http://127.0.0.1:8111/api/v3/ImportFolder | python3 -m json.tool
\`\`\`

Find the existing import-folder ID for \`/Anime\` from the response; replace \`<IMPORT_ID>\` below. The authenticated **GET** \`/api/v3/ImportFolder/{id}/Scan\` queues a scan; verify it once from Shoko CT.

Configure qBittorrent \`Options → Downloads → Run external program on torrent completion\` to call a local executable script in the torrent CT. Example \`/usr/local/bin/notify-shoko.sh\` (Shoko key stored in a readable-to-client-user-only local file at \`/etc/torrenya/shoko-api-key\`):

\`\`\`sh
#!/bin/sh
set -eu
KEY=$(cat /etc/torrenya/shoko-api-key)
curl --fail --silent --show-error --retry 3 --connect-timeout 4 \
  -H "apikey: $KEY" \
  "http://10.169.2.151:8111/api/v3/ImportFolder/<IMPORT_ID>/Scan" >/dev/null
\`\`\`

External program field: \`/usr/local/bin/notify-shoko.sh\`. Adapt the completion hook if the downloader is not qBittorrent. Limit access to the Shoko API port to your trusted private LAN. A successful call means scan was requested, **not** that ED2K/AniDB jobs have already finished. Optional slow periodic import-folder scan is a recovery for missed completion events. Do not run two scans per file or scan half-written files.

## Conservative fallback after Shoko failed

One-shot \`auto_fallback.py\` on **Shoko CT** checks only current \`Unrecognized\` API records. On first observation it records file path, size, mtime and first-seen time. On later runs, after at least 15 minutes with unchanged file state, it prepares a **new** plan, restricts links to strong independent identity evidence (curated public crosswalk, verified exact title, or unambiguous high-score Shoko candidate), and lets the existing \`apply()\` re-check live File ID/path/AniDB ID/episode type+number. Ambiguous franchises, specials and shifted episode numbers remain for review. No forced false links for achieving 100%.

In Shoko CT:
\`\`\`sh
install -d -o shoko -g anime -m 0700 /var/lib/shoko-reconcile
# /etc/shoko-reconcile.env is read by systemd, owned root:shoko and mode 0640:
# SHOKO_API_KEY=<PRIVATE_KEY>
# SHOKO_URL=http://127.0.0.1:8111
\`\`\`

Sample units \`/etc/systemd/system/shoko-reconcile.service\`:
\`\`\`ini
[Unit]
Description=Shoko post-index conservative identification fallback
After=shoko.service

[Service]
Type=oneshot
User=shoko
Group=anime
UMask=0077
WorkingDirectory=/opt/tethys-anime-hub/tools/shoko_reconcile
EnvironmentFile=/etc/shoko-reconcile.env
ExecStart=/usr/bin/python3 auto_fallback.py --catalog /var/cache/tethys/anime-offline-database.jsonl --minimum-age 900 --apply --confirm LINK
\`\`\`

\`/etc/systemd/system/shoko-reconcile.timer\`:
\`\`\`ini
[Unit]
Description=Reconcile truly unknown Shoko files every five minutes

[Timer]
OnBootSec=5min
OnUnitInactiveSec=5min
Persistent=true
Unit=shoko-reconcile.service

[Install]
WantedBy=timers.target
\`\`\`

Activate: \`systemctl daemon-reload && systemctl enable --now shoko-reconcile.timer\`. Monitor \`journalctl -u shoko-reconcile.service -n 100 --no-pager\`. Run \`python3 auto_fallback.py\` without \`--apply\` for a dry-run. Do **not** use the old bulk plan for automatic processing. The same file remains in the Shoko API Unrecognized list until ManualLinkJob actually completes.

## Multiple releases vs false links

Shoko UI **Utilities → Release Management → Multiples** lists *different files attached to the same episode*. It is not proof of identical binary file hashes, and the GUI contains **red Delete controls which must not be used for this audit**. Shoko's official docs explicitly support keeping variations: https://docs.shokoanime.com/shoko-server/release-management

Archived owner's plan (not copied into Git) documented two series of files:
- 5-toubun no Hanayome [OVA] / AniLiberty: file IDs 417 and 418 → AniDB 17968, episodes 1 and 2.
- Go-Toubun no Hanayome~ / AniLibria: file IDs 778 and 779 → AniDB 17968, episodes 1 and 2.

These may be **two releases of the same two-part special**, not four distinct episodes. Verify video identity by comparing durations and several actual frames before any unlink. The manual Reconciler can correctly link multiple encodings to one episode. If content differs, investigate incorrect manual links individually; never delete MKV or use \`DELETE /File/Location\` as a substitute for unlinking an episode.
