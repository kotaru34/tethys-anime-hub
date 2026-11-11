# AGENTS.md — Project continuation rules

This repository is the durable source of truth for Tethys Anime Hub. Read this file, README.md and docs/PRODUCT_ARCHITECTURE.md before changes; for recommender work also read docs/RECOMMENDER_DESIGN.md, docs/DATA_SOURCES.md and docs/DATA_MODEL.md.

## User intent
Personal, self-hosted, high-quality anime catalog with automatically imported torrent releases; announcement-only anime saved by URL/title **without files**; personal score 0–10 and separate review; nuanced self-learning recommendations weekly, especially **visual style and color, protagonist/character personality and relationships, yuri/yaoi subtext, tone, plot complexity, violence**, and atypical preferences. Do not substitute popularity- or genre-only collaborative filtering.

## Non-negotiable decisions
- All `/Anime/release_name/*.mkv` plus optional nested subtitle files are **read only**, including for Shoko, Jellyfin and workers. Never rename or modify a torrent file or Shoko-managed VFS.
- PostgreSQL is the central authoritative DB. Keep it (do not swap to SQLite). Shoko/Jellyfin retain separate internal DBs.
- Shoko/Shokofin/Jellyfin for media identification and streaming; Intel UHD 630 Quick Sync through **DRM render node** in Proxmox LXC – not full PCI passthrough; laptop host display remains working.
- FastAPI + Jinja2 MVP and Python workers; Qwen3.6-35B-A3B via user's existing endpoint for strictly controlled analysis; do not invent unrestricted browsing or shell tools.
- Core anime Work entity **must be independent of Jellyfin ID** before implementing remote-only watchlist; external IDs are namespaced and provenance-based; preserve personal data on rescans/merges.
- Future/announced metadata fields may legitimately be unknown (NULL). MAL URL e.g. /anime/65170/DemVAMPS is a **user-supplied example**, never assume date/cover/studio without actual source response.
- Recommendations require multiple retrieval lanes, aspect features with confidence, exploration/diversity, explicit negative feedback, measurable learning from user data, explanations and versioned evaluation.
- Cover visual style is *not* animation visual style. Real visual analysis needs actual frames or lawful stills and a vision-capable model; never assert text-only Qwen has analyzed pixels.
- Respect external API terms, no bulk AniList harvesting, robots/rate limits, use narrow API calls before any scraper.

## Repository state as of 2026-11-10
GitHub started empty; product/design docs were committed first, and the earlier 32-file runnable MVP v0.1 was then imported as source on main. Local smoke tests passed, but host-specific deployment is not verified. See issue #1 for remaining integration acceptance. Do not claim existing code implements announced watchlist or self-learning engine until built/tested.

## Implementation practices
- Small typed interfaces and adapters; reversible Alembic migrations. Idempotent jobs with source caching, proper retry/backoff and no API hammering.
- Do not create fake `remote:mal:<id>` Jellyfin PK records. Migrate to Work UUID with explicit asset associations.
- Schema: normalized source IDs, evidence/provenance/confidence, missing-data masks, immutable recommendation run snapshots, append-only user preference events, model/prompt versions.
- Direct Play first, Intel QSV fallback, no GPU stealing from Qwen or GTX1650 workloads; compute expensive embeddings off-peak and measure overhead.
- Unit/integration tests for identity deduplication and watchlist merge; playback/ASS/Hi10P smoke tests on real system; recommender evaluation by holdout + novelty/diversity + evidence confidence.
- Credentials: `.env`, API keys, private user history, screenshots containing personal details **never** in Git. No private prompt logs; use synthetic fixtures.
- Document uncertainty and known gaps explicitly; do not claim unverified API compatibility or successful live deployment.

## Issue tracking
- #1 import previously delivered MVP code
- #2 canonical Work + MAL URL watchlist
- #3 evidence and visual-style extraction
- #4 weekly suggestions and explainable interface
- #5 self-learning personalization and offline evaluation
- #6 behavioral playback analytics and privacy controls
- #7 modern AMOLED UI and editable Taste Profile

## When modifying
1. Inspect repository state and latest issues/PRs.
2. Choose an issue, write or update acceptance tests first; check provider rules for external calls.
3. Commit focused changes and document whether feature is **implemented**, **tested locally**, **integration-tested on user's hosts**, or **design-only**.
4. Keep installation/backup docs current with actual code and compose files.

## Development language, UI and learning updates (2026-11-10)
- **English only** during development: UI strings, docs, comments, tests, names, user-facing model summaries; optional localization later. Prefer generic `docs/*.md` paths (no `_UK` suffix).
- Modern accessible responsive UI; selectable **System/Dark/Light/AMOLED**. True AMOLED means page and normal cards/panels **#000**. Refer to docs/UI_DESIGN.md.
- Never assume Ukrainian or any other audio language. Capture every media track; per-user preferences optional, not hardcoded defaults.
- Passive Jellyfin playback signals are **weak, noisy, opt-in evidence**. Repeated patterns across independent anime can contribute despite zero manual ratings; no automatic negative rating from infrequent watching. Session reconstruction, opportunity, autoplay and malfunction checks required. Refer to docs/BEHAVIORAL_LEARNING.md.
- Show an editable, evidence-based, natural-language **Taste Profile** per account. Local Qwen is only a constrained summarizer of structured claims; no invented reasons for viewing behavior. See docs/PREFERENCE_PROFILE.md.

## Current deployment decision (latest, 2026-11-11 – supersedes previous all-in-one LXC)
- **Owner will clean-reinstall and rewind conversation to earlier deployment prompt. This GitHub decision persists after rewind; use [docs/DEPLOY_TOPOLOGY.md](docs/DEPLOY_TOPOLOGY.md) as highest-priority deployment source of truth.**
- Two unprivileged native-service Debian 13 LXCs on **two PVE hosts**: storage PVE host at 10.169.6.200 hosts Shoko 5.3.3 near the physically attached /mnt/neko/Anime; laptop PVE i5-9300H with UHD 630 hosts Jellyfin 10.11.11 + Shokofin 6.0.5 + Tethys Web/Worker. Existing **remote PostgreSQL** for Tethys only. **No Docker, new VM or new PostgreSQL service**. New CT IDs not established.
- /Anime is read-only in both LXCs. On storage-host Shoko use local host bind mount; on laptop Jellyfin/Tethys use NFS (export 10.169.6.200:/mnt/neko). Align path mapping across hosts and verify Shokofin remote Shoko API URL and writable Jellyfin VFS.
- GID 3000 NFS group (anime), 2770 directory. First laptop LXC required custom unprivileged GID mapping, and only **primary** GID=3000 worked for NFS access; avoid chmod/chown of torrents. Recheck independently for new containers.
- **Known critical incident:** Shoko 5.3.3 watcher recursion, stack WatcherOnError→Start, led to Save hang and after restart stuck at "Initializing File Watchers". SQLite `ImportFolder.IsWatched=0` (after backup and stopping Shoko) recovered it. Fresh import folder: Drop Type None, **Watch For New Files OFF**, until root cause isolated.
- Instant discoveries remain required: torrent client **completion event** or writer-side hook → authenticated Shoko API scan; do not rely on NFS inotify or six-hour polling. Even storage-local watchers may miss remote NFS clients' writes.
- docs/NATIVE_LXC.md and docs/DEPLOY.md describe **superseded alternatives**; don't use as current runbook.

## Shoko 5.3.3 unrecognized bulk-recovery (2026-11-11)
- Owner verified 110 recognized / 1057 unrecognized files, with AniDB UDP `320 NO SUCH FILE` on HEVC fansub releases. This is an **identity strategy defect** (hash-only dependency), not UDP transport failure. Preserve Shoko; do not propose replacing it without owner's instruction.
- A conservative standard-library tool is now committed at `tools/shoko_reconcile/shoko_reconcile.py` (+ README and tests). Uses Shoko 5.3.3 API `/File`, `/Series/AniDB/Search`, `/Series/AniDB/{id}/Refresh`, `/File/{id}/LinkFromSeries`, enabling manual-link semantics automatically by release-folder and episode without changing originals. Start with dry-run report.
- Official Shoko OfflineImporter plugin is .NET 10 / Shoko 6 and **not compatible** with 5.3.3; never recommend installing it directly in current LXC.
- **Goal: <=5% unknown based on actual host coverage and correctness**, not by ignoring/mislinking files. This target is NOT yet demonstrated. See issue #undefined.


## Live Shoko identification failure and remediation (2026-11-11)

- **Observed:** owner's Shoko Server 5.3.3 on storage-local anime host indexed 1,167 files, **1,038 Unrecognized** (88.95%); many AniLibria/AniLiberty remuxed/re-encoded files trigger AniDB UDP `320 NO SUCH FILE`. This is not a UDP parse bug and ED2K rehash will not repair genuinely unknown file releases.
- **Do not discard Shoko/Shokofin on this basis.** Its series/episode AniDB/TMDB metadata is valuable. A manual Shoko file→episode cross-reference via supported `/api/v3/File/{id}/LinkFromSeries` works without AniDB File ID. Never fabricate AniDB release-specific data.
- **Implementation:** `tools/shoko_reconcile/` contains Python v2.1 code and tests. It parses release folders/episodes (including localized titles, SxxExx, OVA, specials, movies, OP/ED extras), uses Shoko's existing title candidates and optionally an offline cross-provider ID/alias database, prepares per-file links, validates target AniDB series and exact episode type/number in live Shoko before writes, and exports series **and episode-level** metadata.
- **Actual offline fixture:** user provided a v1 `shoko-plan.json` with 83 release groups. Reanalysis without external alias catalog yielded **808 potentially linkable of 1,038 unknown**, with 21 passing local tests. This is *not* live achieved coverage: even if all succeeded, 230 unknown / 1,167 total = **19.71%**. Need at least 172 further correct links to reach <=5% unknown, and a sample to establish <=10% misidentification. Extras must not be hidden merely to improve denominator.
- **Next actions:** run v2.1 against the owner's original plan **with** the locally cached `cedya77/anime-offline-database` aliases; inspect remaining groups and correct scene/group title aliases, mixed specials, cour splits and series absent from the database. Then apply in small verified batch and compare true `--status`. Metadata completeness >=95% is a field-level audit goal, NOT yet demonstrated; native AniDB File ID/release verification cannot be reconstructed.
- **Source documents:** `tools/shoko_reconcile/README.md` is the authoritative executable runbook. Keep this issue and progress tracked in the repo. **Never commit user's original filename plan, API key, or personal user data**.
