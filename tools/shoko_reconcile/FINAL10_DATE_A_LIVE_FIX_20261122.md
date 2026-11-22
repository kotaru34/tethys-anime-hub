# Shoko CT2601: last 10-file closeout and correction of 3 previous Date A Live NCED XRefs

## Why a correction is necessary

The uploaded `shoko-remaining24-report.json` contained exact AniDB Credits rows for Date A Live TV (AniDB 8808, Shoko Series 280): `C01 Opening`, followed by **nine endings C02..C10**. The previous `resolve_remaining24.py` matched the NCED *ordinal* against the *title suffix* `Ending N`, unintentionally skipping alternate titles `Ending 2a/2b/2c/2d`. This caused three past XRefs to point at the wrong episode. The fixed mapping is the ordered 9 NCED clips to the exact ordered 9 AniDB Credits C02..C10.

| NCED | File ID | Current observed AniDB Episode ID | Correct Credits | Correct AniDB Episode ID | Action |
|---|---:|---:|---|---:|---|
| 01 | 3435 | 148984 | C02 Ending 1 | 148984 | Verify, no change |
| 02 | 3430 | Unrecognized | C03 Ending 2a | 149639 | Add |
| 03 | 3433 | 149748 | C04 Ending 3 | 149748 | Verify, no change |
| 04 | 3432 | 150419 | C05 Ending 2b | 154716 | Correct |
| 05 | 3437 | 150418 | C06 Ending 4 | 150419 | Correct |
| 06 | 3438 | 156907 | C07 Ending 5 | 150418 | Correct |
| 07 | 3429 | Unrecognized | C08 Ending 2c | 154715 | Add |
| 08 | 3439 | Unrecognized | C09 Ending 2d | 154714 | Add |
| 09 | 3434 | Unrecognized | C10 Ending 6 | 156907 | Add |

Also, `NCED 10` is already linked to standalone *Date to Date* OVA AniDB 9734 C01 (ID 157956) and is **not** included in this repair.

This mapping is supported by the Moozzi2 release ordering, all nine corresponding TV AniDB Credits in their correct order, and independently matched indexed file sizes. These establish consistent metadata matching, not direct audiovisual fingerprinting of each clip.

## Single command on CT2601

```bash
cd /opt/tethys-anime-hub
git pull --ff-only
cd tools/shoko_reconcile

python3 fix_dal_endings_final10.py \
  --apply --confirm CORRECT_DAL_NCED_XREFS_9 \
  --report /root/shoko-final10-correction.json
```

Default without `--apply` performs only verification. The apply path already contains a strict nine-file preflight and just-in-time XRef rechecks. It reads **GET `/File/{id}?include=XRefs`** — confirmed in Shoko 5.3.x's actual `FileController.cs` and `Models/Shoko/File.cs` — NOT the ineffective `includeXRefs=true` parameter used by an earlier audit.

**No blind overwrites:** a corrective update is submitted only when the actual existing AniDB episode XRef is *exactly* the known earlier incorrect target; if it has changed or contains multiple episodes, all writes abort before the first POST. New NCED can only be linked if the exact File ID/path/size is still `Unrecognized` and has zero existing XRefs. Target AniDB work/series ID, exact episode number/title/ID, and edition file size are checked live. Every POST is durably journaled before dispatch, re-read after dispatch, and never retried if the outcome is uncertain.

Shoko source authority: [ShokoServer FileController.cs](https://github.com/ShokoAnime/ShokoServer/blob/d316a7429d16401a9748ec014f33dd536b33cf45/Shoko.Server/API/v3/Controllers/FileController.cs) documents POST `/File/{fileID}/LinkFromSeries` and its implementation uses `SaveReleaseForVideo()` to replace current episode release mapping; [File.cs model](https://github.com/ShokoAnime/ShokoServer/blob/d316a7429d16401a9748ec014f33dd536b33cf45/Shoko.Server/API/v3/Models/Shoko/File.cs) returns `SeriesIDs` only when the request's `include=XRefs` field is supplied.

## Six other files are not safely linkable from the current AniDB inventory

- PV `2994`: KonoSuba S1 has `Trailer T01` titled *2nd Season Announcement*, not proven identical to the S1PV MKV.
- PV `2997`, `2999`: KonoSuba S2 has no AniDB Trailer entries.
- PV `3020`: High School DxD BorN has no AniDB Trailer entries.
- OVA `3209`: High School DxD OVA -03 plausibly standalone AniDB 11184 E01 ID 161394, title *OVA*, but its file contains only chronological `03` marker, not a definitive release title.
- OVA `3206`: High School DxD OVA -04 plausibly AniDB 11844 E01 ID 167801, title *OVA*, same uncertainty.

These six are reported but **never** automatically linked, ignored or deleted by this correction. To reduce remaining count below six, validate the two DxD OVA video contents and investigate PV IDs; it is not acceptable to force PV files into unrelated opening/endings or silently ignore preserved torrent content.

## Resuming the original unverified NCED-02 request (File ID 3430)

The operator's first CT2601 run returned `apply_interrupted_unverified` with `submitted: 1`, `verified_after_write: 0`, and file **3430** marked `submitted_unverified`. This is an **unknown acknowledgment state**, not proof of a failed XRef. Its previous attempt is recorded in `STATE`; **never delete or edit the journal**.

After pulling this follow-up patch, **rerun the same one-shot command** with a *new* report name to preserve the earlier evidence:

```bash
cd /opt/tethys-anime-hub
git pull --ff-only
cd tools/shoko_reconcile
python3 fix_dal_endings_final10.py \
  --apply --confirm CORRECT_DAL_NCED_XREFS_9 \
  --report /root/shoko-final10-resume.json
```

The script re-reads the live **`GET /File/3430?include=XRefs`** and may briefly poll for consistency. If the first POST became visible, it is treated as already correct and is **not resubmitted**. If it has still not appeared, the prior request remains pending/uncertain and is **not resubmitted**; all *other six* independently verified new/corrective links may proceed safely. If the live 3430 XRef is unexpected, the run aborts before any new writes. Every new XRef POST gets a bounded (default 15-second) read-after-write verification window, with a maximum of 60 seconds configurable via `--verify-wait`.

Possible outcomes:
- `mode: apply`, `submitted: 6`: 3430 was already correctly linked; all remaining six finished and were reverified.
- `mode: apply_completed_other_links_pending_prior_confirmation`, `submitted: 6`: six finished; 3430 still needs **verification**, and the previous POST was not repeated.
- `mode: apply_interrupted_unverified`: a different newly submitted XRef is not yet visible within the bounded verification window; its attempt is journaled, and rerunning is safe without repeated network writes.

**Do not run `curl POST` or manually link 3430 until the pending state has been resolved**. This patch makes no filesystem changes, schedules no refresh and touches no other media.

## CT2601 second-run report: temporary empty XRef during correction

The operator's subsequent `shoko-final10-resume.json` shows:
- **3430 is now correct** (AniDB 8808 / EID 149639).
- **3432 had POST sent** to replace old EID 150419 with 154716, but the immediate read of `?include=XRefs` returned **`[]`**. This *is not an observed conflicting AniDB episode*; it can occur while Shoko is removing an old release mapping and building its new one.
- **3437, 3438, 3429, 3439, 3434** were not sent in that run.
- Four PVs and two standalone DxD OVAs remain separate outside the corrective scope.

The script formerly classified empty XRefs after a correction as `submitted_conflicting_xref` and aborted. This was wrong. The new recovery logic treats `[]` after a **journalled** replacement POST as an unverified transition, never resubmits that file, and continues the **five** other independently safe XRefs. Unexpected **nonempty** XRefs from another episode still abort. A pre-existing empty XRef without an exact prior attempt remains a preflight failure.

Re-run **one** command (preserve both earlier reports, and keep the journal untouched):

```bash
cd /opt/tethys-anime-hub
git pull --ff-only
cd tools/shoko_reconcile
python3 fix_dal_endings_final10.py \
  --apply --confirm CORRECT_DAL_NCED_XREFS_9 \
  --report /root/shoko-final10-recovered.json
```

Default bounded verification per new XRef is now 3 seconds (adjustable with `--verify-wait 0..60`). An individual XRef still pending does **not** stop writes for other files. The tool makes one final read-only pass over pending XRefs and records `apply_completed_pending_confirmation` if anything is still awaiting Shoko processing. Journalled File IDs are never POSTed twice.

Expected if no intervening file changes: **up to five new POSTs**: two corrections (3437 and 3438) plus three new XRefs (3429, 3439, 3434); 3432 must be confirmed separately from its already-dispatched request. A final state of six unrecognized files is **conditional** on all nine NCED XRefs actually becoming visible.
