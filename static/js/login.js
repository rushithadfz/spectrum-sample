/* ============================================================
   Sign-in screen behaviour. Vanilla JS, no dependencies.
   Everything here is presentation - authentication is Django's.
   ============================================================ */
(function () {
  "use strict";

  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------------------------------------------------------
     1. Animated backdrop: a slow drifting constellation grid
     --------------------------------------------------------- */
  function startCanvas() {
    var canvas = document.getElementById("grid-canvas");
    if (!canvas || reduce) return;

    var ctx = canvas.getContext("2d");
    var nodes = [];
    var w, h;

    function resize() {
      w = canvas.width = canvas.offsetWidth * devicePixelRatio;
      h = canvas.height = canvas.offsetHeight * devicePixelRatio;
      // Density scales with area so a big monitor doesn't look empty.
      var count = Math.min(90, Math.round((w * h) / (26000 * devicePixelRatio)));
      nodes = [];
      for (var i = 0; i < count; i++) {
        nodes.push({
          x: Math.random() * w,
          y: Math.random() * h,
          vx: (Math.random() - 0.5) * 0.22 * devicePixelRatio,
          vy: (Math.random() - 0.5) * 0.22 * devicePixelRatio,
          r: (Math.random() * 1.6 + 0.6) * devicePixelRatio
        });
      }
    }

    var LINK = 132;
    function frame() {
      ctx.clearRect(0, 0, w, h);
      var link = LINK * devicePixelRatio;

      for (var i = 0; i < nodes.length; i++) {
        var n = nodes[i];
        n.x += n.vx; n.y += n.vy;
        if (n.x < 0 || n.x > w) n.vx *= -1;
        if (n.y < 0 || n.y > h) n.vy *= -1;

        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(200,205,212,.40)";
        ctx.fill();

        for (var j = i + 1; j < nodes.length; j++) {
          var m = nodes[j];
          var dx = n.x - m.x, dy = n.y - m.y;
          var d = Math.sqrt(dx * dx + dy * dy);
          if (d < link) {
            ctx.beginPath();
            ctx.moveTo(n.x, n.y);
            ctx.lineTo(m.x, m.y);
            ctx.strokeStyle = "rgba(190,196,205," + (0.14 * (1 - d / link)).toFixed(3) + ")";
            ctx.lineWidth = devicePixelRatio;
            ctx.stroke();
          }
        }
      }
      requestAnimationFrame(frame);
    }

    resize();
    window.addEventListener("resize", resize);
    requestAnimationFrame(frame);
  }

  /* ---------------------------------------------------------
     2. Count-up numbers and the XP ring / bar
     --------------------------------------------------------- */
  function easeOut(t) { return 1 - Math.pow(1 - t, 3); }

  function countUp(el, to, ms) {
    if (reduce) { el.textContent = to.toLocaleString(); return; }
    var start = performance.now();
    (function step(now) {
      var p = Math.min(1, (now - start) / ms);
      el.textContent = Math.round(to * easeOut(p)).toLocaleString();
      if (p < 1) requestAnimationFrame(step);
    })(start);
  }

  function startProgression() {
    document.querySelectorAll(".countup").forEach(function (el, i) {
      var to = parseInt(el.dataset.to, 10) || 0;
      setTimeout(function () { countUp(el, to, 1100); }, 180 + i * 110);
    });

    // The hero panel describes the whole portal, not any one person.
    var teamsEl = document.querySelector(".gchip b");
    var LEVEL = parseInt((document.querySelectorAll(".gchip b")[1] || {}).textContent, 10) || 4;
    var pct = 28 / 31;      // days elapsed in the period

    var lvlNum = document.getElementById("lvlNum");
    if (lvlNum) setTimeout(function () { countUp(lvlNum, LEVEL, 900); }, 200);



    setTimeout(function () {
      var fill = document.getElementById("xpFill");
      if (fill) fill.style.width = (pct * 100) + "%";

      var ring = document.getElementById("lvlRing");
      if (ring) {
        var circumference = 2 * Math.PI * 33;   // r=33 in the SVG
        ring.style.strokeDashoffset = circumference * (1 - pct);
      }
    }, 350);
  }

  /* ---------------------------------------------------------
     3. Rotating objective ticker
     --------------------------------------------------------- */
  var OBJECTIVES = [
    "Close 2 more bundles to finish the Double-Play Bonus — $150 still on the table.",
    "Weekend Blitz ends Aug 31. 9 more 500 Mbps sales completes it.",
    "9 mobile lines from the 50-line accelerator bonus. That is +$250 flat.",
    "Attach Advanced WiFi to every install — the fastest $25 on the board.",
    "You are 12 units from quota. Every sale past it pays 1.15x."
  ];

  function startTicker() {
    var box = document.getElementById("objective");
    if (!box) return;
    var text = box.querySelector(".obj-text");
    var i = 0;

    function show() {
      text.textContent = OBJECTIVES[i];
      box.classList.remove("swap");
      void box.offsetWidth;          // restart the CSS animation
      box.classList.add("swap");
      i = (i + 1) % OBJECTIVES.length;
    }
    show();
    if (!reduce) setInterval(show, 4800);
  }

  /* ---------------------------------------------------------
     4. Role picker - no credentials, pick a persona and enter
     --------------------------------------------------------- */
  function startRolePicker() {
    var form = document.getElementById("roleForm");
    if (!form) return;

    var cards = Array.prototype.slice.call(form.querySelectorAll(".persona"));
    var btn = document.getElementById("enterBtn");
    var label = document.getElementById("enterLabel");

    function select(card) {
      if (card.classList.contains("locked")) {
        // Locked roles are on the picker for shape only.
        card.classList.add("shake");
        setTimeout(function () { card.classList.remove("shake"); }, 450);
        return;
      }
      cards.forEach(function (c) { c.classList.remove("on"); });
      card.classList.add("on");
      // The Continue button carries the chosen slug, so the form posts one
      // value whether you use a card or the button.
      btn.value = card.dataset.persona;
      label.textContent = "Enter as " + card.dataset.name.split(" ")[0];
    }

    cards.forEach(function (card) {
      card.addEventListener("click", function (e) {
        // With JS on, a card selects rather than submitting. With JS off it is
        // a plain submit button and signs you straight in.
        e.preventDefault();
        select(card);
      });
      card.addEventListener("keydown", function (e) {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        select(card);
      });
    });

    // Open on the flagged persona (a field agent), not simply the first card.
    var preferred = form.querySelector(".persona[data-default]") ||
                    cards.filter(function (c) { return !c.classList.contains("locked"); })[0];
    if (preferred) {
      select(preferred);
      if (preferred.scrollIntoView) {
        preferred.scrollIntoView({ block: "nearest" });
      }
    }

    form.addEventListener("submit", function () {
      btn.classList.add("charging");
      label.textContent = "Entering…";
    });

    if (document.getElementById("authError")) {
      var card = document.querySelector(".login-card");
      card.classList.add("shake");
      setTimeout(function () { card.classList.remove("shake"); }, 450);
    }
  }

  /* --------------------------------------------------------- */
  startCanvas();
  startProgression();
  startTicker();
  startRolePicker();
})();
