# CT2601 — verified Nekopara OVA/ONA and combined Yona E03+S01 (2026-11-22)

## 1. Link the TWO Nekopara standalone files

Evidence: `nekopara-works-episodes.json` reports both AniDB works `present_ready`; `shoko-current-unknown-48.json` lists both exact file IDs and paths as unrecognized. They are not Nekopara TV (AniDB 14570).

| File ID | Exact file name | AniDB work | Shoko series | Episode | AniDB Episode ID | AniDB title |
|---:|---|---:|---:|---|---:|---|
| 2909 | `NEKOPARA_[OVA]_[AniLibria_Tv]_[WEB-Rip_1080p].mkv` | 12622 | 274 | E01 | 193701 | OVA |
| 2850 | `Nekopara_Koneko_no_Hi_no_Yakusoku_[ONA]_[AniLibria_TV]_[WEBRip_1080p].mkv` | 14206 | 279 | E01 | 203599 | Web |

First (on CT2601 with exported `SHOKO_API_KEY`):

```bash
cd /opt/tethys-anime-hub
git pull --ff-only
cd tools/shoko_reconcile

python3 manual_review_batch.py \
  --manifest manual_xrefs_nekopara_ova_ona_20261122.json \
  --report /root/shoko-nekopara-two-dry-run.json
```

Review JSON. Only if the two targets are `ready` and no rows are `blocked`, submit:

```bash
python3 manual_review_batch.py \
  --manifest manual_xrefs_nekopara_ova_ona_20261122.json \
  --apply --confirm APPLY_SHOKO_XREFS_2 \
  --report /root/shoko-nekopara-two-apply.json
```

The selected manifest has only TWO rows, each validated live by File ID, exact Shoko RelativePath, local work ID and AniDB Episode ID/type/number/title. Automatically recognized records skip safely. Neither script nor manifest touches the physical media, starts refreshes or discovers additional works.

## 2. One combined Yona MKV actually has both E03 and S01

Evidence: `shoko-yona-03-sp-probe.json`, File `2486`, path `Akatsuki no Yona OVA/Akatsuki no Yona OVA (03+SP).mkv`, local AniDB **11143**, Shoko series **270**, duration **1696.695 s**.

| Time | MKV chapter | Expected AniDB mapping |
|---|---|---|
| 00:00–09:33.573 | `あかい星が昇る Chapter 1` | E03 part 1 |
| 09:33.573–24:04.109 | `あかい星が昇る Chapter 2` | E03 part 2 |
| 24:04.109–28:16.695 | `今日はおやすみ` | S01 |

- **E03:** `The Yellow Dragon Zeno's Past, Part 2: The Red Star Rises`, AniDB episode ID **176847**, Type `Episode`, number `3`.
- **S01:** `Good Night for Today`, AniDB episode ID **183623**, Type `Special`, number `1`.

These chapter titles are direct supporting evidence of the bundled episodes; the physical MKV should never be split or renamed. The final content mapping is strongly supported, but can be visually confirmed near the 24:04 transition if desired.

Shoko's official [Unrecognized Files / Manual Linking](https://docs.shokoanime.com/shoko-server/unrecognized-files) documentation describes **Duplicate Entry** for one file containing multiple episodes. Use the Shoko Web UI for this ONE multi-episode file, rather than the current one-XRef-per-file CLI (which prevents duplicate File IDs by design):

1. Open **Utilities → Unrecognized Files** and locate `Akatsuki no Yona OVA (03+SP).mkv` (File ID 2486).
2. Select it and open **Manual link**. Choose the exact work `11143` (`Akatsuki no Yona OVA`; Shoko 270).
3. Assign the original selected entry to **Episode E03**.
4. Select the same file entry, use **Duplicate Entry** (Shoko creates a *virtual file entry*, not another disk copy), and map that new entry to **Special S01**.
5. Confirm both mappings visibly, then click **Save**. After Shoko processes the queue verify both E03 and S01 show a file.

**Do not** send two raw `LinkFromSeries` API POSTs against the same File ID, or add the same File ID twice to `manual_review_batch.py`: the latter intentionally rejects duplicate file IDs and the former could replace/conflict with the first link. Use the documented Web UI flow to preserve both links.

Expected count from original snapshot: 48 unknown before these three physical files; after linking both Nekopara files and one Yona combined MKV, **45 unknown** if no concurrent library updates or automatic recognitions. The combined Yona E03+S01 represents *two missing episode entries but only one physical file*.
