"""
HTML rendering.

Catalogue content comes from einthusan. Personal data remains in localStorage
for offline browsing and is merged into the account database when signed in.

Markup follows the class names in style.css. Rails are filled from app.js;
everything server-rendered is static HTML so the page paints without JS.
"""

import html
import urllib.parse

from . import einthusan as E

NAV = [
    ("/", "Home"),
    ("/search", "Search"),
    ("/watchlist", "My List"),
]

LANG_OPTIONS = list(E.LANGS)


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


# --------------------------------------------------------------------------
# shell
# --------------------------------------------------------------------------


def lang_options(selected):
    return "".join(
        '<option value="%s"%s>%s</option>'
        % (code, " selected" if code == selected else "", esc(label))
        for code, label in LANG_OPTIONS)


def page(title, body, top_lang="tamil"):
    current = title.lower()
    links = "".join(
        '<a class="nav-link%s" href="%s">%s</a>'
        % (" on" if (href == "/" and current == "home")
           or href.lstrip("/").lower() == current else "", href, esc(label))
        for href, label in NAV)

    return (
        '<!DOCTYPE html>'
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="dark">'
        '<meta name="theme-color" content="#0b0b0f">'
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
        '<script src="/static/app.js"></script>'
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
    href = watch_href(item)
    poster = ('<img loading="lazy" src="%s" alt="">' % esc(item["cover"])
              if item.get("cover") else '<span class="card-none">No artwork</span>')
    meta = " &middot; ".join(esc(b) for b in (item.get("year"), item.get("lang")) if b)

    return (
        '<article class="card" data-id="%s" data-title="%s" data-cover="%s"'
        ' data-url="%s" data-year="%s">'
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
           esc(item["url"]), esc(item.get("year", "")), href, esc(item["title"]),
           poster, ICON_PLAY, esc(item["title"]),
           ('<em>%s</em>' % meta) if meta else "",
           ICON_PLUS, ICON_CHECK))


def shelf(title, shelf_id, items_html="", empty_text="", note=""):
    head = '<h2>%s</h2>' % esc(title)
    if note:
        head += '<p class="shelf-note">%s</p>' % esc(note)
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
            '%s%s%s'
            % (billboard_fallback(),
               shelf("Continue watching", "continue",
                     empty_text="Nothing part-watched yet. Start a film and "
                                "it shows up here."),
               shelf("My list", "watchlist",
                     empty_text="Nothing saved yet. Use the + on any poster."),
               shelf("Recently played", "recent",
                     empty_text="Films you have started will be listed here.")),
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
            "Your browser cannot play this file. The direct link is below."
            "</video></div></div>"
            '<div class="watch-meta">'
            "<div><h1>%s</h1>%s</div>"
            '<div class="watch-actions">'
            '<button class="btn ghost watch-add" type="button" data-action="toggle">'
            '<span class="add-off">%s<span>My List</span></span>'
            '<span class="add-on">%s<span>In My List</span></span></button>'
            '<a class="btn ghost" href="%s" download>Download</a>'
            "</div></div>"
            '<p class="resume" data-role="resume"></p>'
            '<details class="direct"><summary>Direct link</summary><code>%s</code>'
            "</details></article>"
            % (esc(item["id"]), esc(item["title"]), esc(item.get("cover") or ""),
               esc(item["url"]), esc(item.get("year", "")),
               esc(item["url"]), esc(item["title"]),
               ('<p class="watch-sub">%s</p>' % meta) if meta else "",
               ICON_PLUS, ICON_CHECK, esc(item["url"]), esc(item["url"])),
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
