# Final two DxD OVAs — one-shot Shoko 5.3.3 link, 4 PV clips untouched

**Reconciliation checkpoint (CT2601):** `shoko-final10-recovered.json` reported `mode: apply`; all nine Date A Live TV NCED mapped correctly, including two just-verified corrections and three just-verified new XRefs. No pending NCED remains.

## 2 remaining full-length DxD OVAs

| File ID | Local reviewed relative path | Proposed AniDB work | AniDB Episode E01 |
|---:|---|---:|---:|
| 3209 | `High School DxD OVA [BDRip 1080p]/High School DxD OVA - 03 (BDRip 1920x1080).mkv` | 11184, *High School DxD New: Teishi Kyoushitsu no Vampire* | 161394 |
| 3206 | `High School DxD OVA [BDRip 1080p]/High School DxD OVA - 04 (BDRip 1920x1080).mkv` | 11844, *High School DxD BorN: Yomigaeranai Fushichou* | 167801 |

Public release/episode lists consistently describe four main *High School DxD* full-length OVAs: the original two from 2012/2013, followed by the *New* OVA (2015) and the *BorN* OVA (2015). The local numbered files `03` and `04` are therefore **high-confidence ordinal matches**, but there has not been direct frame-based verification of these particular local MKVs. This limitation is intentionally disclosed. Independent sources: [four-OVA compiled release](https://animevost.org/tip/ova/124-high-school-dxd-ova.html), [episodic guide](https://www.tvmaze.com/shows/5304/high-school-dxd/episodeguide), [OVA episode chronology](https://en.wikipedia.org/wiki/List_of_High_School_DxD_episodes).

## One command

```bash
cd /opt/tethys-anime-hub
git pull --ff-only
cd tools/shoko_reconcile

python3 link_final_dxd_two_ova.py \
  --apply --confirm LINK_CHRONOLOGICAL_DXD_OVAS_2 \
  --report /root/shoko-dxd-ova-closeout.json
```

Requires existing exported `SHOKO_API_KEY` (the command never prints it). If the media is not actually the assumed third/fourth full-length OVA, **do not apply**; use the read-only run without `--apply` and verify its content first. No automatic attempts are made if current metadata differs.

### Safeguards

- Only Shoko File IDs `3209` and `3206`, checked for their **exact Shoko RelativePaths** and no pre-existing AniDB XRefs. An already-correct file is skipped. Any other existing reference blocks the batch.
- Local AniDB work identity and actual local E01 Episode Type, **AniDB Episode ID** (`161394` and `167801`) and title `OVA` must all match the live Shoko inventory before either write. This fails closed if the previous metadata requests have not yet populated these two works.
- One bounded `Unrecognized` page (max 100 entries) before writes, and a bounded just-in-time reread for each file; no full library scan, MKV/ASS or torrent edits.
- Operator `--confirm` plus a persistent private journal **before** each POST prevents duplicate sends after uncertain responses. Bounded eventual-consistency check handles empty XRefs while Shoko processes a link.
- No PV action or `Ignore`. The script merely lists the four known unrecognized PV IDs `2994`, `2999`, `2997`, `3020` and explicitly leaves them untouched.

### Why the four PVs remain

Shoko's current AniDB catalogs have no independently confirmed matching Trailer episode IDs for S2 KonoSuba PV1 and PV2 or High School DxD BorN PV. S1 KonoSuba has a trailer *2nd Season Announcement*, but its identity has not been matched to this particular S1PV MKV. Blindly linking PV files to arbitrary TV or Credits entries would falsify the library; silently marking them ignored would hide existing bonus media. The user can later explicitly choose `Ignored` in Shoko if those specific four files are not intended to appear as tracked anime extras. This PR does **not** do that.
