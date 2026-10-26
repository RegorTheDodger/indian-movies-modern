"""
The Flask app, shared by the local dev server and the Vercel function.

Routes
  GET  /                 continue watching and my list
  GET  /search           ?q=&lang=
  GET  /watch/<id>       ?t=&c=&y=&l=   player
  GET  /watchlist
  GET  /settings         POST saves the default language
  GET  /convert          ?u=  and optionally &check=1
"""

import os
from flask import Flask, Response, jsonify, redirect, request

from . import einthusan as E
from . import views

TOP_LANG_COOKIE = "iml_top_lang"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365


def _valid_lang(value):
    value = (value or "").lower()
    return value if value in E.LANG_CODES else "tamil"


def create_app():
    # this module lives in lib/, so Flask would otherwise look for lib/static
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(
        __name__,
        static_folder=os.path.join(project_root, "static"),
        static_url_path="/static",
    )
    app.config["JSON_SORT_KEYS"] = False

    def top_lang():
        return _valid_lang(request.cookies.get(TOP_LANG_COOKIE, "tamil"))

    def render(name, body, lang=None):
        lang = lang or top_lang()
        html = views.page(name, body, lang)
        resp = Response(html, mimetype="text/html; charset=utf-8")
        if not request.cookies.get(TOP_LANG_COOKIE):
            resp.set_cookie(TOP_LANG_COOKIE, lang,
                            max_age=COOKIE_MAX_AGE, samesite="Lax")
        return resp

    # ---------------------------------------------------------------- home
    @app.route("/")
    def home():
        _name, body, _l = views.home_page(top_lang())
        return render("Home", body)

    # -------------------------------------------------------------- search
    @app.route("/search")
    def search():
        query = (request.args.get("q") or "").strip()[:80]
        lang = _valid_lang((request.args.get("lang") or "tamil").lower())

        if not query:
            _n, body, _l = views.search_page("", lang, [], 0, 0, None, lang)
            return render("Search", body, lang)

        # a watch url pasted into the search box means "convert"
        if E._WATCH.search(query) or E._CONTENT.search(query):
            return convert()

        try:
            got = E.search(query, lang)
        except Exception:
            got = None

        if got is None:
            items, pages, count, used = [], 0, 0, query
            failed = True
        else:
            items, pages, count, used = got
            failed = False

        # No model call on the search path. A dead end has to answer as fast
        # as a hit, so suggestions are not worth the extra round trip here.
        _n, body, _l = views.search_page(query, lang, items, pages, count,
                                         used, lang)
        if failed:
            body = ('<p class="empty bad">Could not reach einthusan just now. '
                    'Wait a moment and try again.</p>' + body)
        return render("Search", body, lang)

    # -------------------------------------------------------------- player
    @app.route("/watch/<movie_id>")
    def watch(movie_id):
        movie_id = E.extract_id(movie_id) or movie_id
        item = {
            "id": movie_id,
            "title": (request.args.get("t") or movie_id)[:120],
            "cover": request.args.get("c") or None,
            "year": request.args.get("y") or "",
            "lang": request.args.get("l") or "",
            "url": E.cdn_link(movie_id),
        }
        _n, body, _l = views.watch_page(item, top_lang())
        return render(item["title"], body)

    # ----------------------------------------------------------- watchlist
    @app.route("/watchlist")
    def watchlist():
        _n, body, _l = views.watchlist_page(top_lang())
        return render("Watchlist", body)

    # ------------------------------------------------------------ settings
    @app.route("/settings", methods=["GET", "POST"])
    def settings():
        if request.method == "POST":
            lang = _valid_lang((request.form.get("toplang") or "tamil").lower())
            resp = redirect("/settings", code=303)
            resp.set_cookie(TOP_LANG_COOKIE, lang,
                            max_age=COOKIE_MAX_AGE, samesite="Lax")
            return resp
        _n, body, _l = views.settings_page(top_lang())
        return render("Settings", body)

    # ------------------------------------------------------------- convert
    @app.route("/convert")
    def convert():
        raw = (request.args.get("u") or "").strip()[:500]
        movie_id = E.extract_id(raw)
        if not movie_id:
            _n, body, _l = views.convert_page(
                raw, "", None, "",
                "No movie id found in that. Paste a full einthusan link such as "
                "https://einthusan.tv/movie/watch/7C8l/, or just type the "
                "4-character id (7C8l).")
            return render("Convert", body)

        ok, ctype = None, ""
        if request.args.get("check") == "1":
            try:
                ok, ctype = _verify(movie_id)
            except Exception:
                ok, ctype = False, ""
        _n, body, _l = views.convert_page(raw, movie_id, ok, ctype, "")
        return render("Convert", body)

    # ---------------------------------------------------------------- misc
    @app.route("/healthz")
    def healthz():
        return {"ok": True, "groq": bool(os.environ.get("GROQ_API_KEY"))}

    @app.errorhandler(404)
    def not_found(_e):
        return redirect("/")

    return app


def _verify(movie_id):
    import http.client
    import ssl as ssl_mod
    conn = http.client.HTTPSConnection(E.CDN_HOST, timeout=20,
                                       context=ssl_mod.create_default_context())
    try:
        conn.request("GET", "/etv/content/D%s.mp4" % movie_id,
                     headers={"User-Agent": E.UA, "Range": "bytes=0-255",
                              "Connection": "close"})
        resp = conn.getresponse()
        ctype = resp.getheader("Content-Type", "")
        resp.read(256)
        return resp.status in (200, 206) and "video" in ctype, ctype
    finally:
        conn.close()
