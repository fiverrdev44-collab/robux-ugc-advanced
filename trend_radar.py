"""trend_radar.py — Project ORACLE historical observations + real velocity.

Append-only observations and velocity from actual observation deltas. Never
uses lifetime favorites ÷ item age, and never treats missing/unknown favorites
as zero.
"""
from datetime import datetime, timezone

WINDOWS = {"d1": 1, "d3": 3, "d7": 7, "d30": 30}
CLOSE_TOLERANCE = 0.35  # observation counts as "closest" within ±35%


def _as_utc(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def record_observation(cur, scan_run_id, item, observed_at=None,
                       favorites_status=None):
    """Append one observation. Safe to retry: duplicate (run,item) is ignored."""
    favorites = item.get("favorites")
    if favorites_status is None:
        favorites_status = ("known" if favorites is not None
                            else item.get("favorite_data_status") or "unknown")
    cur.execute("""
        insert into trend_item_observations
          (item_id, creator_id, creator_type, observed_at, scan_run_id,
           favorites, title, description, price, created_at,
           favorite_data_status)
        values (%s, %s, %s, coalesce(%s, now()), %s, %s, %s, %s, %s, %s, %s)
        on conflict (scan_run_id, item_id) do nothing
    """, (item.get("id"), item.get("creator_id"),
          item.get("creator_type"), _as_utc(observed_at), scan_run_id,
          favorites,
          (item.get("name") or "")[:500],
          (item.get("description") or "")[:5000],
          item.get("price"), _as_utc(item.get("created_at")),
          favorites_status))


def observation_from(discovery, batch=None, scan_run_id=0, observed_at=None):
    """Merge discovery metadata with batch details, preserving real timestamps."""
    batch = batch or {}
    favorites = batch.get("favorite_count", discovery.get("favorites"))
    status = "known" if favorites is not None else (
        discovery.get("favorite_data_status") or "missing")
    return {
        "id": discovery.get("id"),
        "creator_id": discovery.get("creator_id") or batch.get("creator_id"),
        "creator_type": (discovery.get("creator_type")
                         or batch.get("creator_type")),
        "name": batch.get("name") or discovery.get("name"),
        "description": batch.get("description") or discovery.get("description"),
        "price": batch.get("price") if batch.get("price") is not None
                 else discovery.get("price"),
        "favorites": favorites,
        "favorite_data_status": status,
        "created_at": discovery.get("created_at"),  # never from batch
        "scan_run_id": scan_run_id,
        "observed_at": observed_at,
    }


def _usable(observations):
    out = []
    for o in observations or []:
        fav = o.get("favorites")
        ts = _as_utc(o.get("observed_at"))
        if fav is None or ts is None:
            continue
        out.append((ts, int(fav)))
    out.sort(key=lambda x: x[0])
    return out


def _nearest(obs, window_days, tolerance=CLOSE_TOLERANCE):
    best = None
    lo, hi = window_days * (1 - tolerance), window_days * (1 + tolerance)
    for ts, fav in obs:
        elapsed = (obs[-1][0] - ts).total_seconds() / 86400.0
        if elapsed <= 0:
            continue
        if lo <= elapsed <= hi:
            dist = abs(elapsed - window_days)
            if best is None or dist < best["distance"]:
                best = {"ts": ts, "favorites": fav,
                        "elapsed_days": elapsed, "distance": dist}
    return best


def compute_velocity(observations, tolerance=CLOSE_TOLERANCE):
    """Velocity from the latest valid observation vs the closest to 24h before."""
    obs = _usable(observations)
    result = {"available": False, "velocity_per_day": None,
              "windows": {}, "reason": None, "observations": len(obs)}
    if len(obs) < 2:
        result["reason"] = "insufficient observations (need >= 2 valid)"
        return result
    latest_ts, latest_fav = obs[-1]
    prev = _nearest(obs, 1, tolerance)
    if not prev or prev["elapsed_days"] <= 0:
        result["reason"] = ("no valid observation close to 24h earlier "
                            f"(tolerance ±{int(tolerance * 100)}%)")
    else:
        elapsed = prev["elapsed_days"]
        result.update({
            "available": True,
            "velocity_per_day": round((latest_fav - prev["favorites"]) / elapsed, 3),
            "elapsed_days": round(elapsed, 2),
            "latest_favorites": latest_fav,
            "previous_favorites": prev["favorites"],
        })
    for key, days in WINDOWS.items():
        w = _nearest(obs, days, tolerance)
        if w and w["elapsed_days"] > 0:
            result["windows"][key] = {
                "delta": latest_fav - w["favorites"],
                "elapsed_days": round(w["elapsed_days"], 2),
                "per_day": round((latest_fav - w["favorites"]) / w["elapsed_days"], 3),
            }
        else:
            result["windows"][key] = {"insufficient": True}
    return result


def velocity_for_item(cur, item_id, days=60):
    cur.execute("""
        select observed_at, favorites from trend_item_observations
        where item_id = %s
          and observed_at > now() - make_interval(days => %s)
          and favorites is not null
        order by observed_at
    """, (item_id, int(days)))
    obs = [{"observed_at": r[0], "favorites": r[1]} for r in cur.fetchall()]
    return compute_velocity(obs)
