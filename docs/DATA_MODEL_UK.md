# PostgreSQL model, canonical identity and migration plan

**Target schema** for watchlist + independent discovery + recommendation engine. Current MVP v0.1 stores `anime.id = Jellyfin item ID`; that is intentionally **not adequate** for announced titles without local files. The migration below is required before implementing the new feature.

## Entity boundaries

1. `work` – a uniquely identified anime *work/season/OVA/movie/special*, persistent independently of storage. Primary key `UUID`. A franchise is a graph/collection of Works, not one monolithic media record.
2. `work_external_id` – zero or more verified provider IDs per work, unique on `(provider, external_id)`. Sources: `anilist`, `anidb`, `mal`, `kitsu`, etc. Store match confidence and origin. External IDs are *not interchangeable numeric values*.
3. `local_media` – Shoko/Jellyfin media items or releases, references one or more Works only through validated assignment; record `jellyfin_item_id`, `shoko_id`, file path, release group, date indexed, last-seen and mapping confidence.
4. `episode_asset` – individual episodes/files and media-stream inventory, including audio language, subtitles and sidecar matching, assigned to a Work and an episode ordinal when verified.
5. `work_metadata` – normalized title, cover URL, synopsis, status, tentative air date, episode total NULL allowed, studios and genres with per-field source records.
6. `work_relation` – typed directed edges between UUID Work IDs; support unresolved external refs for not-yet-imported relations.
7. `user_work` – rating 0–10, review text separately, watch status, progress and personal completion timestamps. `rating=NULL` means no opinion (not zero). Multiple users are permitted in schema although initial product is one user.
8. `user_preference_event` – explicit aspect-level likes/dislikes, reasons, ranking judgments, saves, rejects and optional low-confidence implicit signals; append-only history with event timestamps.
9. `work_feature` – versioned candidate descriptors (ordinal/continuous/categorical/embeddings) with confidence, evidence IDs, model version and missingness status.
10. `evidence` – source, URL, fetched timestamp, content hash, spoiler flag, confidence, rights and short permitted excerpt or normalized claim.
11. `recommendation_run` and `recommendation_candidate` – fixed weekly snapshots, candidate source lanes, scores, rank, reasons, uncertainty, algorithm version and historical feedback.
12. `job` and `provider_cache` – idempotent enrichment tasks, scheduling, retries, lock ownership, TTL, ETag and status.

## Minimal proposed SQL core (illustrative; create via Alembic migrations)

```sql
-- Assumes pgcrypto/UUID generation is available; application-generated UUID also OK.
CREATE TABLE works (
  id uuid PRIMARY KEY,
  preferred_title text NOT NULL,
  work_kind text,                    -- TV, OVA, MOVIE, ONA, SPECIAL, ...
  release_status text NOT NULL DEFAULT 'UNKNOWN',
  aired_at timestamptz,              -- NULL if only year/season or TBA known
  aired_precision text,              -- YEAR, SEASON, DAY, TBA
  total_episodes integer CHECK (total_episodes IS NULL OR total_episodes >= 0),
  summary text,
  cover_url text,
  metadata_updated_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE work_external_ids (
  provider text NOT NULL,
  external_id text NOT NULL,
  work_id uuid NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  method text NOT NULL,              -- exact, crosswalk, manually_confirmed, ...
  confidence real NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  provenance text,
  PRIMARY KEY (provider, external_id)
);
CREATE INDEX work_external_ids_work_idx ON work_external_ids(work_id);

CREATE TABLE local_media (
  id uuid PRIMARY KEY,
  work_id uuid REFERENCES works(id),
  jellyfin_item_id text UNIQUE,
  shoko_item_id text,
  release_path text,
  file_state text NOT NULL DEFAULT 'AVAILABLE',
  last_seen_at timestamptz,
  last_probe_at timestamptz,
  match_method text,
  match_confidence real
);
CREATE INDEX local_media_work_idx ON local_media(work_id);

CREATE TABLE user_works (
  user_id uuid NOT NULL,
  work_id uuid NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  watch_status text NOT NULL DEFAULT 'PLANNED',
  personal_rating numeric(3,1) CHECK (personal_rating IS NULL OR (personal_rating >= 0 AND personal_rating <= 10)),
  personal_review text NOT NULL DEFAULT '',
  last_watched_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, work_id)
);

CREATE TABLE work_relations (
  from_work_id uuid NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  to_work_id uuid NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  relation_type text NOT NULL,
  source text NOT NULL,
  confidence real NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  PRIMARY KEY (from_work_id, to_work_id, relation_type, source)
);

CREATE TABLE evidence (
  id uuid PRIMARY KEY,
  work_id uuid NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  source_name text NOT NULL,
  source_uri text,
  evidence_type text NOT NULL,
  extracted_claim jsonb,
  spoiler_risk text,
  confidence real,
  observed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE work_features (
  work_id uuid NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  feature_key text NOT NULL,
  feature_version integer NOT NULL,
  numeric_value real,
  categorical_value text,
  confidence real,
  evidence_id uuid REFERENCES evidence(id),
  extraction_model text,
  PRIMARY KEY (work_id, feature_key, feature_version)
);
```

**Production detail:** `watch_status` values validated with an application enum or database CHECK; `user_id` linked to real `users` table. Do not use remote URLs from arbitrary user input except through strict provider URL parsers. Put gallery/image embeddings in dedicated tables when added. Metadata source snapshots (JSONB) have separate finite TTL and retention policy; do not treat them as unlimited third-party backups.

### Recommendations / learning tables (target)

```text
user_preference_events(id, user_id, work_id, event_type, aspect_key,
                       direction, intensity, comment, observed_at, provenance)
user_preference_model(id, user_id, version, trained_at, algorithm,
                      weights_json, uncertainty_json, data_fingerprint, eval_json, active)
recommendation_runs(id, user_id, started_at, finished_at, model_version,
                    candidate_count, status, snapshot_hash, config_json)
recommendation_candidates(run_id, work_id, position, rank_score,
                          match_breakdown_json, evidence_ids_json,
                          retrieval_lanes_json, uncertainty, explanation_json)
recommendation_feedback(id, run_id, work_id, user_id, action, reasons_json, created_at)
provider_cache(source, normalized_key, etag, valid_until, fetched_at, error_count)
jobs(id, job_type, unique_key, run_after, attempt, max_attempts, lease_until, payload_json)
```

**Vector extension:** prefer `pgvector` on the PostgreSQL server after validated version compatibility and benchmark. Separate vectors `work_text_embeddings`, `work_visual_embeddings` and model versions. Migrating from base `postgres:17-bookworm` to an image with compatible pgvector requires a *planned image/version/extension* change and backups, not an in-place assumption that the extension already exists. Use CPU cosine similarity in small batches as a valid temporary path; PostgreSQL remains central source of truth.

## Identity/merge algorithm

### Add remote announced anime

1. User pastes official URL `https://myanimelist.net/anime/65170/DemVAMPS`. Parse and validate `mal:65170`.
2. In transaction, `SELECT work_id FROM work_external_ids WHERE provider='mal' AND external_id='65170'`. If found – use the existing Work; otherwise allocate UUID, insert Work with placeholder title and `mal:65170`; enqueue enrichment with an idempotency key.
3. Jikan fetch/other source may fill description, title, date, cover and status *later*. Failure retains Work. Each field records provenance and nullability.
4. The user can mark `PLANNED` and add private notes instantly, independently of API availability.

### Later a local release is scanned

1. Shoko identifies AniDB ID/episode via hash. Jellyfin episode metadata is normalized.
2. Resolve external-ID crosswalk (AniDB → AniList/MAL). Check for **existing** Work matching any **verified** namespace ID, including previous remote watchlist.
3. If exactly one Work matched, attach the new `local_media` and episode assets. **Do not duplicate or replace** user rating, review or planned history. Mark file availability separately.
4. If multiple Work IDs match (crosswalk conflict, remakes or multi-anime bundles), quarantine identity resolution to manual review; **never silently merge**.
5. If no strong ID, fuzzy title/season candidates + LLM-assisted disambiguation. No unverified automatic merge; create provisional Work and show candidate review queue.
6. If a file disappears, set `local_media.file_state = MISSING` but leave Work, watch entry and recommendation evidence intact.

### Merging duplicates
Only after explicit verified identity reconciliation: transaction with row locks; migrate `user_work`, ratings/reviews, evidence, relations and media attachment. If *two personal reviews* conflict, require user decision rather than concatenating silently. Preserve alias/redirection table for old Work UUIDs, audit original records.

## Migration from existing MVP v0.1

Do **not** destroy the current `anime` table or change its `id` column in one destructive step.

1. **Backup:** verify `pg_dump --format=custom`, copy app config; test a restore into disposable DB.
2. **Expand:** Alembic `0002`: create `works`, `work_external_ids`, `local_media`, `user_works`, `work_relations`, `evidence`, `jobs`; add nullable `anime.work_id` referencing `works`.
3. **Backfill:** for each existing `anime`, create or resolve Work by validated AniList/AniDB IDs and constraints, link its Jellyfin ID as local_media; copy personal_rating/review into user_works with sentinel initial user; preserve null ratings; do not merge solely on case-insensitive title.
4. **Dual read / compatibility:** browse old and new as needed; test all 0/10 ratings, reviews, missing files, episode attachments and manual AniList corrections.
5. **Cut over:** UI/worker resolves by canonical Work UUID; all new remote entries can be created without Jellyfin media. Make update routines idempotent and asset joins explicit. Keep old source columns until regression checks pass.
6. **Contract:** only after long-lived tests remove duplicated data or stop syncing old columns. Provide documented downgrade or backup restoration path.

### Tests required before enabling remote work creation
- `mal:65170` stored and shown despite 503/429 response, original ID retained.
- Two simultaneous requests to save the same MAL ID return **one** Work.
- Work with `mal:65170` merges with future Shoko release after *verified mapping*; preserves rating/review/status.
- Two indistinguishable title variants with distinct official IDs stay separate.
- Deleted/temporarily unmounted `/Anime` does not remove any Work.
- `total_episodes = NULL` renders `11/?` and known audio count independently.
- Existing v0.1 rating `0.0` survives database backfill; user-only review without rating survives.
- Repeated background enrichment does not overwrite manual IDs or user inputs.
- Fresh weekly recommendations can include works with zero attached media and unknown airtime.

## Ownership rules / backup

PostgreSQL is authoritative for Work identity and personal history. Jellyfin/Shoko are **external technical services**, retaining their own internal state and DBs – do not fake a PostgreSQL replacement for Shoko. Backup PostgreSQL with pg_dump and optionally WAL; separately back up Shoko, Jellyfin settings/plugins and local model version files. Never back up original torrent data as part of application metadata jobs; existing storage policy applies.
