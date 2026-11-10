# Tethys Anime Hub — product vision, architecture and delivery plan

> Canonical project brief, 2026-11-10. This document is **target design**, not a claim that every feature is implemented. Development language: English. Deployment is for a private, single-user system with reserve capacity for 2–3 streams.

## 1. Purpose and user journeys

An independent self-hosted anime *knowledge library*, not merely a video folder browser.

1. **Downloaded anime:** Existing torrent release appears automatically, normalized to the correct title/season/OVA, cover, synopsis, release year, official studio, fansub/release group, embedded audio and subtitles, nested sidecar subtitles and episode count.
2. **Not downloaded / announced:** Paste a MAL URL such as `https://myanimelist.net/anime/65170/DemVAMPS` or search a title; create a persistent **planned** anime entry with cover and as much metadata as the sources actually know. No MKV, Jellyfin or Shoko ID required. Fields with missing or future information remain unknown, not fabricated.
3. **Transition:** The physical torrent later arrives under `/Anime/<release_name>/*.mkv`; metadata reconciliation links it to the *same* library work, preserving personal rating, review, planned status/history and recommendation evidence. Duplicates are never silently merged based on name alone.
4. **Watch and rate:** Save personal 0–10 rating (including 0), free-form separate review, explicit watch status (planned, watching, completed, paused, dropped, rewatch), completion date and optional concise structured feedback about what exactly was liked/disliked.
5. **Franchise graph:** Show locally playable, owned-but-incomplete, planned, announced and unavailable seasons, films, sequels, OVA, specials and alternative versions. Relations come from canonical metadata and are traversed beyond a single hop (with bounds and cycle detection).
6. **Discover:** On a weekly schedule produce explainable, personal, *varied* anime suggestions – including not-yet-downloaded works – with cover and reasons tied to nuanced preferences. Search does not exclude a title simply because a few descriptors are dissimilar. Enable accept/reject, `not interested because...`, `more like this`, `less of this`, and `already watched`. Suggestions may be saved as planned.
7. **Reliability:** The original torrent trees and subtitles remain untouched. Streaming or read-only inspection only. Service stays useful even if AniList/MAL/Qwen is temporarily unavailable.

## 2. Invariants & filesystem contract

```text
/Anime/<release_folder>/*.mkv
/Anime/<release_folder>/<arbitrary_subtitle_folder>/*.ass, *.srt, ...
```

- Torrent files are immutable: never rename, move, remux, embed tags, rewrite MKV headers, place NFO/posters inside source folders, or modify sidecars.
- Every container that accesses files receives a read-only bind mount. Shoko VFS is owned exclusively by Shoko/Shokofin, not altered by application code.
- Full hash reads are fine: strong disk I/O is available. Optimize primarily **GPU use and CPU time**, not storage reads.
- Catalog, annotations, vector embeddings, preview files, logs, caches and transcoding segments are written outside `/Anime` to SSD state volumes.
- Missing disks and disconnected mounts **must not** cause automatic deletion of user data; retain work records and mark asset state stale/unavailable after validated rescans.

## 3. Confirmed deployment and technology choices

| Role | Choice | Notes |
|---|---|---|
| Source identification | Shoko Server + AniDB | Exact file hash/episode match preferred |
| Jellyfin bridge | Shokofin | Plugin/VFS; do not duplicate source identification |
| Media server | Jellyfin | DRM playback, Direct Play/remux/transcoding |
| Transcode hardware | Intel UHD 630 Quick Sync on i5-9300H | `/dev/dri/renderD*` shared with an unprivileged PVE LXC, **not** exclusive PCI passthrough; host laptop screen stays available |
| UI/API | Python FastAPI + Jinja2 templates | Leaner than Next.js for this private app; retain REST endpoints |
| State | PostgreSQL 17 (MVP version) | Centralized backups, migrations; target pgvector extension for similarity search |
| Media adapters | Jellyfin API, Shoko API, Fribb AniDB/AniList crosswalk | Strict normalization & provenance |
| Public metadata | AniList GraphQL per-title, Jikan/MAL where needed | Read source policies; do not build an indiscriminate copy of upstream databases |
| Local language model | Existing Qwen3.6-35B-A3B endpoint, OpenAI-compatible `llama-server` | On z425 V100, reserve GPU for inference; no permanent extra GPU jobs |
| Embeddings | Initially text semantic embeddings via a CPU/shared existing embedding model; pgvector | Image embeddings separately after quality testing; optional CPU off-peak jobs |
| Recommendation engine | Python scheduled candidate retrieval + feature extraction + adaptive ranker + exploration | See `RECOMMENDER_DESIGN.md` |
| Orchestration | Docker Compose for database, app, Shoko and workers; Jellyfin in LXC | No Kubernetes, no mandatory Redis |
| Automation | DB-backed job queue with retry and jobs scheduled once per week | Use advisory locks / SKIP LOCKED; idempotency |
| Security | LAN-only/VPN, TLS reverse proxy if exposed | Secrets in env, no torrent writes, CSRF, validation & SSRF controls |

**Actual hardware:** i5-9300H laptop, GTX 1650 occupied by MemPalace/embedding, Intel UHD 630 available to host and Jellyfin; z425 AI E5-1620 v2 ~35% background CPU and V100 32 GB largely occupied by Qwen (~2 GB VRAM headroom). Prefer Direct Play, then remux, then Intel QSV. Do not move streaming to V100/GTX1650 without measured benefit.

## 4. Metadata – what every work should express

- IDs with source namespace: AniDB, AniList, MAL, Shoko, Jellyfin and future sources; canonical **local UUID**.
- Titles: original, romaji, English, localized and aliases; format/TV/movie/OVA/ONA/special; status announcement/not-yet-aired/airing/finished/TBA; year/season/air date/timezone where verified; actual vs announced episode count; duration; studios, producers, source material.
- Description, cover/banner, genres, rich tags, age/demographic labels where supported, studio / production data, release group distinct from studio, track/language info with reliability flags.
- Physical: every episode, local file paths, checksum/stream metadata, audio/subtitle codecs/languages, subtitle sidecars and episode match quality; e.g. `11/?` when total unknown. Count dubbed episodes per chosen language, do not infer dub quality.
- Relations: typed, directional PREQUEL/SEQUEL/SIDE_STORY/ALTERNATIVE/CHARACTER/PARENT/ADAPTATION/etc, with directed graph and bounded expansion.
- User: personal rating, review, watch state, completion/progress, planned date, notes, favorites, explicitly liked/disliked *aspects*, skip reasons, manual corrections, negative preference examples.
- Recommendation features: textual themes, animation aesthetics, character agency and affect, protagonist archetype (competent/crybaby/etc), relationship undertones incl. yuri/yaoi, violence intensity vs graphic violence, narrative complexity/coherence, tone, pacing, character chemistry, novelty; **continuous distributions + uncertainty**, not brittle yes/no flags.
- Evidence: source URL and fetched timestamp, model + prompt version, source excerpt where permitted, agreement/disagreement, confidence.

Unknown or announced fields **must not be guessed**; preserve source-specific contradictions instead of auto-overwriting user corrections.

## 5. Architecture and data flow

```text
                /Anime (read only)
                       |
            Shoko (AniDB hashes)
                       |
                 Shokofin/VFS
                       |
               Jellyfin API          User enters MAL URL / title
                       |                       |
                media adapter                 v
                       |                external-ID resolver
                       +--------+--------------+
                                v
                     canonical Work resolver
                                |
              PostgreSQL Work + external IDs + media assets
                   |                     |
              enrichment          user rating/review
              sources / LLM             /feedback
                   +----------+----------+
                              v
                evidence-aware feature extraction
                              |
                    weekly candidate retrieval
                              |
                 adaptive ranking + diversity
                              |
                   recommendation snapshots
                              |
                     FastAPI Web UI / API
```

**Do not** use Jellyfin's ID as the Work primary key. A work may have zero or multiple release files and several external IDs. Keep a foreign-key attachment to Jellyfin objects and reconciliation history. Shoko and Jellyfin may disagree about season grouping; preserve mapping evidence.

## 6. Safe automation and allowed Qwen tools

Shoko hash or verified explicit external ID > reliable crosswalk > metadata candidate score > LLM disambiguation > human review.

Qwen is a *bounded extractor/judge*, **not** a free-browsing agent, arbitrary shell runner, database writer or unquestioned truth source. Allowed task-specific operations (enforced by our service, no model-chosen raw URL):

```text
lookup_work(id_or_provider_key)
search_source(provider, bounded_query)
get_work_details(provider, exact_id)
get_work_relations(provider, exact_id)
get_release_inventory(readonly_release_id)
get_media_streams(readonly_media_id)
get_public_review_excerpt(approved_source, work_id, page)
get_evidence(work_id, feature_name)
```

- Network permitted **only to explicit approved provider adapters**. JSON schema with bounded allowed values; reject invented IDs, broken citations, arbitrary URLs, tool recursion, long outputs, injection text from scraped sources.
- Each inferred feature includes `value`, `polarity`, `confidence`, `evidence_ids`, `model_id`, `prompt_version` and evidence availability.
- Use local Qwen for semantic aggregation, character/theme analysis and weekly pairwise re-ranking; use embeddings/structured descriptors for retrieving candidates. Qwen should not read the full anime folder or unbounded reviews.
- For visual features: a *text-only* LLM cannot actually judge animation colors/quality from synopsis or cover. Use dedicated vision/embedding model on lawful official stills or sampled **owned MKV frames**, and explicitly mark low evidence for unowned/upcoming works. See recommender design.

## 7. Operational policy, low overhead

- Keep SignalR/VFS, media probing, conditional metadata refresh, chapter images and **keyframe-only Trickplay** as useful low steady-state-overhead features. Heavy preview generation should run after import, not during active playback.
- Remove duplicate filesystem indexers and conflicting metadata providers; retain a small subtitle-sidecar mapper for arbitrarily nested directories.
- Avoid wasteful full rescans, but **weekly low-priority integrity scan** is acceptable. Hash new files on import; no need to constrain read throughput in normal use.
- Queue retries with exponential backoff and scheduled refresh: high-frequency only for upcoming/airing titles; static titles refreshed rarely; full recommendation generation once every seven days, with manual re-run on explicit request.
- Store only necessary metadata, source provenance and permitted references; use finite TTL and pagination for provider APIs. **Do not bulk-clone AniList** or rely on unrestricted scraping.
- Separate CPU/GPU workloads by priority. QSV encode, CPU fallback for complex ASS/Hi10P; text/image embeddings off-peak; Qwen calls serialized/rate-limited so it remains responsive to unrelated tasks.
- Backups: PostgreSQL `pg_dump` + WAL/base-backup as desired; independently back up Shoko internal DB/config, Jellyfin config and local app state. Test restoring. Store minimal source caches reproducibly.

## 8. Known caveats and chosen handling

| Risk | Mitigation |
|---|---|
| AniList terms restrict bulk harvesting and competing list/tracker services | Private complementary integration, per-title minimal queries, attribution/caching policy, evaluate permission if distributed; provider abstraction and user-driven imports |
| MAL URL exists but AniList record is absent/not yet mapped | MAL ID first via Jikan or official authorized API; create local Work immediately and enrich asynchronously; no guessed AniList ID |
| Bad fan-release names, broken subtitles/Hi10P | Shoko hashes and episode matching first; sidecar matching with verification; manual conflict resolution; tested QSV/CPU fallbacks |
| Artwork mistaken for animation style | Separate *cover aesthetic* from *actual animation frames*; confidence masks; don't label art style based on genre |
| Review text noisy, spoilers, bias and hallucination | Provenance, multilingual normalization, review aggregation with caps, source agreement, per-feature confidence, no long quotes |
| Sparse personal ratings and shifting tastes | Bayesian priors, contextual factors, explicit feedback, online updates, exploration, uncertainty, model versioning and evaluation |
| Recommendations over-filter interesting outliers | Soft ranking, diverse candidate lanes and exploration quota; user-set hard exclusions only |
| Duplicate entries when planned work becomes local | Strong provider ID matching, atomic asset linking, explicit resolution for ambiguous matches, preserve user fields |
| External source errors or rate limits | Conditional GET/cache, bounded retries, circuit breaker; do not destroy records on API failure |
| Future announced episodes unknown | Store NULL total, tentative dates with provenance, refresh as information appears |
| Poster hotlinks disappear | Provider-compliant fallback, TTL/ETag; keep URL + optional lawful cached thumbnail with attribution |
| Public GitHub repo | No private data, credentials, or personal watch history; `.env` never committed |

## 9. Delivery milestones and acceptance

- **M0 — MVP import:** Existing FastAPI + Shoko/Jellyfin catalog, PostgreSQL and deployment; acceptance real MKV scans & ASS streaming.
- **M1 — Canonical Work + watchlist:** Alembic migration, MAL URL resolver, `planned` entries with covers and incomplete metadata, browser import/search, correct merge when download appears. Strong tests: `65170` URL format, an unmapped MAL-only title, title duplicates and offline API.
- **M2 — Feature extraction:** Controlled ontology, typed evidence/provenance; AniList/MAL/Jikan data, local text embeddings; real art-style media evidence. Compare text vs frames separately.
- **M3 — Recommendation baseline:** Weekly candidate retrieval, scoring, exploration & diversity, explainable Web UI, save-to-watchlist, feedback. Unit tests for no-hard-filter, unknown values and source outages.
- **M4 — Adaptive learning:** Calibrated user preferences, user review analysis, sparse-data regularization, pairwise feedback, temporal drift, offline counterfactual/holdout evaluation and versioned retraining.
- **M5 — Quality:** More frame sources, visual comparisons, spoiler-safe review synthesis, preference controls, context-aware suggestions, optional federated/import/export.

**Quality gates:** identities not duplicated, ratings preserved, no file mutation, deterministic replay of recommendation runs, API outage tolerated, no recommendation based solely on genre when stronger art/character evidence exists, per-run explanation and uncertainty visible, regression tests in CI.

## 10. Links to maintained specs

- [Recommendation engine](RECOMMENDER_DESIGN.md)
- [Provider strategy](DATA_SOURCES.md)
- [DB schema plan](DATA_MODEL.md)
- [v0.1 deployment](DEPLOY.md)

## 11. English-only development language, themes and track neutrality (2026-11-10 revision)

All interface copy, comments, configuration names, tests and docs are **English** for now; localization is optional in the future. The UI must be modern and responsive, with **System / Dark / Light / AMOLED True Black** (black background, panels, cards) as distinct options. See [UI design](UI_DESIGN.md).

Track discovery captures all actual audio and subtitle languages, including `und`, **without a hard-coded language preference or global filter**. Optional account-specific ordered preferences may be applied at playback/UX level, never as a forced media assumption. Legacy `dubbed_count` from MVP must not be interpreted as an authoritative global count.

## 12. Behavioral learning and personal taste profile

An account may have zero explicitly rated titles. The engine must still discover **tentative** factors from repeated, quality-checked Jellyfin viewing events (start/progress/stop/rewatch/continuation), normalized by available episodes, length, autoplay, technical playback quality and opportunity. Slow progress is **not** evidence of dislike by itself and a single binge is **not** a 10/10 rating. Learning must be per-account, consent-aware, and backed by confidence and independent-work sample counts. See [Behavioral Learning](BEHAVIORAL_LEARNING.md).

A private [Taste Profile](PREFERENCE_PROFILE.md) summarizes positive/negative/context-dependent preferences as editable English prose, with evidence levels, sources, uncertainty, correction and deletion controls. Generate it with local Qwen only from validated structured claims; cache snapshots. Never invent explanations about the user's real-world routine or circumstances.
