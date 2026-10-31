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

# The browser stamps everything with Date.now(), so state travels in
# milliseconds. Older records (and the other client) used plain epoch seconds.
MS = 1000
SECONDS_LIMIT = 100 * 10 ** 9
# how far ahead a stamp may sit before it counts as a broken clock
FUTURE_SLACK = 5 * 60 * MS


def _now_ms():
    return int(time.time() * MS)


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
    """A timestamp in the milliseconds the browser compares against.

    A stamp from the future is not a clock we can reason about — some old
    clients wrote microseconds — so it counts as unknown instead of being
    pushed further forward. That matters for removals: an entry dated ahead of
    now can never be out-voted by the tombstone that removing it writes, so it
    would return on every sync and could never be deleted.
    """
    now = _now_ms()
    stamp = int(_number(value, 0, 10 ** 17, 0))
    if 0 < stamp < SECONDS_LIMIT:
        stamp *= MS
    if stamp <= 0 or stamp > now + FUTURE_SLACK:
        return 0
    return min(stamp, now)


def _path(value):
    """A page on this site, the only kind of link we hand back to a client."""
    value = _text(value, 500)
    if value.startswith("/") and not value.startswith("//"):
        return value
    return ""


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
        "href": _path(raw.get("href")),
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
        "dropped": {},
    }


def _meta(raw):
    """Resume-point metadata: known fields, and only those with a value.

    Empty strings are left out on purpose. The browser layers this over its
    catalog, so a blank here would erase a title, cover or language that the
    catalog does know.
    """
    item = _item(raw) or {}
    return {field: value for field, value in item.items() if value}


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

    cutoff = _now_ms() - TOMBSTONE_DAYS * 86400 * MS
    fresh = [(k, v) for k, v in removed.items() if v >= cutoff]
    fresh.sort(key=lambda pair: pair[1], reverse=True)
    return dict(fresh[:MAX_REMOVED])


def _merge_dropped(sources):
    """Ids removed from continue watching, newest timestamp wins."""
    dropped = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key, value in list(source.items())[:MAX_REMOVED * 2]:
            movie_id = _text(key, 64)
            stamp = _at(value)
            if movie_id and stamp > dropped.get(movie_id, 0):
                dropped[movie_id] = stamp

    cutoff = _now_ms() - TOMBSTONE_DAYS * 86400 * MS
    fresh = [(k, v) for k, v in dropped.items() if v >= cutoff]
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
                # An opened-but-not-yet-played page is a resume point of its
                # own; losing this flag hides the show from continue watching
                # as soon as the server copy comes back.
                "started": bool(raw.get("started")),
                "meta": _meta(raw.get("meta")) or None,
            }
            previous = out.get(movie_id)
            if previous is None:
                out[movie_id] = entry
                continue

            newer = entry if entry["at"] >= previous["at"] else previous
            older = previous if newer is entry else entry
            merged = dict(newer)
            # starting an episode is a fact that stays true for as long as the
            # entry exists, whichever device reported it first
            merged["started"] = bool(newer.get("started")) or bool(older.get("started"))
            # the newer record wins, but a field it does not know about (the
            # episode page it resumes, the cover) is better than an empty one
            meta = dict(newer.get("meta") or {})
            for field, value in (older.get("meta") or {}).items():
                if not meta.get(field):
                    meta[field] = value
            merged["meta"] = meta or None
            out[movie_id] = merged
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
                "href": item["href"],
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
                for field in ("id", "title", "cover", "url", "href", "year",
                              "lang")
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
    dropped = _merge_dropped([server.get("dropped"), incoming.get("dropped")])
    watchlist = _merge_watchlist([server.get("watchlist"),
                                  incoming.get("watchlist")], removed)
    catalog = _merge_catalog([server.get("catalog"), incoming.get("catalog")])

    # Finishing a film deletes the resume point locally. If the server still
    # holds the older one, drop it rather than sending the device backwards.
    for movie_id in list(progress):
        dropped_at = dropped.get(movie_id, 0)
        if dropped_at and dropped_at >= progress[movie_id]["at"]:
            del progress[movie_id]
            continue
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
        "dropped": dropped,
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
