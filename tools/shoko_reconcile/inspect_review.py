#!/usr/bin/env python3
"""Read-only explanation of Shoko AUTO-LINK's private review-plan safety gates.

Run ON the Shoko container after the worker has completed a plan:
  python3 inspect_review.py
  python3 inspect_review.py --all --max-candidates 5

This only opens the locally saved review JSON. It never connects to Shoko,
modifies media/torrents, or attempts speculative manual links.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from auto_fallback import auto_link_rejection_reason


def report(plan: dict, *, max_groups=20, max_candidates=3, include_safe=False):
    lines = []
    groups = []
    for g in plan.get("groups") or []:
        rejected = [(r, auto_link_rejection_reason(g, r)) for r in g.get("files") or []]
        rejected = [(r, gate) for r, gate in rejected if gate is not None or include_safe]
        if rejected:
            groups.append((len(rejected), g, rejected))
    groups.sort(key=lambda item: (-item[0], item[1].get("folder") or ""))
    all_gates = Counter(
        gate for _, _, rows in groups for _, gate in rows if gate is not None
    )
    lines.append(f"Plan unknown files: {sum(len(g.get('files') or []) for g in plan.get('groups') or [])}")
    lines.append(f"Rejected by live AUTO-LINK safety policy: {sum(all_gates.values())}")
    lines.append(f"Gate breakdown: {dict(all_gates.most_common())}")
    lines.append("Candidate scores are ranking signals, NOT verified accuracy.")
    for count, group, rows in groups[:max_groups]:
        gates = Counter(gate or "APPROVED" for _, gate in rows)
        modes = Counter(str(row.get("mode") or "unclassified") for row, _ in rows)
        lines.append("")
        lines.append(f"[{count} files] {group.get('folder')}")
        lines.append(f"  proposed modes: {dict(modes)}")
        lines.append(f"  actual blocked gates: {dict(gates)}")
        lines.append(f"  title selection: {group.get('reason')}")
        candidates = group.get("candidates") or []
        for c in candidates[:max_candidates]:
            lines.append(
                f"  candidate AniDB={c.get('anidb_id')} score={c.get('score')}"
                f" season={c.get('season')} type={c.get('type')}"
                f" title={c.get('title')}"
            )
        if not candidates:
            lines.append("  candidates: none")
        for row, gate in rows[:2]:
            lines.append(
                f"  file={row.get('file_id')} target={row.get('target_anidb_id')}"
                f" type={row.get('episode_type')} episode={row.get('episode')}"
                f" source_episode={row.get('source_episode')}"
                f" gate={gate or 'APPROVED'} path={row.get('path')}"
            )
    if len(groups) > max_groups:
        lines.append(f"\n... {len(groups) - max_groups} additional groups")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", default="/var/lib/shoko-reconcile/realtime-plan.review.json")
    parser.add_argument("--max-groups", type=int, default=20)
    parser.add_argument("--max-candidates", type=int, default=3)
    parser.add_argument("--all", action="store_true",
                        help="Include rows already approved by the safety policy")
    args = parser.parse_args()
    if args.max_groups < 1 or args.max_candidates < 1:
        parser.error("limits must be positive")
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    if plan.get("version") != 2 or not isinstance(plan.get("groups"), list):
        parser.error("expected a version-2 reconciler review plan")
    print(report(plan, max_groups=args.max_groups,
                 max_candidates=args.max_candidates, include_safe=args.all))


if __name__ == "__main__":
    main()
