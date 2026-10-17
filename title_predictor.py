"""
title_predictor.py — Self-learning ML predictor for titles.
Trains a linear model on real DB data. Updates daily via scheduler.
"""
import json
import math
import re
from collections import defaultdict

MODEL_VERSION = "v1.0"
LEARNING_RATE = 0.05
EPOCHS = 200
MIN_SAMPLES = 500
TRAIN_LIMIT = 3000

TOKEN_RE = re.compile(r"[a-z0-9]+")

FILLER_WORDS = {
    "chill","groovy","cool","cute","nice","smooth","epic","fun","funny",
    "vibes","vibe","aesthetic","trendy","viral","awesome","amazing",
    "super","best","top","new","hot","troll","meme","memes","lol",
}

ITEM_TYPE_WORDS = {
    "emote","dance","hat","beanie","crown","cap","hair","face","mask",
    "shirt","pants","jacket","shoes","wing","wings","tail","ears","horn",
    "horns","glasses","necklace","chain","backpack","sword","pet","bag",
    "scarf","bandana","beret","visor",
}


def _tokens(text):
    return [t for t in TOKEN_RE.findall((text or "").lower()) if t]


FEATURE_NAMES = [
    "length_score",
    "first_token_volume",
    "first_token_demand",
    "bigram_ratio",
    "exact_match_scarcity",
    "similar_quality",
    "type_anchor",
    "filler_ratio",
    "token_diversity",
]


def extract_features(cur, title, category_asset_ids=None):
    toks = _tokens(title)
    if not toks:
        return None
    n = len(toks)

    if 3 <= n <= 5:
        length_score = 1.0
    elif n in (2, 6):
        length_score = 0.3
    else:
        length_score = 0.0

    first = toks[0]
    if category_asset_ids:
        cur.execute("""
            SELECT COUNT(*), COALESCE(AVG(favorite_count), 0)
            FROM items
            WHERE LOWER(name) LIKE %s AND favorite_count > 5
              AND asset_type_id = ANY(%s)
        """, (f"%{first}%", category_asset_ids))
    else:
        cur.execute("""
            SELECT COUNT(*), COALESCE(AVG(favorite_count), 0)
            FROM items
            WHERE LOWER(name) LIKE %s AND favorite_count > 5
        """, (f"%{first}%",))
    comp_first, avg_favs_first = cur.fetchone()
    comp_first = int(comp_first or 0)
    avg_favs_first = float(avg_favs_first or 0)

    if 50 <= comp_first <= 500:
        first_volume = 1.0
    elif comp_first < 50:
        first_volume = 0.5
    elif comp_first < 2000:
        first_volume = 0.7
    else:
        first_volume = 0.2

    first_demand = min(1.0, math.log1p(avg_favs_first) / math.log1p(50000))

    bigram_hits = 0
    for i in range(n - 1):
        bg = f"{toks[i]} {toks[i+1]}"
        if category_asset_ids:
            cur.execute("""
                SELECT COUNT(*) FROM items
                WHERE LOWER(name) LIKE %s AND favorite_count > 5
                  AND asset_type_id = ANY(%s) LIMIT 1
            """, (f"%{bg}%", category_asset_ids))
        else:
            cur.execute("""
                SELECT COUNT(*) FROM items
                WHERE LOWER(name) LIKE %s AND favorite_count > 5 LIMIT 1
            """, (f"%{bg}%",))
        if cur.fetchone()[0] > 5:
            bigram_hits += 1
    bigram_ratio = bigram_hits / max(1, n - 1)

    if category_asset_ids:
        cur.execute("""
            SELECT COUNT(*) FROM items
            WHERE LOWER(name) LIKE %s AND favorite_count > 5
              AND asset_type_id = ANY(%s)
        """, (f"%{title.lower()}%", category_asset_ids))
    else:
        cur.execute("""
            SELECT COUNT(*) FROM items
            WHERE LOWER(name) LIKE %s AND favorite_count > 5
        """, (f"%{title.lower()}%",))
    exact = int(cur.fetchone()[0] or 0)
    exact_scarcity = 1.0 / (1 + math.log1p(exact))

    tok_set = set(toks)
    if category_asset_ids:
        cur.execute("""
            SELECT LOWER(name), favorite_count FROM items
            WHERE favorite_count > 100 AND asset_type_id = ANY(%s)
            ORDER BY favorite_count DESC LIMIT 500
        """, (category_asset_ids,))
    else:
        cur.execute("""
            SELECT LOWER(name), favorite_count FROM items
            WHERE favorite_count > 100
            ORDER BY favorite_count DESC LIMIT 500
        """)
    sim_favs = []
    for name, favs in cur.fetchall():
        if len(tok_set & set(_tokens(name))) >= 2:
            sim_favs.append(favs or 0)
            if len(sim_favs) >= 3:
                break
    if sim_favs:
        similar_quality = min(1.0, math.log1p(sum(sim_favs)/len(sim_favs)) / math.log1p(50000))
    else:
        similar_quality = 0.3

    type_anchor = 1.0 if toks[-1] in ITEM_TYPE_WORDS else 0.0
    filler_count = sum(1 for t in toks if t in FILLER_WORDS)
    filler_ratio = filler_count / n
    token_diversity = len(set(toks)) / n

    return {
        "length_score": length_score,
        "first_token_volume": first_volume,
        "first_token_demand": first_demand,
        "bigram_ratio": bigram_ratio,
        "exact_match_scarcity": exact_scarcity,
        "similar_quality": similar_quality,
        "type_anchor": type_anchor,
        "filler_ratio": filler_ratio,
        "token_diversity": token_diversity,
        "_raw": {
            "tokens": toks,
            "first_comp": comp_first,
            "exact_matches": exact,
            "filler_count": filler_count,
        }
    }


def _ensure_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS predictor_weights (
            id SERIAL PRIMARY KEY,
            model_version TEXT,
            weights JSONB,
            trained_on_count INTEGER,
            accuracy DOUBLE PRECISION,
            trained_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.connection.commit()


def _save_weights(cur, weights, n_samples, accuracy):
    _ensure_table(cur)
    cur.execute("""
        INSERT INTO predictor_weights
            (model_version, weights, trained_on_count, accuracy)
        VALUES (%s, %s, %s, %s)
    """, (MODEL_VERSION, json.dumps(weights), n_samples, accuracy))
    cur.connection.commit()


def _load_weights(cur):
    try:
        _ensure_table(cur)
        cur.execute("""
            SELECT weights, trained_on_count, accuracy, trained_at
            FROM predictor_weights
            WHERE model_version = %s
            ORDER BY trained_at DESC LIMIT 1
        """, (MODEL_VERSION,))
        row = cur.fetchone()
        if row:
            w = row[0]
            if isinstance(w, str):
                w = json.loads(w)
            return {
                "weights": w,
                "n_samples": row[1] or 0,
                "accuracy": float(row[2] or 0),
                "trained_at": str(row[3]),
            }
    except Exception as e:
        print(f"[predictor] load failed: {e}", flush=True)
    return None


def _train_linear(X, y, lr, epochs):
    if not X:
        return None
    n_features = len(X[0])
    w = [0.0] * n_features
    n = len(X)
    for _ in range(epochs):
        grads = [0.0] * n_features
        for i in range(n):
            pred = sum(w[j] * X[i][j] for j in range(n_features))
            err = pred - y[i]
            for j in range(n_features):
                grads[j] += err * X[i][j]
        for j in range(n_features):
            w[j] -= lr * (grads[j] / n)
            w[j] -= lr * 0.001 * w[j]
    return w


def train_model(cur):
    print("[predictor] Training...", flush=True)
    cur.execute(f"""
        SELECT LOWER(name), favorite_count, asset_type_id
        FROM items
        WHERE favorite_count > 100
          AND name IS NOT NULL AND name != ''
        ORDER BY RANDOM()
        LIMIT {TRAIN_LIMIT}
    """)
    rows = cur.fetchall()
    if len(rows) < MIN_SAMPLES:
        print(f"[predictor] Not enough data: {len(rows)}", flush=True)
        return None

    max_favs = max(r[1] for r in rows)
    log_max = math.log1p(max_favs)

    X, y = [], []
    for name, favs, atype in rows:
        cat = [atype] if atype else None
        try:
            feats = extract_features(cur, name, cat)
            if not feats:
                continue
            X.append([feats[k] for k in FEATURE_NAMES])
            y.append(math.log1p(favs) / log_max)
        except Exception:
            continue

    if len(X) < MIN_SAMPLES:
        print(f"[predictor] Only {len(X)} usable", flush=True)
        return None

    print(f"[predictor] Training on {len(X)} samples", flush=True)
    weights = _train_linear(X, y, LEARNING_RATE, EPOCHS)

    preds = [sum(weights[j] * X[i][j] for j in range(len(weights))) for i in range(len(X))]
    mean_y = sum(y) / len(y)
    ss_res = sum((preds[i] - y[i]) ** 2 for i in range(len(y)))
    ss_tot = sum((y[i] - mean_y) ** 2 for i in range(len(y)))
    r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

    wd = {FEATURE_NAMES[j]: round(weights[j], 4) for j in range(len(FEATURE_NAMES))}
    _save_weights(cur, wd, len(X), r2)
    print(f"[predictor] ✅ R² = {r2:.3f}", flush=True)
    return {"weights": wd, "n_samples": len(X), "accuracy": r2}


def predict_title(cur, title, category_asset_ids=None, auto_train=True):
    loaded = _load_weights(cur)
    if not loaded and auto_train:
        print("[predictor] Training on demand...", flush=True)
        res = train_model(cur)
        if res:
            loaded = {
                "weights": res["weights"],
                "n_samples": res["n_samples"],
                "accuracy": res["accuracy"],
            }
    if not loaded:
        return {"error": "no_model", "score": 0}

    feats = extract_features(cur, title, category_asset_ids)
    if not feats:
        return {"error": "extract_failed", "score": 0}

    raw_score = 0.0
    for name in FEATURE_NAMES:
        raw_score += loaded["weights"].get(name, 0) * feats[name]

    normalized = max(0, min(100, (raw_score + 0.5) * 50))
    data_conf = min(1.0, loaded["n_samples"] / 3000)
    confidence = round(loaded["accuracy"] * data_conf * 100, 1)

    if normalized >= 80:
        verdict = "🥇 GOLD"
    elif normalized >= 65:
        verdict = "🥈 STRONG"
    elif normalized >= 50:
        verdict = "🥉 VIABLE"
    elif normalized >= 35:
        verdict = "⚠️ WEAK"
    else:
        verdict = "❌ DEAD"

    return {
        "title": title,
        "score": round(normalized, 1),
        "confidence": confidence,
        "verdict": verdict,
        "model_samples": loaded["n_samples"],
        "model_accuracy": round(loaded["accuracy"] * 100, 1),
        "raw": feats["_raw"],
    }
