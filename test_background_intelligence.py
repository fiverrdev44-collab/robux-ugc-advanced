"""Offline background category and trend intelligence contract tests."""
from datetime import datetime, timedelta, timezone
import background_intelligence as bg
from category_configs import (detect_family_from_asset_type, get_category_config,
                              to_convergence_family)
from convergence_engine import resolve_family_ids, _family_clause

NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


class FakeCur:
    def __init__(self, items, obs):
        self.items = items
        self.obs = obs
        self.sql = []
        self._result = []

    def execute(self, query, params):
        self.sql.append((query, params))
        assert "92" in str(params) or query.strip().startswith("SELECT item_id"), query
        if "COUNT(*)" in query:
            if "created_at" in query:
                self._result = [(len(self.items),)]
            else:
                self._result = [(len(self.items),)]
        elif "FROM item_history" in query:
            self._result = [(iid,) + tuple(values) for iid, values in self.obs.items()]
        else:
            self._result = [
                (x["id"], x["name"], x["created_at"], x["favorite_count"],
                 x["price"], x["creator_name"]) for x in self.items
            ]

    def fetchone(self):
        return self._result[0]

    def fetchall(self):
        return self._result


def item(iid, name, days, favs=20):
    return {"id": iid, "name": name, "created_at": NOW-timedelta(days=days),
            "favorite_count": favs, "price": 200, "creator_name": "Creator"}


def test_category_and_aliases():
    assert detect_family_from_asset_type(92) == "backgrounds"
    assert get_category_config("avatar backgrounds")["asset_type_ids"] == [92]
    assert to_convergence_family("backgrounds") == "backgrounds"
    assert resolve_family_ids("backgrounds") == [92]
    assert _family_clause("backgrounds") == (" and asset_type_id in (%s)", [92])
    assert _family_clause("not_a_category")[0].strip() == "and 1=0"


def test_real_growth_vs_age_proxy():
    items=[item(1,"Moonlit Forest Background",2,35),
           item(2,"Neon City Background",1,140)]
    observations={1:(NOW-timedelta(hours=30),NOW-timedelta(hours=6),5,35,2)}
    ranked=bg.rank_items(items,observations,NOW,7)
    assert ranked[0]["id"]==1
    assert ranked[0]["measured"] and ranked[0]["velocity"]==30.0
    assert not ranked[1]["measured"]
    assert "city / cyber" in ranked[1]["themes"]


def test_no_recent_data_no_fake_trends():
    cur=FakeCur([],{})
    report=bg.build_report(cur,days=7,now=NOW)
    assert "NO VERIFIED CATALOG DATA" in report
    assert "CTR" in report


def test_report_category_queries_and_confidence():
    items=[item(1,"Cozy Library Background",2,60),
           item(2,"Celestial Castle Background",1,44)]
    obs={1:(NOW-timedelta(hours=26),NOW-timedelta(hours=2),20,60,2)}
    cur=FakeCur(items,obs)
    report=bg.build_report(cur,days=7,now=NOW)
    assert "INSUFFICIENT" in report
    assert "Cozy Library" in report
    assert "TITLE-ONLY" in report
    assert "92 ONLY" in report
    assert "40 ♥" in report
    assert all("92" in str(params) for sql,params in cur.sql if "FROM items" in sql)
    assert "CTR" in report


if __name__=="__main__":
    tests=[f for k,f in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests: fn()
    print(f"ALL {len(tests)} BACKGROUND INTELLIGENCE TESTS PASSED")
