"""
Talking to einthusan.

All network access lives here. No HTML, no framework, so both the Flask app
and the Vercel function can use it, and so it can be tested on its own.
"""

import difflib
import gzip
import http.client
import re
import ssl
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

HOST = "einthusan.tv"
CDN_HOST = "cdn2.einthusan.io"
COVER_BASE = "https://%s/etv/s3/moviecovers/" % CDN_HOST

CDN = "https://%s/etv/content/D{}.mp4" % CDN_HOST

LANGS = [
    ("tamil", "Tamil"),
    ("telugu", "Telugu"),
    ("hindi", "Hindi"),
    ("malayalam", "Malayalam"),
    ("kannada", "Kannada"),
    ("bengali", "Bengali"),
    ("marathi", "Marathi"),
    ("punjabi", "Punjabi"),
]
LANG_NAMES = dict(LANGS)
LANG_CODES = [c for c, _ in LANGS]

FETCH_TIMEOUT = 30
MAX_PAGES = 4
CACHE_TTL = 600

# Search optimises for a complete answer, not the fastest one. No result is
# dropped to beat a clock: every page that exists is fetched, and a page that
# errors is retried before it is given up on.
#
# The speed comes from the pool below, not from cutting work. TLS setup is
# almost the entire cost of a cold search, and a pooled thread keeps its
# keep-alive connection, so search two onward is a plain round trip.
SEARCH_TIMEOUT = 12
SEARCH_ATTEMPTS = 2

# Above this the query is considered present as typed and nothing is widened.
# Below it we shorten the first word and look for titles that are close.
GOOD_MATCH = 0.62
# Candidates below this are noise from an over-wide prefix.
SIMILAR_ENOUGH = 0.45
# Four shortened prefixes is enough to walk past a typo near the end of a word.
MAX_FALLBACKS = 4

_search_pool = None
_search_pool_lock = threading.Lock()
_SEARCH_PROBE = "/movie/results/?alpha=A&find=Alphabets&lang=tamil&page=1"

_pools = threading.local()
_cache = {}
_cache_lock = threading.Lock()


# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------


def http_get(path, host=HOST, redirects=3, timeout=None):
    """GET over a pooled keep-alive socket.

    A TLS handshake to einthusan costs about half a second, so reusing the
    socket is what keeps a multi-page search at roughly one second instead of
    four. Connections are per-thread.
    """
    pool = getattr(_pools, "conns", None)
    if pool is None:
        pool = _pools.conns = []

    conn = None
    for candidate in pool:
        if candidate.sock is not None and candidate.host == host:
            conn = candidate
            break
    if conn is None:
        conn = http.client.HTTPSConnection(
            host, timeout=timeout or FETCH_TIMEOUT,
            context=ssl.create_default_context())
        pool.append(conn)

    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Encoding": "gzip",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    }

    try:
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()

        if resp.status in (301, 302, 303, 307, 308) and redirects > 0:
            location = resp.headers.get("Location", "")
            conn.close()
            if location.startswith("/"):
                return http_get(location, host, redirects - 1)
            parts = urllib.parse.urlsplit(location)
            if parts.scheme in ("http", "https"):
                tail = parts.path + (("?" + parts.query) if parts.query else "")
                return http_get(tail, parts.hostname, redirects - 1)

        if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
            raw = gzip.decompress(raw)
        if resp.will_close:
            conn.close()
        return raw.decode("utf-8", "replace")
    except Exception:
        conn.close()
        raise


def strip_tags(fragment):
    import html as html_mod
    return html_mod.unescape(re.sub(r"<[^>]*>", "", fragment)).strip()


def collapse(text):
    return re.sub(r"\s+", " ", text).strip()


def cached(key, producer):
    now = time.time()
    with _cache_lock:
        entry = _cache.get(key)
        if entry and now - entry[0] < CACHE_TTL:
            return entry[1]
    value = producer()
    if value is None:
        return None
    with _cache_lock:
        _cache[key] = (now, value)
    return value


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

_WATCH = re.compile(r"/movie/watch/([A-Za-z0-9]{4})")
_CONTENT = re.compile(r"/content/D([A-Za-z0-9]{4})\.mp4", re.I)
_BARE = re.compile(r"^[A-Za-z0-9]{4}$")
_COVER = re.compile(r"moviecovers/([A-Za-z0-9]+-[a-z0-9]+)\.jpg")


def parse_results_page(doc):
    """Pull (items, total_pages, total_count) out of a /movie/results/ page."""
    start = doc.find('<section id="UIMovieSummary">')
    if start == -1:
        return [], 0, 0
    tail = doc[start:]
    end = tail.find("<section id=", 10)
    body = tail[:end] if end != -1 else tail

    items = []
    for chunk in re.findall(r"<li>(.*?)</li>", body, re.S):
        mid = _WATCH.search(chunk)
        if not mid:
            continue

        heading = re.search(r"<h3[^>]*>(.*?)</h3>", chunk, re.S)
        title = collapse(strip_tags(heading.group(1))) if heading else ""
        if not title:
            continue

        meta = re.search(r"<p>\s*(\d{4})\s*<span>([^<]*)</span>", chunk)
        cover = _COVER.search(chunk)

        items.append({
            "id": mid.group(1),
            "title": title,
            "year": meta.group(1) if meta else "",
            "lang": collapse(strip_tags(meta.group(2))) if meta else "",
            "cover": COVER_BASE + cover.group(1) + ".jpg" if cover else None,
            "url": CDN.format(mid.group(1)),
        })

    pages_m = re.search(r"Page\s+\d+\s+of\s+(\d+)", doc)
    count_m = re.search(r"\(\s*(\d+)\s*results", doc)
    return (
        items,
        int(pages_m.group(1)) if pages_m else 0,
        int(count_m.group(1)) if count_m else 0,
    )


def fetch_prefix_page(term, lang, page, attempts=3, timeout=None):
    """Page is 1-based: page=0 returns an upsell page with no rows.

    Returns None when every attempt failed, which is deliberately distinct
    from "no matches" so a dropped request never looks like an empty result.
    """
    path = "/movie/results/?alpha={}&find=Alphabets&lang={}&page={}".format(
        urllib.parse.quote(term, safe=""), urllib.parse.quote(lang), page
    )
    for attempt in range(attempts):
        try:
            items, pages, count = parse_results_page(http_get(path, timeout=timeout))
            if items or pages:
                return items, pages, count
        except Exception:
            pass
        if attempt + 1 < attempts:
            time.sleep(0.4 * (attempt + 1))
    return None


def fetch_and_paginate(term, lang, max_pages=MAX_PAGES):
    head = fetch_prefix_page(term, lang, 1)
    if head is None:
        return None
    items, total_pages, total_count = head
    for page in range(2, min(total_pages, max_pages) + 1):
        got = fetch_prefix_page(term, lang, page)
        if got:
            items.extend(got[0])
    return items, total_pages, total_count


def exists(prefix, lang):
    """True only when this exact prefix matches something.

    search() falls back to a shorter prefix when nothing is found, which is
    right for a human but wrong for checking a suggestion: it would accept
    "Velaiyilla Pattathu" because "Velaiyilla" happens to match a film. This
    deliberately does no fallback.
    """
    got = fetch_and_paginate(prefix, lang, max_pages=1)
    return bool(got and got[0])


def lookup(prefix, lang, limit=1):
    """First matches for an exact prefix. No fallback, so it is safe for
    checking a guess: if this is empty, the catalogue really has nothing
    under that spelling."""
    got = fetch_and_paginate(prefix, lang, max_pages=1)
    return got[0][:limit] if got and got[0] else []


def resolve(titles, lang, per_title=1):
    """Turn guessed titles into real, playable records with cover art."""
    def one(title):
        try:
            return title, lookup(title, lang, per_title)
        except Exception:
            return title, []

    out, seen = [], set()
    with ThreadPoolExecutor(max_workers=6) as pool:
        for _title, items in pool.map(one, list(titles)[:20]):
            for item in items:
                if item["id"] in seen:
                    continue
                seen.add(item["id"])
                out.append(item)
    return out


def shorter_prefix(term):
    """The part of a query before its first space or punctuation mark."""
    cleaned = term.strip()
    stop = re.search(r"[^A-Za-z0-9]", cleaned)
    if not stop:
        return None
    head = cleaned[:stop.start()].strip()
    return head or None


def search_pool():
    """One worker per language, kept alive between requests so each thread
    reuses the TLS connection it already paid for."""
    global _search_pool
    if _search_pool is None:
        with _search_pool_lock:
            if _search_pool is None:
                _search_pool = ThreadPoolExecutor(
                    max_workers=len(LANG_CODES),
                    thread_name_prefix="einthusan")
    return _search_pool


def warm():
    """Open every worker's connection up front. Called once by the local dev
    server, so the first real search is already on a warm socket."""
    def probe(_i):
        try:
            http_get(_SEARCH_PROBE, timeout=8)
        except Exception:
            pass
    list(search_pool().map(probe, range(len(LANG_CODES))))


def _cache_get(key):
    now = time.time()
    with _cache_lock:
        entry = _cache.get(key)
        if entry and now - entry[0] < CACHE_TTL:
            return entry[1]
    return None


def _cache_put(key, value):
    with _cache_lock:
        _cache[key] = (time.time(), value)


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def similarity(query, title):
    """How close a catalogue title is to what was typed.

    Plain edit distance alone punishes a long title for one typo in the middle,
    and token overlap alone ignores spelling, so this takes whichever thinks
    the two are more alike. That is what lets "Vishwananth and Sons" reach
    "Vishwanath and Sons".
    """
    q, t = _norm(query), _norm(title)
    if not q or not t:
        return 0.0

    ratio = difflib.SequenceMatcher(None, q, t).ratio()
    qwords = q.split()
    twords = t.split()
    shared = sum(1 for word in qwords if word in twords)
    tokens = shared / max(1, len(qwords))
    return max(ratio, 0.55 * ratio + 0.45 * tokens)


def prefix_candidates(term):
    """Shorter and shorter starts of the first word, longest first. The first
    word is the anchor because the catalogue indexes from the first letter, so
    a prefix of a later word would match nothing."""
    words = _norm(term).split()
    if not words:
        return []

    first = words[0]
    out = []
    for length in range(len(first) - 1, 2, -1):
        piece = first[:length]
        if piece not in out:
            out.append(piece)
        if len(out) >= MAX_FALLBACKS:
            break
    return out


def search(term, lang):
    """(items, total_pages, total_count, used_prefix) or None on total failure.

    Page one is fetched first because it is the only page that knows how many
    follow; the rest are then fetched together.

    If nothing close to the query came back, the first word is shortened and
    the catalogue is asked again. A typo near the end of a word ("Vishwananth")
    still shares a long enough prefix with the real title ("Vishwanath") to
    find it, and the candidates are ranked by similarity so the intended film
    sits above the near misses.
    """
    key = ("search", term.lower(), lang)
    hit = _cache_get(key)
    if hit is not None:
        return hit

    head = fetch_prefix_page(term, lang, 1, attempts=SEARCH_ATTEMPTS,
                             timeout=SEARCH_TIMEOUT)
    if head is None:
        return None

    items = list(head[0])
    pages, count = head[1], head[2]

    extra = list(range(2, min(pages, MAX_PAGES) + 1))
    if extra:
        pool = search_pool()
        futures = [pool.submit(fetch_prefix_page, term, lang, page,
                               SEARCH_ATTEMPTS, SEARCH_TIMEOUT)
                   for page in extra]
        for future in futures:
            try:
                got = future.result()
            except Exception:
                got = None
            if got:
                items.extend(got[0])

    seen = {item["id"] for item in items}
    best = max((similarity(term, item["title"]) for item in items), default=0.0)
    used = term

    if best < GOOD_MATCH:
        for prefix in prefix_candidates(term):
            got = fetch_prefix_page(prefix, lang, 1, attempts=SEARCH_ATTEMPTS,
                                    timeout=SEARCH_TIMEOUT)
            if not got:
                continue
            used = prefix
            for item in got[0]:
                if item["id"] not in seen:
                    seen.add(item["id"])
                    items.append(item)
            best = max(best, max((similarity(term, item["title"])
                                  for item in got[0]), default=0.0))
            if best >= GOOD_MATCH:
                break

        if items:
            items.sort(key=lambda item: similarity(term, item["title"]),
                       reverse=True)
            close = [item for item in items
                     if similarity(term, item["title"]) >= SIMILAR_ENOUGH]
            items = close or items

    result = (items, pages, count, used)
    _cache_put(key, result)
    return result


# --------------------------------------------------------------------------
# browse
# --------------------------------------------------------------------------


def _featured_entry(head, tail):
    """One billboard slot: .block1 holds the cover and runtime, .block2 the
    title, year, language, genres and the imdb link."""
    mid = _WATCH.search(head)
    heading = re.search(r"<h2>(.*?)</h2>", tail, re.S)
    if not mid or not heading:
        return None

    year = lang = ""
    info = re.search(r'<div class="info">(.*?)</div>', tail, re.S)
    if info:
        yl = re.search(r"<p>\s*(\d{4})\s*<span>([^<]*)</span>", info.group(1))
        if yl:
            year = yl.group(1)
            lang = collapse(strip_tags(yl.group(2)))

    # the average-rating labels are scoring criteria, not genres, and the
    # runtime field is the same placeholder on every slide, so neither is used
    imdb = re.search(r'href="(https://www\.imdb\.com/title/tt\d+)/?"', tail)
    trailer = re.search(r'href="(https://www\.youtube\.com/watch\?v=[\w-]+)"', tail)
    cover = _COVER.search(head)

    cast = []
    crew = re.search(r'<div class="professionals">(.*?)</div></div></div>', tail, re.S)
    if crew:
        for name, role in re.findall(r"<p>([^<]*)</p>\s*<label>([^<]*)</label>",
                                     crew.group(1)):
            person = {"name": collapse(strip_tags(name)),
                      "role": collapse(strip_tags(role))}
            if person["name"]:
                cast.append(person)

    return {
        "id": mid.group(1),
        "title": collapse(strip_tags(heading.group(1))),
        "year": year,
        "lang": lang,
        "cover": COVER_BASE + cover.group(1) + ".jpg" if cover else None,
        "imdb": imdb.group(1) if imdb else "",
        "trailer": trailer.group(1) if trailer else "",
        "cast": cast,
        "url": CDN.format(mid.group(1)),
    }


def _showcase_items(view):
    items = []
    for li in re.findall(r"<li>(.*?)</li>", view, re.S):
        mid = _WATCH.search(li)
        title = re.search(r'class="title">([^<]*)<', li)
        if not mid or not title:
            continue
        cover = _COVER.search(li)
        items.append({
            "id": mid.group(1),
            "title": collapse(strip_tags(title.group(1))),
            "cover": COVER_BASE + cover.group(1) + ".jpg" if cover else None,
            "year": "",
            "lang": "",
            "url": CDN.format(mid.group(1)),
        })
    return items


def parse_browse_page(doc):
    """The home page's own content: featured films and the five showcase
    rails. Returns {"featured": [...], "shelves": [{"title", "items"}]}."""
    featured = []
    start = doc.find('<section id="UIFeaturedFilms">')
    if start != -1:
        end = doc.find('<section id="UIShowcasedFilms">')
        chunk = doc[start:end if end > start else len(doc)]
        for part in chunk.split('<div class="block1">')[1:]:
            cut = part.find('<div class="block2">')
            head = part[:cut] if cut != -1 else part
            tail = part[cut:] if cut != -1 else ""
            entry = _featured_entry(head, tail)
            if entry:
                featured.append(entry)

    shelves = []
    start = doc.find('<section id="UIShowcasedFilms">')
    if start != -1:
        end = doc.find('<section id="UIFooter">')
        chunk = doc[start:end if end > start else len(doc)]
        labels = [collapse(strip_tags(t)) for t in
                  re.findall(r"<label[^>]*>\s*<p>([^<]*)</p>", chunk)]
        for i, view in enumerate(chunk.split('<div class="tabview">')[1:]):
            items = _showcase_items(view)
            if items:
                shelves.append({
                    "title": labels[i] if i < len(labels) else "Films",
                    "items": items,
                })

    return {"featured": featured, "shelves": shelves}


def browse(lang=None):
    """Home content for one language, or every language when lang is None."""
    lang = lang if lang in LANG_CODES else None

    def produce():
        path = "/movie/browse/"
        if lang:
            path += "?lang=" + urllib.parse.quote(lang)
        return parse_browse_page(http_get(path))

    return cached(("browse", lang or "all"), produce)


# --------------------------------------------------------------------------
# link helpers
# --------------------------------------------------------------------------


def extract_id(raw):
    """The 4-character id from a watch url, a cdn url, or a bare id."""
    import html as html_mod
    text = html_mod.unescape(raw or "").strip().strip("<>\"'")
    if not text:
        return None
    for pattern in (_WATCH, _CONTENT):
        found = pattern.search(text)
        if found:
            return found.group(1)
    return text if _BARE.match(text) else None


def cdn_link(movie_id):
    return CDN.format(movie_id)
