# Personal taste profile — transparent, editable narrative memory

**Design target.** Each account has an understandable, human-readable taste model, resembling a concise living description rather than a cryptic vector. Users see **why** the model believes something and can correct it. Generated content must never present guesses as personal facts.

## UI destination

Account → **Taste Profile**:

- Main narrative in natural English (other locales possible later), updated after enough evidence or on request. Source is the **structured user model**, never the raw untrusted browsing pages.
- Sections: **What you reliably enjoy**, **What tends not to work**, **Visual and animation tastes**, **Characters and relationships**, **Story and pacing**, **Viewing patterns**, **Potential discoveries**, **Still uncertain**.
- Evidence tags (not decorative badges): `Explicit`, `Inferred from viewing`, `Tentative`, `Needs more evidence`. Provide clickable evidence counts and example anime **only when genuinely supported**.
- Use **first/second person** naturally, qualify uncertainty: “You may gravitate toward bright, expressive character art; this is based on repeated active viewing of three shows and has not yet been confirmed by a rating.”
- Never invent life facts, diagnoses, private activities, “how you felt,” or why a viewing gap happened. Discuss only observed playback behavior and user-authored opinions.
- Show **last generated**, sources (e.g., `3 rated shows, 8 observed shows`), algorithm/prompt version and current privacy setting.
- User actions: `That's accurate`, `Not quite`, `Wrong`, `Prioritize`, `Ignore this factor`, `View examples`, `Delete observed history`, `Refresh summary`.
- Allow a free-form **Your preferences** text field, parsed into signed aspect-level controls but kept as editable original text.

## Evidence claims are first-class data

```text
taste_profile_claim(
  claim_id, user_id, aspect_keys[],
  direction, intensity, confidence, epistemic_status,
  explicit_support_count, independent_works_count,
  behavior_support_count, effective_sample_size,
  counterexamples[], evidence_ids[], explanation_inputs[],
  first_seen_at, last_validated_at, revision,
  human_decision[confirmed|rejected|prioritized|null]
)
```

- Explicitly authored/confirmed claims outrank passive inferences. A user correction is an event, not disposable generated prose.
- Contradictory tastes are allowed and contextualized: “enjoys melodrama in romances but usually prefers competent protagonists in action stories.” Don't force a single score per genre.
- No assertion of animation quality from poster-only evidence.
- Show favorable **and** unfavorable examples only where true; preserve negative and inconclusive feedback.
- When the model changes, store a versioned diff of claims/summary; user can inspect why a previous conclusion disappeared.

## Safe summary generation using local Qwen

1. Deterministic feature models output a **bounded list of claims**, positive/negative weights, confidences, evidence work references, conflict notes, and temporal changes.
2. Apply a strict policy filter: no unsupported claims, no mention of unapproved context, no secrets, no raw identifying watching times unless user chose to display them, and no spoilery review details.
3. Ask Qwen for short, accessible English prose **only over those structured claims**, with stable claim IDs attached to paragraphs. Qwen is a renderer/rephraser, not the authoritative scorer.
4. Parse into JSON schema, validate every referenced claim, direction and evidence ID against persisted records. Reject new invented preferences, new titles or exaggerated confidence.
5. Fallback to deterministic English template if local inference fails; do not block the UI.
6. Store snapshot: claims IDs, prompt/model version, input fingerprint, generated_at, review status. Cache; regenerate on user request, sustained profile change, or after weekly recommender run, **not** per page view.

### Example narrative (synthetic data only)

> Your viewing history suggests that colorful, expressive character designs may be an important part of what keeps you engaged. This is an **emerging** pattern across three independently watched series, not a confirmed preference yet. You're also more likely to continue stories with active, decisive protagonists, although there isn't enough evidence to tell whether this holds for slower dramas.
>
> There is currently **no reliable conclusion** about your tolerance for graphic violence. Your completed shows cover different levels, and you haven't given explicit feedback on this aspect.
>
> A useful next discovery might be a visually vivid character-focused series outside the genres you usually start; the model will leave room for these less obvious matches.

This example is a **format illustration**, not actual account data.

## Privacy, isolation and UX

- Accounts are separate: session and recommendation history must be filtered by authenticated user ID; never combine household profiles.
- Preference text is private user data; do not expose in Git, server logs or third-party enrichment APIs.
- Support opt-out of behavioral learning while continuing ratings-based recommendations; disabling telemetry must stop ingestion (not merely hide it).
- Provide export (structured JSON + narrative) and complete deletion of behavior-derived data and summaries. Distinguish deleting raw sessions from clearing all inferred behavior and model weights.
- Local-only generation; no dependency on always-on GPU to read existing profile.
- Accessible contrast and keyboard-friendly behavior in all Dark, Light and **AMOLED True Black** themes.

## Acceptance tests

1. A new user with zero ratings and no playback events sees “Not enough evidence yet,” not guessed favorite genres.
2. Several similar binge completions with no ratings yield **tentative** preferences, with evidence counts, not fabricated 10/10 ratings.
3. One manual negative review contradicting repeated playback does not get overwritten by automated inference.
4. A model with conflicting visual vs protagonist signals explains both.
5. Qwen response containing unsupported anime titles/claims is discarded and fallback narrative is shown.
6. User rejects a claim; future updates cannot silently resurrect it without novel evidence and clear opt-in correction workflow.
7. Account A's data never appears in Account B's profile.
8. Turning behavioral collection off stops ingest; delete clears history, aggregates, affected weights, cached summaries.
9. Theme switch and mobile rendering preserve readable text and accessible controls.
