# CT2601 — remaining 24 Shoko files: one run, exact bonus-episode matching

After the earlier `resolve_45_onepass.py` apply returned `xref_submitted: 21`, **24** remained: 10 Date A Live NCED, 8 High School DxD New/BorN OP/ED/PV, 3 KonoSuba S1/S2 PV, 2 standalone High School DxD OVA, and one `Yuusha, Yamemasu - 13.mkv`.

This command covers **all 24** in a single, bounded, operator-triggered operation, automatically submitting only verified AniDB credits/trailers/specials and producing a concise reason for every unmatched file. It never labels unclassified media as arbitrary anime or silently ignores extras.

## Run once

With the same `SHOKO_API_KEY` already exported as in earlier operations:

```bash
cd /opt/tethys-anime-hub
git pull --ff-only
cd tools/shoko_reconcile

python3 resolve_remaining24.py \
  --apply --confirm LINK_VERIFIED_REMAINING_24 \
  --report /root/shoko-remaining24-report.json
```

`--apply` includes an internal preflight; you do not need to run a separate dry-run. Only if you *prefer* preview: `python3 resolve_remaining24.py --report /root/shoko-remaining24-dry-run.json`.

## Precisely what it can identify

- **Date A Live NCED 01–10**: The [original Moozzi2 S1 Director's Cut release file listing](https://nyaa.wiki/view/1939083) identifies them as episode endings from **1, 2, 3, 4, 5, 6, 8, 10, 12, 13**, *not* generic TV episodes 1–10. Its rounded per-file sizes are independently checked against the Shoko-indexed files before any credit XRef. The first nine target AniDB **8808**, the tenth (OVA episode 13) AniDB **9734**. Then link only if the actual local AniDB Credits title explicitly and uniquely names the version in its exact work. **Do not invent** 10 separate credits entries if AniDB stores only one generic Ending.
- **High School DxD New/BorN OP/ED**: verify AniDB IDs **9409**/**10691** and actual `Credits` entries. Match `Opening 1a`/`1b`, or `Opening 1/2`, and numbered `Ending` versions only if unique. PVs use `Trailer`, never `Credits` or ordinary Episode.
- **KonoSuba S1/S2 PV**: verify works AniDB **11261**/**11992** and exact unique AniDB `Trailer` entries `PV`, `PV 1`, `PV 2` (if present). No PV→TV fallback.
- **Yuusha, Yamemasu - 13.mkv**: historical CT2601 actual AniDB episode inventory already confirmed `Special S01`, AniDB episode **256391**, titled `Remember, the Work Trip Is First and Foremost a Learning Opportunity (Part 1)`. Require exact live ID/title/number/type and pinned File ID **3222**. This represents OVA Part 1, *not* a fabricated TV E13.
- **High School DxD OVA - 03/04**: two separate AniDB works **11184** (*New: Teishi Kyoushitsu no Vampire*) and **11844** (*BorN: Yomigaeranai Fushichou*) can be created if absent, with an at-most-once durable metadata journal. Their OVA episode candidates are recorded, **not linked blindly**: the numbered files `03/04` do not themselves prove which distinct storyline is present. Both remain flagged for content confirmation.

## Safety, resource use and realistic outcomes

- **Exactly 24 pinned File ID/RelativePath pairs** from the prior 48-file Shoko snapshot; all changes to paths block writes.
- At most **two** bounded `Unrecognized` list reads (up to 100 rows each), then only the exact AniDB works needed for active files; no full `/File` listing, no media filesystem walks.
- No MKV changes, no stream decoding, no subtitle/ASS/font modifications, no torrent rename, no Shoko `Ignore`, no background jobs, no indefinite retries.
- Persistent private journal records every metadata request or XRef **before** sending it, to protect against duplicate requests after timeouts. An already-recognized File ID is never sent again, even if the Reconciler recognized it while metadata loaded.
- All output is private, mode `0600`, in `/root/shoko-remaining24-report.json`. The per-file report contains live candidate AniDB titles/IDs and reasons for every item left unresolved.

**Don't expect a guaranteed zero:** if AniDB does not contain ten distinct matching ED credits or the file variant doesn't match the unique AniDB version, Shoko has no safe one-to-one metadata target. Marking it ignored would hide the warning but not represent the file as an actual anime extra. This command will not silently do that.
