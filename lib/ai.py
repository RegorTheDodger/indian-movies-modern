"""
Optional Groq assist.

Used for three things, all of which fail quietly:

  suggest()  correct the spelling when a search returns nothing

Everything is optional. Without GROQ_API_KEY in the environment this module
does nothing and the site still works.
"""

import json
import os
import urllib.error
import urllib.request

ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

# Tried in order, first usable answer wins. Groq rotates its lineup, and the
# key in use may not reach every model, so this is a chain not a single name.
MODELS = ["qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"]

TIMEOUT = 8

# Groq answers 403 to urllib's default User-Agent, so always send our own.
HEADERS_EXTRA = {"User-Agent": "indian-movies-legacy/1.0"}

SYSTEM = (
    "You help someone find an Indian film in a catalogue that only indexes "
    "titles alphabetically. Given what they typed, reply with the most likely "
    "correct film titles. Reply with a JSON array of strings only, no prose, "
    "no markdown. At most 5 suggestions, most likely first. If you genuinely "
    "have no idea, reply with an empty array []."
)

SYSTEM_TASTE = (
    "You pick Indian films for one specific person, based on what they have "
    "already watched and saved. Match the language, the era and the mood of "
    "what they already like. Reply with a JSON array of real film titles "
    "only, no prose, no markdown, no numbering. Between 8 and 12 titles, best "
    "first. Only include films you are confident exist. If the list they give "
    "you is empty, pick well-known films in the requested language instead."
)


def enabled():
    return bool(os.environ.get("GROQ_API_KEY"))


def _post(model, system, user, max_tokens):
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return None

    body = json.dumps({
        "model": model,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }).encode("utf-8")

    headers = {
        "Authorization": "Bearer %s" % key,
        "Content-Type": "application/json",
    }
    headers.update(HEADERS_EXTRA)

    req = urllib.request.Request(ENDPOINT, data=body, method="POST",
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]
    except (urllib.error.URLError, OSError, ValueError, KeyError,
            IndexError, TypeError):
        return None


def _texts(message):
    """The reply, as a string. Reasoning models answer under "reasoning"."""
    if not isinstance(message, dict):
        return ""
    for field in ("content", "reasoning"):
        value = message.get(field)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _extract(message, opener, closer):
    text = _texts(message)
    start, end = text.find(opener), text.rfind(closer)
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return None


def _ask_array(system, user, max_tokens=160):
    for model in MODELS:
        parsed = _extract(_post(model, system, user, max_tokens), "[", "]")
        if parsed is not None:
            return parsed
    return []


def _ask_object(system, user, max_tokens=800):
    for model in MODELS:
        parsed = _extract(_post(model, system, user, max_tokens), "{", "}")
        if parsed is not None:
            return parsed
    return {}


def _clean_strings(raw, limit):
    seen, out = set(), []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str):
            title = item.strip()[:80]
            if title and title.lower() not in seen:
                seen.add(title.lower())
                out.append(title)
    return out[:limit]


# --------------------------------------------------------------------------
# public
# --------------------------------------------------------------------------


def suggest(query, lang="Tamil"):
    """Likely correct titles for a query that found nothing."""
    if not enabled() or not query:
        return []
    user = "Language: %s\nThey typed: %s" % (lang, query[:80])
    return _clean_strings(_ask_array(SYSTEM, user), 5)


def suggest_from_profile(watched, watchlist, lang="Tamil", note=""):
    """Films for this person, from what they have already watched and saved.

    Returns title strings. The caller must check them against einthusan: a
    confident-sounding title that is not in the catalogue is worth nothing.
    """
    if not enabled():
        return []

    seen = []
    for title in list(watched) + list(watchlist):
        title = (title or "").strip()[:80]
        if title and title not in seen:
            seen.append(title)

    if seen:
        profile = "Films they have watched or saved: %s" % "; ".join(seen[-25:])
    else:
        profile = "Nothing yet, so pick well-known films."

    parts = ["Language: %s" % lang, profile]
    if note:
        parts.append("They asked for: %s" % note[:200])
    parts.append("Suggest films.")

    return _clean_strings(_ask_array(SYSTEM_TASTE, "\n".join(parts), 220), 12)


    user = "Tag these films:\n" + "\n".join("- %s" % t for t in titles)
    raw = _ask_object(SYSTEM_TAGS, user, 800)

    clean = {}
    for title, genres in raw.items():
        if not isinstance(genres, list):
            continue
        clean[str(title)[:80]] = [
            str(g).strip().lower()[:24] for g in genres
            if isinstance(g, str) and g.strip()
        ][:3]
    return clean
