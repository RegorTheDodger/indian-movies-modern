"""Merging the personal state of two devices.

The browser has always owned the list, the resume points and the watch time.
When sync is on, every device posts its whole copy and the server returns the
merged result. Merging (rather than last-write-wins) is what makes a phone and
a laptop safe to use on the same account: a film added on one is not erased by
an older copy from the other.

Rules
  watchlist  one entry per id, the newest add wins; a removal is a tombstone
             with a timestamp, so a stale device cannot resurrect a film
  progress   one entry per id, the newest `at` wins
  watched    one entry per id, the newest entry wins but seconds keep the
             larger tally (playtime accumulates independently per device)
  catalog    titles and covers, field by field; a known value is never
             replaced by an empty one

Every value is normalised and capped so a broken client cannot post a
gigabyte of junk or a `javascript:` cover.
"""

import json
import math
import time

MAX_STATE = 400 * 1024
MAX_WATCHLIST = 500
MAX_PROGRESS = 1000
MAX_WATCHED = 1000
MAX_CATALOG = 1000
MAX_REMOVED = 500
TOMBSTONE_DAYS = 180


def _text(value, limit):
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def _number(value, low, high, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(low, min(high, number))


def _at(value):
    return int(_number(value, 0, time.time() + 86400, 0))


def _cover(value):
    value = _text(value, 500)
    if value.startswith(("http://", "https://", "//")):
        return value
    return ""


def _item(raw):
    """A film as every shelf understands it."""
    if not isinstance(raw, dict):
        return None
    movie_id = _text(raw.get("id"), 64)
    if not movie_id:
        return None
    return {
        "id": movie_id,
        "title": _text(raw.get("title"), 200) or movie_id,
        "cover": _cover(raw.get("cover")),
        "url": _text(raw.get("url"), 500),
        "year": _text(raw.get("year"), 12),
        "lang": _text(raw.get("lang"), 20),
    }


def empty():
    return {
        "watchlist": [],
        "removed": {},
        "progress": {},
        "watched": {},
        "catalog": {},
    }


def _merge_removed(sources):
    removed = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key, value in list(source.items())[:MAX_REMOVED * 2]:
            movie_id = _text(key, 64)
            stamp = _at(value)
            if movie_id and stamp > removed.get(movie_id, 0):
                removed[movie_id] = stamp

    cutoff = int(time.time()) - TOMBSTONE_DAYS * 86400
    fresh = [(k, v) for k, v in removed.items() if v >= cutoff]
    fresh.sort(key=lambda pair: pair[1], reverse=True)
    return dict(fresh[:MAX_REMOVED])


def _merge_watchlist(sources, removed):
    entries = {}
    for source in sources:
        if not isinstance(source, list):
            continue
        for raw in source[:MAX_WATCHLIST * 2]:
            item = _item(raw)
            if not item:
                continue
            item["at"] = _at(raw.get("at"))
            previous = entries.get(item["id"])
            if (previous is None or item["at"] > previous["at"]
                    or (item["at"] == previous["at"]
                        and len(item["title"]) > len(previous["title"]))):
                entries[item["id"]] = item

    kept = [item for item in entries.values()
            if removed.get(item["id"], 0) < item["at"]]
    kept.sort(key=lambda item: item["at"], reverse=True)
    return kept[:MAX_WATCHLIST]


def _merge_progress(sources):
    out = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key, raw in list(source.items())[:MAX_PROGRESS * 2]:
            movie_id = _text(key, 64)
            if not movie_id or not isinstance(raw, dict):
                continue
            duration = int(_number(raw.get("duration"), 0, 10 ** 8))
            if duration <= 0:
                continue
            seconds = int(_number(raw.get("seconds"), 0, duration))
            entry = {
                "seconds": seconds,
                "duration": duration,
                "at": _at(raw.get("at")),
                "meta": _item(raw.get("meta")),
            }
            previous = out.get(movie_id)
            if previous is None or entry["at"] > previous["at"]:
                out[movie_id] = entry
    return dict(list(out.items())[:MAX_PROGRESS])


def _merge_watched(sources):
    out = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key, raw in list(source.items())[:MAX_WATCHED * 2]:
            movie_id = _text(key, 64)
            if not movie_id or not isinstance(raw, dict):
                continue
            item = _item(raw)
            if not item:
                continue
            entry = {
                "id": movie_id,
                "title": item["title"],
                "cover": item["cover"],
                "url": item["url"],
                "year": item["year"],
                "lang": item["lang"],
                "seconds": int(_number(raw.get("seconds"), 0, 10 ** 9)),
                "finished": bool(raw.get("finished")),
                "at": _at(raw.get("at")),
            }
            previous = out.get(movie_id)
            if previous is None:
                out[movie_id] = entry
                continue

            # The newer record carries the better metadata, but play time is
            # cumulative per device: never let a synced copy reduce it.
            newer = entry["at"] >= previous["at"]
            merged = dict(entry if newer else previous)
            merged["seconds"] = max(entry["seconds"], previous["seconds"])
            merged["finished"] = entry["finished"] or previous["finished"]
            merged["at"] = max(entry["at"], previous["at"])
            out[movie_id] = merged
    return dict(list(out.items())[:MAX_WATCHED])


def _merge_catalog(sources):
    out = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key, raw in list(source.items())[:MAX_CATALOG * 2]:
            movie_id = _text(key, 64)
            if not movie_id:
                continue
            item = _item(raw)
            if not item:
                continue
            item["id"] = movie_id
            previous = out.get(movie_id, {})
            out[movie_id] = {
                field: item.get(field) or previous.get(field) or ""
                for field in ("id", "title", "cover", "url", "year", "lang")
            }
    return dict(list(out.items())[:MAX_CATALOG])


def merge(server, incoming):
    if not isinstance(server, dict):
        server = {}
    if not isinstance(incoming, dict):
        incoming = {}

    sources = (server, incoming)
    removed = _merge_removed([server.get("removed"), incoming.get("removed")])
    watched = _merge_watched([server.get("watched"), incoming.get("watched")])
    progress = _merge_progress([server.get("progress"), incoming.get("progress")])
    watchlist = _merge_watchlist([server.get("watchlist"),
                                  incoming.get("watchlist")], removed)
    catalog = _merge_catalog([server.get("catalog"), incoming.get("catalog")])

    # Finishing a film deletes the resume point locally. If the server still
    # holds the older one, drop it rather than sending the device backwards.
    for movie_id in list(progress):
        finished = watched.get(movie_id)
        if finished and finished.get("finished"):
            if finished["at"] >= progress[movie_id]["at"]:
                del progress[movie_id]

    state = {
        "watchlist": watchlist,
        "removed": removed,
        "progress": progress,
        "watched": watched,
        "catalog": catalog,
    }
    return state


def encoded(state):
    return json.dumps(state, separators=(",", ":"), sort_keys=True)


def load(raw):
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def summary(state):
    """Two numbers for the account page, nothing more."""
    state = state if isinstance(state, dict) else {}
    return {
        "saved": len(state.get("watchlist") or []),
        "watching": len(state.get("progress") or {}),
    }
