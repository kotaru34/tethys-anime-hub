#!/usr/bin/env python3
"""Apply private, curated Shoko v3 Manual Links without editing media.

Dry-run by default. JSON mappings stay on the user's server, not in Git.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from shoko_reconcile import ShokoAPI, _series_id_from_api, _write_private_json

VALID_TYPES = {'Episode', 'Special', 'Trailer', 'Credits', 'Parody', 'Other', 'Movie'}


def load_mapping(filename):
    with open(filename, encoding='utf-8') as fh:
        config = json.load(fh)
    if not isinstance(config, dict) or not isinstance(config.get('mappings'), list):
        raise ValueError('Expected JSON object with a mappings array')
    rows, seen = [], set()
    for row in config['mappings']:
        fid = int(row['file_id'])
        aid = int(row['anidb_id'])
        ep = int(row['episode'])
        kind = str(row['type'])
        hint = str(row['path_hint'])
        if fid in seen or min(fid, aid, ep) < 1 or kind not in VALID_TYPES or len(hint) < 5:
            raise ValueError(f'Invalid or duplicate mapping for file {fid}')
        for key in ('expected_series_title_regex', 'expected_episode_title_regex'):
            if row.get(key):
                re.compile(str(row[key]))
        seen.add(fid)
        rows.append({
            'file_id': fid, 'anidb_id': aid, 'episode': ep, 'type': kind,
            'path_hint': hint, 'rationale': str(row.get('rationale', '')),
            'requires_preview_opt_in': bool(row.get('requires_preview_opt_in', False)),
            'expected_series_title_regex': str(row.get('expected_series_title_regex') or ''),
            'expected_episode_title_regex': str(row.get('expected_episode_title_regex') or ''),
        })
    return rows


def run(api, rows, *, include_previews=False, refresh=False, apply=False,
        journal='/root/shoko-curated-audit.json'):
    current = {int(f['ID']): f for f in api.unrecognized()}
    eligible = [r for r in rows if r['file_id'] in current and
                (include_previews or not r['requires_preview_opt_in'])]
    aids = sorted({r['anidb_id'] for r in eligible})
    series, episodes, series_titles, episode_titles = {}, {}, {}, {}
    for aid in aids:
        data = api.local_series(aid)
        sid = _series_id_from_api(data)
        if sid:
            actual = (data.get('IDs') or {}).get('AniDB')
            if actual is None or int(actual) != aid:
                raise RuntimeError(f'Shoko returned unexpected AniDB ID for {aid}')
            episodes[sid] = api.available_episodes(sid)
            series_titles[sid] = str(data.get('Name') or '')
            if any(r['anidb_id'] == aid and r['expected_episode_title_regex'] for r in eligible):
                for e in api.pages(f'/Series/{sid}/Episode', {
                    'includeDataFrom': 'AniDB', 'includeMissing': 'True',
                    'includeUnaired': 'True', 'includeHidden': 'True',
                }):
                    info = e.get('AniDB') or {}
                    kind, number = str(info.get('Type', '')), info.get('EpisodeNumber')
                    if isinstance(number, int):
                        episode_titles[(sid, kind, number)] = str(info.get('Title') or '')
        elif refresh:
            api.refresh_series(aid)
            print(f'REFRESH_REQUESTED AniDB={aid}', flush=True)
        series[aid] = sid

    attempts = []
    if apply and Path(journal).exists():
        try:
            old = json.loads(Path(journal).read_text(encoding='utf-8'))
            attempts = list(old['attempts']) if isinstance(old.get('attempts'), list) else []
        except (ValueError, KeyError, TypeError):
            raise RuntimeError('Existing audit is unreadable; use a different --journal path')

    summary = {'ready': 0, 'submitted': 0, 'errors': 0, 'needs_refresh': 0,
               'missing_episode': 0, 'skipped': 0}
    for row in rows:
        fid, aid = row['file_id'], row['anidb_id']
        if row['requires_preview_opt_in'] and not include_previews:
            summary['skipped'] += 1
            continue
        if fid not in current:
            summary['skipped'] += 1
            continue
        paths = [loc.get('RelativePath', '') for loc in current[fid].get('Locations') or []]
        if not any(row['path_hint'].casefold() in path.casefold() for path in paths):
            summary['skipped'] += 1
            print(f'SKIP_STALE_PATH file={fid}', file=sys.stderr)
            continue
        sid = series.get(aid)
        kind = 'Episode' if row['type'] == 'Movie' else row['type']
        if not sid:
            state = 'NEEDS_SERIES_REFRESH'
            summary['needs_refresh'] += 1
        elif (kind, row['episode']) not in episodes[sid]:
            state = 'EPISODE_NOT_FOUND'
            summary['missing_episode'] += 1
        elif row['expected_series_title_regex'] and not re.search(
            row['expected_series_title_regex'], series_titles.get(sid, ''), re.IGNORECASE
        ):
            state = 'SERIES_TITLE_MISMATCH'
            summary['missing_episode'] += 1
        elif row['expected_episode_title_regex'] and not re.search(
            row['expected_episode_title_regex'],
            episode_titles.get((sid, kind, row['episode']), ''), re.IGNORECASE
        ):
            state = 'EPISODE_TITLE_MISMATCH'
            summary['missing_episode'] += 1
        else:
            state = 'READY'
            summary['ready'] += 1
        print(f'{state:>21} file={fid:4} AniDB={aid:5} '
              f'Shoko={sid} {kind}={row["episode"]} {row["rationale"]}'
              + (f' [Shoko title: {series_titles.get(sid)}]'
                 if sid and state.endswith('MISMATCH') else ''))
        if state != 'READY' or not apply:
            continue
        try:
            api.link(fid, sid, row['episode'], row['type'])
            summary['submitted'] += 1
            attempts.append({**row, 'shoko_series_id': sid, 'result': 'submitted'})
            print(f'  SUBMITTED file={fid}', flush=True)
        except Exception as exc:
            summary['errors'] += 1
            attempts.append({**row, 'result': 'error', 'message': str(exc)[:400]})
            print(f'  ERROR file={fid}: {exc}', file=sys.stderr)
        _write_private_json(journal, {'version': 1, 'attempts': attempts})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping', required=True, help='Private JSON with mappings list')
    parser.add_argument('--url', default=os.getenv('SHOKO_URL', 'http://127.0.0.1:8111'))
    parser.add_argument('--refresh-missing', action='store_true',
                        help='Request missing AniDB series metadata in Shoko')
    parser.add_argument('--apply', action='store_true', help='Submit Manual Links')
    parser.add_argument('--confirm', help='Must equal LINK for --apply')
    parser.add_argument('--include-previews', action='store_true',
                        help='Opt into uncertain PV-to-Trailer mappings')
    parser.add_argument('--journal', default='/root/shoko-curated-audit.json')
    args = parser.parse_args()
    if args.apply and args.confirm != 'LINK':
        parser.error('--apply requires --confirm LINK')
    key = os.getenv('SHOKO_API_KEY')
    if not key:
        parser.error('SHOKO_API_KEY is not set')
    result = run(ShokoAPI(args.url, key), load_mapping(args.mapping),
                 include_previews=args.include_previews, refresh=args.refresh_missing,
                 apply=args.apply, journal=args.journal)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
