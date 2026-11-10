# UI/UX design system — modern, responsive, AMOLED capable

**All user-facing copy, code comments, configuration names, test names and engineering documentation are English during development.** Locale support may be added later, but **no locale/audio/subtitle language is hard-coded as a global assumption**. User-selected preferences and available tracks are per-account/per-media.

## Product information architecture

Global navigation: **Library**, **Discover**, **Watchlist**, **Franchises**, **Taste Profile**, **Settings**. MVP may show Library + Sidecar Inventory first; unfinished areas should not be misleading dummy pages.

- **Library:** poster grid with subtle depth, status chips (Available, Partial, Planned, Announced, Airing), searchable title/alias, rich filters, sort by title/year/personal rating/recently viewed.
- **Detail:** hero cover, localized/alias titles, source attribution, dates (precision explicit), studios, episodes `n/total` with `?` possible, audio/subtitle languages *by availability*, different releases, external sidecars, franchise graph, player link, ratings and separate review.
- **Watchlist:** add MAL/AniList URL or name; placeholders load incrementally, including still-unannounced/unknown episode count. Status and availability independent.
- **Discover:** why-it-fits explanation, possible mismatch, confidence, affinity dimensions (visual, story, characters, relationships), source citations, save, reject, adjust aspects, weekly refresh status.
- **Taste Profile:** editable natural-language summary based on confirmed / inferred / tentative factors; proof by examples, last update, privacy and corrections.
- **Settings:** language for the *interface* (future), audio/subtitle track **preferences** per user, theme, behavior capture controls, account security, import and metadata source status.

## Visual design

Use a restrained contemporary aesthetic:
- Semantic typography, modern card layout, high-resolution artwork with aspect ratio 2:3 and graceful fallback placeholders.
- Medium/large screen: fluid poster grid and details layout; mobile: compact cards, accessible bottom/overflow navigation.
- Clean hierarchy, whitespace, rounded corners and restrained elevation; no excessive gradients/glow, visual noise or ornamental dashboards.
- Transitions short, respect `prefers-reduced-motion`; hover/focus/active states distinguishable. Keyboard navigation and accessible form labels.
- Poster image alt text and loading `lazy`, preserve skeleton/fallback on errors. Do not force fullscreen anime visuals as wallpaper.
- Caution about graph density for big franchises: default to grouped seasons and “show full relation graph” interaction.
- Display evidential uncertainty through readable text, not colors alone; never make unknown future episode count look like 0.

## Theme model

Provide **System / Dark / Light / AMOLED (True Black)**.

| Token | Dark | AMOLED | Light |
|---|---|---|---|
| Main page background | deep charcoal | **#000000** | warm off-white |
| Primary surface/cards | slate/charcoal | **#000000** | white |
| Header/nav | translucent dark | **#000000** | translucent light |
| Border | low-contrast slate | subtle gray | light gray |
| Text | off-white | high-contrast off-white | near-black |
| Accent | refined cyan/seafoam | cyan/seafoam | darker accessible teal |
| Hover/selected | subtle brighter surface | dark gray *only on active controls*, not general fill | pale tinted surface |

**AMOLED contract:** backgrounds, standard panels and cards are truly #000; retain 1px border contrast and focus rings for legibility, allow tiny non-black focus/hover highlights and user-provided poster images. **Do not** apply a dark-gray radial gradient behind AMOLED pages. Avoid burn-in-intense continuous animations and overlarge pure-white blocks.

Preference persisted immediately (MVP: browser localStorage, later per account in PostgreSQL). Set theme on `<html>` before CSS paint to reduce flash; `system` responds to OS preferences. Accessible `<select>` or labeled UI with `aria-label`; every theme must be usable on phone/tablet.

## Design tokens (recommended)

```css
:root {
  --page-background: #0c1019;
  --surface: #151c29;
  --surface-raised: #1e2838;
  --border: #293647;
  --text: #f1f5fa;
  --text-muted: #a8b7c9;
  --accent: #83d4c4;
}
html[data-theme="amoled"] {
  color-scheme: dark;
  --page-background: #000;
  --surface: #000;
  --surface-raised: #000;
  --border: #292929;
  --text: #f5f5f5;
  --text-muted: #ababab;
  --accent: #7be3d3;
}
```

Actual CSS may use alternative variable names but must preserve these semantics. No dynamic theme-image downloads or theme-specific server GPUs.

## No fixed-language assumption

- Probe/store **all** actual audio/subtitle tracks. Normalize language codes (ISO 639 where known) but preserve unknown `und` and original labels.
- Show episode availability for **each** observed audio language, not just Ukrainian, Japanese or English, and never assume dubbing == a language.
- User may *optionally* set preferred audio/subtitle languages and ordered fallback list; no default target locale. No compulsory language-based ranking filter.
- Playback selection is decided by actual Jellyfin capabilities and user settings; the catalog must not transcode just to satisfy a hard-coded language.

## Performance & security

- Private FastAPI + Jinja2 UI remains a good first production step. Use minimal JS for theme, interactions and charts; do not introduce React/Next.js solely for aesthetic polish.
- Cache static assets, use pagination, artwork lazy loading and conditional metadata; reduce unnecessary frontend requests and GPU-heavy background jobs.
- Cookie/session security, CSRF, accessible error messages; avoid inline untrusted HTML from anime synopses/reviews. Hosted fonts not required – use system fonts.
- Prioritize progress/recommendations readability over animated effects.

## Acceptance

- AMOLED background pixel is black and normal cards/panels are black, on mobile and desktop; contrast and focus remain visible.
- App starts in selected theme, persists across reloads and `system` follows OS choice.
- Every visible UI string in implemented routes/templates is English.
- No default target audio language in settings or demo env; all tracks visible, unknown track languages treated honestly.
- Future anime can have art/metadata but no playable asset, yet detail page works and “Play” is disabled or absent.
- Profile summary supports corrections with evidence and private history controls.
