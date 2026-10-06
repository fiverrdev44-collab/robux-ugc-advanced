def hidden_gems(cur, days=30, min_rate=15, max_supply=30, limit=8):
    try:
        cur.execute("""
            SELECT id, name, creator_name, favorite_count,
                   EXTRACT(EPOCH FROM (NOW() - created_at))/86400 AS age_days
            FROM items
            WHERE created_at IS NOT NULL
              AND created_at >= NOW() - INTERVAL '%s days'
              AND favorite_count > 30
            ORDER BY favorite_count DESC
            LIMIT 500
        """, (int(days),))
        rows = cur.fetchall()
    except Exception as e:
        print(f"[xray] hidden gems: {e}", flush=True)
        return []

    if not rows:
        return []

    from early_winners import _is_noise, PLATFORM_CREATORS

    try:
        cur.execute("""
            SELECT LOWER(name) FROM items
            WHERE favorite_count > 5
            LIMIT 50000
        """)
        all_names = [r[0] for r in cur.fetchall() if r[0]]
    except Exception:
        all_names = []

    gems = []
    for item_id, name, creator, favs, age in rows:
        if _is_noise(name):
            continue
        if creator in PLATFORM_CREATORS:
            continue
        try:
            age_f = float(age or 0)
            if age_f <= 0.1:
                continue
            rate = (favs or 0) / age_f
        except Exception:
            continue
        if rate < min_rate:
            continue
        tokens = re.findall(r"[a-z]{4,}", (name or "").lower())
        if not tokens:
            continue
        keyword = tokens[0]
        supply = sum(1 for n in all_names if keyword in n)
        if supply > max_supply:
            continue
        gems.append({
            "id": item_id,
            "name": (name or "")[:50],
            "creator": (creator or "")[:24],
            "favs": int(favs or 0),
            "rate": round(rate, 1),
            "supply": supply,
        })
    gems.sort(key=lambda g: -g["rate"])
    return gems[:limit]
