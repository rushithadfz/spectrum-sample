/* ============================================================
   Interaction layer.

   Four things, all progressive enhancement - the server already
   renders the correct state, this makes it respond:

     1. Live payout preview on the sale form
     2. A chart you can actually interrogate
     3. Progress rings that fill on arrival
     4. Quest claims that feel like they landed

   Nothing here is required for the page to work.
   ============================================================ */
(function () {
  "use strict";

  var reduced = window.matchMedia &&
                window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var money = function (n) {
    return "$" + n.toLocaleString("en-US", {
      minimumFractionDigits: 2, maximumFractionDigits: 2
    });
  };

  /* ---------------------------------------------------------
     1. Live payout preview
     Pick an offer, change the units, and see what the sale is
     worth before submitting it. The server still recomputes on
     save - this only mirrors the same arithmetic.
     --------------------------------------------------------- */
  function payoutPreview() {
    var data = document.getElementById("offerRates");
    var offer = document.getElementById("id_offer");
    var units = document.getElementById("id_units");
    var box = document.getElementById("payoutPreview");
    if (!data || !offer || !units || !box) return;

    var rates;
    try { rates = JSON.parse(data.textContent || "{}"); } catch (e) { return; }

    var elAmount = document.getElementById("ppAmount");
    var elBase = document.getElementById("ppBase");
    var elSpiff = document.getElementById("ppSpiff");
    var elUnits = document.getElementById("ppUnits");

    function update() {
      var rate = rates[offer.value];
      var n = parseInt(units.value, 10);
      if (!rate || !n || n < 1) { box.hidden = true; return; }

      var base = rate.commission * n;
      var spiff = rate.spiff * n;
      box.hidden = false;
      elBase.textContent = money(base);
      elSpiff.textContent = money(spiff);
      elUnits.textContent = n;
      countTo(elAmount, base + spiff);
      box.classList.remove("pulse");
      // Restart the pulse so every change registers visibly.
      void box.offsetWidth;
      box.classList.add("pulse");
    }

    offer.addEventListener("change", update);
    units.addEventListener("input", update);
    update();
  }

  /* Count an element up to a value, so figures land rather than snap. */
  function countTo(el, target) {
    if (!el) return;
    if (reduced) { el.textContent = money(target); return; }
    var from = parseFloat((el.textContent || "0").replace(/[^0-9.]/g, "")) || 0;
    var start = performance.now(), ms = 420;
    (function step(now) {
      var t = Math.min((now - start) / ms, 1);
      var eased = 1 - Math.pow(1 - t, 3);
      el.textContent = money(from + (target - from) * eased);
      if (t < 1) requestAnimationFrame(step);
    })(performance.now());
  }

  /* ---------------------------------------------------------
     2. The chart responds to the pointer
     Hovering anywhere selects the nearest month rather than
     requiring you to hit a 9px dot.
     --------------------------------------------------------- */
  function chart() {
    var wrap = document.querySelector(".area-wrap");
    if (!wrap) return;
    var pts = [].slice.call(wrap.querySelectorAll(".area-pt"));
    if (!pts.length) return;

    // Draw the line in on arrival.
    var line = wrap.querySelector(".area-line");
    if (line && !reduced && line.getTotalLength) {
      var len = line.getTotalLength();
      line.style.strokeDasharray = len;
      line.style.strokeDashoffset = len;
      requestAnimationFrame(function () {
        line.style.transition = "stroke-dashoffset 1.1s cubic-bezier(.22,.68,.28,1)";
        line.style.strokeDashoffset = "0";
      });
    }

    var current = pts[pts.length - 1];

    function select(pt) {
      if (pt === current) return;
      pts.forEach(function (p) { p.classList.remove("active"); });
      pt.classList.add("active");
      current = pt;
    }

    wrap.addEventListener("pointermove", function (e) {
      var box = wrap.getBoundingClientRect();
      var x = e.clientX - box.left;
      var best = null, bestDist = Infinity;
      pts.forEach(function (p) {
        var px = p.offsetLeft;
        var d = Math.abs(px - x);
        if (d < bestDist) { bestDist = d; best = p; }
      });
      if (best) select(best);
    });

    wrap.addEventListener("pointerleave", function () {
      pts.forEach(function (p) { p.classList.remove("active"); });
      current = null;
    });
  }

  /* ---------------------------------------------------------
     3. Progress rings
     An Apple-Fitness style ring reads as progress far faster
     than a percentage does. Filled from a data attribute so
     the server stays the source of truth.
     --------------------------------------------------------- */
  function rings() {
    document.querySelectorAll("[data-ring]").forEach(function (svg) {
      var arc = svg.querySelector(".ring-value");
      if (!arc) return;
      var pct = Math.max(0, Math.min(100, parseFloat(svg.getAttribute("data-ring")) || 0));
      var r = arc.r.baseVal.value;
      var c = 2 * Math.PI * r;
      arc.style.strokeDasharray = c;
      arc.style.strokeDashoffset = c;
      var target = c - (pct / 100) * c;
      if (reduced) { arc.style.strokeDashoffset = target; return; }
      requestAnimationFrame(function () {
        arc.style.transition = "stroke-dashoffset 1.2s cubic-bezier(.22,.68,.28,1)";
        arc.style.strokeDashoffset = target;
      });
    });
  }

  /* ---------------------------------------------------------
     4. Quest claims land
     The XP floats up off the button it came from. Submission
     is left to the form - this only marks the moment.
     --------------------------------------------------------- */
  function questFeedback() {
    document.addEventListener("click", function (e) {
      var btn = e.target.closest(".quest-claim");
      if (!btn || reduced) return;
      var xp = (btn.textContent.match(/\+?\d+/) || ["+XP"])[0];
      var box = btn.getBoundingClientRect();
      var float = document.createElement("span");
      float.className = "xp-float";
      float.textContent = "+" + String(xp).replace("+", "") + " XP";
      float.style.left = (box.left + box.width / 2) + "px";
      float.style.top = box.top + "px";
      document.body.appendChild(float);
      setTimeout(function () { float.remove(); }, 1000);
    });
  }

  /* The character acknowledges being spoken to. */
  function characterNudge() {
    document.addEventListener("click", function (e) {
      var trigger = e.target.closest("#askFab, .next-action");
      if (!trigger) return;
      var ch = trigger.querySelector(".ch");
      if (!ch || reduced) return;
      ch.classList.remove("is-nudged");
      void ch.offsetWidth;               // restart the animation
      ch.classList.add("is-nudged");
      setTimeout(function () { ch.classList.remove("is-nudged"); }, 600);
    });
  }

  /* ---------------------------------------------------------
     The daily roll.

     The face was decided on the server the moment you signed in and
     the XP is already banked, so this cannot change the outcome - it
     only reveals it, and only when the agent asks for it. Rolling on
     its own robs them of the one bit of theatre in the feature.
     --------------------------------------------------------- */
  function dailyRoll() {
    var roll = document.querySelector(".roll");
    if (!roll) return;
    var die = roll.querySelector(".die-btn");
    var real = roll.getAttribute("data-face");
    var verb = roll.querySelector(".roll-verb");
    var result = roll.querySelector(".roll-result");
    if (!die) return;

    function reveal() {
      roll.setAttribute("data-face", real);
      roll.classList.remove("is-rolling");
      roll.classList.add("is-settled");
      if (verb) verb.hidden = true;
      if (result) result.hidden = false;
      die.setAttribute("aria-label", "You rolled " + real);
      die.disabled = true;
    }

    die.addEventListener("click", function () {
      if (roll.getAttribute("data-rolled") === "1") return;   // one roll only
      roll.setAttribute("data-rolled", "1");
      roll.classList.remove("is-ready");

      if (reduced) { reveal(); return; }

      // The cube tumbles for a fixed beat, then the class swap lets the
      // data-face transform bring the real face round to the front.
      roll.classList.add("is-rolling");
      setTimeout(reveal, 1150);
    });
  }

  function init() {
    dailyRoll();
    characterNudge();
    payoutPreview();
    chart();
    rings();
    questFeedback();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
