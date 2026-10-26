/*
 * Motion primitives, after Apple's Designing Fluid Interfaces.
 *
 * The rule everything here follows: animate from whatever is on screen right
 * now, inherit the pointer's velocity, and stay interruptible. A fixed
 * duration CSS transition cannot do any of that, so the rails run their own
 * spring on requestAnimationFrame and never animate with @keyframes.
 *
 * Springs are described the way Apple describes them, with damping ratio and
 * response, rather than mass/stiffness/damping.
 *
 *   damping ratio  1.0 = critically damped, no overshoot
 *                 <1.0 = overshoots, which only suits momentum gestures
 *   response       roughly how long it takes to settle, in seconds
 */

/* ------------------------------------------------------------ preferences */

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/* ----------------------------------------------------------------- spring */

/*
 * Critically damped by default. Overshoot is reserved for releases that
 * actually carried momentum, because bounce on something that merely faded
 * in reads as a mistake.
 */
function spring(opts) {
  var from = opts.from;
  var to = opts.to;
  var damping = opts.damping === undefined ? 1 : opts.damping;
  var response = opts.response === undefined ? 0.4 : opts.response;
  var onUpdate = opts.onUpdate;
  var onRest = opts.onRest;

  if (prefersReducedMotion()) {
    onUpdate(to);
    if (onRest) onRest();
    return { stop: function () {} };
  }

  /* Apple derives stiffness from response: one full cycle in `response` s */
  var omega = (2 * Math.PI) / response;
  var stiffness = omega * omega;
  var dampingC = 2 * damping * omega;

  var x = from - to;              /* displacement from the target */
  var v = opts.velocity || 0;     /* px/s, carried in from the gesture */

  var raf = 0;
  var last = 0;
  var stopped = false;

  function frame(now) {
    if (stopped) return;
    if (!last) last = now;
    /* clamp dt so a backgrounded tab does not explode the integration */
    var dt = Math.min((now - last) / 1000, 1 / 30);
    last = now;

    /* fixed substeps keep it stable at any refresh rate */
    var steps = Math.max(1, Math.ceil(dt / (1 / 240)));
    var h = dt / steps;
    for (var i = 0; i < steps; i++) {
      var a = -stiffness * x - dampingC * v;
      v += a * h;
      x += v * h;
    }

    var value = to + x;
    onUpdate(value);

    /* settled when close enough and slow enough to stop mattering */
    if (Math.abs(x) < 0.35 && Math.abs(v) < 12) {
      onUpdate(to);
      stopped = true;
      if (onRest) onRest();
      return;
    }
    raf = requestAnimationFrame(frame);
  }

  raf = requestAnimationFrame(frame);

  return {
    stop: function () { stopped = true; cancelAnimationFrame(raf); },
    get running() { return !stopped; }
  };
}

/* -------------------------------------------------------------- momentum */

/* Apple's projection, from the Designing Fluid Interfaces sample code. */
function project(velocity, decelerationRate) {
  var d = decelerationRate === undefined ? 0.998 : decelerationRate;
  return (velocity / 1000) * d / (1 - d);
}

/* Progressive resistance at an edge, rather than a hard stop that reads
 * as frozen. */
function rubberband(overshoot, dimension, constant) {
  var c = constant === undefined ? 0.55 : constant;
  return (overshoot * dimension * c) / (dimension + c * Math.abs(overshoot));
}

/* --------------------------------------------------------- rail dragging */

/* A drag that actually moved must not also activate whatever was under the
 * pointer. One listener per rail, removed after it fires. */
function suppressNextClick(rail) {
  function swallow(event) {
    event.stopPropagation();
    event.preventDefault();
    rail.removeEventListener("click", swallow, true);
  }
  rail.addEventListener("click", swallow, true);
  /* never leave the listener armed if no click follows */
  setTimeout(function () {
    rail.removeEventListener("click", swallow, true);
  }, 350);
}

/*
 * 1:1 drag, velocity tracking, momentum on release, and interruptible
 * throughout: grabbing a rail that is already animating stops the spring and
 * hands control straight back, from the position it was actually at.
 */
function attachDrag(rail) {
  var springRun = null;
  var drag = null;
  var history = [];

  function bounds() {
    return { min: 0, max: Math.max(0, rail.scrollWidth - rail.clientWidth) };
  }

  function clamp(value, b) {
    return Math.min(b.max, Math.max(b.min, value));
  }

  function applyRubber(value, b) {
    if (value < b.min) return b.min - rubberband(b.min - value, rail.clientWidth);
    if (value > b.max) return b.max + rubberband(value - b.max, rail.clientWidth);
    return value;
  }

  function onDown(event) {
    if (event.button !== undefined && event.button !== 0) return;

    /* Deliberately no setPointerCapture here. Capturing on pointer-down
     * retargets the follow-up click to the rail, which silently swallows
     * every tap on a poster inside it. Capture happens once the gesture has
     * actually become a drag. */
    if (springRun && springRun.running) {
      springRun.stop();
      springRun = null;
    }

    history = [{ x: event.clientX, t: event.timeStamp }];
    drag = {
      id: event.pointerId,
      startX: event.clientX,
      startScroll: rail.scrollLeft,
      moved: false,
      captured: false
    };
  }

  function onMove(event) {
    if (!drag || event.pointerId !== drag.id) return;

    var dx = event.clientX - drag.startX;

    /* hysteresis: a tap and a small adjustment must not become a drag */
    if (!drag.moved && Math.abs(dx) < 10) return;

    if (!drag.moved) {
      drag.moved = true;
      /* now it is unambiguously a drag, so take the pointer */
      try {
        rail.setPointerCapture(drag.id);
        drag.captured = true;
      } catch (e) { /* not capturable, tracking still works inside the rail */ }
      rail.classList.add("grabbing");
    }

    /* content follows the finger exactly, including the grab offset */
    var b = bounds();
    rail.scrollLeft = applyRubber(drag.startScroll - dx, b);

    history.push({ x: event.clientX, t: event.timeStamp });
    if (history.length > 5) history.shift();
  }

  function onUp(event) {
    if (!drag || (event && event.pointerId !== drag.id)) return;

    var wasMoved = drag.moved;
    var b = bounds();
    var current = rail.scrollLeft;
    var velocity = 0;

    if (wasMoved && history.length > 1) {
      var first = history[0];
      var last = history[history.length - 1];
      var dt = (last.t - first.t) / 1000;
      if (dt > 0.001) velocity = (first.x - last.x) / dt; /* px/s */
    }

    drag = null;
    rail.classList.remove("grabbing");
    try {
      if (event) rail.releasePointerCapture(event.pointerId);
    } catch (e) { /* never captured */ }

    /* a plain tap: leave the click alone so the link inside works */
    if (!wasMoved) return;

    /* a real drag must not also fire the link underneath it */
    suppressNextClick(rail);

    /* outside the rails there is nothing to settle, let go back immediately */
    if (current < b.min || current > b.max) {
      springRun = spring({
        from: current, to: clamp(current, b), velocity: velocity,
        damping: 1, response: 0.35,
        onUpdate: function (v) { rail.scrollLeft = v; },
        onRest: function () { springRun = null; }
      });
      return;
    }

    if (Math.abs(velocity) < 60) return;   /* a nudge, not a flick */

    /* throw it: project where the finger was heading, then spring there */
    var projected = clamp(current + project(velocity), b);
    if (Math.abs(projected - current) < 1) return;

    /* a flick carries momentum, so a little overshoot is honest here */
    springRun = spring({
      from: current, to: projected, velocity: velocity,
      damping: 0.85, response: 0.45,
      onUpdate: function (v) { rail.scrollLeft = v; },
      onRest: function () { springRun = null; }
    });
  }

  rail.addEventListener("pointerdown", onDown);
  rail.addEventListener("pointermove", onMove);
  rail.addEventListener("pointerup", onUp);
  rail.addEventListener("pointercancel", onUp);

  /* keyboard and arrow buttons should move at the same physical feel */
  rail.addEventListener("keydown", function (event) {
    var step = rail.clientWidth * 0.85;
    var b = bounds();
    if (event.key === "ArrowRight") {
      springRun = glide(rail, rail.scrollLeft, clamp(rail.scrollLeft + step, b));
    } else if (event.key === "ArrowLeft") {
      springRun = glide(rail, rail.scrollLeft, clamp(rail.scrollLeft - step, b));
    } else {
      return;
    }
    event.preventDefault();
  });

  function glide(el, from, to) {
    if (prefersReducedMotion()) {
      el.scrollLeft = to;
      return { stop: function () {}, running: false };
    }
    return spring({
      from: from, to: to, velocity: 0, damping: 1, response: 0.42,
      onUpdate: function (v) { el.scrollLeft = v; }
    });
  }

  return {
    glide: function (to) {
      var b = bounds();
      if (springRun && springRun.running) springRun.stop();
      springRun = glide(rail, rail.scrollLeft, clamp(to, b));
    },
    bounds: bounds
  };
}

window.Motion = {
  spring: spring,
  project: project,
  rubberband: rubberband,
  attachDrag: attachDrag,
  prefersReducedMotion: prefersReducedMotion
};
