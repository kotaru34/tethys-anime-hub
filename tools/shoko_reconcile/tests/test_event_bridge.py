"""Protocol and event tests for the Shoko 5.3.3 SignalR bridge."""
import sys
from pathlib import Path
import unittest
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from event_bridge import events_in, websocket_url, HANDSHAKE, resolve_apply_mode, retry_delay_for, Coordinator


class ProtocolTests(unittest.TestCase):
    def test_handshake_is_signalr_json_protocol(self):
        self.assertEqual(HANDSHAKE, '{"protocol":"json","version":1}\x1e')
    def test_native_event_names_and_ping(self):
        data = '{}\x1e{"type":6}\x1e{"type":1,"target":"Shoko:FileNotMatched","arguments":[{"FileID":778}]}\x1e'
        self.assertEqual(list(events_in(data)), [
            ("Shoko:FileNotMatched", [{"FileID": 778}])])
        self.assertEqual(list(events_in('{"type":1,"target":"Queue:QueueStateChanged","arguments":[{"TotalCount":0}]}\x1e')),
                         [("Queue:QueueStateChanged", [{"TotalCount": 0}])])
    def test_loopback_only(self):
        self.assertEqual(websocket_url("http://127.0.0.1:8111"),
                         "ws://127.0.0.1:8111/signalr/aggregate?feeds=shoko")
        with self.assertRaises(ValueError):
            websocket_url("http://10.169.2.151:8111")



class ServiceModeTests(unittest.TestCase):
    def test_existing_service_remains_dry_run_by_default(self):
        self.assertFalse(resolve_apply_mode())

    def test_explicit_env_toggle_enables_auto_linking(self):
        self.assertTrue(resolve_apply_mode(service_setting="LINK"))

    def test_cli_requires_confirmation(self):
        with self.assertRaises(ValueError):
            resolve_apply_mode(cli_apply=True)
        self.assertTrue(resolve_apply_mode(cli_apply=True, cli_confirm="LINK"))

    def test_env_must_be_exact_link_token(self):
        for bad in ("true", "1", "link", "LINK ", "0", "false"):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                resolve_apply_mode(service_setting=bad)



class UnrelatedQueueJobsTests(unittest.TestCase):
    def test_queue_idle_signal_does_not_schedule_full_reconciliation(self):
        worker = object.__new__(Coordinator)
        worker.pending = threading.Event()
        worker.received("Queue:QueueStateChanged", [
            {"Running": True, "TotalCount": 0, "CurrentlyExecuting": []}])
        self.assertFalse(worker.pending.is_set())
        worker.received("Shoko:FileNotMatched", [{"FileID": 7}])
        self.assertTrue(worker.pending.is_set())

    def test_hash_and_detect_events_trigger_but_artwork_queue_does_not(self):
        worker = object.__new__(Coordinator)
        worker.pending = threading.Event()
        for name in ("Shoko:FileDetected", "Shoko:FileHashed",
                     "Shoko:FileNotMatched"):
            worker.received(name, [{"FileID": 42}])
            self.assertTrue(worker.pending.is_set(), name)
            worker.pending.clear()
        for name in ("Shoko:FileMatched", "Queue:QueueStateChanged",
                     "Shoko:SeriesUpdated"):
            worker.received(name, [{"FileID": 42}])
            self.assertFalse(worker.pending.is_set(), name)

    def test_light_unknown_count_uses_one_page_not_library_enumeration(self):
        class API:
            def __init__(self): self.calls = []
            def request(self, method, path, params=None):
                self.calls.append((method, path, params))
                return {"Total": 148, "List": [{"ID": 1}]}
        worker = object.__new__(Coordinator)
        worker.api = API()
        self.assertEqual(worker.unknown_count(), 148)
        self.assertEqual(worker.api.calls, [
            ("GET", "/File", {"include_only": "Unrecognized",
                              "pageSize": 1, "page": 1})
        ])

    def test_only_metadata_triggers_timed_retries(self):
        self.assertIsNone(retry_delay_for({
            "currently_unrecognized": 100,
            "mature_stable_unknown": 0,
            "maturing_nonpartial_files": 0,
            "awaiting_series_refresh": 0, "errors": 0
        }))
        self.assertEqual(retry_delay_for({"awaiting_series_refresh": 4}), 60)
        self.assertEqual(retry_delay_for({"errors": 1}), 60)


if __name__ == "__main__":
    unittest.main()
