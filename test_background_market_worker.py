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

if __name__=="__main__":
    unittest.main()
