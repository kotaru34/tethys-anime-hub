# MVP v0.1 deployment on Proxmox VE 9 (Ukraine)

**Status:** this repository currently stores product and engineering specifications. The *already assembled* runnable v0.1 source archive was supplied in the preceding ChatGPT conversation as `kotaru-anime-v0.1.zip`. **It is not yet present as normal source files in this Git repository.** Install from that archive until the implementation is imported; do not expect `git clone` of this docs-only stage to run `docker compose`.

The source archive already includes a more detailed original `docs/DEPLOY_UK.md` of ~25 KB, a Compose stack, migration, tests and backup helper. This document is the durable deployment overview and checklist; deployment is not yet verified on the actual hosts.

## Target hosts

- **Laptop PVE:** i5-9300H, UHD 630, GTX 1650 in another VM. Create **unprivileged Debian LXC** running Jellyfin/Shokofin; pass **only** Intel render node using PVE 8+/9 **Resources → Add → Device Passthrough**. Host iGPU still drives laptop display (render node is not exclusive PCI passthrough).
- **Debian VM** (can be on laptop PVE): Docker Compose with Shoko, PostgreSQL 17, FastAPI Web UI and worker. Suggested starting resources: 2–4 vCPU, 4–6 GiB RAM. DB is bound only to private Docker network.
- **z425:** existing `llama-server` on V100 with Qwen; use remote configured API endpoint for occasional language tasks. Do not move transcode there by default.
- **/Anime:** same actual torrent data accessible **read-only** from LXC and Compose VM, preferably both mounted as `/Anime`. Do not let empty missing network mount look like deletion.

## Before starting

1. Make snapshots/backups of Proxmox guests before modifications; verify host has working `/dev/dri/renderD*` and an Intel device.
2. Confirm storage bind/NFS `/Anime` contains your `<release>/*.mkv` and optional nested `.ass` subtitle files. Mount `ro`.
3. Match **compatible** Jellyfin, Shokofin and Shoko releases: see [Shokofin compatibility table](https://docs.shokoanime.com/jellyfin/installing-shokofin). As of the checked table, Shokofin 6.0.4–6.0.5 matches Jellyfin 10.10–10.11 and Shoko 5.2.0–5.3.3; always check before upgrade. Do not mix Shoko development builds with stable Shokofin.
4. Prepare a stable private LAN IP/DNS, LAN firewall and reverse proxy/VPN if needed. Do **not** expose ports directly to WAN.

## LXC: Intel QSV + Jellyfin

On the laptop PVE host:

```bash
ls -l /dev/dri/
ls -l /dev/dri/renderD*
# Example for LXC 230, only if /srv/Anime actually exists on PVE host:
pct set 230 -mp0 /srv/Anime,mp=/Anime,ro=1
```

From PVE web, root user → LXC 230 → Resources → Add → Device Passthrough → choose Intel render node (e.g. `/dev/dri/renderD128`). Set advanced GID to actual container `render` group ID; restart LXC. Verify:

```bash
pct exec 230 -- ls -ln /dev/dri/
pct exec 230 -- ls /Anime
```

Inside Debian LXC, install Jellyfin with the [official Debian guide](https://jellyfin.org/docs/general/installation/linux/). Configure Intel QSV using [official Intel acceleration guide](https://jellyfin.org/docs/general/post-install/transcoding/hardware-acceleration/intel/); grant Jellyfin user access to `render`, restart service, verify permissions and a **forced transcoding test** in Jellyfin dashboard. Do not passthrough the entire GPU via VFIO or disable the console.

Jellyfin library configuration: use Shokofin-recommended library type and directory view; point at *Shoko-managed VFS* and never modify its symlinks by hand. Configure Jellyfin metadata providers to avoid conflicts; enable Direct Play, use QSV where required. Chapter images, keyframe-only trickplay and occasional scans may stay enabled because they're low sustained overhead.

## Shoko + private app stack

From the previously supplied `kotaru-anime-v0.1.zip` archive on Debian Docker VM:

```bash
unzip kotaru-anime-v0.1.zip
cd kotaru-anime
cp .env.example .env
chmod 600 .env
```

Set (private secrets never commit):

```dotenv
POSTGRES_DB=anime
POSTGRES_USER=anime
POSTGRES_PASSWORD=<strong-random-secret>
DATABASE_URL=postgresql+psycopg://anime:<same-encoded-secret>@db:5432/anime
APP_USERNAME=admin
APP_PASSWORD=<private-secret>
SESSION_SECRET=<64-or-more-random-hex>
ANIME_PATH=/Anime
JELLYFIN_URL=http://<jellyfin-lan-ip>:8096
JELLYFIN_PUBLIC_URL=http://<jellyfin-lan-ip>:8096
JELLYFIN_API_KEY=<from-jellyfin-dashboard>
BIND_IP=<docker-vm-lan-ip>
TARGET_AUDIO_LANGUAGE=ukr
COOKIE_SECURE=0
LLM_BASE_URL=
LLM_MODEL=
LLM_API_KEY=
```

Prefer letters/digits-only DB password initially so `DATABASE_URL` needs no URL encoding; for special characters URL-encode in DSN. Replace all angle-bracket placeholders, and fill remaining values from `.env.example`. `COOKIE_SECURE=1` when served by HTTPS. Restrict BIND_IP and firewall, or configure VPN.

```bash
findmnt /Anime
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=80 db migrate app worker shoko
curl -i http://127.0.0.1:3080/healthz
```

Import library in Shoko GUI (`http://<VM-IP>:8111`) pointing to `/Anime`; configure AniDB, no rename/move. Set up Shokofin in Jellyfin and verify matching library items before expecting app catalog population. App UI: `http://<VM-IP>:3080`.

## Initial acceptance test

- Read-only: ensure `docker inspect` shows bind mounts `:ro`; no changes to torrent directory.
- Import one standard H.264 anime, one HEVC anime, one 10-bit H.264 Hi10P if available, one complicated ASS release, and a release with nested external subtitles.
- Confirm Shoko identity, Shokofin/Jellyfin catalog, language streams, episodes, local cover and URL to Jellyfin player.
- Set personal rating **0.0** and review, rescan, confirm preservation.
- Confirm ASS complex styling (transcoding/burn-in may require CPU fallback); verify Jellyfin playback metrics vs Direct Play/remux/QSV.
- Test host screen output while another test stream uses Intel Quick Sync.
- Run backup, verify a restore into an isolated DB.
- Add at least one known ambiguous naming case to future matching regression fixtures.

## Existing MVP limitations (before new architecture migration)

- v0.1 primarily catalogs media exposed by Jellyfin; it **cannot yet create a future MAL-only entry from URL**.
- No automated deep recommendation engine yet; this is fully specified in [RECOMMENDER_DESIGN_UK.md](RECOMMENDER_DESIGN_UK.md).
- Nested subtitle files are found and inventoried, **not guaranteed attached to Jellyfin playback**.
- Player opens Jellyfin Web; no native integrated player.
- Some release groups are filename/path heuristics only.
- Existing identity key is Jellyfin ID. **Do not patch in remote-only fake Jellyfin IDs**; migrate Work identity first per [DATA_MODEL_UK.md](DATA_MODEL_UK.md).

## Backup, security and maintenance

- PostgreSQL: nightly custom-format pg_dump in Compose DB container, retain offline copies. Test restoring. Optional WAL backup and PVE snapshot complement, not replace, consistent DB backup.
- Shoko owns separate local DB/config and AniDB hash cache: backup its state independently. Preserve Jellyfin plugin configuration and VFS settings. PostgreSQL is **not** Shoko's underlying DB.
- Protect `.env`, logs and any user ratings/reviews; public GitHub repo stores code/specs only.
- Rebuild only after DB backup; run Alembic migration before worker/app. Avoid automatic `latest` images in production: pin known-compatible versions/digests.
- Weekly recommender and announced anime refresh arrive in later milestone, not in MVP v0.1.
