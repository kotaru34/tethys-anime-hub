#!/usr/bin/env python3
"""Event-driven Shoko 5.3.3 Reconciler using the native SignalR aggregate hub.

Shoko sends Shoko:FileNotMatched for misses and Queue:QueueStateChanged
for scheduler activity. This subscribes to both; no cron or periodic timer.
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

from auto_fallback import run as reconcile, queue_is_busy
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
        self.pending = threading.Event()
        self.idle = threading.Event()
        self.worker = threading.Thread(target=self.process, name="shoko-fallback", daemon=True)
        self.worker.start()

    def received(self, target, arguments):
        if target == "Shoko:FileNotMatched":
            print("Shoko reports unmatched file; queue reconciliation", flush=True)
            self.pending.set()
        if target in ("Queue:OnConnected", "Queue:QueueStateChanged") and arguments:
            if queue_idle(arguments[0]):
                was_idle = self.idle.is_set()
                self.idle.set()
                # Hash-only recognition may leave files unknown without a
                # FileNotMatched notification. The busy->idle transition is
                # therefore another *event-driven* reconciliation trigger.
                if not was_idle:
                    self.pending.set()
            else:
                self.idle.clear()

    def reconcile(self, do_apply):
        result = reconcile(
            self.api, state_path=self.state_path, plan_path=self.plan_path,
            catalog=self.catalog, minimum_age=self.minimum_age,
            do_apply=do_apply)
        print(json.dumps(result, sort_keys=True), flush=True)
        return result

    def process(self):
        while True:
            self.pending.wait()
            self.pending.clear()
            try:
                first = self.reconcile(False)
                if not first["currently_unrecognized"]:
                    continue
                # One event-triggered grace period. Not a recurring polling timer.
                time.sleep(self.minimum_age + 2)
                # Queue activity is signaled by Shoko SignalR, not by polling.
                self.idle.wait()
                if queue_is_busy(self.api):
                    # Queue event may have raced with a newly scheduled job.
                    self.idle.clear()
                    self.idle.wait()
                    if queue_is_busy(self.api):
                        raise RuntimeError("Shoko queue still busy on idle event")
                self.reconcile(self.do_apply)
            except Exception as exc:
                print(f"Reconciliation event failed: {type(exc).__name__}: {exc}", flush=True)


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
    if args.apply and args.confirm != "LINK":
        parser.error("--apply requires --confirm LINK")
    key = os.getenv("SHOKO_API_KEY")
    if not key:
        parser.error("SHOKO_API_KEY missing")
    api = ShokoAPI(args.url, key)
    catalog = AliasCatalog(args.catalog) if args.catalog and Path(args.catalog).is_file() else None
    coordinator = Coordinator(
        api, catalog=catalog, minimum_age=args.minimum_age,
        state_path=args.state, plan_path=args.plan, do_apply=args.apply)

    try:
        from websocket import create_connection
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
                state = api.request("GET", "/Queue")
                if queue_idle({**state, "Running": True}):
                    coordinator.idle.set()
                else:
                    coordinator.idle.clear()
                while True:
                    msg = ws.recv()
                    if not msg:
                        raise ConnectionError("SignalR websocket disconnected")
                    for target, data in events_in(msg):
                        coordinator.received(target, data)
            finally:
                ws.close()
        except (OSError, ValueError, ConnectionError) as exc:
            print(f"SignalR disconnected: {type(exc).__name__}: {exc}", flush=True)
        # Reconnect backoff, not a scheduled scan.
        time.sleep(5)


if __name__ == "__main__":
    main()
