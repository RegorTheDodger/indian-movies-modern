"""The embed player for the English library.

VidSpark takes ids this app already has: IMDb ids from Cinemeta, and the season
and episode numbers the title page already tracks. Playback is an iframe, so
nothing is downloaded, converted or proxied here — which is exactly what makes
it work on Vercel as well as on the Mac.

Unlike a dumb embed, this one is two-way. Its documentation promises:

  * `?t=<seconds>` or `?startAt=1h5m30s` to open at a position;
  * its own auto-resume per viewer, which an explicit `t` overrides;
  * `postMessage` events tagged `source: "vidspark-player"` for play, pause,
    seeked and ended, with `currentTime` and `duration`.

static/app.js listens to those events, so resume, watch time and "finished"
stay in this app's own storage and follow a person between the modern site and
the Lumia build through the account sync.
"""

BASE = "https://vidspark.to"


def available():
    return True


def embed_url(kind, imdb_id, season=0, episode=0, start=0):
    """The player URL for a film or one episode, or "" when unusable.

    Only IMDb ids: that is what Cinemeta returns and what VidSpark documents,
    and guessing at any other mapping would fail silently.
    """
    imdb_id = (imdb_id or "").strip()
    if not imdb_id.startswith("tt"):
        return ""
    if kind == "series":
        if not season or not episode:
            return ""
        url = "%s/tv/%s/%d/%d" % (BASE, imdb_id, int(season), int(episode))
    else:
        url = "%s/movie/%s" % (BASE, imdb_id)
    if start and start > 0:
        url += "?t=%d" % int(start)
    return url
