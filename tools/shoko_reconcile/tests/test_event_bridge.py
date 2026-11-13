"""Protocol and event tests for the Shoko 5.3.3 SignalR bridge."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from event_bridge import events_in, queue_idle, websocket_url, HANDSHAKE, resolve_apply_mode


class ProtocolTests(unittest.TestCase):
    def test_handshake_is_signalr_json_protocol(self):
        self.assertEqual(HANDSHAKE, '{"protocol":"json","version":1}\x1e')
    def test_native_event_names_and_ping(self):
        data = '{}\x1e{"type":6}\x1e{"type":1,"target":"Shoko:FileNotMatched","arguments":[{"FileID":778}]}\x1e'
        self.assertEqual(list(events_in(data)), [
            ("Shoko:FileNotMatched", [{"FileID": 778}])])
        self.assertEqual(list(events_in('{"type":1,"target":"Queue:QueueStateChanged","arguments":[{"TotalCount":0}]}\x1e')),
                         [("Queue:QueueStateChanged", [{"TotalCount": 0}])])
    def test_queue_idle_and_busy(self):
        self.assertTrue(queue_idle({"TotalCount": 0, "CurrentlyExecuting": [], "Running": True}))
        self.assertFalse(queue_idle({"TotalCount": 1, "CurrentlyExecuting": [], "Running": True}))
        self.assertFalse(queue_idle({"TotalCount": 0, "CurrentlyExecuting": [{"Type":"Hash"}], "Running": True}))
        self.assertFalse(queue_idle({"TotalCount": 0, "CurrentlyExecuting": [], "Running": False}))
    def test_loopback_only(self):
        self.assertEqual(websocket_url("http://127.0.0.1:8111"),
                         "ws://127.0.0.1:8111/signalr/aggregate?feeds=shoko,queue")
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



if __name__ == "__main__":
    unittest.main()
