from copy import deepcopy
from datetime import datetime, timedelta, timezone
import threading
import unittest

from roommate.tracker import Tracker


class FakeStorage:
    def __init__(self, products):
        self.products = products

    def state(self):
        return {"products": deepcopy(self.products)}


def watched(identity="desk", **values):
    return {"id": identity, "monitor": True, "url": "https://example.com/product", "is_demo": False, "last_checked_at": None, **values}


class TrackerTests(unittest.TestCase):
    def test_only_opted_in_nondemo_public_watches_are_due(self):
        tracker = Tracker(FakeStorage([]), lambda _: None)
        self.assertTrue(tracker.due(watched()))
        for value in (watched(monitor=False), watched(url=""), watched(is_demo=True)):
            self.assertFalse(tracker.due(value))

    def test_due_time_is_per_product(self):
        now = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
        tracker = Tracker(FakeStorage([]), lambda _: None)
        self.assertFalse(tracker.due(watched(last_checked_at=(now-timedelta(hours=5)).isoformat()), now))
        self.assertTrue(tracker.due(watched(last_checked_at=(now-timedelta(hours=6)).isoformat()), now))

    def test_cycle_records_success_and_continues_after_failure(self):
        called = []
        storage = FakeStorage([watched("one"), watched("two"), watched("off", monitor=False)])
        def check(identity):
            called.append(identity)
            if identity == "one":
                raise ValueError("Unsupported source")
        tracker = Tracker(storage, check)
        self.assertEqual(tracker.run_cycle(), {"checked": 1, "failed": 1})
        self.assertEqual(called, ["one", "two"])

    def test_cycle_rechecks_disabled_watch(self):
        storage = FakeStorage([watched("one"), watched("two")])
        called = []
        def check(identity):
            called.append(identity)
            storage.products[1]["monitor"] = False
        tracker = Tracker(storage, check)
        tracker.run_cycle()
        self.assertEqual(called, ["one"])

    def test_cycle_is_bounded(self):
        called = []
        tracker = Tracker(FakeStorage([watched(str(i)) for i in range(25)]), called.append)
        tracker.run_cycle()
        self.assertEqual(len(called), 20)

    def test_stopping_worker_does_not_wait_for_interval(self):
        completed = threading.Event()
        storage = FakeStorage([watched()])
        tracker = Tracker(storage, lambda _: completed.set())
        tracker.start()
        self.assertTrue(completed.wait(1))
        tracker.stop()
        self.assertFalse(tracker.status()["background_running"])

    def test_status_next_check_and_no_watches(self):
        tracker = Tracker(FakeStorage([]), lambda _: None)
        self.assertIsNone(tracker.status()["next_check_at"])
        future = datetime.now(timezone.utc) + timedelta(hours=5)
        product = watched(last_checked_at=(future-timedelta(hours=6)).isoformat())
        self.assertEqual(tracker.status([product])["next_check_at"], future.isoformat())

    def test_bad_intervals(self):
        for value in (True, 0, -1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Tracker(FakeStorage([]), lambda _: None, value)


if __name__ == "__main__":
    unittest.main()
