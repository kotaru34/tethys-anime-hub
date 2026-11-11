"""Optional locally cached Anime Offline Database crosswalk and aliases.

ODbL/DbCL dataset by cedya77 and manami-project. Fetch explicitly, never in a tight loop:
https://github.com/cedya77/anime-offline-database/releases/download/latest/anime-offline-database.jsonl
"""
from __future__ import annotations
from collections import Counter, defaultdict
from pathlib import Path
import json
import re
from urllib.parse import urlparse
from matching import match_key, similarity, GENERIC

ANIDB_RE=re.compile(r"(?:^|/)anime/(\d+)(?:$|[?#/])")


def anidb_id(sources):
    for url in sources:
        try:
            parsed=urlparse(url)
            if parsed.netloc.lower() not in ("anidb.net","www.anidb.net"):continue
            m=ANIDB_RE.search(parsed.path)
            if m:return int(m.group(1))
        except (TypeError,ValueError):pass
    return None


class AliasCatalog:
    def __init__(self, path: str | Path):
        self.records={};self.index=defaultdict(set);self.exact=defaultdict(set)
        path=Path(path)
        with path.open(encoding="utf-8") as fh:
            first=fh.read(1);fh.seek(0)
            if first=="[":
                entries=json.load(fh)
                if not isinstance(entries,list):raise ValueError("Expected array")
            elif first=="{":
                # legacy wrapped minified database is large; JSONL preferable.
                probe=fh.readline()
                if '"data"' in probe and probe.count("\n")==0 and len(probe)>100000:
                    entries=json.loads(probe).get("data",[])
                else:
                    fh.seek(0);entries=(json.loads(line) for line in fh if line.strip())
            else:entries=(json.loads(line) for line in fh if line.strip())
            for item in entries:
                if not isinstance(item,dict) or "sources" not in item:continue
                aid=anidb_id(item.get("sources") or [])
                if not aid:continue
                aliases=[item.get("title","")]+list(item.get("synonyms") or [])
                aliases=[str(a) for a in aliases if isinstance(a,str) and len(a)>1]
                y=(item.get("animeSeason") or {}).get("year") if isinstance(item.get("animeSeason"),dict) else None
                record={"anidb_id":aid,"title":str(item.get("title", "")),
                        "aliases":aliases,"year":y,"episodes":item.get("episodes"),
                        "type":item.get("type","Unknown"),"source":"anime-offline-database"}
                self.records[aid]=record
                for alias in aliases:
                    key=match_key(alias)
                    if not key:continue
                    self.exact[key].add(aid)
                    for token in key.split():
                        if len(token)>2 and token not in GENERIC:
                            self.index[token].add(aid)

    def lookup(self, query: str, limit=30) -> list[dict]:
        key=match_key(query)
        if not key:return []
        matched=set(self.exact.get(key,[]))
        tokens=[t for t in key.split() if len(t)>2 and t not in GENERIC]
        counts=Counter()
        for token in tokens:
            for aid in self.index.get(token,()): counts[aid]+=1
        # Avoid generic partial-token collisions; inspect up to ~150 records.
        for aid,_ in counts.most_common(160):matched.add(aid)
        candidates=[]
        for aid in matched:
            record=self.records[aid]
            score=max((similarity(query,alias) for alias in record["aliases"]),default=0)
            if score>=0.40:candidates.append((score,record))
        return [r for _,r in sorted(candidates,key=lambda x:-x[0])[:limit]]

    def by_id(self, aid: int):return self.records.get(int(aid))
