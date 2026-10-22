"""revsim.py — revenue scenarios with a stated calibration source and 80% interval.

Priority for the sales-per-favorite conversion:
  1. launch_ledger D30 units / D30 favorites (minimum 5 items)
  2. launch_ledger D7 units / D7 favorites, scaled to 30 days (minimum 5)
  3. launch_ledger recent_units_30d / current favorites (minimum 5)
  4. documented prior: 8% (80% interval 3–15%)

Nothing is silently presented as calibrated. The source and sample size are
always included in the output.
"""
from statistics import median

from confidence import prediction_interval

PROMO = {"organic": 1.0, "moderate": 1.5, "aggressive": 2.4}
MIN_SAMPLE = 5
MIN_UNITS = 10
PRIOR = {
    "point": 0.08,
    "lo": 0.03,
    "hi": 0.15,
    "n": 0,
    "source": "prior",
    "note": (
        "not calibrated — need 5 ledger items with sales; "
        "using 8% units per day-30 favorite (3–15%)"
    ),
}
CONV_FLOOR = 0.005
CONV_CEIL = 0.35


def _clamp_ci(ci):
    return {
        "point": max(CONV_FLOOR, min(CONV_CEIL, ci["point"])),
        "lo": max(CONV_FLOOR, min(CONV_CEIL, ci["lo"])),
        "hi": max(CONV_FLOOR, min(CONV_CEIL, ci["hi"])),
        "n": ci.get("n", 0),
    }


def load_calibration(cur):
    cur.execute("""
        select units_d30, favs_d30
        from launch_ledger
        where units_d30 is not null and favs_d30 is not null
          and favs_d30 > 0
    """)
    rows = [r for r in cur.fetchall() if (r[0] or 0) > 0]
    if len(rows) >= MIN_SAMPLE and sum(u for u, _f in rows) >= MIN_UNITS:
        ratios = [float(u) / float(f) for u, f in rows]
        return {
            **_clamp_ci(prediction_interval(ratios, confidence=0.80)),
            "source": "ledger_d30",
            "note": f"{len(rows)} ledger items: D30 units / D30 favorites",
        }

    cur.execute("""
        select units_d7, favs_d7
        from launch_ledger
        where units_d7 is not null and favs_d7 is not null
          and favs_d7 > 0
    """)
    rows = [r for r in cur.fetchall() if (r[0] or 0) > 0]
    if len(rows) >= MIN_SAMPLE and sum(u for u, _f in rows) >= MIN_UNITS:
        ratios = [float(u) / float(f) * (30.0 / 7.0) for u, f in rows]
        return {
            **_clamp_ci(prediction_interval(ratios, confidence=0.80)),
            "source": "ledger_d7_scaled",
            "note": (
                f"{len(rows)} ledger items: D7 units / D7 favorites, "
                f"scaled to 30d (assumes linear daily sales)"
            ),
        }

    cur.execute("""
        select l.recent_units_30d, i.favorite_count
        from launch_ledger l
        join items i on i.id = l.item_id
        where l.recent_units_30d is not null
          and i.favorite_count > 0
    """)
    rows = [r for r in cur.fetchall() if (r[0] or 0) > 0]
    if len(rows) >= MIN_SAMPLE and sum(u for u, _f in rows) >= MIN_UNITS:
        ratios = [float(u) / float(f) for u, f in rows]
        return {
            **_clamp_ci(prediction_interval(ratios, confidence=0.80)),
            "source": "ledger_recent30",
            "note": (
                f"{len(rows)} ledger items with sales in the last 30d, "
                f"divided by current favorites"
            ),
        }

    return dict(PRIOR)


def favorite_curve(cur, initial_favs, promo_mult):
    cur.execute("""
        select favs_d1, favs_d7, favs_d30
        from launch_ledger
        where favs_d1 > 0 and favs_d7 > 0 and favs_d30 > 0
    """)
    rows = cur.fetchall()
    if len(rows) >= MIN_SAMPLE:
        r7 = median(float(d7) / float(d1) for d1, d7, _d30 in rows)
        r30 = median(float(d30) / float(d1) for d1, _d7, d30 in rows)
        day3 = initial_favs * (r7 ** (2.0 / 6.0))
        return {
            "day3": int(day3 * promo_mult),
            "day7": int(initial_favs * r7 * promo_mult),
            "day30": int(initial_favs * r30 * promo_mult),
            "source": f"ledger medians (n={len(rows)})",
        }
    return {
        "day3": int(initial_favs * 1.8 * promo_mult),
        "day7": int(initial_favs * 2.8 * promo_mult),
        "day30": int(initial_favs * 4.2 * promo_mult),
        "source": "heuristic curve (not calibrated)",
    }


def build_forecast(cur, price, initial_favs, promo_level):
    promo = (promo_level or "moderate").strip().lower()
    if promo not in PROMO:
        promo = "moderate"
    mult = PROMO[promo]

    conv = load_calibration(cur)
    curve = favorite_curve(cur, initial_favs, mult)
    if conv.get("source") == "ledger_d7_scaled":
        base_favs = curve["day7"]
        base_label = "day-7 favorites"
    else:
        base_favs = curve["day30"]
        base_label = "day-30 favorites"

    units_point = int(round(base_favs * conv["point"]))
    units_lo = int(round(base_favs * conv["lo"]))
    units_hi = int(round(base_favs * conv["hi"]))

    def revenue(units):
        gross = int(units * price)
        return gross, int(gross * 0.30)

    gross_point, net_point = revenue(units_point)
    gross_lo, net_lo = revenue(units_lo)
    gross_hi, net_hi = revenue(units_hi)

    return {
        "price": price,
        "initial_favs": initial_favs,
        "promo": promo,
        "promo_mult": mult,
        "base_favs": base_favs,
        "base_label": base_label,
        "conversion": conv,
        "units": {"point": units_point, "lo": units_lo, "hi": units_hi},
        "gross": {"point": gross_point, "lo": gross_lo, "hi": gross_hi},
        "net": {"point": net_point, "lo": net_lo, "hi": net_hi},
        "curve": curve,
    }


def calibration_label(conv):
    source = conv.get("source")
    if source == "ledger_d30":
        return f"Calibrated · {conv['note']}"
    if source == "ledger_d7_scaled":
        return f"Calibrated · {conv['note']}"
    if source == "ledger_recent30":
        return f"Calibrated · {conv['note']}"
    return "PRIOR — not calibrated"
