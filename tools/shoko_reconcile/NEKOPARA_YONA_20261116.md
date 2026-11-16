# CT2601 — Nekopara standalone OVA/ONA and combined Yona (03+SP)

The November 16 read-only 48-file Shoko snapshot confirmed these exact **still-unrecognized** paths:

| File ID | Relative path | Target |
|---:|---|---|
| 2909 | `NEKOPARA_[OVA]_[AniLibria_Tv]_[WEB-Rip_1080p].mkv` | AniDB **12622**, Nekopara 2017 OVA |
| 2850 | `Nekopara_Koneko_no_Hi_no_Yakusoku_[ONA]_[AniLibria_TV]_[WEBRip_1080p].mkv` | AniDB **14206**, standalone ONA |
| 2486 | `Akatsuki no Yona OVA/Akatsuki no Yona OVA (03+SP).mkv` | AniDB **11143**, Shoko **270**, possible E03 + S01 |

Do not rename, split, remux or move any torrents. File ID in Shoko means the file is indexed, not necessarily already assigned to a matching AniDB episode.

## Nekopara: create ONLY two distinct standalone AniDB works

On CT2601 with `SHOKO_API_KEY` exported:

```bash
cd /opt/tethys-anime-hub
git pull --ff-only
cd tools/shoko_reconcile

# Default read-only: 2 exact AniDB work GETs.
python3 nekopara_ova_ona_bootstrap.py \
  --report /root/nekopara-works-dry-run.json

# Operator-initiated, only if missing (and no blocked/api_error):
python3 nekopara_ova_ona_bootstrap.py \
  --apply --confirm CREATE_2_NEKOPARA_WORKS \
  --report /root/nekopara-works-requested.json

# After Shoko's metadata queue has processed requests (one invocation):
python3 nekopara_ova_ona_bootstrap.py \
  --check --report /root/nekopara-works-episodes.json
```

`--apply` makes **at most two** targeted metadata POST requests with a durable per-AniDB-ID journal before each dispatch and a nonblocking file lock; later invocations skip attempted IDs even if their response was lost. It does not link files. `--check` reports actual AniDB episode types, numbers, IDs, titles and local Shoko series IDs; **only after inspecting these** may we write a curated two-file XRef manifest. Keep the prior two OVA/ONA works separate from Nekopara TV AniDB 14570.

## Yona: verify one physical file, no link until content confirmed

```bash
python3 yona_03_sp_probe.py \
  --output /root/shoko-yona-03-sp-probe.json
```

The probe makes **only three targeted Shoko API reads**: GET file **2486**, exact local AniDB work **11143 / Shoko 270**, and the short episode list; requires exact AniDB **Episode E03 ID 176847** and **Special S01 ID 183623**. It runs `ffprobe` for **one known MKV**, `/Anime/Akatsuki no Yona OVA/Akatsuki no Yona OVA (03+SP).mkv`, to report duration, streams, and chapters. It never writes to `/Anime`, does not decode the entire video, has no broader walks, and makes **zero XRefs**. If `ffprobe` is absent, report explicitly says so; installing Debian `ffmpeg` provides it.

**Do not assume chapters or filename prove both E03 and S01 are present.** If manual content examination confirms a combined file, the official Shoko WebUI Manual Linking dialog has **Duplicate Entry** for creating a virtual second file entry and assigning both E03 and S01 without modifying media. See [Shoko Unrecognized Files documentation](https://docs.shokoanime.com/shoko-server/unrecognized-files). Do not try to work around it with two independent raw API submissions without verifying the resulting mapping.

Upload **both** `/root/nekopara-works-episodes.json` and `/root/shoko-yona-03-sp-probe.json` for final exact-match XRef review. This work does not touch the unrelated 24 Date A Live imports or other pending extras.
