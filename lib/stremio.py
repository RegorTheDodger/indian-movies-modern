"""
The two Stremio addons behind the library pages.

Cinemeta answers every metadata question: search, posters, backgrounds,
descriptions, cast, ratings, runtime and the episode list for a series.
It sends no CORS headers, so the browser never calls it; the server does and
renders the result.

No HTML and no Flask live here, so the local server, the Vercel function and
the Lumia build all share this code.
"""

import hashlib
import json
import os
import re
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

CINEMETA = (os.environ.get("CINEMETA_URL")
            or "https://v3-cinemeta.strem.io").rstrip("/")

META_TTL = 600
LIST_TTL = 300
# A failed lookup is remembered only briefly, so a provider that was down for
# one request is asked again on the next page instead of staying broken.
FAIL_TTL = 30

_lock = threading.Lock()
_cache = {}
# One fetch per URL even when a prefetch and a page ask for it at once.
_inflight = {}

# ---------------------------------------------------------------- transport


def _get_json(url, ttl=LIST_TTL, timeout=15):
    """Fetch JSON, with a small in-process cache.

    Two attempts only: these are metadata calls on a page a person is waiting
    for, so a provider having a bad minute must not stall the page.
    """
    now = time.time()
    with _lock:
        hit = _cache.get(url)
        if hit and now < hit[0]:
            return hit[1]
        # an expired entry is still better than an empty page when the
        # provider is having a slow minute
        stale = hit[1] if hit and hit[1] is not None else None

    with _lock:
        event = _inflight.get(url)
        owner = event is None
        if owner:
            event = threading.Event()
            _inflight[url] = event

    if not owner:
        # somebody is already fetching this exact URL: wait for their answer
        event.wait(timeout + 1)
        with _lock:
            hit = _cache.get(url)
        if hit:
            return hit[1]

    data = None
    for attempt in range(2):
        try:
            request = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "application/json,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            })
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read(8 * 1024 * 1024)
            data = json.loads(raw.decode("utf-8", "replace"))
            break
        except Exception:
            data = None
            if attempt == 0:
                time.sleep(0.25)

    with _lock:
        event = _inflight.pop(url, None)
        if data is None and stale is not None:
            _cache[url] = (now + FAIL_TTL, stale)
            data = stale
        else:
            _cache[url] = (now + (ttl if data is not None else FAIL_TTL), data)
    if event is not None:
        event.set()
    return data


# A search is the one call somebody waits on, so its answer also goes to a
# file cache: a repeat query (or a cold Vercel instance) renders at once.
_DISK_TTL = 86400


def _disk_path(key):
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    return os.path.join(tempfile.gettempdir(), "indianmovies-cache",
                        digest + ".json")


def _disk_get(key, ttl=_DISK_TTL):
    try:
        with open(_disk_path(key), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if time.time() - float(payload.get("at") or 0) > ttl:
            return None
        items = payload.get("items")
        return items if isinstance(items, list) else None
    except Exception:
        return None


def _disk_put(key, items):
    path = _disk_path(key)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"at": time.time(), "items": items}, handle)
    except Exception:
        pass


# ------------------------------------------------------------------ shaping


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _year(raw):
    text = str(raw.get("year") or raw.get("releaseInfo") or "")
    found = re.search(r"(19|20)\d{2}", text)
    return found.group(0) if found else ""


def _poster(url):
    return (url or "").replace("/small/", "/medium/")


def normalise(raw, kind=None):
    """One shape for a card, whether it came from search or a catalog."""
    kind = raw.get("type") or kind or "movie"
    popularity = 0.0
    popularities = raw.get("popularities") or {}
    if isinstance(popularities, dict):
        popularity = float(popularities.get("stremio") or 0)
    return {
        "id": raw.get("id") or raw.get("imdb_id") or "",
        "type": "series" if kind == "series" else "movie",
        "name": raw.get("name") or "",
        "year": _year(raw),
        "poster": _poster(raw.get("poster")),
        "background": raw.get("background") or "",
        "description": raw.get("description") or "",
        "rating": raw.get("imdbRating") or "",
        "genres": raw.get("genre") or raw.get("genres") or [],
        "cast": raw.get("cast") or [],
        "popularity": popularity,
    }


_WORD = re.compile(r"[a-z0-9]+")
_LEAD = re.compile(r"^(?:the|a|an)\s+", re.I)


def _tokens(text):
    return _WORD.findall((text or "").lower())


def _compact(text):
    """Letters and digits only: "Spider-Man 3" and "spiderman3" agree."""
    return "".join(_tokens(_LEAD.sub("", text or "")))


def _rank(query, name):
    """Lower is closer, 9 means unrelated and is dropped.

    Punctuation and spacing are ignored first, because people type
    "spiderman 3" for "Spider-Man 3". Failing that, whole words may be
    abbreviated in either direction, which is what makes "monsters" also
    find "Monster House" without dragging in every title with a stray word.
    """
    query = (query or "").strip()
    qtokens = _tokens(_LEAD.sub("", query))
    if not qtokens or not (name or "").strip():
        return 9

    qcompact = "".join(qtokens)
    stripped = _LEAD.sub("", name.lower())
    compact = "".join(_tokens(stripped))
    if not compact:
        return 9

    # literally what was typed wins, so "alien" puts Alien above Alien³
    if name.strip().lower() == query.lower():
        return 0
    # "the office" should find The Office; "spiderman 3" should find
    # "Spider-Man 3". Same title once punctuation and spacing are ignored.
    if compact == qcompact or "".join(_tokens(name.lower())) == qcompact:
        return 1
    if compact.startswith(qcompact):
        return 2
    if qcompact in compact:
        return 3

    ntokens = _tokens(stripped)
    if all(any(word.startswith(token) for word in ntokens) for token in qtokens):
        return 4
    # "monsters" -> "Monster House": one extra letter on the word the title
    # starts with. Deliberately narrow, so a stray word cannot drag in junk.
    if len(qtokens) == 1 and ntokens:
        head = ntokens[0]
        if (len(head) >= 4 and qtokens[0].startswith(head)
                and len(qtokens[0]) - len(head) <= 2):
            return 5
    return 9


def _extra_path(extra):
    return "/".join(
        "%s=%s" % (key, urllib.parse.quote(str(extra[key]), safe=""))
        for key in sorted(extra))


def catalog(kind, catalog_id, extra=None, timeout=8):
    """Cinemeta takes extras in the path: /catalog/movie/top/search=x.json.

    The older ?extra={...} form answers a search with unrelated titles (or
    nothing) and is kept only as a fallback for mirrors that need it.
    """
    base = "%s/catalog/%s/%s" % (CINEMETA, kind, catalog_id)
    url = ("%s/%s.json" % (base, _extra_path(extra))) if extra else base + ".json"
    metas = (_get_json(url, ttl=LIST_TTL, timeout=timeout) or {}).get("metas") or []
    if not metas and extra:
        url = base + ".json?extra=" + urllib.parse.quote(
            json.dumps(extra, separators=(",", ":")))
        metas = (_get_json(url, ttl=LIST_TTL, timeout=timeout) or {}).get("metas") or []
    return [normalise(meta, kind) for meta in metas if meta.get("id")]


def popular(kind, catalog_id="top"):
    return catalog(kind, catalog_id, timeout=8)


def _search_kind(kind, query, timeout):
    """One type's search. The searchable catalog is `top` with a search
    extra; `search` as a catalog id is the older, wrong guess."""
    items = catalog(kind, "top", {"search": query}, timeout=timeout)
    if not items:
        items = catalog(kind, "search", {"search": query}, timeout=timeout)
    return items


def search(query, kinds=("movie", "series")):
    """Search both types at once and keep only titles the query resembles.

    Cinemeta's search is generous: "obsession" comes back with a dozen
    unrelated series. Here every result must clear the ranking ladder, so the
    page shows the film somebody asked for and close variants of its name,
    nothing else. Both types are asked in parallel under a hard deadline,
    because this is the one call waiting on a person.
    """
    query = re.sub(r"\s+", " ", (query or "").strip())[:80]
    if not query:
        return []

    cache_key = "search|" + query.lower()
    cached = _disk_get(cache_key)
    if cached is not None:
        return cached

    # "monsters" should also find "Monster House": Cinemeta indexes whole
    # titles, and its index has no plural form, so ask for both at once.
    variants = [query]
    lowered = query.lower()
    if len(lowered.split()) == 1 and len(lowered) > 4 and lowered.endswith("s"):
        variants.append(lowered[:-1])

    found, seen = [], set()
    jobs = [(kind, variant) for kind in kinds for variant in variants]
    pool = ThreadPoolExecutor(max_workers=max(1, len(jobs)))
    try:
        # two seconds, hard. A provider having a slow minute costs one type,
        # never the whole search, and the answer is cached for the next one.
        futures = [pool.submit(_search_kind, kind, variant, 2.2)
                   for kind, variant in jobs]
        for future in futures:
            try:
                items = future.result(timeout=2.6)
            except Exception:
                items = []
            for item in items:
                key = (item["type"], item["id"])
                if not item["id"] or key in seen:
                    continue
                seen.add(key)
                found.append(item)
    finally:
        pool.shutdown(wait=False)

    ranked = []
    for item in found:
        score = _rank(query, item["name"])
        if score > 5:
            continue
        literal = "".join(_tokens(item["name"].lower()))
        exact = 0 if literal == "".join(_tokens(query.lower())) else 1
        ranked.append((score, exact, -item["popularity"],
                       -(_int(item["year"]) or 0), item["name"], item))
    ranked.sort(key=lambda row: row[:5])
    # row is (score, exact, -popularity, -year, name, item)
    out = [row[5] for row in ranked[:48]]

    if out:
        _disk_put(cache_key, out)
    return out


def _videos(raw):
    out = []
    for entry in raw or []:
        season = _int(entry.get("season"))
        episode = _int(entry.get("episode", entry.get("number")))
        if season is None or episode is None:
            continue
        out.append({
            "id": entry.get("id") or "",
            "season": season,
            "episode": episode,
            "name": entry.get("name") or "",
            "overview": entry.get("overview") or "",
            "released": (entry.get("released") or "")[:10],
            "thumbnail": entry.get("thumbnail") or "",
        })
    out.sort(key=lambda item: (item["season"], item["episode"]))
    return out


def meta(kind, media_id):
    """Everything Cinemeta knows about one title, in our own shape."""
    url = "%s/meta/%s/%s.json" % (CINEMETA, kind, media_id)
    data = _get_json(url, ttl=META_TTL, timeout=20)
    raw = (data or {}).get("meta")
    if not raw:
        return None

    item = normalise(raw, kind)
    trailers = raw.get("trailers") or []
    trailer = ""
    if trailers and isinstance(trailers[0], dict):
        trailer = trailers[0].get("source") or ""

    imdb_id = raw.get("imdb_id") or (media_id if str(media_id).startswith("tt") else "")
    item.update({
        "background": raw.get("background") or item["background"],
        "logo": raw.get("logo") or "",
        "runtime": raw.get("runtime") or "",
        "status": raw.get("status") or "",
        "released": (raw.get("released") or "")[:10],
        "awards": raw.get("awards") or "",
        "country": raw.get("country") or "",
        "genres": raw.get("genre") or raw.get("genres") or item["genres"],
        "cast": raw.get("cast") or item["cast"],
        "directors": raw.get("director") or [],
        "writers": raw.get("writer") or [],
        "trailer": trailer,
        "imdb": ("https://www.imdb.com/title/%s/" % imdb_id) if imdb_id else "",
        "videos": _videos(raw.get("videos")),
        "year_label": str(raw.get("year") or item["year"]),
    })
    return item


def seasons(meta_item):
    seen = []
    for video in meta_item.get("videos") or []:
        if video["season"] not in seen:
            seen.append(video["season"])
    return seen


def episodes_for(meta_item, season):
    return [video for video in meta_item.get("videos") or []
            if video["season"] == season]
