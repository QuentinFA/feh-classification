"""Throttled HTTP GET with an on-disk cache, so re-runs don't hit the sites again."""
import hashlib
import json
import os
import time

import requests

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "cache")
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

_session = requests.Session()
_last_call = {}


def _throttle(host, delay):
    wait = _last_call.get(host, 0) + delay - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_call[host] = time.time()


def get(url, params=None, *, delay=1.5, binary=False, refresh=False, headers=None):
    """GET url (cached). Returns text, or bytes when binary=True."""
    key = url + ("?" + json.dumps(params, sort_keys=True) if params else "")
    path = os.path.join(CACHE_DIR, hashlib.sha1(key.encode()).hexdigest())
    if not refresh and os.path.exists(path):
        with open(path, "rb") as f:
            data = f.read()
        return data if binary else data.decode("utf-8")

    host = requests.utils.urlparse(url).netloc
    hdrs = {"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"}
    hdrs.update(headers or {})
    for attempt in range(6):
        _throttle(host, delay)
        r = _session.get(url, params=params, headers=hdrs, timeout=30)
        # Fandom answers rate limiting with HTTP 200 + an error payload
        limited = r.status_code in (202, 429, 503) or (
            not binary and '"code":"ratelimited"' in r.text.replace(" ", ""))
        if not limited:
            break
        time.sleep(15 * (attempt + 1))
    r.raise_for_status()
    if limited:
        raise RuntimeError(f"still rate limited: {url}")

    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "wb") as f:
        f.write(r.content)
    return r.content if binary else r.text
