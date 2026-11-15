# One-shot current Shoko unrecognized snapshot (48 after Date A Live import)

CT2601 received 24 new Date A Live MKV files. The operator confirmed the current unknown count is 48: 24 historic unknowns remaining after the previous 15+5 manual XRefs and 24 additional files from the new import. The 14 `not_unrecognized_skip` in the 19-file batch must **not** be presumed correctly recognized without checking their current XRefs.

## Run on CT2601

```bash
cd /opt/tethys-anime-hub
git pull --ff-only
cd tools/shoko_reconcile

# Requires exported SHOKO_API_KEY, as in prior probes.
python3 current_unknown_snapshot.py --audit-next19 \
  --output /root/shoko-current-unknown-48.json
```

Upload `/root/shoko-current-unknown-48.json` to review the remaining files. This run is read-only.

## Exact API budget and interpretation

- **One bounded GET** to `/File?include_only=Unrecognized&pageSize=100&page=1`. If Shoko reports more than 100 unknowns or changes the count mid-request, the script fails without manufacturing a partial inventory. It does not enumerate all 3,413 indexed files.
- Group into `original_58` vs `new_since_original_58` using the exact frozen baseline set of 58 File IDs, not fuzzy filenames. The `Date A Live` name hint is a separate tag and must not be treated as an AniDB identity.
- Option `--audit-next19` adds **19 targeted GET /File/{id}** requests using the prior curated manifest. Their returned XRef/episode/series-related fields are included for *manual* review, never automatically interpreted as a successful match. It can reveal missing records or changed IDs, but the absence from Unrecognized alone does not establish correct linking.
- No media filesystem walk, no rehash, no metadata refresh, no automatic or manual XRef writes, no background timers.
- Output saved atomically and chmod 0600. API credentials never appear in output.

Actual current count and cohort split may differ from 48/24/24 if Shoko updates before the command runs. The file will report reality rather than silently forcing those expected numbers.

Next: after reviewing 48 exact File ID/RelativePath rows, identify the 24 Date A Live episodes by season, film, special and OVA work, compare with Shoko AniDB Episode IDs, then prepare individual fail-closed XRefs. Deal with the remaining old 24 independently, including Yona (03+SP) and the unclassified extras.
