#!/usr/bin/env python3
"""Event-driven Shoko 5.3.3 Reconciler using the native SignalR aggregate hub.

Shoko sends Shoko:FileNotMatched for misses and Queue:QueueStateChanged
for scheduler activity. Subscribes to both; linking checks file stability
and individual series/episode readiness without waiting for unrelated Shoko
queue jobs such as poster and character-image downloads.
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


def queue_idle(state):
    """SignalR queue state is idle only when there are no active/pending jobs."""
    if not isinstance(state, dict):
        return False
    return (bool(state.get("Running", True))
            and int(state.get("TotalCount") or 0) == 0
            and int(state.get("WaitingCount") or 0) == 0
            and int(state.get("BlockedCount") or 0) == 0
            and not state.get("CurrentlyExecuting"))


def websocket_url(shoko_url):
    parts = urlsplit(shoko_url)
    if parts.scheme != "http" or parts.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("SignalR collector must connect to locally running Shoko over loopback")
    host = parts.netloc
    return f"ws://{host}/signalr/aggregate?feeds=shoko,queue"


def retry_delay_for(result, *, metadata_retry_seconds=60):
    """Only series metadata/API errors warrant background retries.

    Incomplete .qb! files never enter the workset, and delayed/stabilizing
    media are not repeatedly polled by the service. A single deferred
    eligibility check may be scheduled per incoming unmatched-file event.
    """
    if result.get("awaiting_series_refresh", 0) or result.get("errors", 0):
        return metadata_retry_seconds
    return None


class Coordinator:
    def __init__(self, api, *, catalog=None, minimum_age=120, do_apply=False,
                 state_path="/var/lib/shoko-reconcile/seen.json",
                 plan_path="/var/lib/shoko-reconcile/realtime-plan.json"):
        self.api = api
        self.catalog = catalog
        self.minimum_age = minimum_age
        self.do_apply = do_apply
        self.state_path = state_path
        self.plan_path = plan_path
        # Throttle metadata refresh requests across attempts to prevent
        # duplicate refresh/image jobs while waiting for the *specific* AniDB
        # series to become available.
        self.refresh_requests = {}
        self.pending = threading.Event()
        self.worker = threading.Thread(target=self.process, name="shoko-fallback", daemon=True)
        self.worker.start()

    def received(self, target, arguments):
        if target == "Shoko:FileNotMatched":
            print("Shoko reports unmatched file; queue reconciliation", flush=True)
            self.pending.set()
        # Queue:QueueStateChanged is deliberately NOT a trigger: poster/
        # character-image jobs can toggle queue busy/idle hundreds of times,
        # causing repeated expensive full-library candidate searches. Shoko
        # unmatched-file events, startup/reconnect, and targeted metadata
        # retries are sufficient for this service.

    def reconcile(self, do_apply):
        result = reconcile(
            self.api, state_path=self.state_path, plan_path=self.plan_path,
            catalog=self.catalog, minimum_age=self.minimum_age,
            do_apply=do_apply, refresh_requests=self.refresh_requests)
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

    def process(self):
        retry_delay = None
        retry_kind = None
        maturity_recheck_used = False
        while True:
            signaled = self.pending.wait(timeout=retry_delay)
            self.pending.clear()
            if signaled:
                # A new completed-file event may warrant exactly one
                # post-grace eligibility check, never periodic download
                # polling or busy-to-idle image-queue triggers.
                maturity_recheck_used = False
                retry_kind = None
            try:
                if not signaled and retry_kind == "metadata":
                    result = self.retry_pending_metadata()
                    retry_delay = retry_delay_for(result)
                    if retry_delay is not None:
                        retry_kind = "metadata"
                    else:
                        # The series metadata are now available. Run one new
                        # reconciliation for a complete updated status; this
                        # is NOT triggered by the global Shoko image queue.
                        self.pending.set()
                        retry_kind = None
                    continue

                result = self.reconcile(self.do_apply)
                retry_delay = retry_delay_for(result)
                if retry_delay is not None:
                    retry_kind = "metadata"
                elif (not maturity_recheck_used
                      and result.get("currently_unrecognized", 0)
                      > result.get("mature_stable_unknown", 0)):
                    retry_delay = self.minimum_age + 2
                    retry_kind = "maturity_once"
                    maturity_recheck_used = True
                else:
                    retry_delay = None
                    retry_kind = None
                if retry_delay is not None:
                    print(f"Remaining eligible work recheck in up to {retry_delay}s "
                          f"({retry_kind}; no Shoko global queue wait)", flush=True)
            except Exception as exc:
                # Shoko may be restarting (HTTP 503); bounded API retry.
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
    parser.add_argument("--minimum-age", type=int, default=120)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args(argv)
    if args.minimum_age < 60:
        parser.error("--minimum-age must be at least 60 seconds")
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
        api, catalog=catalog, minimum_age=args.minimum_age,
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
