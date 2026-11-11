# Tethys Shoko Reconciler (experimental)

A conservative **Shoko Server 5.3.3** integration for collections where AniDB does not know the MKV's ED2K hash. It builds safe filename/folder-to-AniDB-episode mappings and submits them through Shoko's supported manual-link API. **Media files and Shoko's database are never modified directly.** Shoko then retains its rich series, episode, relation and metadata model.

## Scope and limits

- The Shoko 5.x API supports `GET /api/v3/File?include_only=Unrecognized`, `GET /api/v3/Series/AniDB/Search`, `POST /api/v3/Series/AniDB/{id}/Refresh?createSeriesEntry=true`, and `POST /api/v3/File/{fileID}/LinkFromSeries`.
- Source support is verified from the v5.3.3 GitHub tag. Host-side Shoko data / compatibility / coverage **has not been tested** here.
- Uses all local filenames already indexed by Shoko. It does not rescan the media, invoke AniDB FILE requests, or require ED2K matches.
- Exact title matches and user-approved per-release-folder AniDB IDs are eligible. Unrecognized episode numbering and ambiguous seasons are deferred.
- Filename-derived `1` for a single-file movie is allowed *only when the AniDB result reports Movie*.
- **No fabricated 95% success claims:** the goal is to lower `Unrecognized / total` to <= 5%; actual success requires integration on the owner's server and correction of any ambiguous release groups. Accurate links matter more than the counter.
- Unlike the newer official `Offline Importer` plugin, which targets .NET 10 / Shoko 6, this works with the currently deployed Shoko 5.3.3.

## Run inside the Shoko LXC

Use a **Shoko admin API key** from Web UI → Settings → API Keys. No password or token is passed as CLI argument or saved to the JSON plan.

```bash
apt install -y python3
install -d -m 0700 /root/tethys-shoko-reconcile
# Copy shoko_reconcile.py into this directory or git clone the repository.
cd /root/tethys-shoko-reconcile
read -rsp 'Shoko API key: ' SHOKO_API_KEY; echo
export SHOKO_API_KEY
export SHOKO_URL=http://127.0.0.1:8111
python3 shoko_reconcile.py --status
python3 shoko_reconcile.py --plan plan.json
```

Inspect `plan.json` **before applying**, particularly series/season mismatches. Output is local and treated as private, because it lists filenames.

You can correct *a whole anime release folder at once* rather than linking every episode separately. Create `overrides.json`:

```json
{
  "Ragna Crimson - AniLibria.TV [WEBRip 1080p HEVC]": 17645,
  "Youkoso Jitsuryoku Shijou Shugi no Kyoushitsu e S4 - AniLiberty [WEB-DL 1080p HEVC]": 0
}
```

**Important:** the IDs above are **illustrative only, not verified for those anime**. Replace with the correct positive AniDB anime IDs and **remove** unknown mappings rather than using `0`. IDs may be discovered from `plan.json` candidates and checked in Shoko's UI/AniDB.

```bash
python3 shoko_reconcile.py --overrides overrides.json --plan plan.json
python3 shoko_reconcile.py --apply --plan plan.json --confirm LINK --limit 10
# After inspecting the first ten linked files and verifying the correct episodes:
python3 shoko_reconcile.py --apply --plan plan.json --confirm LINK
# If the output says QUEUED series, let Shoko fetch that series' AniDB metadata, then repeat:
python3 shoko_reconcile.py --apply --plan plan.json --confirm LINK
# After jobs settle, check actual results:
python3 shoko_reconcile.py --status
unset SHOKO_API_KEY
```

**Use only one process**. Do not delete files, toggle Shoko renamer, submit AVDump, or bulk-update Shoko SQLite. Keep `/Anime` read-only. For a known `0` (no mapping) in the overrides, omit the entry.

## Why not automate every title immediately?

A false link like `Season 3 Episode 9` → `Season 1 Episode 9` can be worse than an unknown file. Exact normalized title / release-folder approval is safer. The audit output shows how many files are eligible and which groups need one-off confirmation. If the coverage remains above 5%, we iterate on the **unresolved groups**, parsing rules or cross-provider identity mapping; not on individual episodes.

## References

- [Shoko 5.3.3 File API linking](https://github.com/ShokoAnime/ShokoServer/blob/v5.3.3/Shoko.Server/API/v3/Controllers/FileController.cs)
- [Shoko 5.3.3 Series API search/refresh](https://github.com/ShokoAnime/ShokoServer/blob/v5.3.3/Shoko.Server/API/v3/Controllers/SeriesController.cs)
- [Shoko unrecognized files](https://docs.shokoanime.com/shoko-server/unrecognized-files)
- [Official Offline Importer plugin (Shoko 6; not compatible here)](https://github.com/ShokoAnime/Shoko.Plugin.OfflineImporter)
