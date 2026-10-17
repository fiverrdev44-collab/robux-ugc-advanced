"""
pivot_history.py — remembers last autopsy recommendation per item.
Flags when current recommendation contradicts previous.
"""
from bot_core import get_db


def get_last_recommendation(item_id):
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            select pivot_keyword, pivot_confidence, pivot_reason,
                   champion_title, verdict, created_at
            from autopsy_history
            where item_id = %s
            order by created_at desc
            limit 1
        """, (item_id,))
        row = cur.fetchone()
        if not row:
            return None
        return {
            "pivot": row[0], "confidence": row[1], "reason": row[2],
            "champion": row[3], "verdict": row[4], "at": row[5],
        }
    finally:
        cur.close(); conn.close()


def save_recommendation(item_id, pivot, confidence, reason, champion, verdict):
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            insert into autopsy_history
              (item_id, pivot_keyword, pivot_confidence, pivot_reason,
               champion_title, verdict)
            values (%s, %s, %s, %s, %s, %s)
        """, (item_id, pivot, confidence, reason, champion, verdict))
        conn.commit()
    finally:
        cur.close(); conn.close()


def consistency_check(item_id, new_pivot, new_confidence):
    """
    Compare to last recommendation. Returns (status, message) or None.
    status: 'same' | 'changed' | 'upgraded' | 'downgraded'
    """
    last = get_last_recommendation(item_id)
    if not last:
        return None

    old_pivot = last["pivot"]
    old_conf = last["confidence"] or 0

    if old_pivot == new_pivot:
        return ("same",
                f"✅ Consistent with last run "
                f"(`{new_pivot}` · conf {new_confidence:.0%} · "
                f"was {old_conf:.0%})")

    # Different pivot — who's more confident?
    if new_confidence > old_conf + 0.2:
        return ("upgraded",
                f"🔄 **Pivot changed** — new recommendation is more "
                f"confident.\n"
                f"  Was: `{old_pivot}` ({old_conf:.0%})\n"
                f"  Now: `{new_pivot}` ({new_confidence:.0%})\n"
                f"  _New data or better signals. Trust the new one._")
    elif old_conf > new_confidence + 0.2:
        return ("downgraded",
                f"⚠️ **Bot is LESS confident this run.** Consider waiting.\n"
                f"  Was: `{old_pivot}` ({old_conf:.0%})\n"
                f"  Now: `{new_pivot}` ({new_confidence:.0%})\n"
                f"  _Data may be noisy. Re-run tomorrow for clarity._")
    else:
        return ("changed",
                f"🔄 **Pivot changed with similar confidence.**\n"
                f"  Was: `{old_pivot}` ({old_conf:.0%})\n"
                f"  Now: `{new_pivot}` ({new_confidence:.0%})\n"
                f"  _Both are viable. Pick either._")
