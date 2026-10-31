/*
 * Everything personal lives in localStorage:
 *
 *   iml:watchlist  [{id, title, cover, url, year}]
 *   iml:progress   {id: {seconds, duration, at, meta}}   resume position
 *   iml:watched    {id: {title, cover, url, year, lang, seconds, finished, at}}
 *   iml:catalog    {id: {title, cover, url, year}}
 *
 * When signed in, this state is merged with the account copy so it follows
 * the person between the modern and Lumia sites.
 *
 * The server renders the catalogue shelves and the billboard. This file only
 * fills the personal shelves and keeps the add buttons in sync.
 */

const LS_LIST = "iml:watchlist";
const LS_PROGRESS = "iml:progress";
const LS_WATCHED = "iml:watched";
const LS_CATALOG = "iml:catalog";
const LS_REMOVED = "iml:removed";
const LS_DROPPED = "iml:dropped";

/* past this fraction a film counts as finished and drops off continue */
const DONE_AT = 0.95;
/* a title earns a card in continue watching only after this much playback */
const MIN_WATCH = 10;
/* under this many seconds it is not worth remembering */
const MIN_SECONDS = 10;
/* a jump longer than this is a seek, not watching */
const SEEK_LIMIT = 6;
/* a resume stamp this far ahead is a broken clock, not a fresh entry */
const FUTURE_SLACK = 5 * 60 * 1000;

/* ------------------------------------------------------------------ icons */

const SVG_PLAY =
  '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true">' +
  '<path d="M8 5v14l11-7z"/></svg>';
const SVG_PLUS =
  '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"' +
  ' stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';
const SVG_CHECK =
  '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"' +
  ' stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="m5 13 4 4L19 7"/></svg>';

/* ------------------------------------------------------------------ store */

function read(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch (e) {
    return fallback;
  }
}

function write(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (e) {
    /* private mode or quota */
  }
}

const getList = () => (Array.isArray(read(LS_LIST, [])) ? read(LS_LIST, []) : []);
const getProgress = () => read(LS_PROGRESS, {}) || {};
const getWatched = () => read(LS_WATCHED, {}) || {};
const getCatalog = () => read(LS_CATALOG, {}) || {};
const getRemoved = () => read(LS_REMOVED, {}) || {};
/* removed from continue watching: {id: at}, so a sync cannot bring it back */
const getDropped = () => read(LS_DROPPED, {}) || {};

/* An older build saved whichever episode was open. Fold those entries into the
 * show once, so an existing list reads the same as one built now. */
function normaliseList() {
  const list = getList();
  const out = [];
  const seen = new Set();
  let changed = false;
  list.forEach((m) => {
    if (!m || !m.id) return;
    const ep = episodeParts(m);
    const id = ep ? "ext:series:" + ep.series : m.id;
    if (seen.has(id)) {
      changed = true;
      return;
    }
    seen.add(id);
    if (ep) {
      changed = true;
      const href = "/title/series/" + ep.series;
      out.push(Object.assign({}, m, { id: id, url: href, href: href }));
    } else {
      out.push(m);
    }
  });
  if (changed) write(LS_LIST, out);
}

function setList(list) {
  write(LS_LIST, list);
  paint();
}

function remember(item) {
  if (!item || !item.id || !item.title) return;
  const cat = getCatalog();
  const prev = cat[item.id] || {};
  cat[item.id] = {
    id: item.id,
    title: item.title || prev.title || item.id,
    cover: item.cover || prev.cover || "",
    url: item.url || prev.url || "/watch/" + item.id,
    href: item.href || prev.href || "",
    year: item.year || prev.year || "",
    lang: item.lang || prev.lang || ""
  };
  write(LS_CATALOG, cat);
}

function toggleList(item) {
  const list = getList();
  const removed = getRemoved();
  const at = list.findIndex((m) => m.id === item.id);
  if (at >= 0) {
    list.splice(at, 1);
    removed[item.id] = Date.now();
  } else {
    delete removed[item.id];
    list.unshift({
      id: item.id,
      title: item.title,
      cover: item.cover || "",
      url: item.url,
      href: item.href || "",
      year: item.year || "",
      lang: item.lang || "",
      at: Date.now()
    });
  }
  write(LS_REMOVED, removed);
  setList(list);
}

/* ------------------------------------------------------------- progress */

function setResume(id, seconds, duration, meta) {
  const p = getProgress();
  if (!duration || duration < 1) {
    return;
  }
  const frac = seconds / duration;
  if (seconds < MIN_SECONDS || frac >= DONE_AT) {
    delete p[id];
  } else {
    if (meta) remember(meta);
    p[id] = {
      seconds: Math.floor(seconds),
      duration: Math.floor(duration),
      at: Date.now(),
      meta: meta || (p[id] && p[id].meta) || null
    };
  }
  write(LS_PROGRESS, p);
}

function addWatchTime(id, delta, meta) {
  if (!delta || delta <= 0 || delta > SEEK_LIMIT) return; // ignore seeks
  const w = getWatched();
  const prev = w[id] || {};
  if (meta) remember(meta);
  w[id] = Object.assign(
    { seconds: 0, finished: false },
    prev,
    meta || {},
    { seconds: (prev.seconds || 0) + delta, at: Date.now() }
  );
  write(LS_WATCHED, w);
}

/* Dropping a show is a tombstone, not just a delete: the account copy would
 * otherwise hand the entry straight back on the next sync. */
function dropFromContinue(id) {
  if (!id) return;
  const progress = getProgress();
  delete progress[id];
  write(LS_PROGRESS, progress);
  const dropped = getDropped();
  dropped[id] = Date.now();
  write(LS_DROPPED, dropped);
  paint();
}

/* Emptying the whole shelf drops every card the same way the single × does:
 * a tombstone per id, so a device that still has them cannot hand them back
 * on the next sync. */
function clearContinueWatching() {
  const progress = getProgress();
  const dropped = getDropped();
  const rail = document.querySelector('[data-shelf="continue"]');
  const ids = rail
    ? Array.from(rail.querySelectorAll("article[data-id]")).map((el) => el.dataset.id)
    : Object.keys(progress);
  const at = Date.now();
  ids.forEach((id) => {
    delete progress[id];
    dropped[id] = at;
  });
  write(LS_PROGRESS, progress);
  write(LS_DROPPED, dropped);
  setContinueConfirm(false);
  paint();
}

/* "Clear all" turns into "Are you sure? Yes / No" in place, so the question
 * sits where the button was and nothing jumps around. */
function setContinueConfirm(open) {
  const ask = document.querySelector('[data-confirm="continue"]');
  const button = document.querySelector('[data-action="clear-continue"]');
  const rail = document.querySelector('[data-shelf="continue"]');
  const any = !!(rail && rail.querySelector("article"));
  if (ask) ask.hidden = !open;
  if (button) button.hidden = open || !any;
}

function markFinished(id, meta) {
  const w = getWatched();
  const prev = w[id] || {};
  if (meta) remember(meta);
  w[id] = Object.assign({ seconds: 0, finished: false }, prev, meta || {},
                        { finished: true, at: Date.now() });
  write(LS_WATCHED, w);
  const p = getProgress();
  delete p[id];
  write(LS_PROGRESS, p);
}

function continueWatching() {
  const p = getProgress();
  const cat = getCatalog();
  const dropped = getDropped();
  const saved = new Set(getList().map((m) => m.id));

  return Object.keys(p)
    .map((id) => {
      const entry = p[id];
      /* A stamp from the future would out-rank every removal tombstone for as
       * long as it stays ahead of the clock, so it counts as no stamp at all. */
      const at =
        entry.at > 0 && entry.at <= Date.now() + FUTURE_SLACK ? entry.at : 0;
      if (dropped[id] && dropped[id] >= at) return null;
      const meta = Object.assign({}, cat[id] || {}, entry.meta || {});
      if (!meta.id) meta.id = id;
      if (!meta.title) return null;
      if (!meta.url) meta.url = "/watch/" + id;
      meta.frac = entry.duration ? entry.seconds / entry.duration : 0;
      meta.seconds = entry.seconds || 0;
      meta.at = at;
      /* a saved show covers every episode of it, so the + on an episode of a
       * show already in the list reads as saved */
      const part = episodeParts(meta);
      meta.saved = saved.has(id) ||
        !!(part && saved.has("ext:series:" + part.series));
      meta.removable = true;
      return meta;
    })
    /* ten seconds of playback is what earns a card: a page that was opened
     * and left is not watching, and an entry still sitting at zero stays off
     * the shelf even if an older build saved one */
    .filter((m) => m && m.seconds >= MIN_WATCH && m.frac < DONE_AT)
    .sort((a, b) => b.at - a.at)
    .slice(0, 24);
}

/* --------------------------------------------------------------- markup */

function esc(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/* What a card adds to the list, which is not always what it opens: an episode
 * page saves the show itself, so My List does not fill up with single
 * episodes of the same series. */
function listIdOf(card) {
  return (card && card.dataset.listId) || (card && card.dataset.id) || "";
}

/* ext:series:<imdb>:<season>:<episode> */
function episodeParts(m) {
  const parts = String((m && m.id) || "").split(":");
  if (parts.length === 5 && parts[0] === "ext" && parts[1] === "series") {
    return { series: parts[2], season: parts[3], episode: parts[4] };
  }
  return null;
}

function pad2(value) {
  return String(value).length < 2 ? "0" + value : String(value);
}

function episodeHref(m) {
  // A resume entry for one episode has to reopen that episode; the show page
  // would otherwise start at S01E01.
  const ep = episodeParts(m);
  return ep
    ? "/title/series/" + ep.series + "?s=" + ep.season + "&e=" + ep.episode
    : "";
}

function watchHref(m) {
  // Library titles carry their own page (a show needs an episode first);
  // an einthusan film still has only its watch route.
  const episode = episodeHref(m);
  if (episode) return episode;
  if (m.href && m.href.charAt(0) === "/") return m.href;
  if (m.url && m.url.charAt(0) === "/") return m.url;
  const q = new URLSearchParams({
    t: m.title || "",
    c: m.cover || "",
    y: m.year || "",
    l: m.lang || ""
  });
  return "/watch/" + m.id + "?" + q.toString();
}

function cardHtml(m) {
  const href = esc(watchHref(m));
  const title = esc(m.title);
  const bits = [m.year, m.lang].filter(Boolean).map(esc);
  const ep = episodeParts(m);
  if (ep) bits.push("S" + pad2(ep.season) + " E" + pad2(ep.episode));
  const meta = bits.join(" &middot; ");
  const cover = m.cover
    ? '<img loading="lazy" src="' + esc(m.cover) + '" alt="">'
    : '<span class="card-none">No artwork</span>';

  const progress =
    typeof m.frac === "number" && m.frac > 0
      ? '<span class="card-progress"><i style="width:' +
        Math.round(m.frac * 100) + '%"></i></span>'
      : "";

  return (
    '<article class="card" data-id="' + esc(m.id) +
    '" data-title="' + title +
    '" data-cover="' + esc(m.cover || "") +
    '" data-url="' + esc(m.url || "") +
    '" data-href="' + esc(m.href || m.url || "") +
    '" data-year="' + esc(m.year || "") +
    '" data-lang="' + esc(m.lang || "") + '">' +
    (m.removable
      ? '<button class="card-drop" type="button" data-action="drop"'
        + ' aria-label="Remove from continue watching"'
        + ' title="Remove from continue watching">&times;</button>'
      : "") +
    '<a class="card-poster" href="' + href + '" aria-label="' + title + '">' +
    cover +
    '<span class="card-shade"></span>' +
    '<span class="card-play">' + SVG_PLAY + "</span>" +
    '<span class="card-text"><b>' + title + "</b>" +
    (meta ? "<em>" + meta + "</em>" : "") +
    "</span>" + progress + "</a>" +
    '<button class="card-add' + (m.saved ? " on" : "") +
    '" type="button" data-action="toggle" aria-label="Add to my list">' +
    '<span class="add-off">' + SVG_PLUS + "</span>" +
    '<span class="add-on">' + SVG_CHECK + "</span></button>" +
    "</article>"
  );
}

function fill(name, items, emptyText) {
  const list = document.querySelector('[data-shelf="' + name + '"]');
  const note = document.querySelector('[data-empty="' + name + '"]');
  if (list) list.innerHTML = items.map(cardHtml).join("");
  if (note) {
    note.hidden = items.length > 0;
    if (!items.length && emptyText) note.textContent = emptyText;
  }
}

/* -------------------------------------------------------------- billboard */

let fallbackBillboard = "";
let shownBillboard = null;

function billboardHtml(m, kicker) {
  const href = esc(watchHref(m));
  const title = esc(m.title);
  const cover = m.cover ? '<img src="' + esc(m.cover) + '" alt="">' : "";
  const chips = [m.year, m.lang].filter(Boolean)
    .map((b) => '<span class="bb-chip">' + esc(b) + "</span>").join("");

  return (
    '<section class="bb">' +
    '<div class="bb-art" aria-hidden="true">' + cover + "</div>" +
    '<div class="bb-scrim" aria-hidden="true"></div>' +
    '<div class="bb-inner">' +
    '<p class="bb-kicker">' + esc(kicker || "From your list") + "</p>" +
    '<h1 class="bb-title">' + title + "</h1>" +
    (chips ? '<p class="bb-meta">' + chips + "</p>" : "") +
    '<div class="bb-actions">' +
    '<a class="btn play" href="' + href + '">' + SVG_PLAY + "Play</a>" +
    '<a class="btn ghost" href="' + href + '">More info</a>' +
    "</div></div>" +
    '<div class="bb-poster" aria-hidden="true">' + cover + "</div>" +
    "</section>"
  );
}

/* The newest saved film takes the hero, falling back to the last film played
 * so a fresh list is not an empty page. Only rewritten when the choice
 * actually changes, so the image does not reload on every paint. */
function renderBillboard() {
  const host = document.querySelector("[data-billboard]");
  if (!host) return;
  if (!fallbackBillboard) fallbackBillboard = host.innerHTML;

  let item = getList()[0] || null;
  let kicker = "From your list";

  if (!item) {
    item = continueWatching()[0] || null;
    if (item) kicker = "Continue watching";
  }

  const key = item ? item.id + "|" + kicker : "";
  if (key === shownBillboard) return;
  shownBillboard = key;
  host.innerHTML = item ? billboardHtml(item, kicker) : fallbackBillboard;
}

function paint() {
  renderBillboard();

  const list = getList();
  const saved = new Set(list.map((m) => m.id));

  list.forEach(remember);
  document.querySelectorAll("[data-id][data-title]").forEach((el) =>
    remember({
      id: el.dataset.id,
      title: el.dataset.title,
      cover: el.dataset.cover,
      url: el.dataset.url,
      href: el.dataset.href,
      year: el.dataset.year,
      lang: el.dataset.lang
    })
  );

  fill("watchlist", list.map((m) => Object.assign({ saved: true }, m)));
  fill("watchlist-full", list.map((m) => Object.assign({ saved: true }, m)));
  const leaving = continueWatching();
  fill("continue", leaving);
  /* nothing to clear means no button; a question left open closes with the
   * last card it was about */
  const clearButton = document.querySelector('[data-action="clear-continue"]');
  if (clearButton) clearButton.hidden = leaving.length === 0;
  if (!leaving.length) setContinueConfirm(false);
  document.querySelectorAll(".card-add, .watch-add").forEach((btn) => {
    const card = btn.closest("[data-id]");
    if (card) btn.classList.toggle("on", saved.has(listIdOf(card)));
  });
}

/* ---------------------------------------------------------------- player */

function wirePlayer() {
  const video = document.getElementById("player");
  const wrap = document.querySelector(".watch");
  if (!video || !wrap) return;

  const id = wrap.dataset.id;
  const meta = {
    id: id,
    title: wrap.dataset.title,
    cover: wrap.dataset.cover,
    url: wrap.dataset.url,
    href: wrap.dataset.href || wrap.dataset.url || "",
    year: wrap.dataset.year
  };
  remember(meta);

  const resume = getProgress()[id];
  const note = wrap.querySelector('[data-role="resume"]');
  /* a converted stream has no index yet, so seeking is not possible */
  const live = wrap.dataset.live === "1";

  if (!live && resume && resume.duration && resume.seconds > MIN_SECONDS) {
    const at = Math.min(resume.seconds, resume.duration - 5);
    video.addEventListener(
      "loadedmetadata",
      function () {
        if (video.seekable && video.seekable.length === 0) {
          if (note) note.textContent =
            "This stream cannot seek, so it starts from the beginning.";
          return;
        }
        video.currentTime = at;
        if (note) {
          note.textContent =
            "Resumed at " + Math.floor(at / 60) + "m " +
            Math.floor(at % 60) + "s.";
        }
      },
      { once: true }
    );
  }

  let last = 0;
  let lastTick = 0;

  const tick = function () {
    const now = video.currentTime;
    const delta = now - lastTick;
    if (delta > 0 && delta <= SEEK_LIMIT) addWatchTime(id, delta, meta);
    lastTick = now;
    setResume(id, now, video.duration, meta);
  };

  video.addEventListener("timeupdate", function () {
    const now = Date.now();
    if (now - last < 4000) return;
    last = now;
    tick();
  });

  video.addEventListener("seeking", function () {
    lastTick = video.currentTime;
  });

  video.addEventListener("play", function () {
    lastTick = video.currentTime;
  });

  video.addEventListener("pause", tick);

  video.addEventListener("ended", function () {
    markFinished(id, meta);
    paint();
    syncAccount();
  });

  window.addEventListener("pagehide", tick);
  window.addEventListener("beforeunload", tick);
}

/* ------------------------------------------------------------- player frame */

/* VidSpark is another origin, but a talkative one: it posts playback events
 * tagged source:"vidspark-player". Listening to them keeps our own resume
 * position, watch time and "finished" state working exactly as they do for the
 * Einthusan <video>, and the account sync carries them to the other clients.
 *
 * On open the frame is handed our saved second with ?t=, which the player
 * documents as taking priority over whatever it remembered itself. */
function wireVidspark() {
  const frame = document.querySelector("iframe[data-vidspark]");
  const article = frame && frame.closest("[data-id]");
  if (!frame || !article) return;

  const id = article.dataset.id;
  const meta = {
    id: id,
    title: article.dataset.title,
    cover: article.dataset.cover,
    url: frame.dataset.vidspark,
    href: article.dataset.href || location.pathname,
    year: article.dataset.year
  };

  paint();

  const base = frame.dataset.vidspark;
  const saved = getProgress()[id];
  if (base && saved && saved.seconds && saved.seconds > MIN_SECONDS) {
    const at = Math.floor(saved.seconds);
    frame.src = base + (base.indexOf("?") === -1 ? "?" : "&") + "t=" + at;
    const note = document.querySelector('[data-role="resume"]');
    if (note) {
      note.textContent =
        "Resumed at " + Math.floor(at / 60) + "m " + Math.floor(at % 60) + "s.";
    }
  }

  let lastTick = 0;
  let lastSave = 0;
  let lastKnown = null;
  /* how much of this visit has actually played, so a page that is merely open
   * never becomes a card; picking up an existing episode counts as playing */
  let played = saved && saved.seconds >= MIN_WATCH ? MIN_WATCH : 0;

  function logTime(now, duration) {
    lastKnown = { now: now, duration: duration };
    /* the same point the rail treats as finished, so an episode the player
     * never formally "ended" still stops haunting continue watching */
    if (duration > 0 && now / duration >= DONE_AT) {
      markFinished(id, meta);
      paint();
      syncAccount();
      return;
    }
    if (played < MIN_WATCH) return;
    const stamp = Date.now();
    if (stamp - lastSave < 4000) return;
    lastSave = stamp;
    setResume(id, now, duration, meta);
  }

  /* One report. The position moving is the only reliable sign of playback: a
   * paused player does not advance, whichever event carried the number, so
   * the event name and the paused flag are not worth trusting over it. */
  function tick(now, duration) {
    const delta = now - lastTick;
    if (delta > 0 && delta <= SEEK_LIMIT) {
      played += delta;
      addWatchTime(id, delta, meta);
    }
    lastTick = now;
    logTime(now, duration);
  }

  window.addEventListener("message", function (event) {
    /* the frame we put on the page, and only its own tagged traffic */
    if (event.source !== frame.contentWindow) return;
    const data = event.data;
    if (!data || data.source !== "vidspark-player") return;

    const now = Number(data.currentTime) || 0;
    const duration = Number(data.duration) || 0;

    if (data.event === "ended") {
      markFinished(id, meta);
      paint();
      syncAccount();
      return;
    }

    if (data.event === "play" || data.event === "seeked") {
      lastTick = now;
      lastSave = 0;
      logTime(now, duration);
      return;
    }

    if (data.event === "pause") {
      lastSave = 0;
      tick(now, duration);
      return;
    }

    if (data.event === "timeupdate" || data.event === "playerstatus") {
      tick(now, duration);
    }
  });

  /* The frame cannot be trusted to announce playback on its own: watching it
   * live, a session nobody touches can go completely quiet, which is how a
   * show ended up logged once at 0:00 and never again. getStatus is the
   * documented way to ask, and its reply is a playerstatus the handler above
   * already reads, so asking on a timer is what makes a plain watch count. */
  let poll = 0;
  function ask() {
    if (document.visibilityState && document.visibilityState !== "visible") return;
    try {
      frame.contentWindow.postMessage({ action: "getStatus" }, "*");
    } catch (e) {
      /* the frame went away */
    }
  }
  function startPoll() {
    if (!poll) poll = window.setInterval(ask, 2500);
    ask();
  }
  startPoll();
  window.addEventListener("load", startPoll);
  window.addEventListener("pageshow", startPoll);
  frame.addEventListener("load", ask);

  /* Most sessions end by closing the tab, not by pressing pause, so the last
   * position the player told us about is written on the way out. */
  window.addEventListener("pagehide", function () {
    if (poll) {
      window.clearInterval(poll);
      poll = 0;
    }
    if (!lastKnown || played < MIN_WATCH) return;
    setResume(id, lastKnown.now, lastKnown.duration, meta);
    syncAccount();
  });
}

/* ------------------------------------------------------------------- rails */

const rails = new WeakMap();

function edgeState(rail) {
  const ctl = rails.get(rail);
  const shelf = rail.closest(".shelf");
  if (!ctl || !shelf) return;
  const b = ctl.bounds();
  const prev = shelf.querySelector(".rail-btn.prev");
  const next = shelf.querySelector(".rail-btn.next");
  if (prev) prev.classList.toggle("at-edge", rail.scrollLeft > 4);
  if (next) next.classList.toggle("at-edge", rail.scrollLeft < b.max - 4);
}

function wireRails() {
  document.querySelectorAll(".rail").forEach((rail) => {
    if (rails.has(rail)) return;
    if (!rail.querySelector("article")) return;
    rails.set(rail, window.Motion.attachDrag(rail));
    rail.addEventListener("scroll", () => edgeState(rail), { passive: true });
    edgeState(rail);
  });
}

/* the nav only becomes solid once something is actually under it */
function wireBar() {
  const bar = document.getElementById("bar");
  if (!bar) return;
  const sync = () => bar.classList.toggle("solid", window.scrollY > 12);
  sync();
  window.addEventListener("scroll", sync, { passive: true });
}

/* Account state is merged on the server, so the same login works on both
 * the modern and Lumia clients without exposing the password to JavaScript. */
function syncAccount() {
  fetch("/auth/me", { credentials: "same-origin" })
    .then((response) => response.json())
    .then((account) => {
      if (!account.authenticated) return;
      const state = {
        watchlist: getList(),
        progress: getProgress(),
        watched: getWatched(),
        catalog: getCatalog(),
        removed: getRemoved(),
        dropped: getDropped()
      };
      return fetch("/api/sync", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(state)
      });
    })
    .then((response) => response && response.ok ? response.json() : null)
    .then((result) => {
      if (!result || !result.state) return;
      const state = result.state;
      write(LS_LIST, state.watchlist || []);
      write(LS_PROGRESS, state.progress || {});
      write(LS_WATCHED, state.watched || {});
      write(LS_CATALOG, state.catalog || {});
      write(LS_REMOVED, state.removed || {});
      /* Removing something is this device's decision. Keep the tombstones it
       * holds even if the reply does not carry them back, so a failed or
       * half-merged sync cannot quietly re-add the film. */
      const synced = Object.assign({}, state.dropped || {});
      const local = getDropped();
      Object.keys(local).forEach((id) => {
        if ((local[id] || 0) > (synced[id] || 0)) synced[id] = local[id];
      });
      write(LS_DROPPED, synced);
      paint();
    })
    .catch(() => {
      /* Offline browsing remains available when the account server is down. */
    });
}

function updateAuthUi(account, message) {
  const guest = document.querySelector("[data-auth-guest]");
  const signedIn = document.querySelector("[data-auth-user]");
  const name = document.querySelector("[data-auth-name]");
  const status = document.querySelector("[data-auth-status]");
  const loggedIn = !!(account && account.authenticated);
  if (guest) {
    guest.hidden = loggedIn;
    if (loggedIn) guest.setAttribute("hidden", "hidden");
    else guest.removeAttribute("hidden");
  }
  if (signedIn) {
    signedIn.hidden = !loggedIn;
    if (loggedIn) signedIn.removeAttribute("hidden");
    else signedIn.setAttribute("hidden", "hidden");
  }
  if (name) name.textContent = loggedIn ? account.user.display : "";
  if (status) {
    status.textContent = message || "";
    status.className = "auth-status" + (message ? " good" : "");
  }
}

function wireAuth() {
  fetch("/auth/me", { credentials: "same-origin" })
    .then((response) => response.json())
    .then((account) => updateAuthUi(account))
    .catch(() => updateAuthUi({ authenticated: false }));

  document.addEventListener("submit", (event) => {
    const form = event.target.closest("[data-auth-form]");
    if (!form) return;
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    fetch(form.action, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data)
    })
      .then(async (response) => {
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Could not sign in.");
        return result;
      })
      .then((account) => {
        form.reset();
        updateAuthUi(account, "Signed in. Your library is syncing.");
        syncAccount();
      })
      .catch((error) => updateAuthUi({ authenticated: false }, error.message));
  });

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-auth-logout]");
    if (!button) return;
    fetch("/auth/logout", { method: "POST", credentials: "same-origin" })
      .then(() => {
        updateAuthUi({ authenticated: false }, "You are signed out.");
        paint();
      });
  });
}

/* ----------------------------------------------------------------- wiring */

document.addEventListener("click", function (event) {
  const btn = event.target.closest("[data-action]");
  if (btn) {
    const action = btn.dataset.action;
    if (action === "toggle") {
      const card = btn.closest("[data-id]");
      if (card) {
        const listHref = card.dataset.listHref || "";
        toggleList({
          id: listIdOf(card),
          title: card.dataset.title,
          cover: card.dataset.cover,
          url: listHref || card.dataset.url,
          href: listHref || card.dataset.href,
          year: card.dataset.year,
          lang: card.dataset.lang
        });
      }
    } else if (action === "drop") {
      const card = btn.closest("[data-id]");
      if (card) dropFromContinue(card.dataset.id);
    } else if (action === "clear-continue") {
      setContinueConfirm(true);
    } else if (action === "confirm-clear-continue") {
      clearContinueWatching();
    } else if (action === "cancel-clear-continue") {
      setContinueConfirm(false);
    } else if (action === "clear-watchlist") {
      const removed = getRemoved();
      getList().forEach((item) => {
        if (item && item.id) removed[item.id] = Date.now();
      });
      write(LS_REMOVED, removed);
      setList([]);
    } else if (action === "copy") {
      const text = btn.dataset.copy || "";
      if (navigator.clipboard && text) {
        navigator.clipboard.writeText(text).catch(function () {});
      }
      const label = btn.textContent;
      btn.textContent = "Copied";
      window.setTimeout(function () {
        btn.textContent = label;
      }, 1600);
    } else if (action === "clear-search") {
      const form = btn.closest("form");
      const field = form && form.querySelector('input[name="q"]');
      if (field) {
        field.value = "";
        field.dispatchEvent(new Event("input"));
        field.focus();
      }
    } else if (action === "clear-all") {
      [LS_LIST, LS_PROGRESS, LS_WATCHED, LS_CATALOG, LS_REMOVED, LS_DROPPED].forEach((k) =>
        localStorage.removeItem(k));
      paint();
    }
    syncAccount();
    return;
  }

  const arrow = event.target.closest("[data-scroll]");
  if (arrow) {
    const shelf = arrow.closest(".shelf");
    const rail = shelf && shelf.querySelector(".rail");
    const ctl = rail && rails.get(rail);
    if (ctl) {
      ctl.glide(rail.scrollLeft +
        Number(arrow.dataset.scroll) * rail.clientWidth * 0.85);
    }
  }
});

document.addEventListener("input", function (event) {
  const input = event.target;
  if (!input.matches || !input.matches('.search-field input[name="q"]')) return;
  const btn = input.parentElement.querySelector('[data-action="clear-search"]');
  if (btn) btn.hidden = !input.value;
});

document.querySelectorAll('.search-field input[name="q"]').forEach((input) => {
  const btn = input.parentElement.querySelector('[data-action="clear-search"]');
  if (btn) btn.hidden = !input.value;
});

normaliseList();
paint();
wireAuth();
syncAccount();
wirePlayer();
wireVidspark();
wireRails();
wireBar();
window.addEventListener("pageshow", () => {
  paint();
  wireRails();
});
