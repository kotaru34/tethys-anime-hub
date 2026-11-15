# CT2601: Targeted AniDB metadata bootstrap (2026-11-15)

This is an **operator-initiated, one-shot** metadata operation, separate from the SignalR Reconciler. It covers six independently identified works representing twenty still-unrecognized media files. It does **not** link or rename those files.

| AniDB | Work | Source files |
|---:|---|---:|
| 14570 | Nekopara TV (2020) | 12 |
| 18865 | KonoSuba S3 Bonus Stage (2025) | 2 |
| 11143 | Akatsuki no Yona OVA (2015) | 3 |
| 14397 | Rascal Does Not Dream of a Dreaming Girl | 1 |
| 17640 | Rascal Does Not Dream of a Sister Venturing Out | 1 |
| 17862 | Rascal Does Not Dream of a Knapsack Kid | 1 |

The exact File IDs are pinned in `targeted_metadata_20261115.json`. Do not broaden these ID lists or reuse this one-time manifest for future RSS episodes.

## Run on CT2601

```bash
cd /opt/tethys-anime-hub
git pull --ff-only
cd tools/shoko_reconcile

# Read-only dry-run: six exact AniDB work GETs, no POSTs or media scans.
python3 targeted_metadata_bootstrap.py \
  --report /root/shoko-metadata-dry-run.json

# Only after reviewing the above report:
python3 targeted_metadata_bootstrap.py \
  --apply --confirm CREATE_6_ANIDB_WORKS \
  --report /root/shoko-metadata-requested.json

# After Shoko's internal metadata jobs have finished, run ONCE:
python3 targeted_metadata_bootstrap.py \
  --check --report /root/shoko-metadata-episodes.json
```

Requires `SHOKO_API_KEY` exported in the command environment, as for existing Shoko probes. Default URL is local `http://127.0.0.1:8111`. Do not put API keys on the command line.

## Load and repeat behavior

- Dry-run: exactly six small AniDB work lookups; no file/library listing.
- Apply: exactly six work lookups, then at most six individual targeted Shoko metadata refresh/create requests, paced by 2 seconds between submissions. Calls `refresh_series()` with `createSeriesEntry=true`, `force=false`, `downloadRelations=false`. Shoko may schedule internal metadata/artwork work, so zero server-side load cannot be guaranteed.
- If an exact AniDB work already exists locally, no create/refresh is sent for it.
- A private attempt journal is persisted to `/var/lib/shoko-reconcile/targeted-metadata-20261115.state.json` and written **before** each request. A later invocation will not retry an already-attempted work, even if its HTTP reply was lost.
- A nonblocking file lock prevents two concurrent CLI apply instances.
- Check: six work lookups plus an episode list only for existing works, emitting AniDB episode ID, title, type and number.
- **No timers, extra retry loops, `/File` scan, `/Anime` walk, media writes, or XRef links.**

**Important:** Work presence does not prove a particular video file matches any episode. Review `shoko-metadata-episodes.json` before building another curated XRef manifest. `Akatsuki no Yona (03+SP)` needs separate scrutiny, and the Rascal films must be proven to be the complete movies.

Do not delete the persistent attempt state to force a retry without inspecting Shoko's queue; this risks duplicate requests.
