#!/usr/bin/env python3
"""Independent qBittorrent Web API observer -> Shoko scan on Anime completion.

Never invoked by qBittorrent. No torrent filesystem writes or subprocesses.
Requires a local service account and a private config JSON.
"""
from __future__ import annotations

import argparse
import getpass
import http.cookiejar
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_CONFIG = "/etc/torrenya/qbit-shoko-poller.json"
DEFAULT_STATE = "/var/lib/torrenya/shoko-poller/state.json"


def log(message):
    print(time.strftime("%Y-%m-%dT%H:%M:%S%z"), message, flush=True)


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def atomic_json(path, data):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w") as out:
            os.fchmod(out.fileno(), 0o600)
            json.dump(data, out, separators=(",", ":"), sort_keys=True)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def new_state():
    return {"version": 1, "initialized": False, "seen": {},
            "pending_at": None, "pending_hashes": [], "retry_at": 0,
            "last_poll": None, "last_scan": None, "scan_count": 0}


def read_state(path):
    state = load_json(path, new_state())
    if not isinstance(state, dict) or state.get("version") != 1:
        raise ValueError("Invalid state version; refusing to rebaseline automatically")
    return state


def is_done(t):
    try:
        return (int(t.get("amount_left", -1)) == 0
                and float(t.get("progress", 0)) >= 0.999999
                and int(t.get("completion_on", -1)) > 0)
    except (TypeError, ValueError):
        return False


def anime_tag(t):
    return any(tag.strip() == "Anime" for tag in str(t.get("tags") or "").split(","))


def observe(state, torrents, now):
    """Process one FULL successful API snapshot, recognizing fresh completions."""
    if not isinstance(torrents, list):
        raise ValueError("qBittorrent API must return a list of torrents")
    previous = state["seen"]
    current = {}
    completions = []
    for torrent in torrents:
        if not isinstance(torrent, dict) or not anime_tag(torrent):
            continue
        torrent_hash = str(torrent.get("hash", "")).lower()
        if not re.fullmatch(r"[a-f0-9]{40}(?:[a-f0-9]{24})?", torrent_hash):
            continue
        done = is_done(torrent)
        marker = int(torrent["completion_on"]) if done else 0
        current[torrent_hash] = {"done": done, "completion_on": marker}
        old = previous.get(torrent_hash)
        if state["initialized"] and done and (
            old is None or not old.get("done") or old.get("completion_on") != marker
        ):
            completions.append(torrent_hash)
    state["seen"] = current
    state["initialized"] = True
    state["last_poll"] = now
    if completions:
        state["pending_at"] = now  # trailing-edge debounce resets on Anime completions
        state["retry_at"] = 0
        state["pending_hashes"] = sorted(set(state["pending_hashes"]) | set(completions))
    return completions


class QbitAPI:
    def __init__(self, config):
        self.root = config.get("qbit_url", "http://127.0.0.1:8080").rstrip("/")
        if self.root != "http://127.0.0.1:8080":
            raise ValueError("qBittorrent Web API must use local http://127.0.0.1:8080")
        self.key = config.get("qbit_api_key") or ""
        self.user = config.get("qbit_username") or ""
        self.password = config.get("qbit_password") or ""
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar),
            urllib.request.ProxyHandler({}))

    def request(self, path, data=None, reauth=True):
        url = self.root + "/api/v2" + path
        headers = {"Referer": self.root, "Origin": self.root}
        if self.key:
            headers["Authorization"] = "Bearer " + self.key
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with self.opener.open(req, timeout=7) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403) and reauth and self.user and self.password and not self.key:
                self.login()
                return self.request(path, data, reauth=False)
            raise

    def login(self):
        if not self.user or not self.password:
            raise RuntimeError("qBittorrent authentication required; configure API key or login")
        data = urllib.parse.urlencode({"username": self.user,
                                       "password": self.password}).encode()
        result = self.request("/auth/login", data=data, reauth=False)
        if result.strip() != "Ok.":
            raise RuntimeError("qBittorrent login failed")

    def json(self, path):
        result = json.loads(self.request(path))
        return result

    def torrents(self):
        # qBittorrent tag parameter is a server-side efficiency optimization.
        # Exact tag token is checked again in observe() (fail closed).
        return self.json("/torrents/info?tag=Anime")

    def preferences(self):
        return self.json("/app/preferences")

    def disable_autorun(self):
        prefs = self.preferences()
        if not isinstance(prefs, dict):
            raise ValueError("qBittorrent preferences response invalid")
        keys = [k for k in ("autorun_enabled", "autorun_on_torrent_finished_enabled")
                if k in prefs]
        if not keys:
            raise RuntimeError("Cannot confirm completion-hook setting; refusing to enable observer")
        desired = {k: False for k in keys if prefs[k] is not False}
        if desired:
            data = urllib.parse.urlencode({"json": json.dumps(desired)}).encode()
            self.request("/app/setPreferences", data=data)
        verify = self.preferences()
        if any(verify.get(k) is not False for k in keys):
            raise RuntimeError("qBittorrent completion hook still enabled; refusing parallel triggers")
        return bool(desired)


def shoko_scan(config):
    key_path = Path(config.get("shoko_key_file", "/etc/torrenya/shoko-api-key"))
    key = key_path.read_text().strip()
    if not key:
        raise RuntimeError("Shoko API key empty")
    url = config.get("shoko_url",
                     "http://10.169.2.151:8111/api/v3/Action/ImportNewFiles")
    if url != "http://10.169.2.151:8111/api/v3/Action/ImportNewFiles":
        raise ValueError("Unexpected Shoko endpoint")
    req = urllib.request.Request(url, headers={"apikey": key}, method="GET")
    with urllib.request.urlopen(req, timeout=20) as res:
        if res.status != 200:
            raise RuntimeError(f"Shoko returned {res.status}")


def maybe_scan(config, state, now, scan_func):
    pending = state.get("pending_at")
    if pending is None:
        return False
    if now < pending + int(config.get("debounce_seconds", 300)):
        return False
    if now < state.get("retry_at", 0):
        return False
    try:
        scan_func(config)
    except Exception as exc:
        state["retry_at"] = now + 60
        log(f"Shoko scan request failed; will retry: {type(exc).__name__}: {exc}")
        return False
    log(f"Shoko scan queued for {len(state['pending_hashes'])} Anime torrents")
    state["pending_at"] = None
    state["pending_hashes"] = []
    state["retry_at"] = 0
    state["last_scan"] = now
    state["scan_count"] = int(state.get("scan_count", 0)) + 1
    return True


def run(config, config_path, state_path, once=False):
    api = QbitAPI(config)
    # Disallow old hook and poller both triggering scans.
    api.disable_autorun()
    state = read_state(state_path)
    interval = max(10, int(config.get("poll_seconds", 30)))
    log("qBittorrent poller started; completed Anime torrents only")
    while True:
        now = int(time.time())
        try:
            torrents = api.torrents()
            completions = observe(state, torrents, now)
            atomic_json(state_path, state)
            if completions:
                log(f"Detected {len(completions)} completed Anime torrents; debounce 300s")
        except Exception as exc:
            log(f"qBittorrent polling unavailable: {type(exc).__name__}: {exc}")
        # Pending scan stays on disk if API is unavailable; it is retried after recovery.
        # Do not schedule Shoko scans during an unverified qBittorrent outage.
        else:
            maybe_scan(config, state, now, shoko_scan)
            atomic_json(state_path, state)
        if once:
            return
        time.sleep(interval)


def configure(config_path):
    print("qBittorrent API auth (localhost only). Existing WebUI auth stays enabled.")
    config = {"qbit_url": "http://127.0.0.1:8080",
              "shoko_key_file": "/etc/torrenya/shoko-api-key",
              "shoko_url": "http://10.169.2.151:8111/api/v3/Action/ImportNewFiles",
              "poll_seconds": 30, "debounce_seconds": 300}
    old = load_json(config_path, {})
    if isinstance(old, dict):
        for k in ("qbit_api_key", "qbit_username", "qbit_password"):
            if old.get(k):
                config[k] = old[k]
    api = QbitAPI(config)
    try:
        api.preferences()
        print("qBittorrent API authentication already works.")
    except (urllib.error.HTTPError, RuntimeError, ValueError) as exc:
        print(f"Authentication required ({type(exc).__name__}).")
        key = getpass.getpass("qBittorrent API key (5.2+; Enter for WebUI login): ").strip()
        if key:
            config["qbit_api_key"] = key
            config.pop("qbit_username", None)
            config.pop("qbit_password", None)
        else:
            config["qbit_username"] = input("qBittorrent WebUI username: ").strip()
            config["qbit_password"] = getpass.getpass("qBittorrent WebUI password: ")
            config.pop("qbit_api_key", None)
        api = QbitAPI(config)
        api.preferences()  # fail closed on wrong credentials
    # Validate Shoko key exists but do not trigger scan during setup.
    if not Path(config["shoko_key_file"]).read_text().strip():
        raise RuntimeError("Missing Shoko API key")
    changed = api.disable_autorun()
    atomic_json(config_path, config)
    print("qBittorrent completion command DISABLED via Web API." if changed
          else "qBittorrent completion command already disabled.")
    print("Configuration saved. No torrent was modified.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--state", default=DEFAULT_STATE)
    parser.add_argument("--configure", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    if args.status:
        print(json.dumps(read_state(args.state), indent=2, sort_keys=True))
        return
    if args.configure:
        configure(args.config)
        return
    config = load_json(args.config)
    if not isinstance(config, dict):
        parser.error("Missing JSON configuration; run --configure")
    run(config, args.config, args.state, args.once)


if __name__ == "__main__":
    main()
