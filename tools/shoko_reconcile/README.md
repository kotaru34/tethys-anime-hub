# Tethys Shoko Reconciler v2.1

**Status:** implemented and locally tested; no live Shoko apply/verification yet. Targets Shoko **5.3.3**, uses its supported **API v3 Manual Links** (no fake ED2K). Files in `/Anime`, MKV tracks, sidecars, torrent paths and Shoko's SQLite database are **never edited** by this tool. A submitted API link may still be processing asynchronously; the final Shoko `--status` is the authority.

## Why v2

v1 examined 1,038 unknown files across 83 release folders. It prepared 690 potential mappings, but title and episode heuristics missed many valid releases. v2 adds:

- Cross-group candidate reuse: when an entry is missing from a release-specific AniDB search, reuse series/sequel candidates discovered in other Shoko groups, with explicit season/year disambiguation.
- Filename alternatives, punctuation and romanization normalization, tech-tag removal, release-group ignorance, Unicode titles, typo-tolerant scoring, multiple query variants.
- Optional **locally cached external alias/ID crosswalk** from `cedya77/anime-offline-database` (ODbL 1.0 + DbCL 1.0, derived from `manami-project`). Supports AniDB IDs from MAL/AniList naming differences without sending the user's file names to external LLMs.
- Episode parser for `S02E01`, `S02EP01`, `[01]`, `- 01`, `Name 01`, `Ep 01`, `special 1`, movie markers. Keeps episode type and series identity separate.
- Correct handling of `Takt Op. Destiny` (`Op` *part of the anime title*, not an opening clip); `No Game No Life` ordinary episodes plus nested Specials; OP/ED/NCOP/NCED/PV/bonus footage **not** silently mapped as regular episodes.
- Season/year/media-type context, explicit uncertainty and **one decision per file**, not an unconditional folder-level link. Previous exact Shoko selections are retained when converting the original v1 plan.
- Enforced live checks: file must still be Unrecognized at the original path, intended AniDB ID must match Shoko series ID, episode **type and number** must exist in Shoko before issuing Manual Link.
- Per-file and per-release approved overrides, global `--limit`, audit journal and idempotent reruns.
- Local **per-episode metadata snapshots** via Shoko API containing AniDB/TMDB records, images where returned, Shoko episode data and associated file/MediaInfo where available. The source of truth remains Shoko's local DB. Export path is private and **never under `/Anime`**.

### Measured offline work so far (not live success)

Using the user's v1 `shoko-plan.json` as an **offline fixture without the external alias catalog**, v2.1 reports **808 potential file links** of 1,038 unknown (vs v1's 690). This is **before** verifying series/episodes through live Shoko APIs, link job completion or actual metadata completeness. With the user-reported **1,167 total files**, even 808 successful links would leave **230/1,167 (19.71%) unknown**, meaning at least **172 further verified links** are still required to reach the `<=5%` target. It is **not** a claim of achieving the `<=5%` unrecognized target. The user's accepted mapping error ceiling `<=10%` also needs sampling against the actual result; a similarity score is not a calibrated error probability. Any unknown AniDB release file record fields must be shown as `Unknown` rather than fabricated.

## Upgrade and run inside Shoko LXC

```bash
cd /opt/tethys-anime-hub
git pull --ff-only
cd tools/shoko_reconcile

# An offline ID/title/season crosswalk (download once; source is public, not your filenames).
mkdir -p /var/cache/tethys
curl -fL --retry 3 \
  'https://github.com/cedya77/anime-offline-database/releases/download/latest/anime-offline-database.jsonl' \
  -o /var/cache/tethys/anime-offline-database.jsonl

# Upgrade the already saved v1 plan without making any Shoko API calls.
python3 shoko_reconcile.py \
  --analyze-plan /root/shoko-plan.json \
  --total-files 1167 \
  --catalog /var/cache/tethys/anime-offline-database.jsonl \
  --plan /root/shoko-plan-v2.json
```

**Review the generated candidates, especially seasons, cour splits, OVAs, specials, movies and localized titles before writing.** Files with uncertain identity remain deferred. The catalog is not a license to claim certainty; it can contain incorrect cross-provider links. You can rerun with `--aggressive` to see a broader **plan**; this has not been accuracy-calibrated.

For a specific proven match, create `/root/approved.json` (file names/IDs below are **synthetic**, not a claim of verified AniDB IDs):

```json
{
  "groups": {"Anime Release Folder - Group [1080p]": 12345},
  "files": {"5000": {"anidb_id": 12345, "episode": 1, "type": "Special"}}
}
```

Re-plan with `--overrides /root/approved.json`; overrides require actual AniDB IDs. To explicitly exclude a group, use `0` for that group. A per-file correction wins over a group decision.

```bash
read -rsp 'Shoko admin API key: ' SHOKO_API_KEY; echo
export SHOKO_API_KEY

# Existing plan is valid for application only if its file IDs/paths are still current.
# Apply a 10-item sample; if series are missing, it queues Shoko metadata refresh first.
python3 shoko_reconcile.py --apply --plan /root/shoko-plan-v2.json \
  --confirm LINK --limit 10 --journal /root/shoko-apply-journal.json

# After Shoko's jobs complete, verify first sample in the WebUI and run:
python3 shoko_reconcile.py --status

# Only when the sample is correct, apply the rest. Repeating is safe:
python3 shoko_reconcile.py --apply --plan /root/shoko-plan-v2.json \
  --confirm LINK --journal /root/shoko-apply-journal.json

# The records of EVERY episode are saved separately from source MKVs:
python3 shoko_reconcile.py --export-metadata /var/lib/tethys/shoko-metadata \
  --plan /root/shoko-plan-v2.json
unset SHOKO_API_KEY
```

For a **fresh live search** rather than upgrading a saved plan:

```bash
python3 shoko_reconcile.py --plan /root/shoko-plan-v2.json \
  --catalog /var/cache/tethys/anime-offline-database.jsonl
```

No new media copies and no rehash needed. The normal Shoko/Jellyfin services continue unchanged. The original Shoko watcher must stay disabled under the known deployment settings.

## Acceptance criteria

1. True post-apply `unrecognized / all Shoko files <= 5%` (not projected plan count). Segregate actual extras from anime episodes in the audit; don't artificially hide unknowns to lower the fraction.
2. Manually audit a statistically meaningful stratified sample of linked **works and episodes** across release groups, seasons, specials, different encodings and language names; estimated wrong links **<= 10%** with uncertainty bounds.
3. Per-series and per-episode metadata coverage relative to comparable native-hash matches **>=95% of fields that Shoko can know at series/episode level** (verify field-level audit). **AniDB file-level release ID, verified group, CRC and release version cannot be legitimately reconstructed from absent AniDB records**; preserve Shoko's own `Unknown` value and optionally record separately observed MKV `MediaInfo`/track labels.
4. No writes to torrent files or to Shoko's SQLite DB outside the supported API, no unsupported Shoko 6 plugin in 5.3.3.

## Known gaps / next iteration

- Automated cour partition across separate AniDB anime IDs when one download contains two cours (`S02E13` may be `Episode 1` of a separate AniDB second-cour work). These are deferred pending validated episode metadata and relations, not blindly mapped to the first cour.
- Rare nested spin-offs and bonus contents need independent identity. Shoko's `Unknown Files` count includes some OP/ED/trailers, but ignoring them would not satisfy a genuine `<=5%` quality goal.
- Crosswalk database may not include localized Ukrainian release titles or recently aired works. Supply approved aliases/explicit IDs for these; no silent speculative identification.
- No API calls have been executed against the user's live Shoko from this development environment. Integration acceptance is blocked until live sampling.

## Sources

- [Shoko 5.3.3 file Manual Link API](https://github.com/ShokoAnime/ShokoServer/blob/v5.3.3/Shoko.Server/API/v3/Controllers/FileController.cs)
- [Shoko 5.3.3 series/episode APIs](https://github.com/ShokoAnime/ShokoServer/blob/v5.3.3/Shoko.Server/API/v3/Controllers/SeriesController.cs)
- [Shoko 5.3.3 episode-type parser](https://github.com/ShokoAnime/ShokoServer/blob/v5.3.3/Shoko.Server/API/v3/Helpers/ModelHelper.cs)
- [Offline cross-provider database and licensing](https://github.com/cedya77/anime-offline-database)
