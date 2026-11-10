# Behavioral learning: cautious inference from real viewing

**Target design, not yet implemented.** A user may have zero manually rated anime; the recommender must still build a *tentative* profile from repeated behavior, without mistaking workload, scheduling, playback failures or missing files for taste.

## Event acquisition and boundaries

Prefer Jellyfin's official **Webhook plugin** notifications for PlaybackStart, PlaybackProgress and PlaybackStop. Validate plugin/version compatibility and payload format during integration. Jellyfin exposes corresponding session/playing APIs, but those are generally **client-to-server reporting endpoints, not a general webhook subscription**. Do not call them pretending they return historical viewing events. An optional low-rate, change-detection sync of Jellyfin per-user `UserData` is a **coarser** fallback for watched/progress states, not an equivalent replacement for telemetry.

Transport: Jellyfin LXC → authenticated, LAN-only HTTPS/webhook receiver in the app (or mTLS/reverse proxy on trusted network). Secret shared outside Git; request size limit, strict JSON schema, timestamp window, replay protection, idempotency key and user mapping. Reject events with unrecognized user/work identity; quarantine unresolved mappings for retry. Never accept webhook instructions or arbitrary network references as data-fetch commands. Avoid logging tokens or raw personal payloads.

Normalize events to one user's canonical Work and episode, with monotonic server receive timestamps and source event timestamps; keep provider ID/session ID, media duration, position ticks, playback state, client identity when allowed, playback rate if available, autoplay/automated flag if provided, and event quality. Do not rely on wall-clock alone. Event order may be wrong, events may be duplicated or lost.

### Configurable privacy and overhead

- Behavior learning is an **account-scoped opt-in/out control** with an on-screen explanation of the data being collected. Initial private owner setup may enable it explicitly; never silently expand surveillance to new accounts.
- Offer `Off`, `Completion only`, `Engagement (recommended)` granularity. Per-user pause and **Delete my viewing behavior** must erase raw/derived habit records and trigger model rebuild.
- Collect **no system-wide browsing telemetry, window focus, calendar, employment, school, GPS or background computer activity**. External life context is unknown unless the user explicitly provides it.
- Retain raw per-session events for **30 days by default (configurable)**; retain small derived aggregates for learning while enabled, with provenance and deletion capability. Never commit histories to Git or transmit them to external APIs/LLMs.
- Event-driven worker, bounded inserts and batched aggregates; no continuous high-frequency Jellyfin polling. If webhook progress cadence is noisy, debounce/deduplicate by session and store sparse checkpoints (e.g. 15–60 s configurable).
- Use PostgreSQL for persistent state, append-only event log / compact per-session aggregates, advisory-lock worker, and safe backup/restore.

## Session reconstruction: never confuse watching with a video position jump

Group by `(user, source_session, episode)` where reliably provided. Otherwise construct heuristic sessions with a configurable inactivity threshold; annotate less reliable reconstruction.

1. Deduplicate by delivery ID or normalized `user,item,session,event_type,time_bucket,position`.
2. Ignore negative time deltas, impossible playback speed and out-of-order state changes for engagement calculations; retain diagnostic counters.
3. Estimate **engaged seconds** from contiguous intervals with `playing` state and reasonable playback-position advance. Clamp by elapsed wall time × plausible playback speed; remove pause time, seeks and large timestamp gaps.
4. Separate **position coverage**, **active watch time**, **wall-clock time**, **episode completion**, and **distinct viewing occasions**. A 20-minute position jump is not 20 minutes watched.
5. Infer completion only with supported end position / watched flag / repeated progress: `>=90%` may be a *candidate*, but intro/outro skipping and variable run lengths require calibration. Autoplay or `Mark played` is not strong positive feedback.
6. Account for rewatches: distinguish genuine rewatched minutes from repeated starts or seeking to a scene.
7. Track possible playback friction (buffering, transcode failure, stalled progress, app crash), if accessible; otherwise mark `playback_quality_unknown` and downweight abandonment evidence.
8. Series progress uses available episode count and total announced count **separately**. A two-episode OVA completed in one evening is not directly comparable with an ongoing 24-episode series; airing schedule affects opportunity.

## Observed patterns (features, NOT automatic taste judgments)

- **Completion:** fraction of available/released episodes genuinely watched, and time-to-completion relative to *opportunity*.
- **Engagement velocity:** active watch duration / eligible available minutes; number of days with episodes watched; time until next episode; gaps between episodes; progression trend.
- **Binge tendency:** sustained intentional viewing across episodes in contiguous sessions vs accidental autoplay; normalized to personal baseline, episode duration and access.
- **Rewatch:** repeated active engagement with already completed works, not just repeated seek or a playback error.
- **Drop/revisit:** explicit drop/continue vs long inactivity (inactivity by itself is not evidence of dislike).
- **Starting behavior:** starts that turn into active viewing, starts followed by short disengagement, changes in frequency; distinguish opening to inspect, technical tests and genuine watch starts.
- **Choice under opportunity:** what was chosen among *known available alternatives* in the same period, not among works the user could not play.
- **Context:** time-of-day/week only if user consents; model as viewing *availability/routine*, **never** as personality or genre preference by itself.
- **Format:** movies vs short series, episodic vs serialized; unowned/announced entries have no direct viewing evidence.
- **Audio/subtitle track selection:** descriptive preference evidence only, with account-configurable locale; **no global target-language default**.
- **Explicit negative reasons:** a manual `Dropped — disliked slow pacing` is strong evidence; a four-week inactivity gap is not.

Work-level aggregates should include `observed_count`, `eligible_minutes`, `engaged_minutes`, `completion_ratio`, `rewatch_ratio`, `days_active`, `time_to_next_episode_distribution`, `start_to_completion_span`, `session_quality`, `autoplay_fraction`, `available_since`, `last_observed_at`, and missingness masks. Preserve all denominators. Never label a person “dislikes horror” from a single skipped episode.

## Statistical inference: patterns across *comparable* anime

**Simple example:** The same user owns 10 series and has rated none. One complete series barely progressed, another finished within a day. This is insufficient to learn which is better. With multiple *distinct works* sharing salient visual/character/narrative features, repeated fast intentional completion may raise a cautious positive affinity estimate; repeated revisits of similarly characterized works also help. Slow progress remains weak/missing unless opportunity and friction have been accounted for.

**Estimate preference ≠ estimate exposure.** Observed engagement is a product of enjoyment, watch opportunities, duration, availability, friction, release schedule, autoplay, and user habits. We do not observe the causal factors directly. Treat inferred preference as a hypothesis.

Recommended learning pipeline:

1. Infer the user's **personal pace baseline** from viewing opportunities and comparable episode lengths. Avoid comparing absolute `episodes/day` directly across years, release schedules or changing work routines.
2. Model *propensity to start* and *engagement given a start* separately; do not interpret not-started releases or downloads as disliked. Use known available alternatives when possible.
3. For a rated work: the explicit rating/review takes priority over an opposing passive signal. For unrated works: transform reliable behavior aggregates into **weak noisy preference observations** with uncertainty; do not assign fake personal ratings (e.g. a one-day binge ≠ 10/10).
4. Learn aspect affinities with **hierarchical regularization / shrinkage** across works, rather than raw correlation to genre labels; require diversity across titles and sessions. Avoid counting 12 episodes of one show as 12 independent likes.
5. Separate the consistent latent preference model from a slow-moving **routine/context** model (weekday, recent availability, workload unknown). Model abrupt routine change as reduced behavioral reliability, not as new genre hatred.
6. Update weights **only when repeated evidence warrants it**. Example initial minimum: multiple independent works, multiple observation days and positive/negative comparisons. Use tunable thresholds, posterior uncertainty and effective sample size, not brittle universal cutoffs.
7. Use temporal holdout and robustness checks, comparing same-season/format/duration and similar opportunity. Downweight automated starts, partial stale data and suspected playback problems. Prefer within-user pairwise comparisons under comparable opportunities.
8. Log **how much** inferred behavior influenced ranking, and allow user to mute behavior signals, delete them, correct a false conclusion or flag a technical playback session.

Suggested ranker combines sources with learned per-user reliability: `explicit ratings + review aspects` (high-trust), `repeat engagement/revisits` (medium), `one-off long binge` (weak), `unplayed/slow/missing data` (normally no negative effect). These are qualitative priors, not hard numerical weights. Explicit preference and metadata uncertainty remain independently tracked.

### Calibration examples

| Situation | Allowed interpretation |
|---|---|
| One show watched in one day | Interesting signal, **not enough** to declare it beloved |
| Three similar visually vibrant shows intentionally finished quickly across different weeks | Tentative evidence favoring some shared traits, if confounders checked |
| Many paused shows during an exam period | Unknown reason; do **not** punish genres |
| Several short tests, seeking and playback crashes | Technical noise; don't infer rejection |
| Rewatching favorite scenes repeatedly | Potential positive signal, stronger with repeated active minutes |
| New announced anime in watchlist, not playable | Saving is *intent*, not completed enjoyment |
| Autoplay went through an entire season overnight | Low-confidence, not binge enthusiasm |
| Manual review `Loved the art but hated the MC` despite fast completion | Preserve both separate aspect signals, not generic positive vote |

## Offline evaluation and safeguards

- A/B ablation: explicit-only vs explicit+behavior on withheld later ratings and actions, NDCG, calibration and qualitative regression fixtures.
- Cold-start zero-rating simulation: hold out all ratings for users/title histories and check whether repeated behavioral patterns improve **out-of-sample** rank compared with popularity/genre baselines; report uncertainty.
- Sensitivity test: changing available episode counts or inserting a 2-week no-watch period should **not** flip a strong preference.
- Equal-weight episode events are forbidden as independent user labels. Evaluate per *work* and per time period.
- Keep per-model training dataset hash, event ranges, reliability and rollback; never silently overwrite user corrections or manual aspect priorities.
- Profile summary generator must treat behavioral claims as `tentative observation` unless corroborated with explicit ratings and repeated independent work patterns.

## Implementation path

**Stage 1:** account controls and secure Jellyfin Webhook receiver, normalized sessions in PostgreSQL, private dashboard showing sessions/coverage *without training effects*.

**Stage 2:** reconstruction metrics, quality masking, aggregation and playback coverage verification against actual Jellyfin; test duplicate/out-of-order events and progress seeks.

**Stage 3:** posterior behavioral affinity features with per-user reliability; weekly recommendation updates, shadow-mode learning and ablation. Do not activate automatic ranking effects until evaluated.

**Stage 4:** natural-language preference profile explanation + editable controls and evidence navigation (see PREFERENCE_PROFILE.md).

This is useful with **zero explicit ratings**, but must not claim certainty until actual evidence exists.
