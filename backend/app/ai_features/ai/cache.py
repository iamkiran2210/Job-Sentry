"""Two-tier content-addressed AI response cache (in-process LRU + optional shared Redis).

Cache keys hash (task_name, prompt_version, engine, primary_model, wrapped_input) so
any prompt, version, model, or input change automatically invalidates stale entries.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any

log = logging.getLogger("ai.cache")

_MAX_L1_ENTRIES = 512
_l1_lock = threading.Lock()
_l1_cache: OrderedDict[str, tuple[float, str]] = OrderedDict()

_redis_lock = threading.Lock()
_redis_client: Any | None = None
_redis_init_attempted = False

_stats = {"l1_hits": 0, "l2_hits": 0, "misses": 0, "writes": 0}


def _get_redis():
    global _redis_client, _redis_init_attempted
    if _redis_init_attempted:
        return _redis_client
    with _redis_lock:
        if _redis_init_attempted:
            return _redis_client
        _redis_init_attempted = True
        url = (os.getenv("REDIS_URL") or "").strip()
        if not url:
            return None
        try:
            import redis

            client = redis.Redis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=0.35,
                socket_timeout=0.5,
            )
            client.ping()
            _redis_client = client
        except Exception as exc:  # noqa: BLE001
            log.debug("AI Redis cache unavailable (%s); using in-process LRU only", type(exc).__name__)
            _redis_client = None
        return _redis_client


def make_cache_key(
        *,
        task_name: str,
        prompt_version: str,
        engine: str,
        primary_model: str,
        wrapped_input: str,
) -> str:
    h = hashlib.sha256()
    for part in (task_name, prompt_version, engine, primary_model, wrapped_input):
        h.update(part.encode("utf-8", errors="ignore"))
        h.update(b"\x00")
    return f"ai:v1:{task_name}:{h.hexdigest()}"


def get_cached_output(key: str) -> dict[str, Any] | None:
    now = time.monotonic()
    with _l1_lock:
        entry = _l1_cache.get(key)
        if entry is not None:
            expires_at, raw_json = entry
            if expires_at > now:
                _l1_cache.move_to_end(key)
                _stats["l1_hits"] += 1
                try:
                    return json.loads(raw_json)
                except ValueError:
                    _l1_cache.pop(key, None)
            else:
                _l1_cache.pop(key, None)

    rclient = _get_redis()
    if rclient is not None:
        try:
            raw = rclient.get(key)
            if raw:
                parsed = json.loads(raw)
                with _l1_lock:
                    _l1_cache[key] = (now + 3600.0, raw)
                    _l1_cache.move_to_end(key)
                    while len(_l1_cache) > _MAX_L1_ENTRIES:
                        _l1_cache.popitem(last=False)
                _stats["l2_hits"] += 1
                return parsed
        except Exception:  # noqa: BLE001
            pass

    _stats["misses"] += 1
    return None


def set_cached_output(key: str, payload: dict[str, Any], *, ttl_seconds: int = 86400) -> None:
    try:
        raw = json.dumps(payload, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return
    expires_at = time.monotonic() + max(10, int(ttl_seconds))
    with _l1_lock:
        _l1_cache[key] = (expires_at, raw)
        _l1_cache.move_to_end(key)
        while len(_l1_cache) > _MAX_L1_ENTRIES:
            _l1_cache.popitem(last=False)
        _stats["writes"] += 1

    rclient = _get_redis()
    if rclient is not None:
        try:
            rclient.setex(key, max(60, int(ttl_seconds)), raw)
        except Exception:  # noqa: BLE001
            pass


def clear_ai_cache(*, reset_redis_probe: bool = False) -> None:
    global _redis_client, _redis_init_attempted
    with _l1_lock:
        _l1_cache.clear()
        for k in _stats:
            _stats[k] = 0
    if reset_redis_probe:
        with _redis_lock:
            _redis_client = None
            _redis_init_attempted = False


def ai_cache_stats() -> dict[str, int]:
    with _l1_lock:
        return {**_stats, "l1_size": len(_l1_cache)}
