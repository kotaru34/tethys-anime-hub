# Deployment topology – storage-local Shoko, GPU-local Jellyfin

**Decision: 2026-11-11. Current plan for a clean reinstall. This supersedes the earlier all-in-one LXC plan in [NATIVE_LXC.md](NATIVE_LXC.md) and the older Docker/VM plan in [DEPLOY.md](DEPLOY.md).**

## Confirmed infrastructure and chosen placement

| Component | Placement | Rationale |
| --- | --- | --- |
| Anime storage | Second PVE host at **10.169.6.200**, physical anime disk mounted under **/mnt/neko/Anime** | Source of truth; files are active torrent releases and must never be modified by catalog services |
| **Shoko Server** | **New unprivileged Debian 13 LXC on the storage PVE host** (10.169.6.200) | Hash ED2K locally without sending whole files through NFS; Shoko's own database/config/cache stays local to Shoko |
| **Jellyfin 10.11.11 + Shokofin 6.0.5** | **New unprivileged Debian 13 LXC on the i5-9300H / Intel UHD 630 PVE host** | Direct Play/remux and Intel QSV from `/dev/dri/renderD*`; preserve host laptop screen and do not use occupied GTX1650 |
| **Tethys FastAPI + worker** | Same LXC as Jellyfin, native Python virtualenv + systemd | Low footprint; call local Jellyfin API, remote Shoko API and existing PostgreSQL |
| **Tethys PostgreSQL** | Existing independent PostgreSQL server on private LAN | Dedicated DB and account; **no new PostgreSQL deployment** |
| LLM | Existing Qwen llama-server on V100 when needed | No GPU passthrough to Shoko/Tethys and no always-on inference |
| Containers/runtime | Native services in **two LXCs**; no Docker, no VM | The two-LXC separation is because storage-local hashing and GPU-local playback belong on different PVE hosts |

Do not assume specific new CT IDs, storage pool, CPU/RAM sizes, PostgreSQL address or downloader identity until checked. LXC 1510 (10.169.2.151) was used in the **superseded first attempt**, not a requirement for the clean install.

## Media path conventions

- Storage PVE host: **/mnt/neko/Anime**, actual local underlying filesystem (verify with `findmnt -T /mnt/neko/Anime` on that host).
- New Shoko LXC: **/Anime**, bind-mounted read-only from the storage host's local directory.
- New Jellyfin/Tethys LXC: **/Anime**, read-only NFS mount via PVE host from storage export `10.169.6.200:/mnt/neko` with subdir `Anime`.
- Same canonical `/Anime` spelling across both LXCs makes Shoko-produced paths usable through Shokofin. Verify actual Shokofin path translation and generated VFS; symlinks/VFS are managed in the **writable Jellyfin data directory**, never under `/Anime`.
- Use dedicated service users and group-based read/traverse permissions, never `chmod -R 777` or `chown -R` on torrents. Source directory observed `3000:3000`, mode `2770`. In the first (NFS) LXC, unprivileged GID 3000 remap was required and **primary** `anime` GID 3000 worked whereas a supplementary GID 3000 did not. Test and configure each new host/LXC independently – the storage-local bind mount may have different behavior.
- NFS source remains read-only for media consumers, including the Tethys worker. Absence of an NFS mount is a hard error; avoid treating it as empty media.

## Known blocker / must-not-repeat from first installation

Shoko 5.3.3 was initially installed natively in the Jellyfin LXC and an Import Folder `/Anime` was saved with `Watch For New Files = Yes`. The .NET `FileSystemWatcher` entered a repeated **`WatcherOnError() → Start()`** loop; Save hung, and after systemd restart Shoko hung at **"Initializing File Watchers"**. Read access as user `shoko` with primary group `anime` was already proven fine. Recovery required stopping Shoko, **backing up its private SQLite DB `JMMServer.db3`** and changing `ImportFolder.IsWatched` to `0`; afterward Shoko booted normally. Do not assume a simple restart repairs a faulty watcher.

On fresh Shoko installation:
1. Configure Import Folder **Name=Anime, Path=/Anime, Drop Type=None, Watch For New Files=No** until the real cause of watcher failure is isolated and its safety verified.
2. Confirm a new folder creates a DB entry and scan through Shoko's UI/API; do not repeatedly press Save if it hangs.
3. Avoid enabling Shoko file renamer, move-on-import, or writeback into torrents. All source mounts remain read-only.
4. Never edit SQLite while Shoko runs. If recovery is ever needed, stop service, find actual DB path, take a consistent backup, inspect table/schema before any surgical update.

**Instant-new-file requirement:** User expects newly completed anime to be discovered within seconds, not on a six-hour polling schedule. Do *not* assume `inotify` on an NFS client observes writes made remotely. Even a storage-local watcher only receives locally generated filesystem events when the relevant writer and mount semantics support it; if the downloader writes through another NFS client, the storage server's local watcher may not see those remote changes either. Prefer an **event/completion hook on the actual torrent client or writer** to call an authenticated Shoko Import Folder scan (or safe per-file discovery API), with short debounce and completed-file checks. Use periodic low-frequency scans only as a recovery fallback, not the primary discovery path. Verify API path and authentication against the running Shoko 5.3.3; do not expose it publicly.

Source inspection confirms Shoko 5.3.3 `FileWatcherService` only starts watchers for `IsWatched=1`; `ImportFolderController` supports `GET /api/v3/ImportFolder/{folderID}/Scan` for authenticated folder scanning. See [upstream code](https://github.com/ShokoAnime/ShokoServer/blob/v5.3.3/Shoko.Server/API/v3/Controllers/ImportFolderController.cs). No assumptions about the torrent client's own completion hook before identifying the software.

## Clean install sequence

1. **On storage PVE host**, verify filesystem is local to that host, its real source path, read-only bind mount availability, CPU/RAM, and downloader/write path. Create a new unprivileged Debian 13 LXC for Shoko with suitable CPU for hashing, local SSD root/state, and no GPU. Map group as required; verify `runuser -u shoko -g anime -- ls /Anime` after creating user. Install exact **Shoko Server 5.3.3**, .NET 8 runtime and native dependencies; use systemd. Make its database and settings backup plan.
2. Register Shoko import folder **with watcher off**. Start initial scan; validate ED2K hashing and AniDB mappings; ensure import/rename options cannot write to release files.
3. **On i5-9300H PVE host**, create a fresh unprivileged Debian 13 LXC for Jellyfin + Tethys. Bind the existing NFS source read-only as `/Anime`, and verify media group access. Pass only the Intel render DRM node through Proxmox's LXC Device Passthrough, with container `render` GID; no full PCI GPU passthrough.
4. Install **Jellyfin 10.11.11** pinned to its version family, then **Shokofin 6.0.5** stable. Configure the *remote* Shoko LAN address (not `127.0.0.1`). Match source paths; verify VFS in Jellyfin state, metadata, playback, Direct Play and QSV transcode.
5. Deploy Tethys in the **Jellyfin LXC** using Python venv, `alembic upgrade head`, and `systemd` units; point `DATABASE_URL` to the **existing remote PostgreSQL** with a dedicated DB/user. No containerized/local PostgreSQL. Protect app/Jellyfin/API secrets; do not expose databases publicly.
6. Implement and test torrent completion **event → Shoko scan**; optional periodic reconcile to handle missed events. Verify latency, duplicate events, backpressure, files still being written, NFS staleness.
7. Verify actual MKV, ASS, nested sidecars, read-only torrent safety, backup/restore of Shoko/Jellyfin/Tethys PostgreSQL, and rescan preserving user reviews.

## Follow-up after conversation rewind

The owner intends to **rewind the conversation to the first deployment-planning request after the last code commit** to save context, and re-create LXCs cleanly. **This document is newer and overrides any older topology suggested by the rewound chat**. In the next deployment conversation: read this document and AGENTS.md; do not advocate the old all-in-one LXC, Docker Compose, or a new backend VM by default.

This is a deployment **decision**, not a claim that the new LXCs, Shoko/Jellyfin link, or event hook are already installed or tested.
