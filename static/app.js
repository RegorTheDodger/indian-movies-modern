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

/* past this fraction a film counts as finished and drops off continue */
const DONE_AT = 0.95;
/* under this many seconds it is not worth remembering */
const MIN_SECONDS = 8;
/* a jump longer than this is a seek, not watching */
const SEEK_LIMIT = 6;

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
    year: item.year || prev.year || "",
    lang: item.lang || prev.lang || ""
  };
  write(LS_CATALOG, cat);
}

function toggleList(item) {
  const list = getList();
  const at = list.findIndex((m) => m.id === item.id);
  if (at >= 0) {
    list.splice(at, 1);
  } else {
    list.unshift({
      id: item.id,
      title: item.title,
      cover: item.cover || "",
      url: item.url,
      year: item.year || "",
      lang: item.lang || ""
    });
  }
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

/* Cumulative play time, which is what the Recently played rail sorts by.
 * Separate from the resume position on purpose: the resume entry is deleted
 * when a film finishes, and this has to outlive it. */
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

function recentlyPlayed() {
  const watched = getWatched();
  return Object.keys(watched)
    .filter((id) => (watched[id].seconds || 0) > 0)
    .sort((a, b) => (watched[b].at || 0) - (watched[a].at || 0))
    .map((id) => Object.assign({}, watched[id], { id: id }))
    .slice(0, 24);
}

function continueWatching() {
  const p = getProgress();
  const cat = getCatalog();
  const saved = new Set(getList().map((m) => m.id));

  return Object.keys(p)
    .map((id) => {
      const entry = p[id];
      const meta = Object.assign({}, cat[id] || {}, entry.meta || {});
      if (!meta.id) meta.id = id;
      if (!meta.title) return null;
      if (!meta.url) meta.url = "/watch/" + id;
      meta.frac = entry.duration ? entry.seconds / entry.duration : 0;
      meta.at = entry.at || 0;
      meta.saved = saved.has(id);
      return meta;
    })
    .filter((m) => m && m.frac > 0.01 && m.frac < DONE_AT)
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

function watchHref(m) {
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
  const meta = [m.year, m.lang].filter(Boolean).map(esc).join(" &middot; ");
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
    '" data-year="' + esc(m.year || "") +
    '" data-lang="' + esc(m.lang || "") + '">' +
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
    item = recentlyPlayed()[0] || continueWatching()[0] || null;
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
      year: el.dataset.year,
      lang: el.dataset.lang
    })
  );

  fill("watchlist", list.map((m) => Object.assign({ saved: true }, m)));
  fill("watchlist-full", list.map((m) => Object.assign({ saved: true }, m)));
  fill("continue", continueWatching());
  fill("recent", recentlyPlayed().map((m) =>
    Object.assign({ saved: saved.has(m.id) }, m)));

  document.querySelectorAll(".card-add, .watch-add").forEach((btn) => {
    const card = btn.closest("[data-id]");
    if (card) btn.classList.toggle("on", saved.has(card.dataset.id));
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
    year: wrap.dataset.year
  };
  remember(meta);

  const resume = getProgress()[id];
  const note = wrap.querySelector('[data-role="resume"]');

  if (resume && resume.duration && resume.seconds > MIN_SECONDS) {
    const at = Math.min(resume.seconds, resume.duration - 5);
    video.addEventListener(
      "loadedmetadata",
      function () {
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
  });

  window.addEventListener("pagehide", tick);
  window.addEventListener("beforeunload", tick);
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
        watchlist: getList().map((item) =>
          Object.assign({}, item, { at: item.at || Date.now() })),
        progress: getProgress(),
        watched: getWatched(),
        catalog: getCatalog(),
        removed: {}
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
        toggleList({
          id: card.dataset.id,
          title: card.dataset.title,
          cover: card.dataset.cover,
          url: card.dataset.url,
          year: card.dataset.year,
          lang: card.dataset.lang
        });
      }
    } else if (action === "clear-watchlist") {
      setList([]);
    } else if (action === "clear-search") {
      const form = btn.closest("form");
      const field = form && form.querySelector('input[name="q"]');
      if (field) {
        field.value = "";
        field.dispatchEvent(new Event("input"));
        field.focus();
      }
    } else if (action === "clear-all") {
      [LS_LIST, LS_PROGRESS, LS_WATCHED, LS_CATALOG].forEach((k) =>
        localStorage.removeItem(k));
      paint();
    }
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

paint();
wireAuth();
syncAccount();
wirePlayer();
wireRails();
wireBar();
window.addEventListener("pageshow", () => {
  paint();
  wireRails();
});
