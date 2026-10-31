"""
HTML rendering.

Catalogue content comes from einthusan. Personal data remains in localStorage
for offline browsing and is merged into the account database when signed in.

Markup follows the class names in style.css. Rails are filled from app.js;
everything server-rendered is static HTML so the page paints without JS.
"""

import html
import re
import urllib.parse

from . import einthusan as E
from . import vidspark

NAV = [
    ("/", "Home", "home"),
    ("/search", "Search", "search"),
    ("/watchlist", "My List", "list"),
]

# English is first and is the default: it has no einthusan catalogue, so the
# search page answers it from Cinemeta instead.
LANG_OPTIONS = [("english", "English")] + list(E.LANGS)


def esc(text):
    return html.escape(text or "", quote=True)


# --------------------------------------------------------------------------
# icons
# --------------------------------------------------------------------------

ICON_SEARCH = ('<svg viewBox="0 0 24 24" width="18" height="18" fill="none"'
               ' stroke="currentColor" stroke-width="2" stroke-linecap="round"'
               ' aria-hidden="true"><circle cx="11" cy="11" r="7"/>'
               '<path d="m20 20-3.5-3.5"/></svg>')

ICON_PLAY = ('<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"'
             ' aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>')

ICON_PLUS = ('<svg viewBox="0 0 24 24" width="18" height="18" fill="none"'
             ' stroke="currentColor" stroke-width="2.2" stroke-linecap="round"'
             ' aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>')

ICON_CHECK = ('<svg viewBox="0 0 24 24" width="18" height="18" fill="none"'
              ' stroke="currentColor" stroke-width="2.4" stroke-linecap="round"'
              ' stroke-linejoin="round" aria-hidden="true">'
              '<path d="m5 13 4 4L19 7"/></svg>')

ICON_PREV = ('<svg viewBox="0 0 24 24" width="22" height="22" fill="none"'
             ' stroke="currentColor" stroke-width="2.4" stroke-linecap="round"'
             ' stroke-linejoin="round" aria-hidden="true">'
             '<path d="m15 6-6 6 6 6"/></svg>')

ICON_NEXT = ('<svg viewBox="0 0 24 24" width="22" height="22" fill="none"'
             ' stroke="currentColor" stroke-width="2.4" stroke-linecap="round"'
             ' stroke-linejoin="round" aria-hidden="true">'
             '<path d="m9 6 6 6-6 6"/></svg>')

ICON_GEAR = ('<svg viewBox="0 0 24 24" width="19" height="19" fill="none"'
             ' stroke="currentColor" stroke-width="1.8" stroke-linecap="round"'
             ' stroke-linejoin="round" aria-hidden="true">'
             '<path d="M9.6 3.2h4.8l.7 2.1a7.3 7.3 0 0 1 1.7 1l2.1-.6 2.4 4.1-1.5 1.6'
             'a7.4 7.4 0 0 1 0 2l1.5 1.6-2.4 4.1-2.1-.6a7.3 7.3 0 0 1-1.7 1l-.7 2.1H9.6l-.7-2.1'
             'a7.3 7.3 0 0 1-1.7-1l-2.1.6-2.4-4.1 1.5-1.6a7.4 7.4 0 0 1 0-2L2.7 9.8l2.4-4.1 2.1.6'
             'a7.3 7.3 0 0 1 1.7-1z"/><circle cx="12" cy="12.4" r="2.7"/></svg>')

ICON_HOME = ('<svg viewBox="0 0 24 24" width="17" height="17" fill="none"'
             ' stroke="currentColor" stroke-width="2" stroke-linejoin="round"'
             ' aria-hidden="true"><path d="m3 11 9-8 9 8v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/>'
             '<path d="M9 21v-6h6v6"/></svg>')
ICON_LIST = ('<svg viewBox="0 0 24 24" width="17" height="17" fill="none"'
             ' stroke="currentColor" stroke-width="2" stroke-linecap="round"'
             ' aria-hidden="true"><path d="M5 5h14M5 12h14M5 19h14"/></svg>')

ICON_LIB = ('<svg viewBox="0 0 24 24" width="17" height="17" fill="none"'
            ' stroke="currentColor" stroke-width="2" stroke-linecap="round"'
            ' stroke-linejoin="round" aria-hidden="true">'
            '<rect x="3" y="4" width="7" height="7" rx="1.5"/>'
            '<rect x="14" y="4" width="7" height="7" rx="1.5"/>'
            '<rect x="3" y="15" width="7" height="7" rx="1.5"/>'
            '<rect x="14" y="15" width="7" height="7" rx="1.5"/></svg>')

NAV_ICONS = {"home": ICON_HOME, "search": ICON_SEARCH, "list": ICON_LIST,
             "lib": ICON_LIB}


# --------------------------------------------------------------------------
# shell
# --------------------------------------------------------------------------


def lang_options(selected):
    return "".join(
        '<option value="%s"%s>%s</option>'
        % (code, " selected" if code == selected else "", esc(label))
        for code, label in LANG_OPTIONS)


def page(title, body, top_lang="english"):
    current = title.lower()
    links = "".join(
        '<a class="nav-link%s" href="%s">%s<span>%s</span></a>'
        % (" on" if (href == "/" and current == "home")
           or href.lstrip("/").lower() == current else "",
           href, NAV_ICONS[key], esc(label))
        for href, label, key in NAV)

    return (
        '<!DOCTYPE html>'
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="dark">'
        '<meta name="theme-color" content="#0b0b0f">'
        '<link rel="icon" href="/static/icon.svg" type="image/svg+xml">'
        "<title>%s</title>"
        '<link rel="stylesheet" href="/static/style.css">'
        "</head><body>"
        '<header class="nav" id="bar"><div class="nav-inner">'
        '<a class="brand" href="/">Indian<span>Movies</span></a>'
        '<nav class="nav-links">%s</nav>'
        '<form class="nav-search" action="/search" method="get" role="search">'
        '<span class="nav-field">%s'
        '<input type="search" name="q" placeholder="Search films"'
        ' autocomplete="off" aria-label="Search films"></span>'
        '<select name="lang" aria-label="Language">%s</select>'
        "</form>"
        '<a class="nav-gear" href="/settings" aria-label="Settings">%s</a>'
        "</div></header>"
        '<main class="page" data-lang="%s">%s</main>'
        '<script src="/static/motion.js"></script>'
        '<script src="/static/app.js?v=2"></script>'
        "</body></html>"
        % (esc(title), links, ICON_SEARCH, lang_options(top_lang),
           ICON_GEAR, esc(top_lang), body)
    )


# --------------------------------------------------------------------------
# pieces
# --------------------------------------------------------------------------


def search_field(value="", lang="tamil", action="/search"):
    return (
        '<form class="search-field" action="%s" method="get" role="search">'
        '<span class="sf-input">%s'
        '<input type="search" name="q" value="%s" placeholder="Search films"'
        ' autocomplete="off" aria-label="Film title" required></span>'
        '<select name="lang" aria-label="Language">%s</select>'
        '<button class="btn" type="submit">Search</button>'
        "</form>" % (esc(action), ICON_SEARCH, esc(value), lang_options(lang)))


def watch_href(item):
    """The bare id cannot render a player, so the card passes on what it
    already knows rather than paying for a lookup."""
    return "/watch/%s?%s" % (esc(item["id"]), urllib.parse.urlencode({
        "t": item["title"], "c": item.get("cover") or "",
        "y": item.get("year") or "", "l": item.get("lang") or "",
    }))


def card(item):
    """A card for anything already known to be playable. `href` lets a
    library title point at its own page instead of straight at a player."""
    href = item.get("href") or watch_href(item)
    poster = ('<img loading="lazy" src="%s" alt="">' % esc(item["cover"])
              if item.get("cover") else '<span class="card-none">No artwork</span>')
    meta = " &middot; ".join(esc(b) for b in (item.get("year"), item.get("lang")) if b)

    return (
        '<article class="card" data-id="%s" data-title="%s" data-cover="%s"'
        ' data-url="%s" data-href="%s" data-year="%s" data-lang="%s">'
        '<a class="card-poster" href="%s" aria-label="%s">%s'
        '<span class="card-shade"></span>'
        '<span class="card-play">%s</span>'
        '<span class="card-text"><b>%s</b>%s</span>'
        "</a>"
        '<button class="card-add" type="button" data-action="toggle"'
        ' aria-label="Add to my list"><span class="add-off">%s</span>'
        '<span class="add-on">%s</span></button>'
        "</article>"
        % (esc(item["id"]), esc(item["title"]), esc(item.get("cover") or ""),
           esc(item["url"]), esc(href), esc(item.get("year", "")),
           esc(item.get("lang", "")), href, esc(item["title"]),
           poster, ICON_PLAY, esc(item["title"]),
           ('<em>%s</em>' % meta) if meta else "",
           ICON_PLUS, ICON_CHECK))


def continue_head_actions():
    """Emptying the shelf at once, behind its own yes/no question."""
    return (
        '<button class="shelf-clear" type="button" data-action="clear-continue"'
        ' hidden>Clear all</button>'
        '<span class="shelf-confirm" data-confirm="continue" hidden>'
        "<span>Are you sure?</span>"
        '<button class="btn tiny" type="button"'
        ' data-action="confirm-clear-continue">Yes</button>'
        '<button class="btn ghost tiny" type="button"'
        ' data-action="cancel-clear-continue">No</button></span>'
    )


def shelf(title, shelf_id, items_html="", empty_text="", note="",
          head_extra=""):
    head = '<h2>%s</h2>' % esc(title)
    if note:
        head += '<p class="shelf-note">%s</p>' % esc(note)
    head += head_extra
    return (
        '<section class="shelf">'
        '<div class="shelf-head">%s</div>'
        '<div class="rail-wrap">'
        '<div class="rail" data-shelf="%s" tabindex="0" aria-label="%s">%s</div>'
        '<button class="rail-btn prev" data-scroll="-1" tabindex="-1"'
        ' aria-label="Scroll left">%s</button>'
        '<button class="rail-btn next" data-scroll="1" tabindex="-1"'
        ' aria-label="Scroll right">%s</button>'
        "</div>"
        '<p class="empty" data-empty="%s"%s>%s</p>'
        "</section>"
        % (head, esc(shelf_id), esc(title), items_html, ICON_PREV, ICON_NEXT,
           esc(shelf_id), "" if empty_text else " hidden", esc(empty_text))
    )


def grid(items_html, empty_text=""):
    return (
        '<div class="grid">%s</div>'
        '<p class="empty"%s>%s</p>'
        % (items_html, "" if empty_text else " hidden", esc(empty_text))
    )


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------


def billboard_fallback():
    """Shown when the list is empty. app.js swaps this for the newest saved
    film as soon as it can read localStorage, so this has to look complete on
    its own for the first paint."""
    return (
        '<section class="bb bb-plain"><div class="bb-inner">'
        '<p class="bb-kicker">Indian Movies</p>'
        '<h1 class="bb-title">Your next film<br>is one search away.</h1>'
        '<p class="bb-sub">Save anything with the + on a poster and the newest '
        'one shows up here.</p>%s</div></section>'
        % search_field())


def home_page(top_lang):
    return ("Home",
            '<div class="bb-host" data-billboard>%s</div>'
            '%s%s'
            % (billboard_fallback(),
               shelf("Continue watching", "continue",
                     empty_text="Nothing part-watched yet. Start a film and "
                                "it shows up here.",
                     head_extra=continue_head_actions()),
               shelf("My list", "watchlist",
                     empty_text="Nothing saved yet. Use the + on any poster."),
               ),
            top_lang)


def lang_tabs(query, lang):
    """Picking a language keeps the query, so switching is one click instead
    of retyping."""
    links = []
    for code, label in LANG_OPTIONS:
        qs = urllib.parse.urlencode({"q": query, "lang": code})
        links.append(
            '<a class="lang-tab%s" href="/search?%s">%s</a>'
            % (" on" if code == lang else "", qs, esc(label)))
    return '<div class="lang-tabs">%s</div>' % "".join(links)


def search_hero(title_html, sub, query, lang, extra=""):
    return (
        '<section class="search-hero">%s%s'
        '<form class="search-field sf-center" action="/search" method="get"'
        ' role="search">'
        '<span class="sf-input">%s'
        '<input type="search" name="q" value="%s" placeholder="Search films"'
        ' autocomplete="off" aria-label="Film title">'
        '<button class="sf-clear" type="button" data-action="clear-search"'
        ' aria-label="Clear">&times;</button></span>'
        '<select name="lang" aria-label="Language">%s</select>'
        '<button class="btn" type="submit">Search</button>'
        "</form>%s%s</section>"
        % (title_html, ('<p class="lede">%s</p>' % esc(sub)) if sub else "",
           ICON_SEARCH, esc(query), lang_options(lang), extra,
           lang_tabs(query, lang)))


def search_page(query, lang, items, total_pages, total_count, used_prefix,
                top_lang, suggestions=()):
    if not query:
        return ("Search",
                search_hero(
                    '<p class="eyebrow">Search</p>'
                    '<h1 class="display">Find something to watch</h1>',
                    "Every language at once, or pick one. Titles are indexed "
                    "from their first letter, so start with the first word.",
                    "", lang),
                top_lang)

    label = E.LANG_NAMES.get(lang, lang)

    if not items:
        return ("Search",
                search_hero(
                    '<p class="eyebrow">No match in %s</p>'
                    '<h1 class="display">Nothing for &ldquo;%s&rdquo;</h1>'
                    % (esc(label), esc(query)),
                    "Check the spelling, try just the first word, or switch "
                    "language. Another catalogue may have it.",
                    query, lang),
                top_lang)

    note = ""
    if used_prefix and used_prefix.strip().lower() != query.strip().lower():
        note = ('Nothing matched "%s" exactly, so these start with "%s".'
                % (query, used_prefix))
    elif total_count and total_count > len(items):
        note = ("Showing %d of %d matches." % (len(items), total_count))

    count = "%d result%s" % (len(items), "" if len(items) == 1 else "s")

    return ("Search",
            search_hero(
                '<p class="eyebrow">%s &middot; %s</p>'
                '<h1 class="display search-query">%s</h1>'
                % (esc(label), esc(count), esc(query)),
                note, query, lang)
            + '<section class="results"><div class="grid">%s</div></section>'
            % "".join(card(i) for i in items),
            top_lang)


def watchlist_page(top_lang):
    return ("My List",
            '<section class="page-head">'
            '<p class="eyebrow">Saved</p>'
            '<h1 class="h1">My list</h1>'
            '<p class="lede">Kept in this browser. Clearing site data or '
            "switching device will empty it.</p>"
            '<p class="head-actions">'
            '<button class="btn ghost" type="button" data-action="clear-watchlist">'
            "Clear list</button></p></section>"
            '<div class="grid" data-shelf="watchlist-full"></div>'
            '<p class="empty" data-empty="watchlist-full">Nothing saved yet.</p>',
            top_lang)


def settings_page(top_lang):
    rows = "".join(
        '<label class="radio"><input type="radio" name="toplang" value="%s"%s>'
        "<span>%s</span></label>"
        % (code, " checked" if code == top_lang else "", esc(name))
        for code, name in LANG_OPTIONS)
    return ("Settings",
            '<section class="page-head">'
            '<p class="eyebrow">Preferences</p>'
            '<h1 class="h1">Settings</h1></section>'
            '<section class="panel"><h2>Default language</h2>'
            '<p class="panel-note">The language the search box starts on. '
            "You can still switch it per search.</p>"
            '<form class="setlang" action="/settings" method="post">%s'
            '<button class="btn" type="submit">Save</button></form></section>'
            '<section class="panel auth-panel" data-auth-panel><h2>Sync between devices</h2>'
            '<p class="panel-note">Create an account or log in to sync your '
            "list, watch time and resume positions between Lumia and modern.</p>"
            '<p class="auth-status" data-auth-status role="status"></p>'
            '<div data-auth-guest>'
            '<form class="auth-form" data-auth-form="login" action="/auth/login" method="post">'
            '<input type="text" name="username" placeholder="Username" '
            'autocomplete="username" required>'
            '<input type="password" name="password" placeholder="Password" '
            'autocomplete="current-password" required>'
            '<button class="btn" type="submit">Log in</button></form>'
            '<form class="auth-form" data-auth-form="register" action="/auth/register" method="post">'
            '<input type="text" name="username" placeholder="New username" '
            'autocomplete="username" required>'
            '<input type="password" name="password" placeholder="New password (8+ characters)" '
            'autocomplete="new-password" required>'
            '<button class="btn ghost" type="submit">Create account</button></form>'
            '</div><div data-auth-user hidden>'
            '<p class="auth-welcome">Signed in as <b data-auth-name></b></p>'
            '<button class="btn ghost" type="button" data-auth-logout>Log out</button>'
            '</div>'
            '<form action="/auth/logout" method="post" hidden>'
            '<button class="btn ghost" type="submit">Log out</button></form>'
            '<p class="panel-note">Your list stays local until you log in; '
            "the browser syncs it after authentication.</p></section>"
            '<section class="panel"><h2>Stored data</h2>'
            '<p class="panel-note">Erase this browser\'s local list, watch time '
            "and resume positions.</p>"
            '<button class="btn ghost" type="button" data-action="clear-all">'
            "Erase everything</button></section>" % rows,
            top_lang)


def watch_page(item, top_lang):
    meta = " &middot; ".join(esc(b) for b in (item.get("year"), item.get("lang")) if b)
    return (item["title"],
            '<article class="watch" data-id="%s" data-title="%s" data-cover="%s"'
            ' data-url="%s" data-year="%s">'
            '<div class="watch-top"><a class="back" href="/">Back to home</a></div>'
            '<div class="player-wrap"><div class="player">'
            '<video id="player" controls preload="metadata" playsinline>'
            '<source src="%s" type="video/mp4">'
            "Your browser cannot play this file."
            "</video></div></div>"
            '<div class="watch-meta">'
            "<div><h1>%s</h1>%s</div>"
            '<div class="watch-actions">'
            '<button class="btn ghost watch-add" type="button" data-action="toggle">'
            '<span class="add-off">%s<span>My List</span></span>'
            '<span class="add-on">%s<span>In My List</span></span></button>'
            '<a class="btn ghost" href="%s" target="_blank" rel="noopener noreferrer">'
            'Open in new tab</a>'
            "</div></div>"
            '<p class="resume" data-role="resume"></p>'
            "</article>"
            % (esc(item["id"]), esc(item["title"]), esc(item.get("cover") or ""),
               esc(item["url"]), esc(item.get("year", "")),
               esc(item["url"]), esc(item["title"]),
               ('<p class="watch-sub">%s</p>' % meta) if meta else "",
               ICON_PLUS, ICON_CHECK, esc(item["url"])),
            top_lang)


def convert_page(raw, movie_id, ok, ctype, error):
    if error:
        return ("Convert",
                '<section class="page-head"><h1 class="h1">Convert</h1>'
                '<p class="lede bad">%s</p>%s</section>'
                % (esc(error), search_field()), "tamil")

    item = {"id": movie_id, "title": "id %s" % movie_id, "year": "", "lang": "",
            "cover": None, "url": E.cdn_link(movie_id)}

    if ok is None:
        badge = ""
    elif ok:
        badge = '<p class="lede good">Confirmed live (%s).</p>' % esc(ctype)
    else:
        badge = ('<p class="lede bad">No file at that address on the CDN. The id '
                 "may be wrong, or the film may be gone.</p>")

    return ("Convert",
            '<section class="page-head"><h1 class="h1">Convert a link</h1>'
            '<form class="search-field" action="/convert" method="get">'
            '<span class="sf-input"><input type="text" name="u"'
            ' placeholder="einthusan link or 4-character id" autocomplete="off"'
            ' required></span>'
            '<button class="btn" type="submit">Convert</button></form>%s</section>'
            '<div class="grid">%s</div>'
            % (badge, card(item)), "tamil")


# --------------------------------------------------------------------------
# library (Cinemeta for metadata, VidSpark for playback)
# --------------------------------------------------------------------------


def library_card(item):
    """A Cinemeta title. It links to its own page, not to a player, because
    a source has to be chosen first."""
    kind = "series" if item.get("type") == "series" else "movie"
    href = "/title/%s/%s" % (kind, esc(item["id"]))
    ext_id = "ext:%s:%s" % (kind, item["id"])
    cover = item.get("poster") or ""
    poster = ('<img loading="lazy" src="%s" alt="">' % esc(cover)
              if cover else '<span class="card-none">No artwork</span>')

    bits = [item.get("year")]
    if item.get("rating"):
        bits.append("%s/10" % item["rating"])
    meta = " &middot; ".join(esc(bit) for bit in bits if bit)

    return (
        '<article class="card" data-id="%s" data-title="%s" data-cover="%s"'
        ' data-url="%s" data-href="%s" data-year="%s" data-lang="English">'
        '<a class="card-poster" href="%s" aria-label="%s">%s'
        '<span class="card-shade"></span><span class="card-play">%s</span>'
        '<span class="card-text"><b>%s</b>%s</span></a>'
        '<button class="card-add" type="button" data-action="toggle"'
        ' aria-label="Add to my list"><span class="add-off">%s</span>'
        '<span class="add-on">%s</span></button></article>'
        % (esc(ext_id), esc(item.get("name")), esc(cover), esc(href), esc(href),
           esc(item.get("year") or ""), href, esc(item.get("name") or ""),
           poster, ICON_PLAY, esc(item.get("name") or ""),
           ('<em>%s</em>' % meta) if meta else "", ICON_PLUS, ICON_CHECK))


def library_field(value=""):
    return (
        '<form class="search-field sf-center" action="/search"'
        ' method="get" role="search">'
        '<input type="hidden" name="lang" value="english">'
        '<span class="sf-input">%s<input type="search" name="q" value="%s"'
        ' placeholder="Search movies and shows" autocomplete="off"'
        ' aria-label="Search the library" required></span>'
        '<button class="btn" type="submit">Search</button></form>'
        % (ICON_SEARCH, esc(value)))


def english_search_page(query, items=(), movies=(), series=(), failed=False):
    """The English half of the search page.

    English has no einthusan catalogue, so this asks Cinemeta directly and
    links each result at its own title page. With no query it shows what is
    popular instead, which is what the old library page did.
    """
    if query:
        count = "%d result%s" % (len(items), "" if len(items) == 1 else "s")
        body = [search_hero(
            '<p class="eyebrow">English &middot; %s</p>'
            '<h1 class="display search-query">%s</h1>'
            % (esc(count), esc(query)),
            "", query, "english")]
        if items:
            body.append('<section class="results"><div class="grid">%s</div>'
                        '</section>'
                        % "".join(library_card(i) for i in items))
        elif failed:
            body.append('<p class="empty bad">Cinemeta could not be reached '
                        'just now. Try again in a moment.</p>')
        else:
            body.append('<p class="empty">Nothing in English matches '
                        '&ldquo;%s&rdquo;. Another language tab may have it.'
                        '</p>' % esc(query))
        return ("Search", "".join(body), "english")

    body = ['<section class="search-hero"><p class="eyebrow">Search</p>'
            '<h1 class="display">Find something to watch</h1>'
            '<p class="lede">English films and shows come from Cinemeta; the '
            'Indian catalogue is one language tab away.</p>%s%s</section>'
            % (library_field(), lang_tabs("", "english"))]
    if movies:
        body.append('<section class="results"><div class="shelf-head">'
                    '<h2>Popular movies</h2></div><div class="grid">%s</div>'
                    '</section>' % "".join(library_card(i) for i in movies))
    if series:
        body.append('<section class="results"><div class="shelf-head">'
                    '<h2>Popular shows</h2></div><div class="grid">%s</div>'
                    '</section>' % "".join(library_card(i) for i in series))
    if not movies and not series:
        body.append('<p class="empty bad">Nothing could be loaded just now. '
                    'Search above, or reload in a moment.</p>')
    return ("Search", "".join(body), "english")


def _progress_id(kind, media_id, season, episode):
    """What continue-watching counts as one thing: a film, or one episode."""
    base = "ext:%s:%s" % (kind, media_id)
    if kind == "series":
        return "%s:%d:%d" % (base, season, episode)
    return base


def _runtime_seconds(value):
    """Cinemeta writes runtimes as "22 min" or "1h 22min"; seconds please."""
    text = str(value or "").lower()
    hours = re.search(r"(\d+)\s*h", text)
    minutes = re.search(r"(\d+)\s*m", text)
    total = (int(hours.group(1)) * 3600 if hours else 0) + \
            (int(minutes.group(1)) * 60 if minutes else 0)
    if not total:
        plain = re.match(r"^\s*(\d+)\s*$", text)
        total = int(plain.group(1)) * 60 if plain else 0
    return total


def title_page(item, season=1, episode=1, seasons=(), by_season=None):
    """One film or one episode: the player first, every known fact beneath it.

    Cinemeta is the only source here — backdrop, poster, year, runtime, rating,
    genres, synopsis, cast, crew, awards, links and the episode list all come
    from it, so a film and a show are laid out the same way.
    """
    kind = "series" if item.get("type") == "series" else "movie"
    href = "/title/%s/%s" % (kind, item["id"])
    # what continue-watching reopens: one episode, not just the show
    entry_href = ("%s?s=%d&e=%d" % (href, season, episode)
                  if kind == "series" else href)
    progress_id = _progress_id(kind, item["id"], season, episode)
    seasons = list(seasons) or [1]
    by_season = by_season or {}
    poster = item.get("poster") or ""
    background = item.get("background") or poster

    # The list saves a show, not the episode somebody happens to be on: adding
    # Game of Thrones from S04E02 puts Game of Thrones in My List. Resume
    # positions stay per episode, so continue watching can still reopen it.
    list_id = "ext:series:%s" % item["id"] if kind == "series" else progress_id

    body = ['<article class="title" data-id="%s" data-title="%s"'
            ' data-cover="%s" data-url="%s" data-href="%s" data-year="%s"'
            ' data-runtime="%d" data-lang="English"'
            ' data-list-id="%s" data-list-href="%s">'
            % (esc(progress_id), esc(item.get("name")), esc(poster), esc(href),
               esc(entry_href), esc(item.get("year") or ""),
               _runtime_seconds(item.get("runtime")), esc(list_id), esc(href))]

    # ---------------------------------------------------------------- stage
    # The frame is the page. Nothing is stacked above it but the navigation
    # bar, so a click on a card lands on the film rather than on a poster.

    body.append('<section class="stage">')
    if background:
        body.append('<div class="stage-art"><img src="%s" alt=""></div>'
                    % esc(background))
    body.append('<div class="stage-scrim"></div><div class="stage-inner">')

    # Playback is somebody else's player in a frame. Nothing is downloaded,
    # converted or proxied here, which is what makes this work on Vercel too.
    player = vidspark.embed_url(kind, item.get("id"), season, episode)
    if player:
        where = ("Season %d, episode %d" % (season, episode)
                 if kind == "series" else "This film")
        body.append(
            '<div class="player-wrap"><div class="player">'
            '<iframe id="player" src="%s" data-vidspark="%s" allowfullscreen'
            ' allow="autoplay; fullscreen; encrypted-media; picture-in-picture"'
            ' referrerpolicy="origin" loading="eager" title="%s on VidSpark">'
            '</iframe></div></div>'
            '<div class="stage-under">'
            '<p class="resume" data-role="resume"></p>'
            '<p class="play-note">%s plays on VidSpark, which remembers your '
            'place — and so does this site. Its own quality, subtitles and ads '
            'apply. <a href="%s" target="_blank" rel="noopener noreferrer">'
            'Open in a new tab</a> if the frame stays blank.</p></div>'
            % (esc(player), esc(player), esc(where), esc(where), esc(player)))
    else:
        body.append('<p class="play-note">Cinemeta did not return an IMDb id '
                    'for this title, so there is no player to open.</p>')
    body.append('</div></section>')

    # ---------------------------------------------------------------- sheet
    # Everything Cinemeta knows, underneath the frame: the poster, title, blurb
    # and people on the left; the numbers and the buttons on the right, starting
    # level with the title so the two columns read as one row.

    body.append('<section class="sheet"><div class="sheet-cols">')

    body.append('<div class="sheet-main"><div class="sheet-head">')
    if poster:
        body.append('<div class="sheet-poster"><img src="%s" alt=""></div>'
                    % esc(poster))
    body.append('<div class="sheet-id">')
    eyebrow = "Series" if kind == "series" else "Film"
    if kind == "series":
        eyebrow += (" &middot; Season %d &middot; Episode %d"
                    % (season, episode))
    body.append('<p class="eyebrow">%s</p>' % eyebrow)
    body.append('<h1 class="display">%s</h1>' % esc(item.get("name")))
    body.append('</div></div>')

    if item.get("description"):
        body.append('<p class="synopsis">%s</p>' % esc(item["description"]))

    rows = []
    if item.get("directors"):
        rows.append(("Director", esc(", ".join(item["directors"]))))
    if item.get("writers"):
        rows.append(("Written by", esc(", ".join(item["writers"]))))
    cast = [name for name in (item.get("cast") or [])[:10] if name]
    if cast:
        rows.append(("Cast", esc(", ".join(cast))))
    if item.get("country"):
        rows.append(("Country", esc(item["country"])))
    if item.get("awards"):
        rows.append(("Awards", esc(item["awards"])))
    if rows:
        body.append('<dl class="facts">%s</dl>'
                    % "".join("<dt>%s</dt><dd>%s</dd>" % (esc(key), value)
                              for key, value in rows))
    body.append('</div>')

    body.append('<div class="sheet-side"><h2 class="side-head">Details</h2>')
    details = []
    if item.get("year"):
        details.append(("Year", esc(item["year"])))
    if item.get("runtime"):
        details.append(("Runtime", esc(item["runtime"])))
    if item.get("rating"):
        details.append(("Rating", esc("%s/10 on IMDb" % item["rating"])))
    if item.get("status"):
        details.append(("Status", esc(item["status"])))
    if item.get("released"):
        details.append(("Released", esc(item["released"])))
    if details:
        body.append('<dl class="facts side-facts">%s</dl>'
                    % "".join("<dt>%s</dt><dd>%s</dd>" % (esc(key), value)
                              for key, value in details))

    genre_html = "".join(
        '<a class="chip" href="/search?q=%s&amp;lang=english">%s</a>'
        % (esc(urllib.parse.quote(genre)), esc(genre))
        for genre in (item.get("genres") or [])[:6])
    if genre_html:
        body.append('<div class="tag-row">%s</div>' % genre_html)

    body.append('<div class="sheet-actions">'
                '<button class="btn ghost watch-add" type="button"'
                ' data-action="toggle"><span class="add-off">%s'
                '<span>My List</span></span><span class="add-on">%s'
                '<span>In My List</span></span></button>' % (ICON_PLUS, ICON_CHECK))
    if item.get("trailer"):
        body.append('<a class="btn ghost" href="https://www.youtube.com/watch?v=%s"'
                    ' target="_blank" rel="noopener noreferrer">Trailer</a>'
                    % esc(item["trailer"]))
    if item.get("imdb"):
        body.append('<a class="btn ghost" href="%s" target="_blank"'
                    ' rel="noopener noreferrer">IMDb page</a>' % esc(item["imdb"]))
    body.append('</div></div></div>')

    body.append('<p class="title-foot">Every detail on this page comes from '
                'Cinemeta &middot; playback runs in the VidSpark player.</p>')
    body.append('</section>')

    # ------------------------------------------------------------- episodes

    if kind == "series" and by_season:
        # every season is rendered once: switching is a class change in
        # app.js instead of a round trip through the server
        tabs = "".join(
            '<a class="season-tab%s" href="%s?s=%d" data-season-tab="%d">'
            'Season %d</a>'
            % (" on" if value == season else "", esc(href), value, value, value)
            for value in seasons)
        groups, total = [], 0
        for value in seasons:
            entries = by_season.get(value) or []
            total += len(entries)
            cards = []
            for entry in entries:
                thumb = ('<img loading="lazy" src="%s" alt="">'
                         % esc(entry["thumbnail"])) if entry.get("thumbnail") else ""
                overview = ('<span class="ep-overview">%s</span>'
                            % esc(entry["overview"])) if entry.get("overview") else ""
                on = value == season and entry["episode"] == episode
                cards.append(
                    '<a class="episode%s" href="%s?s=%d&amp;e=%d"'
                    ' data-season="%d" data-episode="%d">'
                    '<span class="ep-thumb">%s</span>'
                    '<span class="ep-body"><span class="ep-no">S%02d E%02d</span>'
                    '<b class="ep-name">%s</b>%s</span></a>'
                    % (" on" if on else "", esc(href), value, entry["episode"],
                       value, entry["episode"], thumb, value, entry["episode"],
                       esc(entry.get("name")
                           or "Episode %d" % entry["episode"]), overview))
            groups.append('<div class="episodes" data-season-group="%d"%s>%s</div>'
                          % (value, "" if value == season else " hidden",
                             "".join(cards)))
        body.append('<section class="tv"><div class="shelf-head">'
                    '<h2>Episodes</h2><p class="shelf-note" data-ep-count>%d '
                    'episodes &middot; Season %d</p></div>'
                    '<div class="seasons">%s</div>%s</section>'
                    % (total, season, tabs, "".join(groups)))

    body.append('</article>')
    return (item.get("name") or "Title", "".join(body), "english")
