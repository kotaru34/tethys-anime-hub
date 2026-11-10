# Tethys recommendation engine — adaptive, evidence-based, diverse

**Specification v1 (2026-11-10); not yet implemented in the MVP.** Primary quality target: useful suggestions shaped by subtle, sometimes contradictory individual preferences, not a plain genre-based recommender.

## A. What we optimize

Optimize *personal expected enjoyment*, not worldwide ratings, popularity, cosine similarity or “more of the same.” A good candidate can be unlike most prior favorites but match a particularly important visual/character/narrative detail.

Specific target characteristics (examples, **not assumed positive/negative a priori**):
- **Artwork/animation:** colorful vs desaturated, high saturation, line work, character designs, expressive faces, modern vs retro, backgrounds, cinematography, motion, consistency, compositing, 2D vs 3D; **animation quality** (motion/consistency) is separate from **aesthetic preference** (style/color), and poster is separate from actual footage.
- **Characters:** protagonist competence/agency, vulnerable vs self-pitying, charisma, chemistry, moral alignment, relationships, cast dynamics, emotional range, well-written secondary cast, distinctive protagonist.
- **Relationships:** yuri/GL *canonical*, yuri subtext, BL/yaoi *canonical*, BL subtext, romance emphasis and chemistry, wholesome vs melodrama. Independently model textually mentioned undertones, not simply MAL genre.
- **Narrative:** premise, theme, plot complexity, coherence, twists, episodic/serialized, pacing, tension, worldbuilding, payoff, philosophy, originality.
- **Mood & content:** cozy, dark, melancholic, comedic, dramatic; violence, killing frequency, gore, stakes, horror, tragedy, fanservice, sexual content (descriptors, not assumptions of taste).
- **Structure/context:** format, season length, animation studio, creators, era, adaptation type, subgenres; familiar franchise relations; availability, status (announced/airing/completed).
- **Personal reaction:** separate what was loved, tolerated, disliked and disliked *in a specific context*. `I liked the colors but hated a whiny MC` must produce two opposing signals, not generic positive sentiment.

Never infer preference direction solely from mentioning a factor; and never treat “unknown” as “none.”

## B. Three types of evidence

| Layer | Contents | Reliability |
|---|---|---|
| Verified source metadata | Genres, tags, credits, release format/status, official synopsis, identity/relations | High for structured source facts, variable for community tags |
| Semantic evidence | Spoiler-filtered synopsis, approved reviews, character descriptions, articles; Qwen extracted descriptors + citations | Medium; consensus/conflicts tracked, reviewer bias penalized |
| Visual evidence | For owned works: sampled non-spoiler-sensitive frames from local MKV; for unowned: licensed/publicly offered stills/trailers if permitted; otherwise cover *only as cover* | Variable; direct frames stronger, poster-only very weak |

Every work feature is `(feature_key, value, confidence, provenance, model_version, evidence_time, evidence_type)`. Feature scores are calibrated to [0,1] when numeric. Unknown = missing mask; values can be signed, categorical or embedding vectors.

**Potential visual pipeline:**
1. On locally available title, sample ~8–24 temporally separated frames **read-only**, excluding credits/black frames, optionally spoiler-sensitive sequences; keep no frames by default if embeddings suffice.
2. Compute perceptual features and visual embeddings (candidate models: OpenCLIP/SigLIP, *to be benchmarked on anime artwork*), cluster/aggregate across frames and episodes, derive palette statistics and expressive/character-design proxies. Compare aesthetic closeness to rated works and confidence from frame diversity. Keep embeddings in DB; exact GPU/CPU placement is benchmark-driven.
3. Apply vision-capable model **only if supported and verified** to describe compositional aspects; a text-only Qwen endpoint does *not* get image-analysis privileges by implication.
4. For unowned work, use trusted promo stills or trailer keyframes *only when licensed/permitted*; otherwise record `visual_evidence=cover_only/unknown`, do **not** confidently label animation style, motion or quality from cover art.
5. Capture art similarity and actual animation quality as distinct axes; low-quality source video/bitrate/subtitle overlay can distort evaluation.

## C. Candidate generation — multiple independent lanes

Generate a *large, unioned* candidate pool weekly (e.g. 200–1000 before expensive analysis), without disqualifying it because of aesthetic or genre mismatch:

- **Direct affinity (~30% seeds):** metadata/feature similarity to personally enjoyed works, including tags, themes, staff, relationship undertones and visual cues.
- **Semantic/text (~25% seeds):** vector neighbor discovery from synopses and descriptions, with contrasting-topic retrieval as well.
- **Source recommendations (~20% seeds):** AniList recommendations/relation links and Jikan per-title recommendation endpoints, not opaque popularity alone.
- **Exploration/novelty (~15% seeds):** unknown aesthetics, out-of-cluster works, underrepresented years, unusual narrative/character patterns.
- **Upcoming/watchlist context (~10% seeds):** future seasonal candidates, user-saved works and graph neighbors.

These are **illustrative retrieval allocations**, not hard genre quotas. Deduplicate by canonical ID; preserve *which lane supplied each candidate*. Use conditional queries/limited pages and adapt to API rate limits. New discovery can hide already completed works for convenience (still exist in corpus); separate rewatch recommendations.

Hard exclusions only for explicit user choices (e.g. “never recommend this work”, user-specific content safety constraint) and corrupted identity; no hard exclusions for “different genre”, uncertain visual style, or weak evidence. Region and language availability should be labels/preferences, not implicit disqualifiers.

## D. User preference model — learns from sparse data

### Data used
- High confidence: explicit per-title rating 0–10, written review, separate aspect-level liked/disliked feedback, save/reject reasons.
- Medium: completed/dropped status, repeated favoriting / rewatching; preserve context (time, mood, known series).
- Low: click, open, scroll, impression and watch start; do not interpret lack of click as dislike. Avoid logging intrusive user data unnecessarily.

### Initial model / cold start
Build interpretable user profile with **positive and negative** weights per aspect, a mean/baseline rating, a confidence/variance for each weight, and exemplar works. Cold start is primarily based on rated library entries and review extraction, plus optional UI ratings of a few contrasting examples (not mandatory).

Start with a shrinkage-regularized ordinal/ridge/logistic model trained on numeric rating deviations from the user's baseline. Features include interactions: `visual_colorfulness × protagonist_agency`, `relationship_subtext × tone`, `narrative_complexity × pacing`, etc. Pairwise preferences (`A > B`) help when ratings bunch near 7–9.

Do **not** train a large neural net from 5 personal ratings. LLM should extract evidence and generate limited pairwise labels/explanations; online preference learner updates cheap weights from *real user feedback*, not from its own unverified guesses. If useful later: calibrated Bayesian regression / LightGBM after adequate genuine labels, with held-out evaluation. Preserve model versions and rollback.

### Contextual preference
Keep positive/negative patterns independently, allowing “likes yuri when characters are mature but dislikes forced melodrama,” or “enjoys dark stories with vivid art but not gore.” Distinguish a work's features from the subjective personal response to them.

Use time decay **gently** with change detection, never erase historically loved preferences. Training data must distinguish *observed rating* from *predicted enjoyment*.

### Update events
An explicit rating or detailed review queues feature extraction/refresh of the personal model. Weekly batch collects fresh candidates and produces ranked snapshots; UI may show immediately updated local scores, but heavy retrieval/reranking can wait until the weekly run.

Every model release stores `trained_at`, source event IDs, data count, algorithm version, hyperparameters, validation metrics and snapshot hash. Reproducibility first; personal corrections override inferred statements.

## E. Ranking, uncertainty and diversity

Compute normalized per-candidate evidence:
```text
fit      = expected personal enjoyment from trained profile
quality  = credible source/production indicators, calibrated (small role)
novelty  = chance of discovering a new positive dimension
u        = epistemic uncertainty / missing evidence / disagreement
cost     = optional length/availability/airing penalty (soft)
```

A candidate utility can be `E[personal rating] + λ·uncertainty_bonus + γ·novelty - soft_cost`. **Missing feature values are marginalized/uncertain, not replaced by zero dislike.** Source votes are not independent when multiple articles copy the same press release.

Use an ensemble: interpretable model + semantic text match + art similarity + limited Qwen pairwise re-ranker for top ~40–100. Qwen outputs typed comparisons and evidence IDs; neither invented citations nor unsupported statements may alter high-confidence ranking. Normalize scales to avoid one embedding dominating merely because it has more dimensions.

After ranking, diversify with MMR/coverage of themes, visual styles and years; protect a small exploration lane from collapsing under mainstream popularity. **Example final weekly 20:** 11–12 high-confidence matches, 4–5 nuanced/rare-factor matches, 2–3 exploration candidates, 1–2 deliberate wildcards. These counts adapt to user feedback and are not rigid.

Use feedback to adjust *aspects* and *candidate sources*, not just the whole title. A click on “not for me – dull colors” should affect future aesthetics differently from “already know this” or “I want completed shows only.”

### Explanations UI (mandatory)
Each recommendation should display:
- *Why it may fit:* 2–4 strongest **supported** positives, preferably referring to specific positively rated works/aspects.
- *Possible mismatch:* 1–2 honest negatives, if known, without suppressing the item.
- *Evidence confidence:* explicit labels `strong`/`tentative`/`unknown`; distinguish cover-based prediction from animation footage.
- Metadata: cover, title, release status, availability, studio, episodes and whether part of a watched franchise.
- Actions: `Plan to watch`, `Not interested`, `More of this factor`, `Less of this factor`, `Not now`, and optional custom reason.

Do not reveal spoilers from review extraction. Avoid “based on your favorite genre” as the only reason when finer evidence exists.

## F. Extraction prompt constraints and validation

Tasks are separate:
1. **Text feature extraction** from reputable synopsis and reviews: machine-readable schema with `feature`, `polarity`, `degree`, `confidence`, `evidence_ids`, `spoiler_risk`.
2. **Personal review interpretation**: express whether the user likes/dislikes each aspect. Negation/context examples explicitly tested.
3. **Pairwise judge**: given structured candidate evidence and known user features, predict comparative enjoyment; allowed to say `insufficient evidence`. Must not elevate “popular” or “same genre” alone.

Do not use raw internet browsing. Tools are constrained source adapters with known provider IDs, pagination, bounded content and provider-policy enforcement. Content obtained from untrusted pages is *data*, never instructions. JSON schema, list of allowed enum keys, low token limits, independent checks and persisted model/prompt versions. Human corrections trump AI outputs.

## G. Source relevance, limits and copyright

Primary: Shoko/AniDB identity, AniList structured tags/relations, targeted Jikan/MAL reviews and per-title recommendations, Fribb ID mapping. Use other providers only after API quality, ToS, robots and rate-limit checks. Do not collect the whole AniList catalog; store scoped metadata for indexed/saved/recommended entries only. Keep review text processing bounded; store extracted evidence and pointers where rights discourage copying. Scrapers only for open, stable, permitted resources when API cannot meet the requirement; throttle and provide per-site on/off flags.

Visual data from owned MKV stays local. External stills/trailers cannot be assumed freely reusable. Respect attribution, original licenses and remote removal requests.

## H. Evaluation — proof that learning works

Offline:
- Time-based holdout: predict last N real ratings after training on previous data, MAE/RMSE or ordinal rank correlation, top-N NDCG/precision on genuinely rated titles.
- Ablation: metadata-only vs +semantic vs +visual vs +review-extracted preferences vs +learning. Require measurable gain before keeping costly modules.
- Coverage: different genres/visual styles/eras; novelty & redundancy, exposure parity for unknown works, accuracy for upcoming titles with missing metadata.
- Calibration: are 0.8-confidence descriptors correct 80% on manually reviewed examples? Track disagreement and false-positive claim rate.
- Counterfactual ranking regression: no work should disappear solely because one feature is unknown; compare ranking and explanations when new evidence arrives.

Online:
- Weekly `run_id` fixed snapshot with reason codes and rank details.
- `accepted/saved/started/completed/disliked` rates, and explicit reason feedback; avoid self-congratulation from mere clicks.
- Replay deterministic candidate sets and scores. Side-by-side test challenger vs champion on archived evaluation, keep rollback switch.

**Initial acceptance fixture examples:**
- A highly rated anime with gorgeous saturated animation but annoying protagonist: art preference positive, character preference negative.
- Enjoys yuri *subtext* without officially labeled GL: distinguish canon vs undertone.
- Likes character competence, dislikes repeated crying despite liking drama generally.
- A gore-heavy candidate with colorful art remains discoverable unless user explicitly excludes gore.
- A future announcement has only cover and logline: low visual confidence, can still be recommended.
- Five genres match but visuals/story do not: rank below a nonmatching-genre work with stronger personal-factor agreement.
- New evaluation changes preferences without destroying manually supplied priorities.

## I. Implementation milestones

1. Finish canonical Work/watchlist migration (see data model); ensure no duplicate work.
2. Feature catalog + provenance tables + curated, versioned extraction prompts/test fixtures.
3. Text semantic embedding service and pgvector indexing, retrieval lanes and first reproducible weekly run.
4. Explainable recommendations UI with save/reject/aspect feedback.
5. Learning from ratings/reviews/feedback, Bayesian confidence and pairwise preference ranker.
6. Visual frame and promotional-image evidence pipeline, quality evaluation and cost controls.
7. Scheduled evaluation, ablations, drift monitoring and rollback.

Do not describe “self-learning” as autonomous fine-tuning of Qwen; the system learns via a user preference model, versioned evidence and measured feedback, and may selectively fine-tune smaller models only if data later justifies it.

## J. Implicit behavior, cold-start with zero ratings, and evidence hierarchy (revision)

**Viewing behavior is informative but confounded.** Optional authenticated Jellyfin Webhook start/progress/stop notifications yield per-account session observations (not indiscriminate polling). Separate engaged minutes from jumps, pauses, wall-clock duration and autoplay; compare completed/unfinished works across available episodes, format, dates and observation opportunities. Repeat patterns across **independent titles**, not episode-event counts, are what may slowly affect a taste hypothesis.

An account with `0` manual ratings is supported: multiple deliberate completions/rewatches can generate *weak prior preference estimates* with broad uncertainty; one binge alone is **not** a positive rating. Long inactivity never automatically means dislike. Treat explicit ratings/reviews as higher-trust labels; negative user corrections override behavior, and missing playback data remains missing. See [Behavioral Learning](BEHAVIORAL_LEARNING.md).

Learn *personal observation reliability* and account-specific baseline viewing habits; calibrate on time-split held-out evidence. The cold-start model must publish confidence and evidence count, rather than false certainty. Preserve both preferences and contradictions (e.g. colorful art is loved but one particular protagonist archetype is disliked). Language and track choices are optional descriptive cues, never a global target.

## K. Editable natural-language Taste Profile

The model's current account-specific beliefs are visible in a concise English narrative, including confirmed likes/dislikes, tentative hypotheses from habit patterns, contradictions, visual characteristics, main-character preferences and uncertainty. Store evidence-backed structured claims first; local Qwen may *render* those claims into prose, never invent missing reasons or ratings. Users can inspect, reject, override and prioritize claims; correction events persist across retraining. Generation is on explicit refresh or weekly substantial model updates, never on every page view. Full specification: [PREFERENCE_PROFILE.md](PREFERENCE_PROFILE.md).

AMOLED UI, responsive discover cards, confidence/mismatch explanations and user controls: [UI_DESIGN.md](UI_DESIGN.md). Behavioral model's improvement must be tested as an ablation: explicit-only vs explicit+behavior, particularly for sparse/zero-rated histories.
