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



def parenthetical_title_variants(folder: str) -> list[str]:
    """Extract independently usable aliases from a dual-language release title.

    'Original (English Translation) (Season 1)' supplies two full names.
    Ignore season labels, release metadata, nested codec blocks and dates.
    Do not guess that every parenthesized string is a title.
    """
    title = clean_release_title(folder)
    for m in re.finditer(r"\(([^()]*)\)", title):
        alternative = m.group(1).strip()
        before = title[:m.start()]
        # An inner '(by GROUP)' within '[AMZN (by GROUP)]' is not an alias.
        if before.rfind("[") > before.rfind("]"):
            continue
        if (len(alternative) < 10 or len(match_key(alternative).split()) < 2
                or TECH.search(alternative) or RE_SEASON.search(alternative)
                or RE_YEAR.search(alternative) or RE_PART.search(alternative)
                or re.match(r"(?i)^(?:by|group|source|release|video|audio|subs?|dub|codec)\b", alternative)):
            continue
        primary = before.strip(" ._-")
        if len(match_key(primary).split()) < 2:
            continue
        return [primary, alternative]
    return []


def season_hint(s: str) -> int | None:
    m = RE_SEASON.search(s)
    if m: return int(next(g for g in m.groups() if g))
    # AniDB sequels often use trailing Roman numerals (e.g. title II).
    m = re.search(r"(?i)(?:^|[\s:._-])(II|III|IV|V|VI|VII|VIII)\s*$", s)
    if m: return ROMAN[m.group(1).casefold()]
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
    if season_hint(s) and re.search(r"\s+[1-9]$",s):
        s=re.sub(r"\s+[1-9]$","",s)
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
        season=season_hint(stem) or season_hint(clean_release_title(group))
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
    choices=[title]+parenthetical_title_variants(folder)
    stems=[]
    for f in files[:8]:
        rel=f.get("path") or f.get("RelativePath") or ""
        stem=PurePosixPath(rel).stem
        if RE_EXTRA.search(rel):continue
        stem=strip_brackets(stem)
        stem=RE_SXE.sub(" ",stem)
        stem=RE_EP.sub(" ",stem)
        # S01E11v2 is episode 11, revision 2; v2 is not part of the anime name.
        stem=re.sub(r"(?i)(?:[\s._-]+)?v[1-9]\d?\s*$", "", stem)
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



def contextual_candidate_season(title: str, release: str) -> int | None:
    """Recognize numbered sequels only when the *whole* title stem agrees.

    Bare trailing numbers and 'Part N' are contextual: a number may be part
    of an unrelated anime title, so the release must provide an independently
    matching franchise stem. Do not assume a bare file name means S1.
    """
    explicit = season_hint(title)
    if explicit is not None:
        return explicit
    tail = re.search(r"(?i)(?:[\s:._-]+part[\s._-]*([2-9])|[\s:._-]+([2-9]))[!.\s]*$", title)
    if tail:
        n = int(tail.group(1) or tail.group(2))
        stem = title[:tail.start()].strip(" ._-:!")
        if similarity(base_title(release), stem) >= 0.82:
            return n
    return None


def group_season_evidence(folder: str, files: list[dict]) -> tuple[int | None, bool]:
    """Resolve a consistent season from folder AND per-file SXE markers.

    Reject contradictory/mixed evidence instead of silently mapping all files
    from one directory to a first-season AniDB work. Untagged files inherit
    an explicit folder season; bare folders do not imply season one.
    """
    folder_season = season_hint(clean_release_title(folder))
    found = {ep.season for f in files
             if (ep := classify_episode(f.get("path") or f.get("RelativePath") or "",
                                        group=folder)).category != "Extra"
             and ep.season is not None}
    if len(found) > 1 or (folder_season is not None and found and found != {folder_season}):
        return None, True
    return (next(iter(found)) if found else folder_season), False


def season_aware_queries(folder: str, files: list[dict], original: list[str]) -> list[str]:
    """Search the sequel as well as the bare release name, without title IDs."""
    season, conflict = group_season_evidence(folder, files)
    queries = list(original)
    if season and season > 1 and not conflict:
        root = base_title(folder)
        # Keep both an explicit season title and the original romaji spelling.
        extra = [f"{root} Season {season}", f"{root} {season}"]
        queries = extra + [q for q in queries if q not in extra]
    return list(dict.fromkeys(queries))[:6]


def target_season_supported(group: dict, row: dict) -> bool:
    """Independent fail-closed guard for applying an automatic series link.

    Strong title similarity and a valid episode number do NOT establish that
    an S02E01 file belongs to a first-season E01. Candidate season evidence
    must originate from matching (including catalog year chronology), or an
    explicit season in the candidate's title/aliases. Manually approved rows
    are outside this automatic policy.
    """
    if row.get("mode") in {"approved_file_override", "approved_override", "approved_release"}:
        return True
    path = row.get("path") or ""
    parsed = classify_episode(path, group=group.get("folder", ""))
    requested = parsed.season
    if requested is None:
        return True
    aid = row.get("target_anidb_id")
    if not aid:
        return True
    candidates = [c for c in group.get("candidates", [])
                  if int(c.get("anidb_id") or -1) == int(aid)]
    if not candidates:
        # Do not assume a user-supplied/old plan has trustworthy provenance.
        return False
    target = candidates[0]
    candidate_season = target.get("season")
    if candidate_season is None:
        candidate_season = contextual_candidate_season(str(target.get("title") or ""), group.get("folder", ""))
    if candidate_season is None:
        for alias in target.get("aliases") or []:
            candidate_season = contextual_candidate_season(str(alias), group.get("folder", ""))
            if candidate_season is not None:
                break
    # Prior v1 exact matches may use year-suffixed AniDB titles rather than
    # numbered seasons (e.g. the third release named "(2026)"). Preserve
    # that historical evidence only when it was an actual Shoko exact-title
    # anchor, and when the franchise stem agrees. Fresh fuzzy plans do not
    # qualify for this exception.
    if (candidate_season is None and row.get("mode") == "prior_exact_title"
            and group.get("prior_exact_evidence")
            and year_hint(str(target.get("title") or ""))):
        stem = re.sub(r"\s*\((?:19|20)\d{2}\)\s*$", "",
                      str(target.get("title") or ""))
        if similarity(base_title(group.get("folder", "")), stem) >= 0.82:
            return True
    # S01 with an exact base title is a permissible implicit S1 signal.
    if candidate_season is None and requested == 1:
        return True
    return candidate_season == requested


def rank_candidates(queries: list[str], candidates: list[dict], *, folder: str = "", season: int | None = None) -> list[dict]:
    """Combine all aliases and contextual evidence. Scores are ranks, not calibrated probabilities."""
    hint_s=season if season is not None else season_hint(clean_release_title(folder));hint_y=year_hint(folder);hint_t=type_hint(folder)
    # For titles named only by year on AniDB (e.g. Season 2 = (2022)), infer
    # the chronology from same-franchise candidates. Undated base title counts as S1.
    query_base=base_title(folder)
    companion_years=set()
    dated_ids=set()
    undated_base_ids=set()
    for c in candidates:
        t=str(c.get("title") or c.get("Title") or "")
        t_base=re.sub(r"\s*\((?:19|20)\d{2}\)\s*$","",t)
        if similarity(query_base,t_base)<0.87:continue
        aid = c.get("anidb_id") or c.get("ID")
        y=c.get("year") or year_hint(t)
        if y:
            companion_years.add(int(y))
            if aid: dated_ids.add(int(aid))
        elif match_key(t_base)==match_key(query_base) and aid:
            undated_base_ids.add(int(aid))
    # Shoko search may emit an undated copy of the SAME entry found with a
    # year in the alias catalog. It is not an extra S1: count unique AniDB IDs.
    seen_undated_base=bool(undated_base_ids - dated_ids)
    ordered_years=sorted(companion_years)
    year_season={y:i+1+(1 if seen_undated_base else 0) for i,y in enumerate(ordered_years)}
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
        candidate_s=contextual_candidate_season(title, folder)
        if candidate_s is None:
            for alias in aliases:
                candidate_s=contextual_candidate_season(alias, folder)
                if candidate_s:break
        candidate_y=c.get("year") or year_hint(title)
        if hint_s and not candidate_s:
            stripped_year=re.sub(r"\s*\((?:19|20)\d{2}\)\s*$","",title)
            if candidate_y and similarity(query_base,stripped_year)>=0.87:
                candidate_s=year_season.get(int(candidate_y))
            elif not candidate_y and match_key(stripped_year)==match_key(query_base):
                candidate_s=1
        # Release-pack S01 / Season 1 is often an *uploader's* label,
        # while AniDB's first work has no explicit 'season' field. Accept
        # a first-season inference only from an EXACT full-title/alias match,
        # with no conflicting known year. This avoids penalizing an exact
        # S01 match to 0.82 while never promoting unknown S02 sequels.
        if hint_s == 1 and candidate_s is None:
            exact_full_title = any(
                match_key(q) == match_key(alias)
                for q in queries for alias in aliases if alias
            )
            if exact_full_title and (
                not candidate_y or (
                    hint_y is not None and int(hint_y) == int(candidate_y)
                )
            ):
                candidate_s = 1
        # A known explicit season disagreement is a hard rejection.
        if hint_s and candidate_s and hint_s!=candidate_s:continue
        if hint_s and hint_s > 1 and candidate_s is None:continue
        if hint_t=="Movie" and type_.casefold() not in ("unknown","movie","film"):continue
        if hint_t=="OVA" and type_.casefold() not in ("unknown","ova","special"):continue
        if hint_t=="ONA" and type_.casefold() not in ("unknown","ona","web"):continue
        adjusted=raw_score
        if hint_s and candidate_s==hint_s:adjusted+=0.115
        if hint_y and candidate_y:
            if int(hint_y)==int(candidate_y):adjusted+=0.025
            elif abs(int(hint_y)-int(candidate_y))>=2:adjusted-=0.14
        if hint_t and type_.casefold()==hint_t.casefold():adjusted+=0.025
        if hint_s and not candidate_s:
            # Strong guard: an exact franchise root is NOT evidence of sequel identity.
            adjusted-=0.18
        # Prefer a clearly distinct exact alias, and do not let unrelated short hits dominate.
        val={"anidb_id":int(aid),"shoko_id":c.get("shoko_id") or c.get("ShokoID"),
             "title":title,"type":type_,"score":round(max(0,min(1,adjusted)),4),
             "title_score":round(raw_score,4),"matched_alias":matched,
             "year":candidate_y,"episodes":c.get("episodes"),"season":candidate_s,
             "source":c.get("source","shoko")}
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
    # When the release explicitly says OVA/ONA, a generic TV record with unknown
    # type is not sufficient. Preserve it for an external typed catalog lookup.
    if type_hint(folder) in ("OVA","ONA") and str(top["type"]).casefold() not in ("ova","ona","special"):
        return None,"review","OVA/ONA requires a verified matching media type"
    # Multi-cour numbering needs a verified part-2 AniDB work plus episode offset.
    # Otherwise 14..25 could be silently mapped to the wrong season's episode IDs.
    if RE_PART.search(folder) and not ("part 2" in top["title"].casefold() or "dai 2 bu" in top["title"].casefold()):
        return None,"review","part/cour boundary requires independent identification"
    if (season_hint(clean_release_title(folder)) or any(p.season and p.season > 1 for p in parsed)) and top["score"]<0.91:
        return None,"review","season requires additional evidence"
    return int(top["anidb_id"]),"auto_evidence","title + context matched"
