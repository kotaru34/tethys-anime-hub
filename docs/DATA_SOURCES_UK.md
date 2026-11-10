# Data sources, external APIs, provenance, permissions

**Source-adapter contract.** No arbitrary outbound URLs from the LLM. Source IDs are always namespaced (`mal:65170`, `anilist:123`, `anidb:456`) and crosswalk links carry provenance and confidence.

## Source priority by task

| Task | First choice | Conditional alternatives / caveats |
|---|---|---|
| Identify local MKV episode/release | Shoko file hashes → AniDB | Filename heuristics/LLM **only when hash identification fails** |
| Resolve external IDs | [Fribb/anime-lists](https://github.com/Fribb/anime-lists) crosswalk | Kitsu mappings, additional vetted ODbL crosswalk (check license, staleness); never assume same numeric ID across providers |
| Title, synonyms, cover, synopsis, format/status, premiere, episodes | [AniList GraphQL](https://docs.anilist.co/guide/graphql/) for targeted records | [Jikan v4](https://jikan.moe/) for MAL-specific entry, or anime-domain Kitsu API if verified live |
| Future/announced MAL-only title | MAL ID extracted from URL → Jikan `GET /anime/{id}/full` (or `/anime/{id}`) | Create local Work immediately even when provider returns 404/429; queue retry and optional title search, retain original URL/ID |
| Relations, franchise | AniList `Media.relations.edges` | Jikan `/anime/{id}/relations`, Shoko/AniDB verified relations; dedupe graph |
| Studio / staff / tags / genres | AniList/official metadata | Jikan/MAL, ANN Encyclopedia where policy permits; separate “animation studio” from fansub group |
| User/public similar-title signals | AniList media recommendations | Jikan `/anime/{id}/recommendations` for matched MAL ID; use as *candidates*, not final personalized ranking |
| Review semantic descriptors | Targeted AniList or Jikan per-title reviews | Approved open articles only after policy check, excerpts capped, spoiler filtering, source attribution |
| Artwork | Official/provider `coverImage`, `bannerImage` links | For **animation style**, use real frames from owned local MKV, or permissible promos; do **not** infer motion from a poster |
| Offline discovery seed | Existing personal catalog / provider recommendation edges | Independently licensed crosswalk/candidate database, targeted search, explicit rate limit |

## Important documented limits and legal caveats

### AniList
- API endpoint `POST https://graphql.anilist.co`. Query specific works, relations, tags, studios, recommendations and metadata. See [Media docs](https://docs.anilist.co/guide/graphql/queries/media).
- Current [rate-limit documentation](https://anilist.gitbook.io/anilist-apiv2-docs/docs/guide/rate-limiting) warns about temporary degraded **30 requests/minute** despite nominal 90/min. Never hard-code that limit as eternal. Honor `X-RateLimit-*`, `Retry-After`, avoid burst and cache source records appropriately.
- **[Official Terms](https://docs.anilist.co/guide/terms-of-use):** prohibit using API as storage/backup, mass collection, and certain *competing non-complementary list/tracker services*. A private, complementary catalog does not automatically guarantee permission. Minimize API usage to titles actually used by the owner; do not bulk-export the catalog. If intending to publicly distribute a general list/tracker, obtain permission or change provider strategy.

### Jikan / MyAnimeList
- [Jikan API](https://jikan.moe/) is an **unofficial** API that parses public MyAnimeList data; it is not an official MAL backend. Nevertheless it is the **direct adapter for pasted MAL IDs**, because original records may not yet have AniList IDs/crosswalk entries.
- Typical `https://api.jikan.moe/v4/anime/{mal_id}/full`; also `/anime/{id}/recommendations`, `/anime/{id}/reviews`, `/anime/{id}/pictures`, and `/anime/{id}/relations`. Verify existence against [OpenAPI](https://github.com/jikan-me/jikan-rest/blob/master/storage/api-docs/api-docs.json) during implementation.
- Rate limit in maintained API spec: **3 requests/second and 60/minute**; cached results ~24h. The upstream MAL connection can fail independently. Use limiter, Retry-After, conditional caching, circuit breaker.
- Do not treat a Jikan 404/timeout as proof an anime does not exist. Persist a placeholder with the MAL URL and enqueue enrichment. Once covered, fill cover and metadata; no blocking on successful page fetch.
- Do not scrape MAL itself as an automatic error fallback without separately checking its ToS and robots policy. Jikan already exposes the needed public dataset through a structured interface.

### Fribb & ID crosswalk
- [Fribb/anime-lists](https://github.com/Fribb/anime-lists) offers an AniDB-based mapping to AniList, MAL and other services. It may have missing/new-season mappings. Refresh its compressed snapshot periodically and retain previous good version on parse errors. Keep all IDs as **separate provider keys**, never convert by numeric equality.
- An independent [anime-offline-database successor](https://github.com/cedya77/anime-offline-database) was available in 2026 after original manami-project archive. Data publishes under ODbL/DbCL (see repository); license/attribution/share-alike constraints matter if redistributed. Optional crosswalk source, not a license to indiscriminately republish upstream metadata.
- Store `source`, `fetched_at`, `source_updated_at`, `match_method`, `confidence`, `manually_verified` for each association.

### Other candidates
- Kitsu anime service `https://kitsu.io/api/edge` (JSON:API) may offer alternate cover/description and crosswalk; do **not** confuse with the unrelated CGWire “Kitsu” production management API.
- Anime News Network Encyclopedia may expose XML metadata and staff; if used, verify official endpoint, attribution and access terms. “Article” source requires separate copyright and site-policy review.
- Avoid scraping Reddit/blogs/forums by default. If a genuinely useful stable open resource lacks an API: per-site adapter, robots/ToS review, bounded HTML parsing, page refresh TTL, crawl delay, no authentication bypass, no anti-bot evasion, sanitize and minimize excerpts, visible attribution and the ability to disable an adapter. Malfunction must not break local catalog.

## MAL URL parsing (example)

Input: `https://myanimelist.net/anime/65170/DemVAMPS`

Required:
1. Parse host exactly: `myanimelist.net` or `www.myanimelist.net`; HTTPS only; accept path matching `^/anime/([0-9]+)(?:/[^?#]*)?$`. Ignore arbitrary query strings and reject unfamiliar hosts and URL redirects outside approved origins.
2. Store `provider='mal', external_id='65170'` as unique alias to canonical Work **before any network request**. User can save it even if Jikan is unavailable.
3. Background fetch Jikan `/anime/65170/full`; validate MAL ID response matches input; transfer title, alternative titles, synopsis, posters (as provider URLs), announced/airing status, tentative dates, tags, credits and source timestamp.
4. Query crosswalk for AniList/AniDB (optional). When absent, remain MAL-only, never hallucinate IDs. Track missing fields, retry weekly or faster when near airdates.
5. When download arrives, match on verified IDs/crosswalk; if none, show reconciliation candidates and require confirmation. Preserve record, personal rating, watchlist history and artwork metadata.

This path example is provided by the owner; its **current metadata and release status must be verified at runtime**. Do not hard-code any title or release year into code or tests.

## Freshness & failure strategy

| Data state | Suggested refresh |
|---|---|
| Announced / TBA / nearing premiere | 1–3 days, with ETag and conditional requests where supported |
| Currently airing | 1–3 days |
| Finished / stable | 30–90 days or manual |
| Relations & crosswalk | 7–30 days, conditional check |
| User ratings/reviews | Local transaction immediately, no remote API required |
| Recommendation discovery | Weekly snapshot plus manual rerun |
| External public review evidence | Long TTL, only on needed candidates |

Network failures: exponential backoff + jitter, process a small bounded batch, HTTP timeouts, pagination caps, provider circuit breakers. Empty source data must not erase older good data. Attach provenance to every field; prefer manual overrides, then verified IDs, then source freshness/authority; use per-field confidence and conflicts for reconciliation.

## Recommended data access safeguards

- Only server adapters can issue HTTP. Strict allowlist of domains; deny IP literals, localhost, private/link-local/reserved destination IP ranges, unexpected redirects and non-HTTPS to prevent SSRF.
- No LLM-generated raw URL fetch. The LLM gets bounded `source_id + work_id` lookups, source excerpts and official metadata already validated by application code.
- Never blindly retain entire scraped review or article; keep citation URL, finite short excerpt where permitted, normalized semantic claims and fetch/hash timestamps.
- Track provider rate-limit headers and spend; show an “enrichment delayed” state instead of dropping an entry.
- Remember a website's terms/rights and API availability can change; adapters are replaceable, mandatory local state remains in PostgreSQL.

## External references

- [AniList GraphQL](https://docs.anilist.co/guide/graphql/)
- [AniList Media](https://docs.anilist.co/reference/object/media)
- [AniList Terms](https://docs.anilist.co/guide/terms-of-use)
- [Jikan](https://jikan.moe/)
- [Jikan OpenAPI specification](https://github.com/jikan-me/jikan-rest/blob/master/storage/api-docs/api-docs.json)
- [Fribb/anime-lists](https://github.com/Fribb/anime-lists)
- [Alternative anime-offline-database successor](https://github.com/cedya77/anime-offline-database)
