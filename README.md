# Tethys Anime Hub

**Self-hosted anime library, torrent-safe media catalog, watchlist for unowned/upcoming works, and adaptive personal recommendations.**

Tethys unifies local MKV releases and online metadata with works saved before they have aired or been downloaded. Ratings and personal reviews are separate, and the recommendation system is designed to learn from **fine-grained taste and cautious observation of actual viewing habits**, not merely genres or popularity.

## Documentation

- [Product vision, architecture, hardware and roadmap](docs/PRODUCT_ARCHITECTURE.md)
- [Personalized recommendation engine](docs/RECOMMENDER_DESIGN.md)
- [Behavioral learning from Jellyfin playback](docs/BEHAVIORAL_LEARNING.md)
- [Natural-language and editable Taste Profile](docs/PREFERENCE_PROFILE.md)
- [UI/UX: responsive modern design and AMOLED True Black](docs/UI_DESIGN.md)
- [Data sources, providers and API policies](docs/DATA_SOURCES.md)
- [PostgreSQL data model and safe migration](docs/DATA_MODEL.md)
- [**Current clean-install topology – storage-local Shoko + GPU-local Jellyfin/Tethys**](docs/DEPLOY_TOPOLOGY.md)
- [Superseded all-in-one LXC instructions (historical)](docs/NATIVE_LXC.md)
- [Alternative older Docker/VM deployment](docs/DEPLOY.md)
- [Machine-readable anime feature ontology (91 factors)](spec/features.v1.json)
- [Behavior signal definitions](spec/behavior_signals.v1.json)
- [Instructions for coding agents and future sessions](AGENTS.md)

**Working language:** English for UI, code, comments, technical documentation, configuration and tests. Localization can be added later. **No global default anime audio/subtitle language**; detect all tracks, preserve unknowns, and use optional per-account preferences.

## Stack and infrastructure

| Concern | Choice |
|---|---|
| Release/episode identification | Shoko + AniDB hashes |
| Jellyfin integration | Shokofin / Shoko-managed VFS |
| Media playback | Jellyfin in PVE LXC, Intel UHD 630 QSV via DRM render node |
| Own application | FastAPI + Jinja2 + minimal JavaScript |
| Durable state | PostgreSQL; pgvector when benchmarked and installed |
| Data enrichment | AniList GraphQL, Jikan/MAL, Fribb anime-lists; narrowly scoped, rate-limited |
| Local reasoning | Qwen3.6-35B-A3B through existing llama-server; constrained tools and validated output |
| Habit observations | Jellyfin Webhook events; account-controlled collection and confidence-aware aggregation |
| Recommendations | Weekly multi-lane retrieval + explainable preference model + diversity/exploration |
| UI | Contemporary responsive poster catalog; Dark, Light, System, **AMOLED** (#000 background and surfaces) |

## Invariants

1. `/Anime/<release>/*.mkv` and nested subtitles are **read-only**. Active torrents and Shoko-managed VFS are never modified by our code.
2. **Canonical Work UUID is independent of Jellyfin media IDs**. A future MAL-only title exists before there is an MKV and later gains a local-media association without losing annotations.
3. Missing metadata is *unknown*, not false. Cross-provider IDs are namespaced, evidence-backed and never fabricated.
4. The recommendation system considers artworks/colors **and actual animation evidence**, protagonist temperament, relationships/subtext, narrative factors, violence, and other subtle signals. Poster art ≠ animation quality.
5. Implicit watch behavior is weaker and more confounded than explicit reviews: bingeing is not automatically `10/10`; slow watching is not automatically dislike. The taste profile displays confidence and supports corrections.
6. No rigid genre exclusions or globally preferred audio language. Only explicit user restrictions can act as hard filters.
7. User viewing histories, tokens and secrets remain private and do not go to public providers or Git.

## Current status

**MVP v0.1 source is committed**: FastAPI/Jinja UI, Jellyfin-based indexing, sidecar inventory, AniDB→AniList matching, PostgreSQL, ratings/reviews, Compose and tests. The MVP UI supports a local theme switcher, including AMOLED, and displays detected audio-language episode availability without a forced target locale.

**Design-only / next milestones:** independent canonical Work migration, MAL-only upcoming watchlist, secured playback telemetry ingestion, confidence-aware self-learning recommendation engine, visual embeddings, and generated editable Taste Profile. The code is **not yet validated on the owner's Proxmox hosts**. Do not claim those future capabilities are implemented.

**Current installation decision (supersedes 2026-11-11 single-LXC attempt):** two unprivileged Debian 13 LXCs on **different PVE hosts** – native Shoko on the physical anime-storage PVE host (10.169.6.200), and Jellyfin/Shokofin + Tethys Web/Worker on the Intel UHD 630 laptop PVE host. Existing private-LAN PostgreSQL remains remote, no Docker or VM. The user intends to reinstall LXCs from scratch and rewind chat; [DEPLOY_TOPOLOGY.md](docs/DEPLOY_TOPOLOGY.md) is authoritative even if older conversation says otherwise.

See [GitHub Issues](https://github.com/kotaru34/tethys-anime-hub/issues) for milestones. Develop in small, reproducible, tested changes; retain Shoko/Jellyfin independently owned databases and backup them separately.

*Personal project. Not affiliated with AniList, MyAnimeList, Jellyfin or Shoko.*
