"""Offline regression checks for dedicated background collection."""
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock
import background_market_worker as w
import avatar_backgrounds as ab

NOW = datetime(2026, 11, 24, tzinfo=timezone.utc)

def raw(i=1000001, **kw):
    return dict({"id":i,"name":"Moonlit Shrine Background","assetType":92,
                 "itemType":"Asset","favoriteCount":0,
                 "itemCreatedUtc":"2026-11-23T00:00:00Z"}, **kw)

class TestBackgroundCoverage(unittest.TestCase):
    def test_strict_normalization(self):
        row = w._normalize(raw(), NOW)
        self.assertEqual(row["favorite_count"], 0)
        self.assertEqual(row["created_at"], NOW-timedelta(days=1))
        self.assertIsNone(w._normalize(raw(assetType=8), NOW))
        self.assertIsNone(w._normalize(raw(itemType="Bundle"), NOW))
        self.assertIsNone(w._normalize(raw(favoriteCount=None), NOW)["favorite_count"])
        self.assertIsNone(w._normalize(raw(itemCreatedUtc="2027-01-01T00:00:00Z"), NOW)["created_at"])
        self.assertIsNone(w._normalize(raw(itemCreatedUtc=None), NOW)["created_at"])

    def test_discovery_deduplicates_and_bounds(self):
        get = Mock()
        get.return_value.status_code = 200
        get.return_value.json.return_value = {"data":[raw(),raw(1000002,assetType=8)],"nextPageCursor":"repeat"}
        rows, calls, failures, deferred = w.discover(NOW, get, lambda _:False)
        self.assertEqual(list(rows), [1000001])
        self.assertLessEqual(calls, w.MAX_SEARCH_PAGES)
        self.assertEqual(failures, 0)
        self.assertFalse(deferred)
        self.assertEqual(get.call_count, calls)
        self.assertEqual(len(w._queries(NOW)),8)
        self.assertNotEqual(w._queries(NOW),w._queries(NOW+timedelta(hours=6)))

    def test_rate_limit_stops_cycle_search(self):
        get = Mock()
        get.return_value.status_code = 429
        rows, calls, failures, deferred = w.discover(NOW,get,lambda _:False)
        self.assertEqual((rows,calls,failures,deferred),({},1,1,True))
        self.assertEqual(get.call_count,1)

    def test_favorite_fallback_reads_catalog_count_and_preserves_zero(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"favoriteCount": 17}
        with mock.patch.object(w, "safe_get", return_value=response) as get:
            self.assertEqual(w._fetch_favorite_count(12345), 17)
        self.assertIn("12345", get.call_args.args[1])

        response.json.return_value = {"favoriteCount": 0}
        with mock.patch.object(w, "safe_get", return_value=response):
            self.assertEqual(w._fetch_favorite_count(12345), 0)

    def test_favorite_fallback_does_not_mask_rate_limit(self):
        response = Mock()
        response.status_code = 429
        with mock.patch.object(w, "safe_get", return_value=response):
            self.assertIsNone(w._fetch_favorite_count(12345))

    def test_only_observed_favorites_create_history(self):
        cur=Mock()
        cur.rowcount=1
        rows=[w._normalize(raw(),NOW),w._normalize(raw(1000002,favoriteCount=None),NOW)]
        self.assertEqual(w.store_rows(cur,rows),1)
        calls=cur.execute.call_args_list
        self.assertEqual(len(calls),3)
        self.assertIn("ON CONFLICT DO NOTHING",calls[1].args[0])
        self.assertIn("COALESCE(items.created_at, EXCLUDED.created_at)",calls[0].args[0])
        self.assertEqual(calls[1].args[1]["favorite_count"],0)

    def test_watchlist_is_not_ranked_growth(self):
        text=ab.format_background_watchlist({"insufficient":[{"name":"Moonlit Shrine Background","url":"https://www.roblox.com/catalog/1000001","current_favorites":15,"observations":1}]})
        self.assertIn("Unranked",text)
        self.assertIn("15 current favorites",text)
        self.assertIn("1 stored observation(s)",text)
        self.assertNotIn("/day",text)

class TestEarlyTraction(unittest.TestCase):
    def test_sparse_history_has_separate_traction(self):
        cur = Mock()
        cur.fetchall.return_value = [
            (1, "Zero", "A", 0, 200, 0.2, NOW, 92, 1),
            (2, "Strong", "B", 100, 200, 2, NOW-timedelta(days=2), 92, 1),
            (3, "Young", "C", 30, 200, 0.1, NOW-timedelta(hours=2), 92, 1),
            (4, "Unknown", "D", None, 200, 1, NOW-timedelta(days=1), 92, 1),
        ]
        result = ab.find_background_early_winners(cur, now=NOW)
        self.assertEqual(result["usable_history"], 0)
        self.assertEqual(result["ranked"], [])
        self.assertEqual([r["id"] for r in result["early_traction"]], [2, 3])
        self.assertEqual(result["early_traction"][1]["estimated_favs_per_day"], 30)
        output = ab.format_background_early_winners(result)
        self.assertIn("estimated, not measured growth", output)
        self.assertIn("50.0/day estimated", output)
        self.assertNotIn("Zero", output)


if __name__=="__main__":
    unittest.main()
