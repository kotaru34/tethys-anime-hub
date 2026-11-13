"""Protocol and event tests for the Shoko 5.3.3 SignalR bridge."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from event_bridge import events_in, queue_idle, websocket_url, HANDSHAKE


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


if __name__ == "__main__":
    unittest.main()
