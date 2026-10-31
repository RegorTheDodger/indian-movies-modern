# RogFlix

Films and shows from eight Indian languages, plus an English catalogue, streamed
in the browser: search, a player, My List, continue watching, and accounts that
keep that state in step across devices.

Server-rendered Flask (Python) with a small vanilla-JavaScript front end. No
framework, no bundler, no build step — `vercel --prod` uploads the source and
Vercel runs `api/index.py` as a Python function.

## How it is built

| Layer | What it uses | Why that choice |
| --- | --- | --- |
| Server | Python 3.12, Flask 3.1 | One process serves both HTML and JSON, and the same code runs locally and as a Vercel function. Nothing has to be rewritten per host. |
| Markup | Python strings in `lib/views.py` | Pages are assembled from a few helpers (`page`, `card`, `shelf`, `grid`). Every page is real HTML before a byte of JavaScript runs, so first paint does not wait on the client. No template engine, no template files to ship. |
| Client | Vanilla JS: `static/app.js`, `static/motion.js` | The server already renders the catalogue and the shelves' markup; the browser only fills personal shelves and drives gestures. A framework would add a bundle and a hydration delay for work the server has done. |
| Styles | Hand-written CSS with custom properties | One file, no preprocessor, no build step. |
| Personal data | `localStorage`, six keys | Instant and offline. The account copy is a *merge* of it, never a replacement, so the browser stays usable while signed out. |
| Accounts | Postgres in production, SQLite locally; driver `pg8000` | Vercel's filesystem is ephemeral, so accounts need a real database. `pg8000` is pure Python, so the function needs no native build; SQLite keeps local development offline. |

## Layout

```
app.py               local dev server (Flask, port 8090)
api/index.py         Vercel entry point
lib/webapp.py        routes, cookies, auth wiring
lib/views.py         every HTML page
lib/einthusan.py     the Indian catalogue: fetch, parse, search
lib/stremio.py       Cinemeta: English search, metadata, episodes
lib/vidspark.py      the embed player's URLs
lib/accounts.py      passwords, sessions, signup policy, stored state
lib/sync.py          merging two devices' copies of the same state
lib/db.py            Postgres/SQLite adapter and schema
lib/ai.py            optional Groq spelling suggestions (no route calls it)
static/app.js        My List, resume, continue watching, accounts, sync
static/motion.js     spring and momentum for the shelves
static/style.css     styles
static/*.svg, *.png  logo, favicon, app icons, share card
static/manifest.json installable web app
```

## Routes

| Route | What it does |
| --- | --- |
| `GET /` | Home: continue watching and My List, filled in by `app.js` |
| `GET /search?q=&lang=` | English searches Cinemeta; any other language searches einthusan |
| `GET /title/<kind>/<id>?s=&e=` | One film or one episode: VidSpark player, full metadata, episode list |
| `GET /watch/<id>?t=&c=&y=&l=` | The einthusan `<video>` player |
| `GET /watchlist` | My List |
| `GET/POST /settings` | Default language (stored in a cookie) |
| `GET /convert?u=&check=1` | Turns an einthusan link or 4-character id into a playable page |
| `GET /library`, `/library/search` | 303 to `/search?lang=english`, so old bookmarks still work |
| `POST /auth/register`, `/auth/login`, `/auth/logout` | JSON or form; sets or clears the session cookie |
| `GET /auth/me` | `{authenticated, user}` |
| `GET/POST /api/sync`, `POST /api/sync/clear` | Whole-state merge for the signed-in account |
| `GET /healthz` | Liveness, provider configuration, database dialect |
| anything else | 303 to `/` |

## Features

### Search

Two engines behind one box.

**English** goes to Cinemeta (default `https://v3-cinemeta.strem.io`). It answers
everything the page needs: films, shows, posters, backgrounds, synopsis, cast,
crew, runtime, rating, genres, trailer, IMDb id and episode lists. Responses are
cached in-process for ten minutes; searches are also cached to disk for a day,
so a repeat query — including on a cold Vercel instance — renders immediately.

**The Indian languages** have no full-text API at all. einthusan indexes titles
by first letter, so a search is a prefix walk over its A–Z listing (up to four
pages). If what was typed matches poorly, the first word is shortened up to four
times and near matches are accepted, so a typo near the end of a word still
finds the film. Every page that exists is fetched — nothing is dropped to beat a
clock — and the speed comes from a keep-alive connection pool, because the TLS
handshake is most of the cost of a cold search.

The language tabs keep the query when you switch. There are nine: English plus
Tamil, Telugu, Hindi, Malayalam, Kannada, Bengali, Marathi and Punjabi. A watch
URL pasted into the box is treated as a conversion and sent to `/convert`.

### My List

Add with the + on any poster. A **show is saved as the show** (`ext:series:tt0944947`),
not as whichever episode happened to be open; older episode-level entries are
folded into the show once on load. Removing writes a timestamped tombstone, so a
stale device cannot resurrect the film at the next sync.

### Continue watching

The player writes a resume position, and the shelf shows what is part-watched,
most recent first, with a percentage.

- a title earns a card only after **10 seconds** of real playback
- a jump longer than **6 seconds** is a seek, not watching, and is not credited
- the position is saved at most every **4 seconds**
- at **95%** a title counts as finished and leaves the shelf
- clearing the shelf writes per-title tombstones, so sync cannot bring them back

For a series the resume point is per episode (`ext:series:<id>:<season>:<episode>`),
so reopening S04E02 returns to that episode at its second, while My List holds
only the show.

### Resume, from either player

VidSpark accepts `?t=<seconds>` to open at a position, and posts
`postMessage` events tagged `source: "vidspark-player"` (`play`, `pause`,
`seeked`, `ended`, each with `currentTime` and `duration`). The einthusan side is
an ordinary `<video>`. Both feed the same record in this app's storage, which is
what makes continue watching mean the same thing on both sides.

### Accounts and sync

Passwords are PBKDF2-HMAC-SHA256, 240,000 iterations, per-user salt. A session is
a random token; only its SHA-256 is stored, so a database dump cannot be replayed
as a login. Sessions last 30 days and the cookie is `HttpOnly`, `SameSite=Lax`.
Attempts are throttled per IP: 5 registrations an hour, 8 logins per 10 minutes.

Sync posts the device's whole state and the server returns the merged result —
merging, not last-write-wins, is what makes a phone and a laptop safe on one
account:

- **watchlist** — newest add per id wins; a removal is a tombstone that outvotes
  older adds and expires after 180 days
- **progress** — newest `at` wins; once a title is marked started it stays
  started, whichever device said so first
- **watched** — newer record supplies the metadata, but play time keeps the
  larger tally and `finished` stays true once true
- **catalog** — merged field by field, so a known title or cover is never
  replaced by a blank
- **finished or cleared** titles drop the resume point rather than sending a
  device backwards

Total state is capped at 400 KB. `IML_ALLOW_SIGNUP` decides who may register:
`first` (default — only while the database is empty), `open`, or `closed`.

### Convert

`/convert?u=` pulls the 4-character id out of an einthusan link (or accepts the
id on its own) and builds the player page. `&check=1` reads the first 256 bytes
of the CDN file to confirm it is really there and reports the content type.

## Playback sources

| Catalogue | Page | Player | URL shape |
| --- | --- | --- | --- |
| einthusan | `/watch/<id>` | native `<video>` | `https://cdn2.einthusan.io/etv/content/D<id>.mp4` |
| English (Cinemeta) | `/title/<kind>/<id>` | VidSpark iframe | `https://vidspark.to/movie/tt0413300`, `https://vidspark.to/tv/tt0944947/2/3` |

Nothing is downloaded, converted or proxied: the server only builds the URL. That
is what lets playback work on Vercel, where a function cannot carry a two-hour
file. The trade is that VidSpark is somebody else's player, so its quality,
subtitles and ads apply. A series opens on its first real season — season 0 is
the specials list, which VidSpark has no episode for.

## Running it

```sh
cd einthusan-web
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py            # http://127.0.0.1:8090
```

Without `DATABASE_URL` it uses SQLite at `.data/iml.db`, so it runs offline.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | unset → SQLite | Postgres for accounts and sync (`POSTGRES_URL` and friends are also read) |
| `IML_DB_PATH` | `.data/iml.db` | SQLite file for local development |
| `IML_ALLOW_SIGNUP` | `first` | `first`, `open` or `closed` |
| `CINEMETA_URL` | `https://v3-cinemeta.strem.io` | Metadata provider |
| `GROQ_API_KEY` | unset | Only for `lib/ai.py`; no route calls it at present |

## Deploying

```sh
cd einthusan-web
vercel --prod
```

`api/index.py` is the entry point and `vercel.json` only raises the function's
`maxDuration` to 30 seconds. Set `DATABASE_URL` and `IML_ALLOW_SIGNUP` in the
project's environment variables. Both are read per request, but Vercel only
hands a new value to a new deployment, so redeploy after changing them.

## Stored data

In the browser:

| Key | Contents |
| --- | --- |
| `iml:watchlist` | saved titles, newest first |
| `iml:progress` | resume points, per film or per episode |
| `iml:watched` | play time and finished flag per title |
| `iml:catalog` | title, cover, year, language for anything seen |
| `iml:removed` | tombstones for removed list entries |
| `iml:dropped` | tombstones for cleared continue-watching entries |

In the database: `iml_users`, `iml_sessions`, `iml_state` (the merged JSON and
its revision), `iml_throttle` (attempt counters).

## Interface

- The page is complete before JavaScript: catalogue cards, title pages and
  episode lists are server-rendered; only personal shelves are client-filled.
- The shelves are physics, not CSS transitions: `static/motion.js` integrates a
  spring on `requestAnimationFrame`, so a drag tracks 1:1, a flick carries
  momentum, and grabbing a moving shelf hands over from where it actually is.
  Damping ratio and response are the parameters, the way Apple's springs are
  described.
- `prefers-reduced-motion` replaces springs with cross-fades,
  `prefers-reduced-transparency` frosts translucent layers to solid, and
  `prefers-contrast: more` strengthens edges.
- The name is RogFlix; the `einthusan-web` folder keeps its old name so git
  history and existing links still resolve.
