# Indian Movies Legacy — new site

Search, a player, a watchlist, continue watching and watch statistics. This is
the **second** site and is entirely separate from the Windows Phone one, which
is untouched and still running.

| | what it is | where |
| --- | --- | --- |
| `einthusan-cdn/` | old, zero JavaScript, built for the Lumia | port 8080 |
| `einthusan-web/` | this one | port 8090 |
| `movserver.py` | your movie library, untouched | port 8000 |

The Lumia cannot do the modern TLS a CDN needs, so it keeps using the old
zero-JavaScript version over plain HTTP on the LAN. Nothing here is expected to
work on it, and nothing here breaks it.

## Run it

```sh
cd einthusan-web
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
GROQ_API_KEY=gsk_... .venv/bin/python app.py     # http://127.0.0.1:8090
```

## Features

**Search.** Prefix search against einthusan's A–Z listing, with real poster
art. Titles are indexed from their first letter, so search on the first word.

**My list.** Tap My List on any poster. Stored in `localStorage`; no account.

**Continue watching.** The player writes a resume position, and the shelf shows
what is part-watched, most recent first, with a percentage. Reopening a film
resumes at the saved second. Under 8 seconds is ignored, and past 95% it counts
as finished.

**Analytics.** Time watched, films started, finished, list size, top genres,
split by language, and what you played most recently.

**Recently played.** Your own history on the home page. There are no
recommendations and no assistant; the only thing on the home page is what you
have actually done.

## Analytics, and where the genres come from

Play time is accumulated in the browser, and it is a **separate record from the
resume position** on purpose. The resume entry is deleted when a film is
finished, so if it were also the tally the stats would forget everything you
watched. Time is credited per tick and jumps longer than 6 seconds are treated
as seeks, not watching.

Genres are the interesting problem: **einthusan publishes no genres at all** —
no genre, no rating, no cast, no popularity. There is nothing to read. So the
browser posts the titles you have seen to `/api/tags` and a model assigns them,
and the result is cached. A film splits its time evenly across its genres so
one three-genre film does not outrank three one-genre films. If you have not
watched enough for time to be meaningful, it falls back to counting what you
have saved and says so on the page.

## Design

Built on Apple's foundations, mainly:

- **Response.** Buttons and list buttons react on pointer-down, not release.
- **Materials.** The bar and the stat panels are translucent layers with
  `backdrop-filter`, so content scrolls underneath rather than the chrome
  eating a fixed strip.
- **Springs, not durations.** `static/motion.js` has a real spring integrated
  on `requestAnimationFrame`, described with damping ratio and response the way
  Apple describes them. The rails use it for 1:1 drag, momentum on release and
  momentum projection (`(v/1000)·d/(1-d)`, d = 0.998), with progressive
  rubber-banding at the ends. Nothing gesture-driven uses a CSS transition,
  because those cannot be grabbed and reversed mid-flight.
- **Interruptibility.** Grabbing a rail that is already throwing stops the
  spring and hands over from wherever it actually was, so there is no jump.
- **Typography.** Tracking is size-specific: the display type is `-0.028em` with
  `1.03` leading, body text sits near zero, and the small uppercase labels pull
  the other way at `0.055em`.
- **Preferences.** `prefers-reduced-motion` swaps every spring for a
  cross-fade, `prefers-reduced-transparency` frosts the materials to solid,
  and `prefers-contrast: more` strengthens edges.

Two Apple numbers worth knowing: a critically damped spring (damping 1.0) does
not overshoot, which is right for anything that merely faded in; the rail
release uses damping 0.85 because a flick really did carry momentum.

## The Groq key

Only used for genre tags, and only for films you have not tagged yet. Read from
the environment; `.env` is gitignored.

```sh
GROQ_API_KEY=gsk_...
```

`GET /healthz` reports whether one was found. Without it the site still works,
the genre panels just stay empty.

Two things learned the hard way:

- Groq answers **403 to urllib's default User-Agent**. `lib/ai.py` sends its
  own.
- Models rotate and your key cannot reach `llama-3.1-8b-instant`. Only
  `qwen/qwen3.8-27b`, the gpt-oss models and whisper are available, so `MODELS`
  is a fallback chain tried in order.

**Rotate that key.** It was pasted in a chat, so treat it as public.

## Deploying to Vercel

```sh
cd einthusan-web
vercel --prod
```

`api/index.py` is the entry point. `vercel.json` only sets `maxDuration`.
Set `GROQ_API_KEY` in the project's environment variables.

## Layout

```
app.py            local dev server
api/index.py      Vercel entry
lib/einthusan.py  all network access, parsing, search
lib/ai.py         optional Groq, off without a key
lib/webapp.py     routes
lib/views.py      HTML
static/motion.js  springs, momentum, rubber-banding
static/app.js     list, watch time, analytics
static/style.css
```

Per-person state is deliberately client-side and there is no database, which
also means a list does not follow the person between devices.
