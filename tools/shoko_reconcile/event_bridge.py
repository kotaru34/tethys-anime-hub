#!/usr/bin/env python3
"""Event-driven Shoko 5.3.3 Reconciler using the native SignalR aggregate hub.

Subscribe to Shoko file detected/hashed/unmatched events, not image-related
queue state events. A count-only watchdog catches missed file notifications. qBittorrent partial suffixes determine download readiness;
per-target series/episode metadata checks never wait for image downloads.
Use --apply only after confirming the dry-run behavior on your host.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit

from auto_fallback import run as reconcile
from catalog import AliasCatalog
from shoko_reconcile import ShokoAPI

RECORD_SEPARATOR = "\x1e"
HANDSHAKE = '{"protocol":"json","version":1}' + RECORD_SEPARATOR


def events_in(message):
    """Read JSON SignalR protocol records. Ignore handshake and ping frames."""
    for part in message.split(RECORD_SEPARATOR):
        if not part:
            continue
        value = json.loads(part)
        if value.get("type") == 1:
            yield value.get("target"), value.get("arguments") or []


def websocket_url(shoko_url):
    parts = urlsplit(shoko_url)
    if parts.scheme != "http" or parts.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("SignalR collector must connect to locally running Shoko over loopback")
    host = parts.netloc
    return f"ws://{host}/signalr/aggregate?feeds=shoko"


def retry_delay_for(result, *, metadata_retry_seconds=60):
    """Only series metadata/API errors warrant background retries.

    Incomplete .qb! files never enter the workset. There is no filesystem
    age gate, download polling, or maturity recheck timer.
    """
    if (result.get("awaiting_series_refresh", 0)
            or result.get("awaiting_tv_metadata", 0)
            or result.get("errors", 0)):
        return metadata_retry_seconds
    return None


class Coordinator:
    def __init__(self, api, *, catalog=None, do_apply=False,
                 state_path="/var/lib/shoko-reconcile/seen.json",
                 plan_path="/var/lib/shoko-reconcile/realtime-plan.json"):
        self.api = api
        self.catalog = catalog
        self.do_apply = do_apply
        self.state_path = state_path
        self.plan_path = plan_path
        # Throttle metadata refresh requests across attempts to prevent
        # duplicate refresh/image jobs while waiting for the *specific* AniDB
        # series to become available.
        self.refresh_requests = {}
        self.tv_pending_aids = set()
        self.tv_watch_polls = 0
        self.pending = threading.Event()
        self.last_unknown_count = None
        self.worker = threading.Thread(target=self.process, name="shoko-fallback", daemon=True)
        self.worker.start()

    def received(self, target, arguments):
        # Shoko 5.3.3 ShokoEventEmitter sends FileDetected and FileHashed
        # independently of FileNotMatched. Some new files never produce a
        # FileNotMatched event, especially across import/restart boundaries.
        # Trigger one coalesced scan for the completed import, not one per file.
        if target in ("Shoko:FileNotMatched", "Shoko:FileHashed",
                      "Shoko:FileDetected"):
            self.pending.set()
        # Deliberately ignore Queue:QueueStateChanged: most traffic is artwork.

    def unknown_count(self):
        """One Shoko API page, not a filesystem/library scan."""
        data = self.api.request("GET", "/File", {
            "include_only": "Unrecognized", "pageSize": 1, "page": 1
        })
        if not isinstance(data, dict) or not isinstance(data.get("Total"), int):
            raise RuntimeError("Shoko /File unrecognized total missing")
        return data["Total"]

    def reconcile(self, do_apply):
        result = reconcile(
            self.api, state_path=self.state_path, plan_path=self.plan_path,
            catalog=self.catalog, do_apply=do_apply,
            refresh_requests=self.refresh_requests)
        self.last_unknown_count = result.get("currently_unrecognized")
        self.tv_pending_aids = set(result.get("pending_tv_metadata_aids") or [])
        self.tv_watch_polls = 0
        print(json.dumps(result, sort_keys=True), flush=True)
        return result

    def retry_pending_metadata(self):
        """Reapply only last safe plan; avoid repeating expensive title search.

        apply() rechecks the current unrecognized-file list and per-file
        paths/episode metadata, so stale rows are safely deferred.
        """
        from shoko_reconcile import apply
        if not self.do_apply or not Path(self.plan_path).is_file():
            return {"submitted": 0, "errors": 0, "awaiting_series_refresh": 0,
                    "deferred": 0}
        plan = json.loads(Path(self.plan_path).read_text(encoding="utf8"))
        result = apply(self.api, plan,
                       journal=str(Path(self.plan_path).with_suffix(".journal.json")),
                       refresh_requests=self.refresh_requests)
        print(json.dumps({**{k: v for k, v in result.items() if k != "audit"},
                          "metadata_retry": True}, sort_keys=True), flush=True)
        return result

    def poll_target_tv_metadata(self):
        """Cheap AniDB-only probe; schedule a full scan only once metadata exists.

        Shoko's global artwork queue may continue indefinitely. Only the
        specific AniDB series IDs identified by fail-closed full-title proof
        are probed, and only until metadata becomes available or 15 probes
        have passed (after which a new import event can resume discovery).
        """
        if not self.tv_pending_aids:
            return False
        self.tv_watch_polls += 1
        for aid in sorted(self.tv_pending_aids):
            series = self.api.local_series(aid)
            ids = (series or {}).get("IDs") or {}
            if int(ids.get("AniDB") or -1) != int(aid) or not ids.get("ID"):
                continue
            if self.api.available_episodes(int(ids["ID"])):
                print(f"Target AniDB metadata ready: {aid}; rechecking complete TV proof",
                      flush=True)
                return True
        if self.tv_watch_polls >= 15:
            print("Target AniDB metadata did not arrive after 15 lightweight "
                  "checks; pausing until new Shoko import event", flush=True)
            self.tv_pending_aids.clear()
        return False

    def process(self):
        retry_delay = None
        retry_kind = None
        while True:
            # A single cheap Shoko /File count probe every 60 seconds
            # recovers missed SignalR events; it is NOT media-file polling.
            signaled = self.pending.wait(timeout=retry_delay if retry_delay is not None else 60)
            self.pending.clear()
            try:
                if not signaled and retry_kind == "tv_metadata":
                    if self.poll_target_tv_metadata():
                        # Re-run discovery: a complete-work proof wasn't yet
                        # in the old safe plan, so apply(old_plan) cannot link.
                        self.pending.set()
                        retry_delay = None
                        retry_kind = None
                    elif not self.tv_pending_aids:
                        retry_delay = None
                        retry_kind = None
                    else:
                        retry_delay = 60
                    continue
                if not signaled and retry_kind == "metadata":
                    result = self.retry_pending_metadata()
                    retry_delay = retry_delay_for(result)
                    if retry_delay is not None:
                        retry_kind = "metadata"
                    else:
                        self.pending.set()
                        retry_kind = None
                    continue
                if not signaled and retry_kind != "error":
                    unknown = self.unknown_count()
                    previous = self.last_unknown_count
                    self.last_unknown_count = unknown
                    if previous is not None and unknown <= previous:
                        continue
                    print(f"Shoko unknown count increased: {previous} -> {unknown}; "
                          "reconciling missed import event", flush=True)
                if signaled:
                    # Coalesce a batch of file-detected/hashed signals. They
                    # come in bursts during the same completed-torrent scan.
                    time.sleep(5)
                    self.pending.clear()
                result = self.reconcile(self.do_apply)
                retry_delay = retry_delay_for(result)
                retry_kind = (
                    "metadata" if result.get("awaiting_series_refresh", 0)
                    or result.get("errors", 0)
                    else "tv_metadata" if result.get("awaiting_tv_metadata", 0)
                    else None)
                if retry_delay is not None:
                    print(f"Metadata recheck in up to {retry_delay}s "
                          "(no global queue wait)", flush=True)
            except Exception as exc:
                retry_delay = 30
                retry_kind = "error"
                print(f"Reconciliation event failed: {type(exc).__name__}: {exc}; "
                      f"retry in up to {retry_delay}s", flush=True)


def resolve_apply_mode(cli_apply=False, cli_confirm="", service_setting=""):
    """Explicit opt-in only: CLI --apply --confirm LINK or systemd LINK flag."""
    if cli_apply and cli_confirm != "LINK":
        raise ValueError("--apply requires --confirm LINK")
    if service_setting not in ("", "LINK"):
        raise ValueError("SHOKO_RECONCILE_APPLY must be unset or exactly LINK")
    return bool(cli_apply or service_setting == "LINK")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("SHOKO_URL", "http://127.0.0.1:8111"))
    parser.add_argument("--catalog", default="/var/cache/tethys/anime-offline-database.jsonl")
    parser.add_argument("--state", default="/var/lib/shoko-reconcile/seen.json")
    parser.add_argument("--plan", default="/var/lib/shoko-reconcile/realtime-plan.json")
    parser.add_argument("--minimum-age", type=int, default=None,
                        help="Legacy compatibility; ignored (qBittorrent handles completion)")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args(argv)
    try:
        do_apply = resolve_apply_mode(
            args.apply, args.confirm, os.getenv("SHOKO_RECONCILE_APPLY", ""))
    except ValueError as exc:
        parser.error(str(exc))
    print(f"Shoko reconciler mode: {'AUTO-LINK' if do_apply else 'DRY-RUN'}", flush=True)
    key = os.getenv("SHOKO_API_KEY")
    if not key:
        parser.error("SHOKO_API_KEY missing")
    api = ShokoAPI(args.url, key)
    catalog = AliasCatalog(args.catalog) if args.catalog and Path(args.catalog).is_file() else None
    coordinator = Coordinator(
        api, catalog=catalog,
        state_path=args.state, plan_path=args.plan, do_apply=do_apply)

    try:
        from websocket import create_connection, WebSocketException
    except ImportError as exc:
        raise SystemExit("Install websocket-client into the service virtualenv") from exc

    url = websocket_url(args.url)
    while True:
        try:
            ws = create_connection(url, header={"apikey": key}, timeout=60)
            try:
                ws.send(HANDSHAKE)
                # Startup/reconnect reconciliation catches events lost while offline.
                coordinator.pending.set()
                # No /Queue read is necessary for linking. A new connection
                # must survive a Shoko startup period with API 503 responses.
                while True:
                    msg = ws.recv()
                    if not msg:
                        raise ConnectionError("SignalR websocket disconnected")
                    for target, data in events_in(msg):
                        coordinator.received(target, data)
            finally:
                ws.close()
        except (OSError, ValueError, ConnectionError, RuntimeError, WebSocketException) as exc:
            print(f"SignalR disconnected: {type(exc).__name__}: {exc}", flush=True)
        # Reconnect backoff, not a scheduled scan.
        time.sleep(5)


if __name__ == "__main__":
    main()
