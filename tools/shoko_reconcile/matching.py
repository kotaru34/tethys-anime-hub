"""Identity and episode inference from untrusted, inconsistent anime release names.

All functions in this module are side effect free. A folder association is NOT evidence that
its nested bonus clips are ordinary episodes. Never strip semantic sequel/OVA markers.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from pathlib import PurePosixPath
import re
import unicodedata

TECH = re.compile(r"(?ix)(?:\b(?:webrip|web[-_. ]?dl(?:rip)?|bd(?:rip)?|blu[-_. ]?ray|dvd(?:rip)?|hdtv(?:rip)?|\bcr\b|\bnf\b|x26[45]|h\.?26[45]|hevc|avc|av1|flac|aac|opus|ac3|dts|10[-_. ]?bit|hi10p|hdr|dv|dual[-_. ]?audio|multi[-_. ]?subs|\b(?:rus|jap|jpn|eng|ukr|ua)\b|(?:720|1080|2160|480)p|\d{3,4}x\d{3,4}|\d{4}kbps|\b(?:8|10)bit\b)\b)")
RELEASE = re.compile(r"(?i)^(?:anilibria(?:\.tv)?|aniliberty|anilibiria|anilibiria\.tv|reinforce|beatrice[- ]?raws|vcb[- ]?studio|neko[- ]?raws|kioto anime|amanogawa|judas|subsplease|erai[- ]?raws|rip time|fanvoxua)$")
GENERIC = {"raw", "raws", "anime", "release", "batch", "complete", "multi", "audio", "sub", "subs", "x265", "265", "10bit", "season", "series", "ep", "episode", "ova", "movie", "web", "bd", "tv", "dual", "jap", "eng", "rus", "ukr"}
ROMAN = {"i":1,"ii":2,"iii":3,"iv":4,"v":5,"vi":6,"vii":7,"viii":8,"ix":9,"x":10}
RE_SEASON = re.compile(r"(?ix)(?<![\w])(?:s(?:eason)?[\s._-]*0*([1-9]\d?)|([1-9]\d?)(?:st|nd|rd|th|nd|rd)?[\s._-]*season|tv[\s._-]*0*([1-9]\d?))(?!\w)")
RE_YEAR = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
RE_PART = re.compile(r"(?i)\bpart[\s._-]*([1-9]\d?)\b")
RE_ORD = re.compile(r"(?i)\b([1-9]\d?)(?:st|nd|rd|th)\b")
RE_ROMAN_END = re.compile(r"(?i)\b(I|II|III|IV|V|VI)\s*$")
RE_BRACKET = re.compile(r"\[([^\[\]]*)\]|\(([^()]*)\)|<([^<>]*)>")
RE_SXE = re.compile(r"(?i)(?<![a-z0-9])s\s*0*(\d{1,2})[\s._-]*e(?:p(?:isode)?)?[\s._-]*0*(\d{1,3})(?:\.(\d+))?(?!\d)")
RE_EP = re.compile(r"(?i)(?<![a-z0-9])(?:ep(?:isode)?)[\s._-]*0*(\d{1,3})(?:\.(\d+))?(?!\d)")
RE_BRACKET_EP = re.compile(r"(?i)(?:^|[\s._-])\[0*(\d{1,3})(?:\.(\d+))?\](?=$|[\s._-])")
RE_SEP_EP = re.compile(r"(?i)(?:\s+-\s+|_+)(\d{1,3})(?:\.(\d+))?(?=\s|_|\.|\[|\(|$)")
RE_TRAIL_EP = re.compile(r"(?:\s+|\.)0*([1-9]\d?)(?=\s*(?:\[|\(|$))")
RE_START_EP = re.compile(r"^0*([1-9]\d?)(?=\[|[_. -])")
RE_EXTRA_LABEL = re.compile(r"(?i)(?:^|[\s._-])(?:NCOP|NCED|OP|ED|PV)\s*\d{0,2}(?=\s*(?:\[|\(|$))")
RE_SPECIAL_N = re.compile(r"(?i)(?:specials?|ova|oad|ona|sp)[\s._-]*0*([1-9]\d?)(?!\d)")
RE_LEAD_QUALITY = re.compile(r"(?i)^(?:\s*(?:720|1080|2160)p\s+)+")
RE_EXTRA = re.compile(r"(?i)(?:^|[/_.\s-])(?:extras?|creditless|ncop|nced|nc|op\s*\d*|ed\s*\d*|preview|pv\s*\d*|trailer|teaser|bonus|menu|cm\s*\d*|promos?|opening|ending)(?:$|[/_.\s-])")
RE_SPECIAL = re.compile(r"(?i)(?:^|[/_.\s-])(?:specials?|ova|oad|ona|sp\s*\d*)(?:$|[/_.\s-])")
RE_MOVIE = re.compile(r"(?i)(?:^|[/_.\s-])(?:movie|film|eiga|gekijouban|фильм|фільм)(?:$|[/_.\s-])")


def unicode_norm(s: str) -> str:
    """Canonical case, scripts, punctuation. Keep significant ~ and * in strict identity."""
    return unicodedata.normalize("NFKC", str(s)).casefold().replace("ё", "е").replace("і", "i")


def strip_brackets(s: str) -> str:
    """Strip codec/channel/group blocks; preserve OVA/Season/year and semantic titles."""
    def repl(match):
        value = (match.group(1) or match.group(2) or match.group(3) or "").strip()
        if RE_SEASON.search(value) or re.fullmatch(r"(?i)(?:ova|oad|ona|special|movie|film|\d{4})", value):
            return f" {value} "
        if TECH.search(value) or RELEASE.fullmatch(value) or re.fullmatch(r"(?i)(?:tv[- ]?\d+|bd|cr|n?c|\d{3,4}p|\d{2,8}[a-f\d]{0,8})", value):
            return " "
        # Non-technical [] at beginning with following title is likely a release group.
        if match.start() == 0 and match.end() < len(s) and s[match.end():].strip():
            return " "
        return match.group(0)
    return RE_BRACKET.sub(repl, s)


def clean_release_title(folder: str) -> str:
    s = PurePosixPath(folder.replace("\\", "/")).name.strip()
    s = strip_brackets(s)
    s = re.sub(r"(?i)\s+-\s+(?:anilibria(?:\.tv)?|aniliberty|anilibiria(?:\.tv)?|amanogawa|fanvoxua|(?:\[.+?\]))\b.*$", "", s)
    s = re.sub(r"(?i)\s+-\s+(?:subsplease|erai[- ]?raws|nyaa|raws|fansub)\b.*$", "", s)
    # Remaining technical tail outside parentheses: codec tokens at the end only.
    s = re.sub(r"(?i)\s+(?:1080p|720p|2160p|hevc|x265|x264|flac|hdr)\b(?:[\s_.-]+(?:1080p|720p|2160p|hevc|x265|x264|flac|hdr))*\s*$", "", s)
    s = RE_LEAD_QUALITY.sub("", s)
    s = re.sub(r"(?i)\s+(?:anilibria(?:\.tv)?|aniliberty|amanogawa|fanvoxua)\s*$", "", s)
    s = re.sub(r"\s+", " ", s).strip(" ._-")
    return s


def season_hint(s: str) -> int | None:
    m = RE_SEASON.search(s)
    if m: return int(next(g for g in m.groups() if g))
    # Trailer number after title where series known as TV seasons: 'Oshi no Ko 3'.
    # Only infer if <=9 and not likely a literal number in the title.
    m = re.search(r"(?i)\b(?:osh[i]?\s+no\s+ko|yani\s+neko)\s+([1-9])\s*$", unicode_norm(s))
    return int(m.group(1)) if m else None


def year_hint(s: str) -> int | None:
    # Ignore years for filename episode numbers; use folder/series only.
    m=RE_YEAR.search(s)
    return int(m.group(1)) if m else None


def type_hint(s: str) -> str | None:
    if RE_MOVIE.search(s): return "Movie"
    if re.search(r"(?i)(?:^|[\s\[\(])(?:ova|oad)(?:$|[\s\]\)])", s): return "OVA"
    if re.search(r"(?i)(?:^|[\s\[\(])(?:ona)(?:$|[\s\]\)])", s): return "ONA"
    return None


def base_title(s: str) -> str:
    s=clean_release_title(s)
    s=re.sub(r"(?i)(?:\s+[\(\[]?\s*(?:season|s|tv)\s*0*[1-9]\d?\s*[\)\]]?|\s+[1-9]\d?(?:st|nd|rd|th)\s+season)\s*$", "", s)
    s=re.sub(r"(?i)\s+\(?part\s+[1-9]\d?\)?$", "", s)
    return s.strip()


def match_key(s: str, *, strict: bool=True) -> str:
    s=unicode_norm(s).replace("_", " ")
    s=RE_ORD.sub(lambda m:m.group(1),s)
    s=re.sub(r"(?i)\bwo\b", "o", s)
    s=re.sub(r"(?i)\bshitemo\b", "shite mo", s)
    s=re.sub(r"(?i)\bdeshouka\b", "deshou ka", s)
    # All symbols except * and ~ are punctuation, but * and ~ can encode a distinct anime.
    s=re.sub(r"[^\w~*]+", " ", s)
    s=" ".join(s.split())
    if not strict:
        s=s.replace("~", "").replace("*", "")
        return " ".join(s.split())
    return s


def similarity(a: str,b: str) -> float:
    x,y=match_key(a),match_key(b)
    if not x or not y:return 0.0
    if x==y:return 1.0
    sm=SequenceMatcher(None,x,y).ratio()
    compact=SequenceMatcher(None,x.replace(" ",""),y.replace(" ","")).ratio()
    xset,yset=set(x.split()),set(y.split())
    jac=len(xset & yset)/max(1,len(xset | yset))
    score=max(0.78*sm+0.22*jac, 0.88*compact)
    # Distinct franchise entries containing literal ~ or * must not collapse.
    if ("~" in x)!=("~" in y) or ("*" in x)!=("*" in y): score-=0.14
    return max(0.0,min(1.0,score))


@dataclass(frozen=True)
class EpisodeInfo:
    category: str  # Episode, Special, Movie, Extra, Unknown
    number: int | None
    season: int | None
    fraction: str | None = None
    reason: str = ""
    def json(self):return asdict(self)


def classify_episode(relative_path: str, *, group: str = "") -> EpisodeInfo:
    path=relative_path.replace("\\", "/")
    parts=PurePosixPath(path).parts
    stem=PurePosixPath(path).stem
    parents="/".join(parts[1:-1]) if len(parts)>=2 else ""
    # Extras must be identified before ep number extraction. Preview/Ep 01 is not episode 1.
    if RE_EXTRA.search(parents) or RE_EXTRA_LABEL.search(stem):
        return EpisodeInfo("Extra",None,None,reason="creditless/preview/promo/bonus")
    if "theater manner" in stem.casefold():
        return EpisodeInfo("Extra",None,None,reason="theater manners extra")
    season=None
    m=RE_SXE.search(stem)
    number=None; fraction=None
    if m:
        season=int(m.group(1));number=int(m.group(2));fraction=m.group(3)
    else:
        m=RE_EP.search(stem)
        if m: number=int(m.group(1));fraction=m.group(2)
        if m is None:
            for pattern in (RE_BRACKET_EP, RE_SEP_EP, RE_TRAIL_EP, RE_START_EP):
                candidate=list(pattern.finditer(stem))
                if candidate:
                    m=candidate[-1];number=int(m.group(1));fraction=m.group(2) if m.lastindex and m.lastindex>=2 else None
                    break
    if season is None:
        season=season_hint(stem) or season_hint(group)
    if number is None:
        extra_number = RE_SPECIAL_N.search(stem)
        if extra_number: number = int(extra_number.group(1))
    if re.search(r"(?i)\b(?:ep\s*00|s\d{2}ep\s*00|s\d{2}e00)\b",stem):
        return EpisodeInfo("Special",0,season,reason="episode 00")
    if RE_MOVIE.search(stem) or re.search(r"(?i)\[(?:movie|film)\]",stem) or (RE_MOVIE.search(group) and len(parts)<=2):
        return EpisodeInfo("Movie",1 if number is None else number,season,reason="movie title")
    if RE_SPECIAL.search(parents) or RE_SPECIAL.search(stem) or type_hint(group) in ("OVA","ONA"):
        return EpisodeInfo("Special",number,season,fraction,reason="special/OVA")
    if number==0:return EpisodeInfo("Special",0,season,reason="episode zero")
    if fraction:
        return EpisodeInfo("Special",number,season,fraction,reason="fractional/interstitial episode; requires confirmation")
    if number is not None and 1<=number<=999:
        return EpisodeInfo("Episode",number,season)
    # Movie filenames often contain neither an ep number nor the literal word movie.
    if type_hint(group)=="Movie":return EpisodeInfo("Movie",1,season,reason="movie directory")
    return EpisodeInfo("Unknown",None,season,reason="no unambiguous episode")


def main_title_candidates(folder: str, files: list[dict]) -> list[str]:
    """Release-level consensus. Include names stripped from filenames for bad folder titles."""
    title=clean_release_title(folder)
    choices=[title]
    stems=[]
    for f in files[:8]:
        rel=f.get("path") or f.get("RelativePath") or ""
        stem=PurePosixPath(rel).stem
        if RE_EXTRA.search(rel):continue
        stem=strip_brackets(stem)
        stem=RE_SXE.sub(" ",stem)
        stem=RE_EP.sub(" ",stem)
        stem=re.sub(r"(?i)\s*[-_. ]+\d{1,3}(?:\.\d+)?\s*(?:\[|\(|$).*", "", stem)
        stem=re.sub(r"(?i)\s*\[\d{1,3}\].*", "", stem)
        stem=re.sub(r"(?i)\s*\[.*", "", stem)
        stem=re.sub(r"(?i)\s*\(.*", "", stem)
        stem=stem.strip("-_. ")
        if stem and len(stem)>4: stems.append(stem)
    if stems:
        # Modal title, not random filename. Limit to avoid uncontrolled querying.
        from collections import Counter
        popular=Counter(match_key(x) for x in stems).most_common(2)
        for common,_ in popular:
            match=next(x for x in stems if match_key(x)==common)
            if match_key(match)!=match_key(title):choices.append(match)
    # Search stripped season name too: Shoko title dumps often name sequels by year.
    bt=base_title(title)
    if bt and match_key(bt)!=match_key(title):choices.append(bt)
    return list(dict.fromkeys(x for x in choices if x))[:4]


def rank_candidates(queries: list[str], candidates: list[dict], *, folder: str = "") -> list[dict]:
    """Combine all aliases and contextual evidence. Scores are ranks, not calibrated probabilities."""
    hint_s=season_hint(folder);hint_y=year_hint(folder);hint_t=type_hint(folder)
    best={}
    for c in candidates:
        aid=c.get("anidb_id") or c.get("ID")
        if not aid:continue
        title=c.get("title") or c.get("Title") or ""
        aliases=list(dict.fromkeys([title]+(c.get("aliases") or [])))
        if c.get("Titles"):
            for item in c["Titles"]:
                if isinstance(item,dict):aliases.extend(str(item.get(k,"")) for k in ("Name","Title","Value"))
                elif isinstance(item,str):aliases.append(item)
        raw_score=0.0;matched=""
        for q in queries:
            for alias in aliases:
                score=similarity(q,alias)
                if score>raw_score:
                    raw_score,matched=score,alias
        if raw_score<=0:continue
        type_=str(c.get("type") or c.get("Type") or "Unknown")
        candidate_s=season_hint(title)
        if candidate_s is None:
            for alias in aliases:
                candidate_s=season_hint(alias)
                if candidate_s:break
        candidate_y=c.get("year") or year_hint(title)
        # A known explicit season disagreement is a hard rejection.
        if hint_s and candidate_s and hint_s!=candidate_s:continue
        if hint_t=="Movie" and type_.casefold() not in ("unknown","movie","film"):continue
        if hint_t=="OVA" and type_.casefold() not in ("unknown","ova","special"):continue
        if hint_t=="ONA" and type_.casefold() not in ("unknown","ona","web"):continue
        adjusted=raw_score
        if hint_s and candidate_s==hint_s:adjusted+=0.03
        if hint_y and candidate_y:
            if int(hint_y)==int(candidate_y):adjusted+=0.025
            elif abs(int(hint_y)-int(candidate_y))>=2:adjusted-=0.14
        if hint_t and type_.casefold()==hint_t.casefold():adjusted+=0.025
        if hint_s and not candidate_s and c.get("year") is None:
            # The title may omit season, but a score of 1 cannot imply season correct.
            adjusted-=0.07
        # Prefer a clearly distinct exact alias, and do not let unrelated short hits dominate.
        val={"anidb_id":int(aid),"shoko_id":c.get("shoko_id") or c.get("ShokoID"),
             "title":title,"type":type_,"score":round(max(0,min(1,adjusted)),4),
             "title_score":round(raw_score,4),"matched_alias":matched,
             "year":candidate_y,"episodes":c.get("episodes"),"source":c.get("source","shoko")}
        if aid not in best or best[aid]["score"]<val["score"]:best[aid]=val
    return sorted(best.values(),key=lambda d:(-d["score"],-d["title_score"], d["anidb_id"]))[:10]


def choose_candidate(ranked: list[dict], *, folder: str, parsed: list[EpisodeInfo], min_score: float=0.87):
    """Return selection only with diverse, consistent evidence; otherwise review.

    Lower default than v1 exact-only, yet no guessed 90% accuracy certification.
    """
    if not ranked:return None,"review","no candidate"
    top=ranked[0];second=ranked[1] if len(ranked)>1 else None
    if top["score"]<min_score:return None,"review","low confidence"
    if second and top["score"]-second["score"]<0.055:
        return None,"review","ambiguous candidate margin"
    # A special with broad series title must not target the main TV anime by default.
    types={x.category for x in parsed if x.category!="Extra"}
    if "Movie" in types and (str(top["type"]).casefold() not in ("movie","unknown")):
        return None,"review","movie type mismatch"
    if "Special" in types and types=={"Special"} and str(top["type"]).casefold() not in ("ova","ona","special","unknown"):
        return None,"review","special/OVA type mismatch"
    if season_hint(folder) and top["score"]<0.91:
        return None,"review","season requires additional evidence"
    return int(top["anidb_id"]),"auto_evidence","title + context matched"
