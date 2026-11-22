# Final Shoko closeout: mark exactly four PV clips as Ignored

After the two DxD OVAs were linked and verified (`shoko-dxd-ova-closeout.json`, `submitted=2`, `verified_after_post=2`), the only expected remaining unrecognized items were promotional videos (PV = **Promotional Video**):

| File ID | Type | RelativePath |
|---:|---|---|
| 2994 | KonoSuba S1 PV | `[Kawaiika-Raws] (2016) KonoSuba S1 [BDRip 1920x1080 HEVC FLAC]/Bonus/[Kawaiika-Raws] KonoSuba S1PV [BDRip 1920x1080 HEVC FLAC].mkv` |
| 2997 | KonoSuba S2 PV2 | `[Kawaiika-Raws] (2017) KonoSuba S2 [BDRip 1920x1080 HEVC FLAC]/Bonus/[Kawaiika-Raws] KonoSuba S2PV2 [BDRip 1920x1080 HEVC FLAC].mkv` |
| 2999 | KonoSuba S2 PV1 | `[Kawaiika-Raws] (2017) KonoSuba S2 [BDRip 1920x1080 HEVC FLAC]/Bonus/[Kawaiika-Raws] KonoSuba S2PV1 [BDRip 1920x1080 HEVC FLAC].mkv` |
| 3020 | High School DxD BorN PV | `[Snow-Raws] High School DxD Born [BDRip 1920x1080 HEVC FLAC]/NC/[Snow-Raws] High School DxD BorN PV [BDRip 1920x1080 HEVC FLAC].mkv` |

These are promotional clips, not missing TV/OVA episodes. Their exact AniDB Trailer identities could not be proved; the operator **explicitly approved** marking *only these four* Ignored while preserving the original media/torrent paths.

## Apply with one command on CT2601

```bash
cd /opt/tethys-anime-hub
git pull --ff-only
cd tools/shoko_reconcile

python3 ignore_final_four_pvs.py \
  --apply --confirm IGNORE_FOUR_PVS \
  --report /root/shoko-final-four-pv-ignore.json
```

This makes at most four `PUT /api/v3/File/{fileID}/Ignore?value=true` requests. It does **not** call DELETE, rescan, remux, unlink, or modify `/Anime`; no torrent upload/seeding is interrupted. Shoko's `VideoService.SetVideoIgnored()` only updates the `IsIgnored` flag on the stored video entity. `ModelHelper.FilterFiles()` excludes ignored videos from `Unrecognized` **by default**, so the resulting count is expected to be zero unless new unrecognized files have appeared.

Before any request: one bounded Unrecognized listing plus four exact `GET /File/{id}?include=XRefs` reads. Each file's ID, exact `RelativePath`, `IsIgnored=false`, **empty AniDB and other metadata cross-references**, and `Unrecognized` membership must match. One mismatch aborts the batch. Each flag change is journaled before its PUT and verified after writing; an uncertain reply is not blindly resent. Repeated runs skip already Ignored files. The final report includes all remaining unknown IDs and count, not just success messages.

**Shoko source verification:** [FileController.cs](https://github.com/ShokoAnime/ShokoServer/blob/master/Shoko.Server/API/v3/Controllers/FileController.cs) implements `[HttpPut("{fileID}/Ignore")]` and delegates to `SetVideoIgnored`; [VideoService.cs](https://github.com/ShokoAnime/ShokoServer/blob/master/Shoko.Server/Services/VideoService.cs) modifies only `IsIgnored`; [ModelHelper.cs](https://github.com/ShokoAnime/ShokoServer/blob/master/Shoko.Server/API/v3/Helpers/ModelHelper.cs) excludes ignored files from standard file lists unless explicitly requested.

To reverse later, Shoko's UI can unmark a video as Ignored; the API inverse is `PUT /api/v3/File/{id}/Ignore?value=false` (do not need to move any MKV).

