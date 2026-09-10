import json
import time
from collections import OrderedDict
from threading import Lock
from typing import Protocol
from redis import Redis, RedisError
from backend.config import settings


class Cache(Protocol):
    def get(self, key): ...
    def set(self, key, value, ttl=30): ...


class ResilientCache:
    def __init__(self, max_entries=128):
        self.redis = Redis.from_url(settings().redis_url, socket_connect_timeout=0.15, socket_timeout=0.15)
        self.local = OrderedDict()
        self.lock = Lock()
        self.max_entries = max_entries
        self.degraded_until = 0
        self.failures = 0

    def _call(self, method, *args, **kwargs):
        if time.monotonic() < self.degraded_until:
            return None
        try:
            return getattr(self.redis, method)(*args, **kwargs)
        except (RedisError, OSError):
            self.degraded_until = time.monotonic() + 10
            self.failures += 1
            return None

    def get(self, key):
        value = self._call("get", key)
        if value:
            return json.loads(value)
        with self.lock:
            item = self.local.get(key)
            if item and item[0] > time.monotonic():
                self.local.move_to_end(key)
                return item[1]
            self.local.pop(key, None)
            return None

    def set(self, key, value, ttl=30):
        self._call("set", key, json.dumps(value), ex=ttl)
        with self.lock:
            self.local[key] = (time.monotonic() + ttl, value)
            while len(self.local) > self.max_entries:
                self.local.popitem(last=False)


cache = ResilientCache()


class RateLimiter:
    """Bounded per-process token window. Redis outages never disable this lower safety bound."""

    def __init__(self, limit=120, window=60):
        self.limit, self.window = limit, window
        self.buckets = OrderedDict()
        self.lock = Lock()

    def allow(self, actor):
        with self.lock:
            start, count = self.buckets.get(actor, (time.monotonic(), 0))
            if time.monotonic() - start >= self.window:
                start, count = time.monotonic(), 0
            self.buckets[actor] = (start, count + 1)
            if len(self.buckets) > 1000:
                self.buckets.popitem(last=False)
            return count < self.limit


limiter = RateLimiter()
