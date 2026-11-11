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

## Current deployment decision (2026-11-11)
- The owner chose **single unprivileged Debian 13 LXC 1510**, with native systemd services for Jellyfin, Shoko and Tethys; **no Docker, new VM or new PostgreSQL server**. Existing remote private-LAN PostgreSQL is for Tethys only. See docs/NATIVE_LXC.md. Keep Compose as optional alternative.
- NFS /Anime is read-only, group GID 3000. Primary GID 3000 works on the host and LXC but supplementary GID 3000 does not suffice in this NFS setup. Run Jellyfin, Shoko and Tethys worker with primary group anime (GID 3000) and separate private credential groups to prevent secret leakage.
- Native Shoko 5.3.3 uses .NET 8, mediainfo/librhash, separate own database in its service home; verify at runtime. Shokofin 6.0.5 in Jellyfin 10.11.11; own PostgreSQL is not Shoko DB.
- docs/DEPLOY.md is the older optional Docker/VM route, not the present runbook. Add native deployment tests and maintain this guide upon real integration.
