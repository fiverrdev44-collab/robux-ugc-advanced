"""roblox_batch_client.py — async 30-item batch ingestion for the Roblox catalog.

POSTs to the catalog details endpoint with up to 30 asset IDs per request.
Includes a token bucket, AIMD congestion window, full-jitter backoff and CSRF
handling. Read-only with respect to Roblox (no writes).
"""
import asyncio
import random
import time

import aiohttp

CATALOG_DETAILS_URL = "https://catalog.roblox.com/v1/catalog/items/details"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
MAX_BATCH = 30


class TokenBucket:
    """Simple async token bucket (requests per minute)."""

    def __init__(self, rate_per_min=90):
        self.rate = max(1.0, float(rate_per_min)) / 60.0
        self.capacity = max(1.0, self.rate * 10)
        self.tokens = self.capacity
        self.updated = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self, n=1):
        async with self.lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.capacity,
                                  self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= n:
                    self.tokens -= n
                    return
                await asyncio.sleep(max((n - self.tokens) / self.rate, 0.01))


class RobloxBatchClient:
    def __init__(self, max_batch=MAX_BATCH, rate_per_min=90,
                 max_concurrency=3, timeout=15):
        self.max_batch = max(1, min(int(max_batch), MAX_BATCH))
        self.rate = max(1, min(int(rate_per_min), 300))
        self.timeout = timeout
        self.bucket = TokenBucket(self.rate)
        self.sem = asyncio.Semaphore(max(1, int(max_concurrency)))
        self._session = None
        self._csrf = None
        self._lock = asyncio.Lock()
        # AIMD congestion window (in-flight requests).
        self.cwnd = 2.0
        self.ssthresh = 8.0
        self._active = 0

    async def __aenter__(self):
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._session:
            await self._session.close()
            self._session = None

    def _headers(self):
        h = {"Content-Type": "application/json",
             "User-Agent": USER_AGENT,
             "Accept": "application/json"}
        if self._csrf:
            h["X-CSRF-TOKEN"] = self._csrf
        return h

    async def _window_acquire(self):
        while True:
            async with self._lock:
                if self._active < self.cwnd:
                    self._active += 1
                    return
            await asyncio.sleep(0.05)

    async def _window_release(self):
        async with self._lock:
            self._active = max(0, self._active - 1)

    def _aimd_success(self):
        self.cwnd = min(self.ssthresh, self.cwnd + 1.0 / max(self.cwnd, 1.0))

    def _aimd_congestion(self):
        self.ssthresh = max(1.0, self.cwnd * 0.5)
        self.cwnd = 1.0

    @staticmethod
    def _backoff(attempt, retry_after=None):
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except (TypeError, ValueError):
                pass
        return random.uniform(0, min(30.0, 1.0 * (2 ** attempt)))

    async def _post(self, ids):
        if not self._session:
            raise RuntimeError("use RobloxBatchClient as an async context manager")
        payload = {"items": [{"itemType": "Asset", "id": int(i)} for i in ids]}
        failed = {}
        for attempt in range(5):
            await self.bucket.acquire()
            await self._window_acquire()
            try:
                async with self.sem:
                    async with self._session.post(
                        CATALOG_DETAILS_URL, json=payload, headers=self._headers()
                    ) as resp:
                        if resp.status == 200:
                            data = (await resp.json(content_type=None) or {}).get("data")
                            data = data or []
                            self._aimd_success()
                            requested = {int(i) for i in ids}
                            returned = {int(d.get("id"))
                                        for d in data if d.get("id")}
                            for missing in requested - returned:
                                failed[missing] = "not found (batch)"
                            return data, failed
                        if resp.status == 403:
                            # CSRF challenge: capture the token and retry.
                            token = resp.headers.get("X-CSRF-TOKEN")
                            if token:
                                self._csrf = token
                            await asyncio.sleep(0.25)
                            continue
                        if resp.status == 429:
                            self._aimd_congestion()
                            await asyncio.sleep(self._backoff(
                                attempt, resp.headers.get("Retry-After")))
                            continue
                        if resp.status == 404:
                            for i in ids:
                                failed[int(i)] = "404"
                            return [], failed
                        if 400 <= resp.status < 500:
                            for i in ids:
                                failed[int(i)] = f"HTTP {resp.status}"
                            return [], failed
                        await asyncio.sleep(self._backoff(attempt))
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(self._backoff(attempt))
            finally:
                await self._window_release()
        for i in ids:
            failed[int(i)] = "rate limited"
        return [], failed

    async def fetch_many_items(self, asset_ids):
        """Fetch many assets. Returns (items_by_id, failed_by_id)."""
        ids = [int(i) for i in asset_ids if i]
        items, failed = {}, {}
        chunks = [ids[i:i + self.max_batch]
                  for i in range(0, len(ids), self.max_batch)]
        results = await asyncio.gather(*(self._post(c) for c in chunks),
                                      return_exceptions=True)
        for chunk, res in zip(chunks, results):
            if isinstance(res, Exception):
                for i in chunk:
                    failed[int(i)] = f"{type(res).__name__}"
                continue
            data, bad = res
            failed.update(bad)
            for d in data:
                item = _normalize(d)
                if item["id"]:
                    items[item["id"]] = item
        return items, failed


def _normalize(d):
    item_id = d.get("id")
    return {
        "id": int(item_id) if item_id else None,
        "name": (d.get("name") or "")[:500],
        "description": (d.get("description") or "")[:5000],
        "price": d.get("price") or 0,
        "favorite_count": d.get("favoriteCount"),
        "asset_type_id": d.get("assetType") or 0,
        "creator_name": (d.get("creatorName") or "")[:200],
        "creator_id": d.get("creatorTargetId"),
    }


async def _run(ids, **kwargs):
    async with RobloxBatchClient(**kwargs) as client:
        return await client.fetch_many_items(ids)


def fetch_many_items_sync(asset_ids, **kwargs):
    """Blocking wrapper for synchronous callers (enricher/scanner)."""
    return asyncio.run(_run(asset_ids, **kwargs))


async def _run_window(start_id, count, **kwargs):
    ids = list(range(int(start_id), int(start_id) + int(count)))
    async with RobloxBatchClient(**kwargs) as client:
        return await client.fetch_many_items(ids)


def fetch_id_window_sync(start_id, count, **kwargs):
    """Scan a monotonic ID window (scanner ID stepping)."""
    return asyncio.run(_run_window(start_id, count, **kwargs))
