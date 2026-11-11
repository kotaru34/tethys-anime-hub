# Native single-LXC deployment (Debian 13, remote PostgreSQL)

**Current target topology, 2026-11-11.** This replaces the *optional* Docker/VM deployment path for the owner's Proxmox install. All runtime services live in existing **unprivileged LXC 1510**. PostgreSQL for Tethys is on a pre-existing remote private-LAN server. No Docker, no additional VM, no PostgreSQL server inside the LXC.

## Layout

- Jellyfin 10.11.11 + Shokofin 6.0.5, Intel UHD 630 QSV via existing /dev/dri/renderD128
- Shoko Server **5.3.3** as a native systemd service, with its **own** private database/state in the dedicated service home (`~/.shoko/Shoko.CLI` by default). Shoko's DB is **not** the app's remote PostgreSQL.
- Tethys FastAPI + worker as separate native systemd services, sharing one Python venv and using **remote PostgreSQL** via `DATABASE_URL`.
- `/Anime` is a read-only NFS bind mount; never rename/move/update torrents. Shokofin VFS is created in Jellyfin's writable data directory, not on /Anime.

## NFS permissions (already diagnosed)

On PVE, the source is NFS `10.169.6.200:/mnt/neko`, subdirectory `/mnt/neko/Anime`; host source ownership `3000:3000` and mode `2770`. The unprivileged container maps **GID 3000 → 3000**, so `ls -ldn /Anime` shows `65534:3000`. *Some NFS setups reject supplementary GIDs while accepting the primary GID.* This was demonstrated: with primary GID 3000, access works on both PVE host and inside LXC.

- Keep Jellyfin `Group=anime` systemd drop-in where required; do not change owner/permissions of NFS files.
- Run **Shoko** and **Tethys** worker with **primary group `anime`** too; creating a group entry or using only `SupplementaryGroups=anime` may not be sufficient.
- Verify each daemon's effective primary group with `ps -o pid,user,group,args -p <PID>` and use `setpriv` to isolate NFS permission behavior.
- Root inside LXC may still get `Permission denied` on `/Anime`, which does not mean group=anime daemons cannot access it.

## Phase 1: preflight

In LXC as root:

```bash
getent group anime
ls -ldn /Anime
findmnt /Anime
systemctl show jellyfin -p User -p Group
runuser -u jellyfin -g anime -- ls /Anime | head
ls -l /dev/dri/renderD128
```

If `/Anime` is unavailable, stop here; do not let Shoko index an empty missing mount.

## Phase 2: Shoko 5.3.3 without Docker

The upstream Linux bare-metal documentation currently illustrates Ubuntu and warns that manual upgrades and troubleshooting are the administrator's responsibility. The Debian 13 variant below uses Microsoft's Debian 13 .NET packages and the **exact 5.3.3 release asset**, not unpinned `latest`. This has **not yet been tested inside the owner's LXC**.

```bash
apt update
apt install -y ca-certificates curl wget unzip mediainfo librhash-dev
wget -q https://packages.microsoft.com/config/debian/13/packages-microsoft-prod.deb -O /tmp/packages-microsoft-prod.deb
dpkg -i /tmp/packages-microsoft-prod.deb
apt update
apt install -y aspnetcore-runtime-8.0
dotnet --list-runtimes
getent group anime
id shoko 2>/dev/null || useradd --system --user-group --home-dir /var/lib/shoko --create-home --shell /usr/sbin/nologin shoko
# Keep shoko's own user-private primary group? No: primary GID must be 3000 for this NFS export.
usermod -g anime shoko
install -d -o shoko -g anime -m 0750 /var/lib/shoko
install -d -m 0755 /opt/shoko/5.3.3
curl -fL --retry 3 -o /tmp/shoko-5.3.3.zip \
  https://github.com/ShokoAnime/ShokoServer/releases/download/v5.3.3/Shoko.CLI_Framework_any-x64.zip
unzip -q /tmp/shoko-5.3.3.zip -d /opt/shoko/5.3.3
SHOKO_BIN="$(find /opt/shoko/5.3.3 -type f -name Shoko.CLI -print -quit)"
test -n "$SHOKO_BIN" || { echo "Shoko.CLI not found"; exit 1; }
chmod 0755 "$SHOKO_BIN"
SHOKO_DIR="$(dirname "$SHOKO_BIN")"
printf 'Binary: %s\nWorking directory: %s\n' "$SHOKO_BIN" "$SHOKO_DIR"
```

Install unit using **detected** executable path, rather than assuming the ZIP layout:

```bash
cat >/etc/systemd/system/shokoserver.service <<EOF
[Unit]
Description=Shoko Server 5.3.3
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=shoko
Group=anime
Environment=HOME=/var/lib/shoko
WorkingDirectory=$SHOKO_DIR
ExecStart=$SHOKO_BIN
Restart=on-failure
RestartSec=10
UMask=0027

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now shokoserver
systemctl status shokoserver --no-pager
journalctl -u shokoserver -n 80 --no-pager
```

Open `http://<LXC-IP>:8111` on trusted LAN. If Shoko prompts for a Web UI installation, use its **Install Shoko Web UI** button; set admin login and AniDB credentials. Configure read-only `/Anime` as an import folder. Disable any renaming/moving/organizing of source files (NFS read-only adds a hard boundary). Verify matched titles and hashing before Shokofin setup.

**Backups:** Shoko's own SQLite/config/image files typically live at `/var/lib/shoko/.shoko/Shoko.CLI/`; back up the entire state directory while Shoko is stopped, or with a consistent SQLite backup. This is independent of the remote Tethys database.

## Phase 3: Shokofin in Jellyfin

In Jellyfin Dashboard → Plugins → Manage Repositories, add:

`https://raw.githubusercontent.com/ShokoAnime/Shokofin/metadata/stable/manifest.json`

Install *stable* Shokofin **6.0.5** and restart Jellyfin. Set Shokofin Private Host URL to `http://127.0.0.1:8111` (all services share LXC), Shoko username and password. Create a **new** Jellyfin library of type `Shows` and add `/Anime` as the source directory. Enable/default VFS in Shokofin; **do not** manually add/edit the generated VFS path – Shokofin attaches it and manages symlinks in writable Jellyfin state. Avoid competing metadata downloaders, NFO output and saving artwork next to source. Verify a playable Jellyfin title and metadata.

Official guides:
- https://docs.shokoanime.com/getting-started/installing-shoko-server
- https://docs.shokoanime.com/jellyfin/installing-shokofin
- https://docs.shokoanime.com/jellyfin/configuring-shokofin
- https://learn.microsoft.com/en-us/dotnet/core/install/linux-debian

## Phase 4: Tethys app with remote PostgreSQL

The remote PostgreSQL server is a **user-existing private-LAN service**; do **not** install another PostgreSQL server, do **not** run `docker compose`. An administrator must first create a dedicated empty DB/user with `CONNECT/CREATE` permissions for Tethys migrations, configure `pg_hba.conf` and server firewall for the LXC's IP, and test reachability.

```bash
apt install -y git python3 python3-venv python3-pip postgresql-client
getent group tethys || groupadd --system tethys
id tethys 2>/dev/null || useradd --system --home-dir /var/lib/tethys --create-home \
  --gid anime --groups tethys --shell /usr/sbin/nologin tethys
install -d -o tethys -g tethys -m 0750 /var/lib/tethys
git clone https://github.com/kotaru34/tethys-anime-hub.git /opt/tethys
cd /opt/tethys
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
# Generate a private APP_PASSWORD and SESSION_SECRET; edit .env accordingly.
openssl rand -hex 32
nano .env
chown root:tethys .env
chmod 0640 .env
```

Set in `/opt/tethys/.env` (example only – no real credentials in Git):

```dotenv
DATABASE_URL=postgresql+psycopg://tethys_user:URL_ENCODED_PASSWORD@PG_HOST:5432/tethys?sslmode=prefer
APP_USERNAME=admin
APP_PASSWORD=YOUR_PRIVATE_APP_PASSWORD
SESSION_SECRET=RANDOM_64_HEX
JELLYFIN_URL=http://127.0.0.1:8096
JELLYFIN_PUBLIC_URL=http://LXC_IP:8096
JELLYFIN_API_KEY=JELLYFIN_DASHBOARD_API_KEY
ANIME_PATH=/Anime
STATE_DIR=/var/lib/tethys
LLM_BASE_URL=
LLM_MODEL=
LLM_API_KEY=
```

Set TLS mode to `verify-full` with trusted CA where PostgreSQL TLS is configured; otherwise use LAN firewall and agree on transport security explicitly. Do not use `sslmode=disable` unless accepting plaintext over trusted LAN. Remote PostgreSQL is used **only by Tethys**, not by Jellyfin or Shoko.

Before migration:

```bash
cd /opt/tethys
# If psql isn't available or certificate configuration differs, first debug basic reachability.
runuser -u tethys -g anime -- .venv/bin/python -c 'from app.db import engine; from sqlalchemy import text; c=engine.connect(); print(c.execute(text("select current_database(), version()")).fetchone()); c.close()'
runuser -u tethys -g anime -- .venv/bin/alembic upgrade head
```

Systemd web unit:

```ini
# /etc/systemd/system/tethys-web.service
[Unit]
Description=Tethys Anime Hub Web
Wants=network-online.target
After=network-online.target

[Service]
User=tethys
Group=anime
WorkingDirectory=/opt/tethys
Environment=STATE_DIR=/var/lib/tethys
ExecStart=/opt/tethys/.venv/bin/uvicorn app.web:app --host 0.0.0.0 --port 3080
Restart=on-failure
RestartSec=5
UMask=0027

[Install]
WantedBy=multi-user.target
```

Systemd worker unit:

```ini
# /etc/systemd/system/tethys-worker.service
[Unit]
Description=Tethys Anime Hub Worker
Wants=network-online.target
After=network-online.target

[Service]
User=tethys
Group=anime
WorkingDirectory=/opt/tethys
Environment=STATE_DIR=/var/lib/tethys
ExecStart=/opt/tethys/.venv/bin/python -m app.worker
Restart=on-failure
RestartSec=10
UMask=0027

[Install]
WantedBy=multi-user.target
```

Reload/start after creating unit files:

```bash
systemctl daemon-reload
systemctl enable --now tethys-web tethys-worker
systemctl status tethys-web tethys-worker --no-pager
journalctl -u tethys-worker -n 100 --no-pager
curl -fsS http://127.0.0.1:3080/healthz
runuser -u tethys -g anime -- ls /Anime | head
```

Visit `http://<LXC-IP>:3080` from trusted LAN. If accessible from beyond LAN, terminate HTTPS at reverse proxy and set `COOKIE_SECURE=1`. App password/Session secret, Shoko credentials, Jellyfin API key are independent secrets. Do not commit `.env`. The first version does not have canonical Work/watchlist or behavioral learning yet.

## Verification checklist

- PVE LXC ID **1510** is unprivileged; primary NFS group for all three daemons is GID 3000.
- Jellyfin has proper render permissions and QSV transcoding works with real media.
- Shoko reads read-only `/Anime`; Shokofin sees the correct import directory and generates VFS in Jellyfin state.
- Tethys connects to existing remote PostgreSQL with a **dedicated** account and migrates it with Alembic; no extra database service.
- Tethys reads Jellyfin catalog; user review/rating is preserved across rescans.
- Shoko data and remote Tethys DB have **separate** backup/restore strategies.
- Actual LXC/host integration is *pending until run by the owner*.

Reference for native support and caveats: https://docs.shokoanime.com/getting-started/installing-shoko-server .
