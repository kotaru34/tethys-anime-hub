# Tethys Shoko Reconciler v2.1

**Status:** implemented and locally tested; no live Shoko apply/verification yet. Targets Shoko **5.3.3**, uses its supported **API v3 Manual Links** (no fake ED2K). Files in `/Anime`, MKV tracks, sidecars, torrent paths and Shoko's SQLite database are **never edited** by this tool. A submitted API link may still be processing asynchronously; the final Shoko `--status` is the authority.

## Why v2

v1 examined 1,038 unknown files across 83 release folders. It prepared 690 potential mappings, but title and episode heuristics missed many valid releases. v2 adds:

- Cross-group candidate reuse: when an entry is missing from a release-specific AniDB search, reuse series/sequel candidates discovered in other Shoko groups, with explicit season/year disambiguation.
- Filename alternatives, punctuation and romanization normalization, tech-tag removal, release-group ignorance, Unicode titles, typo-tolerant scoring, multiple query variants.
- Optional **locally cached external alias/ID crosswalk** from `cedya77/anime-offline-database` (ODbL 1.0 + DbCL 1.0, derived from `manami-project`). Supports AniDB IDs from MAL/AniList naming differences without sending the user's file names to external LLMs.
- Episode parser for `S02E01`, `S02EP01`, `[01]`, `- 01`, `Name 01`, `Ep 01`, `special 1`, movie markers. Keeps episode type and series identity separate.
- Correct handling of `Takt Op. Destiny` (`Op` *part of the anime title*, not an opening clip); `No Game No Life` ordinary episodes plus nested Specials; OP/ED/NCOP/NCED/PV/bonus footage **not** silently mapped as regular episodes.
- Season/year/media-type context, explicit uncertainty and **one decision per file**, not an unconditional folder-level link. Previous exact Shoko selections are retained when converting the original v1 plan.
- Enforced live checks: file must still be Unrecognized at the original path, intended AniDB ID must match Shoko series ID, episode **type and number** must exist in Shoko before issuing Manual Link.
- Per-file and per-release approved overrides, global `--limit`, audit journal and idempotent reruns.
- Local **per-episode metadata snapshots** via Shoko API containing AniDB/TMDB records, images where returned, Shoko episode data and associated file/MediaInfo where available. The source of truth remains Shoko's local DB. Export path is private and **never under `/Anime`**.

### Measured offline work so far (not live success)

Using the user's v1 `shoko-plan.json` as an **offline fixture without the external alias catalog**, v2.1 reports **808 potential file links** of 1,038 unknown (vs v1's 690). This is **before** verifying series/episodes through live Shoko APIs, link job completion or actual metadata completeness. With the user-reported **1,167 total files**, even 808 successful links would leave **230/1,167 (19.71%) unknown**, meaning at least **172 further verified links** are still required to reach the `<=5%` target. It is **not** a claim of achieving the `<=5%` unrecognized target. The user's accepted mapping error ceiling `<=10%` also needs sampling against the actual result; a similarity score is not a calibrated error probability. Any unknown AniDB release file record fields must be shown as `Unknown` rather than fabricated.

## Upgrade and run inside Shoko LXC

```bash
cd /opt/tethys-anime-hub
git pull --ff-only
cd tools/shoko_reconcile

# An offline ID/title/season crosswalk (download once; source is public, not your filenames).
mkdir -p /var/cache/tethys
curl -fL --retry 3 \
  'https://github.com/cedya77/anime-offline-database/releases/download/latest/anime-offline-database.jsonl' \
  -o /var/cache/tethys/anime-offline-database.jsonl

# Upgrade the already saved v1 plan without making any Shoko API calls.
python3 shoko_reconcile.py \
  --analyze-plan /root/shoko-plan.json \
  --total-files 1167 \
  --catalog /var/cache/tethys/anime-offline-database.jsonl \
  --plan /root/shoko-plan-v2.json
```

**Review the generated candidates, especially seasons, cour splits, OVAs, specials, movies and localized titles before writing.** Files with uncertain identity remain deferred. The catalog is not a license to claim certainty; it can contain incorrect cross-provider links. You can rerun with `--aggressive` to see a broader **plan**; this has not been accuracy-calibrated.

For a specific proven match, create `/root/approved.json` (file names/IDs below are **synthetic**, not a claim of verified AniDB IDs):

```json
{
  "groups": {"Anime Release Folder - Group [1080p]": 12345},
  "files": {"5000": {"anidb_id": 12345, "episode": 1, "type": "Special"}}
}
```

Re-plan with `--overrides /root/approved.json`; overrides require actual AniDB IDs. To explicitly exclude a group, use `0` for that group. A per-file correction wins over a group decision.

```bash
read -rsp 'Shoko admin API key: ' SHOKO_API_KEY; echo
export SHOKO_API_KEY

# Existing plan is valid for application only if its file IDs/paths are still current.
# Apply a 10-item sample; if series are missing, it queues Shoko metadata refresh first.
python3 shoko_reconcile.py --apply --plan /root/shoko-plan-v2.json \
  --confirm LINK --limit 10 --journal /root/shoko-apply-journal.json

# After Shoko's jobs complete, verify first sample in the WebUI and run:
python3 shoko_reconcile.py --status

# Only when the sample is correct, apply the rest. Repeating is safe:
python3 shoko_reconcile.py --apply --plan /root/shoko-plan-v2.json \
  --confirm LINK --journal /root/shoko-apply-journal.json

# The records of EVERY episode are saved separately from source MKVs:
python3 shoko_reconcile.py --export-metadata /var/lib/tethys/shoko-metadata \
  --plan /root/shoko-plan-v2.json
unset SHOKO_API_KEY
```

For a **fresh live search** rather than upgrading a saved plan:

```bash
python3 shoko_reconcile.py --plan /root/shoko-plan-v2.json \
  --catalog /var/cache/tethys/anime-offline-database.jsonl
```

No new media copies and no rehash needed. The normal Shoko/Jellyfin services continue unchanged. The original Shoko watcher must stay disabled under the known deployment settings.

## Acceptance criteria

1. True post-apply `unrecognized / all Shoko files <= 5%` (not projected plan count). Segregate actual extras from anime episodes in the audit; don't artificially hide unknowns to lower the fraction.
2. Manually audit a statistically meaningful stratified sample of linked **works and episodes** across release groups, seasons, specials, different encodings and language names; estimated wrong links **<= 10%** with uncertainty bounds.
3. Per-series and per-episode metadata coverage relative to comparable native-hash matches **>=95% of fields that Shoko can know at series/episode level** (verify field-level audit). **AniDB file-level release ID, verified group, CRC and release version cannot be legitimately reconstructed from absent AniDB records**; preserve Shoko's own `Unknown` value and optionally record separately observed MKV `MediaInfo`/track labels.
4. No writes to torrent files or to Shoko's SQLite DB outside the supported API, no unsupported Shoko 6 plugin in 5.3.3.

## Known gaps / next iteration

- Automated cour partition across separate AniDB anime IDs when one download contains two cours (`S02E13` may be `Episode 1` of a separate AniDB second-cour work). These are deferred pending validated episode metadata and relations, not blindly mapped to the first cour.
- Rare nested spin-offs and bonus contents need independent identity. Shoko's `Unknown Files` count includes some OP/ED/trailers, but ignoring them would not satisfy a genuine `<=5%` quality goal.
- Crosswalk database may not include localized Ukrainian release titles or recently aired works. Supply approved aliases/explicit IDs for these; no silent speculative identification.
- No API calls have been executed against the user's live Shoko from this development environment. Integration acceptance is blocked until live sampling.

## Sources

- [Shoko 5.3.3 file Manual Link API](https://github.com/ShokoAnime/ShokoServer/blob/v5.3.3/Shoko.Server/API/v3/Controllers/FileController.cs)
- [Shoko 5.3.3 series/episode APIs](https://github.com/ShokoAnime/ShokoServer/blob/v5.3.3/Shoko.Server/API/v3/Controllers/SeriesController.cs)
- [Shoko 5.3.3 episode-type parser](https://github.com/ShokoAnime/ShokoServer/blob/v5.3.3/Shoko.Server/API/v3/Helpers/ModelHelper.cs)
- [Offline cross-provider database and licensing](https://github.com/cedya77/anime-offline-database)

## v2.2 – Public crosswalk, series/cour recovery and Shoko episode typing

**Measured on the owner's uploaded v2 plan (2026-11-11), no Shoko writes:**
`1,038` unknown of `1,167` total; v2.1 with cached catalog proposed `851` links. The v2.2 refinements produce **981 potential links**, leaving **57/1,167 = 4.88%** *if every mapped row passes live Shoko validation*. This projection is NOT an achieved unrecognized percentage, nor a demonstrated <10% match-error rate. **Only one failed link would put the forecast on the edge of the 5% threshold**. The real `--status`, episode-metadata availability, curated corrections and accuracy audit remain mandatory.

- `known_aliases.json` is a documented, versioned public anime-title ↔ AniDB ID crosswalk; it resolves short names, localized Ukrainian releases and known AniDB sequel IDs **without falsely claiming an AniDB File ID or modifying MKV**. The IDs have sources and may be overridden. Generic fuzzy matching remains distinct from title crosswalk evidence.
- Exact series identity matters: *Go-Toubun* first season vs `∽`, `∬` and `*`; sequel titles and movie/OVA formats are kept separate. No silent S1-for-S2 mapping.
- Full season downloads covering multiple AniDB works are partitioned **per file**, e.g. S02 E01–E12 → first cour and E13–E24 → second cour E01–E12 when the second AniDB work and its episode count are evidenced. Recaps (`24.5`), unknown E00, OP/ED and trailers are not fabricated as episodes.
- An individual AniDB **OVA/ONA work** uses ordinary E01–E## episodes; `S##` identifies specials within another work. This is essential for Shoko's link endpoint.
- The downloaded `anime-offline-database.jsonl` is still used for **independently named nested works**, e.g. `Youjo Senki/Youjo Shenki/`: a chibi spin-off has its own AniDB identity, not the containing parent TV series. Files with no verified crosswalk are deferred.
- `--limit` caps not only submitted API links but also files pending series metadata refresh, preventing a ten-file trial from queuing the entire library.

### Convert your existing v2 plan, without re-scanning anything

Run in the Shoko LXC after updating the repository:

```bash
cd /opt/tethys-anime-hub
 git pull --ff-only
cd tools/shoko_reconcile

# Uses the existing local crosswalk you already downloaded during v2.1.
python3 shoko_reconcile.py \
  --analyze-plan /root/shoko-plan-v2.json \
  --total-files 1167 \
  --catalog /var/cache/tethys/anime-offline-database.jsonl \
  --plan /root/shoko-plan-v2.2.json
```

**The output is an offline forecast only.** The new plan is version 2 (v2.2 enhancements are recorded in `refinements`), and is compatible with the existing v2 Shoko API link operation.

Before any large write, validate a small live sample, including at least a sequel, an OVA/ONA, and a localized title:

```bash
read -rsp 'Shoko admin API key: ' SHOKO_API_KEY; echo
export SHOKO_API_KEY
python3 shoko_reconcile.py --apply --plan /root/shoko-plan-v2.2.json \
  --confirm LINK --limit 10 --journal /root/shoko-apply-v2.2.json
python3 shoko_reconcile.py --status
```

If Shoko queues metadata fetching, let its jobs settle and rerun. Verify the sample file-to-episode links visually in Shoko before an unbounded `--apply`. **No 5% or 10% claim can be made without these host-side results.** Never commit the user's private plan, inventory, API key, or snapshots.

## v2.3 – Source-season evidence and event-driven recovery (2026-11-13)

**Safety first:** a successful Shoko file-to-episode manual link is not proof that the AniDB series/season is correct. Shoko's episode E01 exists in several works. This revision uses **episode source season** (e.g. `S02E11`) as independent identity evidence, even when the release directory has no season marker. It never considers a valid episode number alone as evidence for S01 vs S02.

- Search and rank season-specific candidate titles from per-file tags and alias-catalog metadata. Date chronology operates on **distinct AniDB IDs**, not duplicate Shoko/alias results for the same anime. Numbered `... 2` and `Part 2` suffixes are contextual and require a sufficiently matching complete title stem; no named-anime special cases were introduced.
- When a single release directory contains **both** `S01E..` and `S02E..`, independently resolve the season batches; untagged files must not be silently inherited into one of them.
- The season safety check is performed in **fresh plans**, **offline refinement of legacy plans**, **direct manual-link apply**, and **unattended fallback**. Explicit file/release-approved mappings remain possible when source numbering is known to be exceptional.
- On Shoko queue **busy → idle** events, the SignalR bridge schedules fallback reconciliation even if Shoko does not emit `Shoko:FileNotMatched`. Startup/reconnect also triggers a check. After its event-triggered grace period, the worker checks the **live** Shoko `/Queue` state before awaiting SignalR; if busy it rechecks at most every 30 seconds so a missed idle notification cannot stall it indefinitely. This is **not** a fixed periodic library scanner.
- Synthetic regression tests cover sequel vs original, aliases/candidate chronology collisions, same-directory mixed seasons, old-plan first-season corruption, OVA/cour and publisher-verified specials, and queue transitions. CI tests Python 3.11/3.12/3.13. Private `shoko-plan*.json` inventories must **never** be committed.

To validate on the Shoko host **without changing any file, database, or link**:

```bash
cd /opt/tethys-anime-hub/tools/shoko_reconcile
python3 -m unittest discover -s tests -v
python3 shoko_reconcile.py --status
python3 shoko_reconcile.py \
  --plan /root/shoko-future-dry-run.json \
  --catalog /var/cache/tethys/anime-offline-database.jsonl

# Optional offline replay of a PRIVATE legacy v2 plan: do not copy to Git.
python3 shoko_reconcile.py \
  --analyze-plan /root/shoko-plan-v2.2.json \
  --total-files 1167 \
  --catalog /var/cache/tethys/anime-offline-database.jsonl \
  --plan /root/shoko-v2.3-replay.json
```

**Important:** the archived `--analyze-plan` path rechecks historical decisions, not actual present-day Shoko state, and can correctly defer previously optimistic links. Compare the proposed mappings **by file ID and AniDB identity**, not solely the total count of potential links. If the library has zero Unrecognized files, an ordinary new `--plan` will be empty; exercise the automatic fallback with a later newly ingested release or an isolated API fixture. Leave the event service in dry-run until its live behavior and accuracy are confirmed. Any timestamp-based franchise-season inference is heuristic and must fail closed if necessary evidence is missing.

## Diagnose missing media / apparently skipped Shoko scans (read-only)

`qbit-shoko-poller.service` sends Shoko's
`GET /api/v3/Action/ImportNewFiles` only after the five-minute Anime
completion debounce. HTTP 200 means Shoko completed the import-folder
enumeration and queued any discovered file jobs; it does **not** mean every
expected file was discovered or successfully hashed. The default import scans
only new files. A manual import-folder `GET /api/v3/ImportFolder/{id}/Scan`
rescans every candidate file. Shoko's recursive directory enumeration sets
`IgnoreInaccessible = true` in Shoko 5.3.3, so unreadable nested paths may
be silently skipped.

For an exact comparison, run on **CT2601**, using the **OS user that runs the
Shoko Server** for the most representative filesystem access check:

```bash
cd /opt/tethys-anime-hub/tools/shoko_reconcile
read -rsp 'Shoko API key: ' SHOKO_API_KEY; echo
export SHOKO_API_KEY
PYTHONDONTWRITEBYTECODE=1 python3 -B audit_inventory.py
# If Shoko Server itself runs as 'shoko':
runuser -u shoko -- env SHOKO_API_KEY="$SHOKO_API_KEY" PYTHONDONTWRITEBYTECODE=1 \\
  /opt/tethys-anime-hub/.venv-shoko/bin/python -B audit_inventory.py
unset SHOKO_API_KEY
```

The audit fetches read-only `/ImportFolder` and paginated `/File`
locations, opens video files to confirm they can actually be read, then
compares them to disk paths and sizes. It reports `UNINDEXED MEDIA`,
stale/indexed-but-invisible files, file-size mismatches, scan errors, and
missing files grouped by release folder. It never changes files, schedules
a Shoko scan, or computes hashes. A nonzero exit code flags incomplete
coverage or missing readable files.

The Shoko import-folder `FileSize` sums **indexed VideoLocal** file sizes,
not arbitrary data under `/Anime`; total recognized anime/series do not
equal the number of release folders. Interpret `du`, Shoko's UI size,
and folder counts accordingly.

## AUTO-LINK review backlog exceeds 5%

The Shoko dashboard lists TV Series, Movies, Web and other recognized work
types. These work counts are **not** the number of unrecognized video files.
The actual quality metric is `Unrecognized / Files`, from
`python3 shoko_reconcile.py --status`; for instance 137 of 2155 = 6.36%,
so at least 30 additional *correct* links are needed to get back to <=5%
if the library size stays the same.

The fallback intentionally does **not** auto-link ambiguous title searches,
numberless episodes, speculative cour shifts, unknown specials or a sequel
based on a franchise root. A `needs_review:137` line means the worker reached
the reconciliation plan and *none of the 137 stable unknowns passed safety
gates*. It is not a failure to run Shoko's filesystem scan.

The unattended policy now also accepts `strong_context` matches **only
when they pass the same strict candidate score >=0.98 and >=0.18 gap
against every rival**, plus the existing source-season and episode checks
required for `auto_evidence`. The normal `strong_context` 0.91/0.075
threshold is deliberately **not** enough on its own for unattended linking.

For incrementally downloaded RSS episodes, fallback also queries Shoko's
**read-only existing file XRefs**. If two **different numbered episodes** in
the **exact same parent directory** are already linked to exactly one AniDB
work with non-conflicting source-season evidence, a fresh stable third
E-numbered episode can inherit that verified *work identity* (not an invented
AniDB file record). Mixed seasons, conflicting work IDs, unnumbered files,
OVAs/specials and existing competing title selections remain manual review.
The link operation still verifies the destination AniDB episode actually
exists before writing.

Every idle plan run now writes a private inspection snapshot to
`/var/lib/shoko-reconcile/realtime-plan.review.json` (or the service's
configured plan base name), including even 100%-rejected plans. The journal
prints `unknown_percent`, `additional_links_for_5pct`,
`review_by_mode`, `review_by_reason`, and up to 12 `review_top_groups`.
Review the JSON *locally on CT2601*, **never commit it**:

```bash
journalctl -u shoko-reconcile-events.service -n 30 --no-pager
python3 - <<'PY'
import json
p="/var/lib/shoko-reconcile/realtime-plan.review.json"
d=json.load(open(p))
for g in sorted(d["groups"], key=lambda g:-len(g.get("files",[]))):
    rejected=[f for f in g["files"] if f.get("mode") in
              ("review","episode_review","strong_context")]
    if rejected:
        print(g["folder"], len(rejected), g.get("mode"), g.get("reason"),
              [(f["path"],f.get("mode"),f.get("reason")) for f in rejected[:2]])
PY
```

Do not lower matching thresholds merely to meet the numerical target:
incorrectly identifying a work or episode degrades the archive. The private
review plan can be used to validate release-specific AniDB IDs, fill curated
aliases or publisher-backed overrides, then rerun the unattended fallback.

## Opt-in systemd unattended linking (after live verification)

The standalone Shoko LXC event listener is `shoko-reconcile-events.service`.
Once the host's Manual Link samples and XRefs are verified, opt in **without
replacing its existing ExecStart or changing its API-key configuration**:

```bash
# Run as root inside the Shoko LXC, after pulling the updated repo.
install -d -m 755 /etc/systemd/system/shoko-reconcile-events.service.d
printf '%s\n' '[Service]' 'Environment=SHOKO_RECONCILE_APPLY=LINK' \
  > /etc/systemd/system/shoko-reconcile-events.service.d/30-auto-link.conf
systemctl daemon-reload
systemctl restart shoko-reconcile-events.service
systemctl is-active shoko-reconcile-events.service
journalctl -u shoko-reconcile-events.service -n 50 --no-pager
```

Look for `Shoko reconciler mode: AUTO-LINK` on startup. This is an exact-token
opt-in: absent or empty `SHOKO_RECONCILE_APPLY` remains dry-run, and any
nonempty value other than `LINK` causes startup to reject configuration.
The existing `--apply --confirm LINK` CLI method remains supported. The
event bridge waits for Shoko's jobs to finish and for media stability before
submitting only `is_safe_automatic_link()`-approved candidates. Ordinary
`strong_context` and unnumbered `episode_review` are not auto-applied.
Existing unknown files can be considered at service startup, not just new
torrent completions.

Rollback to dry-run without disturbing other drop-ins:

```bash
rm /etc/systemd/system/shoko-reconcile-events.service.d/30-auto-link.conf
systemctl daemon-reload
systemctl restart shoko-reconcile-events.service
```

The separate `qbit-shoko-poller.service` running in CT 540 should continue
handling torrent-completion import scans; do not add a second scanner.

## qBittorrent completion hook (5-minute debounce)

`notify-shoko.sh` is a replacement for the Torrenya CT 540 completion hook at
`/usr/local/bin/notify-shoko.sh`. It preserves the existing Shoko 5.3.3
`GET /api/v3/Action/ImportNewFiles` endpoint and API key
(`/etc/torrenya/shoko-api-key`). **Required qBittorrent setting change:** In Settings → Downloads → **Run external
program on torrent completion**, use this exact command:

```text
/usr/local/bin/notify-shoko.sh "%G"
```

qBittorrent substitutes `%G` with the completed torrent's comma-separated
**tags** (not its category). Only the exact, case-sensitive `Anime` tag is
accepted, including combinations like `Movies, Anime`. Whitespace around tag
names is ignored; `anime`, `AnimeArt`, untagged torrents, and missing `%G`
arguments are ignored **before touching debounce state**. Non-anime completions
therefore do not restart the five-minute timer. A no-argument manual run is
intentionally a no-op; use `runuser -u kotaru -- /usr/local/bin/notify-shoko.sh Anime`
for a tagged manual test.

**Upgrade note:** The previous qBittorrent setting contained only the script
path. After installing this update, that old setting will safely do nothing
until you append `"%G"` in qBittorrent.

The hook records every completion, returns immediately to qBittorrent and
coalesces events into **one scan 300 seconds after the latest completion**.
Another completion resets the timer, even while the worker is already waiting.
If a torrent completes during the Shoko API call, it schedules another scan
300 seconds after that new completion. The worker uses an exclusive state lock,
checks an incrementing event ID before acknowledging work, and retains failed
requests for retries. No existing media files are touched.

The writable, private state directory must be created **once** as root on
Torrenya before installing the hook:

```bash
install -d -o kotaru -g "$(id -gn kotaru)" -m 0700 /var/lib/torrenya/shoko-notify
install -o root -g root -m 0755 notify-shoko.sh /usr/local/bin/notify-shoko.sh
```

Keep the already-configured ACL allowing the `kotaru` process to read the
Shoko API key; do **not** make the key world-readable. Observe requests and
errors with `tail -f /var/lib/torrenya/shoko-notify/worker.log`. The pending
state contains `<unix-time> <event-id>`; a zero time indicates no outstanding
work. No qBittorrent restart or change to its configured hook path is required.

### One-time recovery/install on Torrenya CT 540

If the old hook has been temporarily replaced with `#!/bin/sh; exit 0`, install
the known-good `Anime`-tagged debounce version and provision its writable state
with a single root-side command inside CT 540:

```bash
curl -fsSL https://raw.githubusercontent.com/kotaru34/tethys-anime-hub/main/tools/shoko_reconcile/install-torrenya-hook.sh | bash
```

The installer: restricts the API key ACL to `kotaru`, prepares
`/var/lib/torrenya/shoko-notify` owned by `kotaru` with mode `0700`,
backs up and replaces `notify-shoko.sh` with a **pinned** working revision,
and installs `torrenya-qbt-vfork-watchdog.timer` (checks every ~30 seconds).
The watchdog never calls Shoko: it only looks for the exact observed
qBittorrent WebUI hang signature (main thread in `kernel_clone`, unresponsive
localhost HTTP, QProcess double-fork chain older than 45 seconds) and sends
SIGKILL only to the stuck grandchild, leaving the main qBittorrent PID intact.
No qBittorrent restart and no torrent/session writes are performed by the
installer. The watchdog mitigates one specific known hang; it is **not** a
general guarantee against every possible Qt/QProcess failure. Its logs are
tagged `qbt-vfork-watchdog` in journald.

After installation, re-enable the qBittorrent setting `Run external program
on torrent completion` and set the command to
`/usr/local/bin/notify-shoko.sh "%G"`. The installer cannot change the
WebUI preference without a valid authenticated session. Other torrent tags
are ignored.

The installer prints potential *other* import callers in the Torrenya
systemd/cron configuration; it intentionally does **not** auto-disable unknown
services. The Shoko LXC's `shoko-reconcile-events.service` listens to Shoko
queue events and is not a second import-folder scanner. Confirm no separate
scheduled ImportNewFiles action exists on either container before declaring
the entire deployment free of duplicate triggers.

## Torrenya completion detection: independent qBittorrent API poller (preferred)

The previous qBittorrent **Run external program on torrent completion** hook
uses Qt `QProcess::startDetached()` and repeatedly deadlocked the Torrenya
qBittorrent main process in a double-`vfork` chain. A SIGKILL of the stuck
grandchild could recover the UI, but a watchdog is not a satisfactory solution.
**Do not re-enable that completion command.**

The replacement `qbit_shoko_poller.py` runs as a **separate systemd service**.
It reads qBittorrent's local `GET /api/v2/torrents/info?tag=Anime` every
30 seconds; it does **not** spawn from qBittorrent. Only an exact `Anime`
tag and a completed torrent (`amount_left=0`, `progress≈1`,
`completion_on>0`) count. It persists its state under
`/var/lib/torrenya/shoko-poller/state.json` and schedules **one** Shoko
`GET /api/v3/Action/ImportNewFiles` call 300 seconds after the most
recent relevant completion. Old completed torrents are baselined without
triggering a scan on initial installation. A missed completion during service
downtime is detected after restart if the torrent remains in qBittorrent.

The installer disables the old qBittorrent completion command **via its Web
API** and verifies the setting is false, then disables the obsolete vfork
watchdog timer. It requires valid WebUI API authentication to make this change.
On qBittorrent 5.2+ enter an API key from WebUI settings, or use the existing
WebUI username/password; credentials stay in a `0600` file readable only to
the `kotaru` user. It never disables WebUI authentication, restarts
qBittorrent, rewrites torrents, or edits files under `/Anime`.

Run as **root inside CT 540 Torrenya**:

```bash
curl -fsSLo /tmp/install-qbit-shoko-poller.sh \
  https://raw.githubusercontent.com/kotaru34/tethys-anime-hub/main/tools/shoko_reconcile/install-qbit-shoko-poller.sh
bash /tmp/install-qbit-shoko-poller.sh
```

Once the installer succeeds, the only required systemd service for this
transition is `qbit-shoko-poller.service`. The separate
`shoko-reconcile-events.service` in the Shoko LXC is still used to identify
already imported unknown files; it is **not** an import-folder scan trigger.

To check: `systemctl status qbit-shoko-poller.service --no-pager` and
`journalctl -u qbit-shoko-poller.service -n 30 --no-pager`. Optional pending
state: `python3 /usr/local/libexec/qbit_shoko_poller.py --status`.

The poller retries failed Shoko API requests without losing the pending state.
A crash between Shoko's accepting a scan and the state commit may result in
one redundant import request, but Shoko's ImportNewFiles is idempotent for
registered paths. The poller does not prevent separate Shoko scheduled imports;
those should be checked in the Shoko LXC if strict global deduplication matters.
