# CT2601 — one-pass resolution of the remaining 45 Shoko unknown files

This **one-shot command** covers the complete snapshot after Nekopara OVA/ONA and combined Yona were linked (45 files): 24 newly imported Date A Live Director's Cut and NC clips, and 21 older unknowns. It does **not** require an operator to run six separate probes and batches.

## Verified work identities

- **Date A Live Director's Cut 01–12**: AniDB **8808**, `Episode E01–E12`. The 2015 Japanese official Blu-ray contains 12 TV episodes with extended scenes.
- **Date A Live Director's Cut 13**: the included first-season OVA **Date to Date**, independent AniDB **9734**, `Episode E01`. Original separately downloaded Date A Live OVA File ID **2955** is *another release of the same OVA*; both physical files may reference the same AniDB episode.
- Standalone works already identified in the uploaded historical triage: Date A Live II Kurumi Star Festival **10568** (File 2957); Kaguya-sama 2021 OVA **15807** (3374); Goblin Slayer's Crown **14782** (3023); ORESUKI OVA **15329** (2253). Each proposed E01 is checked against local AniDB episode metadata before submission.
- 11 Date A Live NC clips, five KonoSuba extras, and eight DxD extras are **not blindly assigned**. Only if *exactly one* whole-work unambiguous `Credits` entry exists and matches a generic single OP/ED filename does the tool allow that clip. All numbered alternatives, PVs, and variants stay flagged for content verification.
- **Deliberate skips**: DxD standalone OVA -03/-04 File 3209/3206 whose content/provenance remains uncertain, and Yuusha Yamemasu -13 File 3222 which is not TV E13.

Official Japanese release verification: https://store.kadokawa.co.jp/shop/g/g302203002588/ and https://date-a-live-anime.com/1st-2nd/bldvd/bdbox.html

## Single command on CT2601

Export `SHOKO_API_KEY` exactly as you did previously, then:

```bash
cd /opt/tethys-anime-hub
git pull --ff-only
cd tools/shoko_reconcile

python3 resolve_45_onepass.py \
  --apply --confirm RESOLVE_SAFE_XREFS_45 \
  --report /root/shoko-resolve-45.json
```

**That's it.** The tool itself first performs a fail-closed read-only preflight and one bounded `Unrecognized` preflight (max 100 files) plus one additional bounded recheck immediately before XRef writes, to skip files auto-recognized during metadata retrieval, and refuses to write if any pinned existing File ID no longer has its exact RelativePath. It then queries only pinned AniDB works, submits at most one metadata request per missing **independently known story work** (6-ID allowlist), journals each attempt before POST, and waits up to 120 seconds for those specific works' episode records. If the Shoko server has an outstanding backlog beyond this bounded wait, the report says `waiting_for_work_metadata`; a **rerun of the same command** later continues safely without resubmitting previous metadata/XRefs.

When a work's episodes are available, the script checks **exact AniDB work ID, Shoko Series ID, Episode Type/Number, positive AniDB Episode ID, and nonempty title**, then posts safe XRefs only. It writes each attempted File ID to a private persistent journal before the network request, preventing duplicate submissions after an uncertain response. Already recognized files are skipped and never linked twice.

Expected deterministic safe proposals from the snapshot: **18 story releases** (12 TV Director's Cut + 1 OVA included as #13 + 5 older standalone copies/releases). Up to three strictly unique OP/ED clips may also qualify, depending on live AniDB credits (actual results may be lower). This is *not* a promise to recognize all 45: files with ambiguous credits, PV variants, and content-indeterminate OVA must not be forcibly linked to the wrong episode.

The command emits full per-file status/candidates/candidate credits and compact counts in `/root/shoko-resolve-45.json`. No video/ASS/font changes, no filesystem walk, no background service, no renaming, and no full recognized library scan. Outputs and attempt journal are mode 0600. Share this **single report** if any items remain unresolved.

Optional non-writing preview: `python3 resolve_45_onepass.py --report /root/shoko-resolve-45-dry-run.json`.
