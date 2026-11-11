#!/usr/bin/env python3
"""Shoko 5.3.3 filename-to-AniDB-episode reconciler.

Only changes Shoko's API-side manual links (when explicitly approved). Never writes media,
Shoko SQLite, AniDB, or Jellyfin. Standard-library only; Python 3.11+.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
import json
import os
from pathlib import PurePosixPath
import re
import sys
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_VERSION = "3"
AUTO_EXACT_SCORE = 0.995
FORMAT_TAGS = re.compile(r"(?i)\b(?:web[- ]?rip|web[- ]?dl|bdrip|blu[- ]?ray|dvd(?:rip)?|1080p|720p|2160p|480p|x26[45]|h\.?26[45]|hevc|av1|flac|aac|opus|hi10p|dual audio)\b")
RELEASE_SUFFIX = re.compile(r"(?i)\s+-\s+(?:anilibria(?:\.tv)?|aniliberty|subsplease|erai[- ]?raws|nyaa|raws|fansub|(?:\[[^\]]+\]))(?:\b|$)")
SEASON = re.compile(r"(?i)(?<!\w)(?:s(?:eason)?\s*0*([1-9]\d?)|([1-9]\d?)(?:st|nd|rd|th)\s+season)(?!\w)")
EP_PATTERNS = (
    re.compile(r"(?i)\bS\d{1,2}\s*E(?:P)?\s*0*(\d{1,3})(?!\d)"),
    re.compile(r"(?i)(?:^|[\s._-])(?:episode|ep|e)\s*0*(\d{1,3})(?=$|[\s._-])"),
    re.compile(r"(?i)(?:^|[\s._-])\[0*(\d{1,3})\](?=$|[\s._-])"),
    re.compile(r"(?i)(?:\s+-\s+|_)(\d{1,3})(?=\s|_|\.|\[|$)"),
)
MAX_EP = 999


def normalized(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).casefold()
    s = s.replace("&", " and ")
    # Normalize equivalent season suffixes across release names and AniDB titles.
    # Restrict this rule to season markers, not arbitrary trailing title numbers.
    s = re.sub(r"(?<!\w)s(?:eason)?\s*0*([1-9]\d?)(?!\w)",
               lambda m: " season " + str(int(m.group(1))) + " ", s)
    s = re.sub(r"(?<!\w)([1-9]\d?)(?:st|nd|rd|th)\s+season(?!\w)",
               lambda m: " season " + str(int(m.group(1))) + " ", s)
    s = re.sub(r"[^\w]+", " ", s, flags=re.UNICODE)
    return " ".join(s.split())


def extract_title(folder: str) -> str:
    """Extract a *conservative* release title; do not discard season identity."""
    title = folder.strip()
    title = re.sub(r"^\[[^\]]+\]\s*", "", title)  # release group prefix
    title = re.sub(r"\s*\[[^\]]*\]\s*$", "", title)  # trailing codec/source tags
    title = RELEASE_SUFFIX.split(title, maxsplit=1)[0]
    title = re.sub(r"\s*\((?:BD|WEB|DVD)[^)]*\)\s*$", "", title, flags=re.I)
    return title.strip(" ._-")


def episode_number(filename: str) -> int | None:
    stem = PurePosixPath(filename).stem
    for pattern in EP_PATTERNS:
        matches = [int(x) for x in pattern.findall(stem)]
        if len(set(matches)) == 1 and matches and 0 < matches[0] <= MAX_EP:
            return matches[0]
    return None


def season_number(title: str) -> int | None:
    m = SEASON.search(title)
    return int(m.group(1) or m.group(2)) if m else None


def title_similarity(query: str, candidate: str) -> float:
    a, b = normalized(query), normalized(candidate)
    if not a or not b:
        return 0.0
    return 1.0 if a == b else SequenceMatcher(None, a, b).ratio()


def _titles(entry: dict) -> list[str]:
    titles = [entry.get("Title", "")]
    for item in entry.get("Titles") or []:
        if isinstance(item, dict):
            titles.extend(str(item.get(k, "")) for k in ("Title", "Name", "Value"))
        elif isinstance(item, str):
            titles.append(item)
    return [t for t in titles if t]


def _season_compatible(query: str, candidate: str) -> bool:
    q, c = season_number(query), season_number(candidate)
    # Ambiguous season naming -> must be approved at *series* level.
    return q == c if q is not None or c is not None else True


def ranked_candidates(query: str, results: list[dict]) -> list[dict]:
    scored = []
    for item in results:
        titles = _titles(item)
        compatible = [t for t in titles if _season_compatible(query, t)]
        best = max((title_similarity(query, t) for t in compatible), default=0)
        if best <= 0:
            continue
        scored.append({"anidb_id": item.get("ID"), "shoko_id": item.get("ShokoID"),
                       "title": item.get("Title"), "type": item.get("Type"), "score": round(best, 4)})
    return sorted(scored, key=lambda x: x["score"], reverse=True)[:5]


class ShokoAPI:
    def __init__(self, base: str, key: str, timeout: float = 20):
        if not base.startswith(("http://127.0.0.1:", "http://localhost:", "https://")):
            raise ValueError("Use localhost or an HTTPS Shoko URL; do not send API keys over remote HTTP")
        self.base = base.rstrip("/") + "/api/v3"
        self.key = key
        self.timeout = timeout

    def request(self, method: str, path: str, params: dict | None = None, body: dict | None = None):
        url = self.base + path + (("?" + urlencode(params)) if params else "")
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"apikey": self.key, "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=self.timeout) as response:
                payload = response.read()
                return json.loads(payload) if payload else None
        except HTTPError as ex:
            detail = ex.read(500).decode("utf-8", "replace")
            raise RuntimeError(f"Shoko API {method} {path} -> {ex.code}: {detail}") from ex
        except URLError as ex:
            raise RuntimeError(f"Shoko API unavailable: {ex.reason}") from ex

    def pages(self, path: str, params: dict | None = None, size=500):
        page = 1
        while True:
            r = self.request("GET", path, {**(params or {}), "pageSize": size, "page": page})
            if not isinstance(r, dict) or not isinstance(r.get("List"), list):
                raise RuntimeError(f"Unexpected Shoko API ListResult for {path}")
            yield from r["List"]
            if page * size >= r.get("Total", len(r["List"])) or not r["List"]:
                break
            page += 1

    def unrecognized(self):
        return list(self.pages("/File", {"include_only": "Unrecognized"}))

    def anime_search(self, title: str):
        return list(self.pages("/Series/AniDB/Search", {"query": title, "fuzzy": "true",
                       "includeTitles": "true", "searchById": "false"}, size=100))[:100]

    def local_series(self, anidb_id: int):
        # Shoko may already know the series by AniDB ID, even if no local media is linked.
        try:
            return self.request("GET", f"/Series/AniDB/{anidb_id}/Series")
        except RuntimeError as e:
            if "-> 404:" in str(e):
                return None
            raise

    def refresh_series(self, anidb_id: int):
        return self.request("POST", f"/Series/AniDB/{anidb_id}/Refresh",
                            {"createSeriesEntry": "true", "downloadRelations": "false", "force": "false"})

    def available_episodes(self, series_id: int) -> set[int]:
        # No blind writes when series episode metadata hasn't finished importing.
        records = self.pages(f"/Series/{series_id}/Episode", {
            "includeDataFrom": "AniDB", "includeMissing": "True", "includeUnaired": "True",
            "includeHidden": "True", "includeManuallyLinked": "True"})
        numbers = set()
        for record in records:
            source = record.get("AniDB") or {}
            if str(source.get("Type", "")).casefold() in ("episode", "normal"):
                num = source.get("EpisodeNumber")
                if isinstance(num, int) and num > 0:
                    numbers.add(num)
        return numbers

    def link(self, file_id: int, series_id: int, episode: int):
        # Do not call until this file has been revalidated as Unrecognized.
        return self.request("POST", f"/File/{file_id}/LinkFromSeries", body={
            "SeriesID": series_id, "RangeStart": str(episode), "RangeEnd": str(episode)})


def group_unrecognized(files: list[dict]) -> dict[str, list[dict]]:
    groups = defaultdict(list)
    for f in files:
        locations = f.get("Locations") or []
        if not locations:
            groups["__missing_location__"].append(f)
            continue
        # Group by the top-level release folder, not a subtitles subdirectory.
        relative = (locations[0].get("RelativePath") or "").replace("\\", "/")
        parts = [p for p in PurePosixPath(relative).parts if p not in (".", "/")]
        group = parts[0] if len(parts) >= 2 else "__missing_folder__"
        groups[group].append(f)
    return dict(groups)


def prepare(api: ShokoAPI, overrides: dict[str, int], allow_exact=True):
    files = api.unrecognized()
    groups = group_unrecognized(files)
    report = {"version": 1, "total_unrecognized_at_scan": len(files), "groups": []}
    for folder, media in sorted(groups.items()):
        title = extract_title(folder)
        results = api.anime_search(title) if title and not folder.startswith("__") else []
        ranked = ranked_candidates(title, results)
        selected = None
        mode = "review"
        if folder in overrides:
            selected = int(overrides[folder]); mode = "approved_override"
        elif allow_exact and ranked and ranked[0]["score"] >= AUTO_EXACT_SCORE and (
                len(ranked) == 1 or ranked[1]["score"] < 0.99):
            selected = int(ranked[0]["anidb_id"]); mode = "exact_title"
        movie_single = (len(media) == 1 and selected is not None and any(
            x["anidb_id"] == selected and str(x.get("type", "")).casefold() == "movie"
            for x in ranked))
        entries = []
        for f in media:
            loc = (f.get("Locations") or [{}])[0]
            rel = loc.get("RelativePath") or ""
            ep = episode_number(PurePosixPath(rel).name)
            if ep is None and movie_single:
                ep = 1  # one-file, exact movie title; still validate endpoint and source
            entries.append({"file_id": int(f["ID"]), "path": rel, "episode": ep})
        episodes = {x["episode"] for x in entries if x["episode"] is not None}
        # Genuine duplicate episodes in a folder are legal (multiple releases).
        valid_count = sum(x["episode"] is not None for x in entries)
        report["groups"].append({"folder": folder, "title_guess": title,
              "mode": mode, "selected_anidb_id": selected, "candidates": ranked,
              "count": len(entries), "numbered": valid_count,
              "distinct_episode_numbers": len(episodes), "files": entries})
    return report


def _series_id_from_api(value) -> int | None:
    if not isinstance(value, dict):
        return None
    # Shoko GET /Series/AniDB/{id}/Series exposes Series with IDs.ID.
    ids = value.get("IDs") or {}
    number = ids.get("ID") or value.get("ID")
    return int(number) if number else None


def apply(api: ShokoAPI, plan: dict, delay=0.25, limit=None):
    if plan.get("version") != 1:
        raise ValueError("Unsupported plan version")
    # Current Unknown whitelist protects existing manual/automatic links.
    current = {int(f["ID"]): f for f in api.unrecognized()}
    accepted = errors = deferred = pending = 0
    for group in plan["groups"]:
        aid = group.get("selected_anidb_id")
        if not aid:
            deferred += len(group["files"])
            continue
        if group["mode"] not in ("exact_title", "approved_override"):
            deferred += len(group["files"])
            continue
        series = api.local_series(int(aid))
        series_id = _series_id_from_api(series)
        if series_id:
            actual_anidb = (series.get("IDs") or {}).get("AniDB")
            if actual_anidb is None or int(actual_anidb) != int(aid):
                raise RuntimeError(f"Series identity mismatch for AniDB {aid}: {series.get('IDs')}")
        if not series_id:
            api.refresh_series(int(aid))
            pending += len(group["files"])
            print(f"QUEUED anime {aid}, folder {group['folder']!r}; rerun after refresh")
            time.sleep(delay)
            continue
        existing_episodes = api.available_episodes(series_id)
        for f in group["files"]:
            if limit is not None and accepted + errors >= limit:
                break
            fid, ep = int(f["file_id"]), f["episode"]
            if not ep or int(ep) not in existing_episodes or fid not in current:
                deferred += 1
                continue
            locations = current[fid].get("Locations") or []
            current_paths = {x.get("RelativePath") for x in locations}
            if f["path"] not in current_paths:
                print(f"SKIP file {fid}: path changed, refusing stale plan", file=sys.stderr)
                deferred += 1
                continue
            try:
                api.link(fid, series_id, int(ep))
                print(f"LINKED file={fid} series={series_id} episode={ep}")
                accepted += 1
            except RuntimeError as e:
                errors += 1
                print(f"ERROR {fid}: {e}", file=sys.stderr)
            time.sleep(delay)
    return {"submitted": accepted, "errors": errors, "awaiting_series_refresh": pending,
            "not_eligible_or_review": deferred}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("SHOKO_URL", "http://127.0.0.1:8111"))
    parser.add_argument("--plan", default="shoko-reconcile-plan.json")
    parser.add_argument("--overrides", help="JSON mapping full release folder -> approved AniDB anime ID")
    parser.add_argument("--apply", action="store_true", help="Write verified manual links via Shoko REST API")
    parser.add_argument("--status", action="store_true", help="Show verified API-side unrecognized fraction only")
    parser.add_argument("--confirm", help="Must equal LINK before --apply")
    parser.add_argument("--limit", type=int, default=None, help="Limit link write attempts")
    args = parser.parse_args(argv)
    key = os.getenv("SHOKO_API_KEY", "")
    if not key:
        parser.error("Set SHOKO_API_KEY to an admin API key; do not put it in command arguments")
    api = ShokoAPI(args.url, key)
    if args.status:
        total = len(list(api.pages("/File")))
        unknown = len(api.unrecognized())
        print(json.dumps({"total_files": total, "unrecognized": unknown,
                          "unknown_percent": round(100 * unknown / total, 2) if total else None,
                          "meets_5_percent_target": bool(total and unknown / total <= .05)}, indent=2))
    elif args.apply:
        if args.confirm != "LINK":
            parser.error("--apply requires --confirm LINK")
        with open(args.plan, encoding="utf-8") as f:
            plan = json.load(f)
        print(json.dumps(apply(api, plan, limit=args.limit), indent=2))
    else:
        overrides = {}
        if args.overrides:
            with open(args.overrides, encoding="utf-8") as f:
                overrides = json.load(f)
        plan = prepare(api, overrides)
        # The report includes local filenames: permissions should prevent disclosure.
        old_umask = os.umask(0o077)
        try:
            with open(args.plan, "w", encoding="utf-8") as f:
                json.dump(plan, f, indent=2, ensure_ascii=False)
        finally:
            os.umask(old_umask)
        prepared = sum(g["numbered"] for g in plan["groups"] if g["selected_anidb_id"])
        print(f"Unrecognized: {plan['total_unrecognized_at_scan']}; safely eligible: {prepared}; ")
        print(f"Release groups: {len(plan['groups'])}; report: {args.plan}")
        print("No changes made. Review group selections before running --apply.")


if __name__ == "__main__":
    main()
