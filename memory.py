"""memory.py — durable conversation context scoped to user + channel.

Stores only what the router needs to keep continuity ("that beanie",
"the second one", pending offers). It never stores credentials or raw
third-party content.
"""
import json

SCHEMA = """
create table if not exists conversation_memory (
    channel_id bigint not null,
    user_id bigint not null,
    state jsonb not null,
    updated_at timestamptz default now(),
    primary key (channel_id, user_id)
);
create index if not exists idx_conversation_memory_updated
    on conversation_memory (updated_at);
"""


def ensure_schema(cur, conn=None):
    cur.execute(SCHEMA)
    if conn is not None:
        conn.commit()


def save(cur, channel_id, user_id, state_dict):
    cur.execute("""
        insert into conversation_memory (channel_id, user_id, state, updated_at)
        values (%s, %s, %s::jsonb, now())
        on conflict (channel_id, user_id) do update set
            state = excluded.state,
            updated_at = now()
    """, (int(channel_id), int(user_id), json.dumps(state_dict, default=str)))


def load(cur, channel_id, user_id, max_age_hours=24):
    cur.execute("""
        select state from conversation_memory
        where channel_id = %s and user_id = %s
          and updated_at > now() - make_interval(hours => %s)
    """, (int(channel_id), int(user_id), int(max_age_hours)))
    row = cur.fetchone()
    if not row:
        return None
    state = row[0]
    if isinstance(state, str):
        try:
            state = json.loads(state)
        except Exception:
            return None
    return state if isinstance(state, dict) else None
