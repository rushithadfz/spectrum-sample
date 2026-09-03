/* ============================================================
   Motion + game feedback: scroll reveals, animated bars, confetti,
   toasts and the level-up moment. Vanilla JS, no dependencies.
   ============================================================ */
(function () {
  "use strict";

  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------------- reveal on scroll ---------------- */
  function initReveal() {
    var targets = document.querySelectorAll("[data-reveal]");
    if (!targets.length) return;

    if (reduce || !("IntersectionObserver" in window)) {
      targets.forEach(function (el) { el.classList.add("in"); });
      return;
    }

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        var el = entry.target;
        // Stagger siblings so a grid cascades instead of snapping in at once.
        var delay = parseInt(el.dataset.revealDelay || "0", 10);
        setTimeout(function () { el.classList.add("in"); }, delay);
        io.unobserve(el);
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });

    targets.forEach(function (el, i) {
      if (!el.dataset.revealDelay) el.dataset.revealDelay = String((i % 6) * 55);
      io.observe(el);
    });
  }

  /* ---------------- fill bars from zero ---------------- */
  function initBars() {
    // Widths are rendered inline by Django; move them to a data attribute so
    // the bar can start at zero and animate to the real value.
    var bars = document.querySelectorAll(".bar > span, .xp-mini-track > span, .quest-track > span");
    bars.forEach(function (el) {
      var target = el.style.width;
      if (!target) return;
      el.dataset.target = target;
      if (reduce) return;
      el.style.width = "0%";
    });

    var chart = document.querySelectorAll(".chart-bar");
    chart.forEach(function (el) {
      el.dataset.target = el.style.height;
      if (!reduce) el.style.height = "0%";
    });

    function run() {
      bars.forEach(function (el) {
        if (el.dataset.target) el.style.width = el.dataset.target;
      });
      chart.forEach(function (el) {
        if (el.dataset.target) el.style.height = el.dataset.target;
      });
    }
    // One frame later so the browser registers the zero state first.
    requestAnimationFrame(function () { requestAnimationFrame(run); });
  }

  /* ---------------- toasts ---------------- */
  function stack() {
    var el = document.querySelector(".toast-stack");
    if (!el) {
      el = document.createElement("div");
      el.className = "toast-stack";
      document.body.appendChild(el);
    }
    return el;
  }

  function toast(icon, title, sub, ms) {
    var el = document.createElement("div");
    el.className = "toast";
    el.innerHTML = '<span class="toast-ic"></span><span><span class="toast-title"></span>' +
                   '<br><span class="toast-sub"></span></span>';
    el.querySelector(".toast-ic").textContent = icon;
    el.querySelector(".toast-title").textContent = title;
    el.querySelector(".toast-sub").textContent = sub || "";
    stack().appendChild(el);
    setTimeout(function () {
      el.classList.add("out");
      setTimeout(function () { el.remove(); }, 340);
    }, ms || 4200);
  }
  window.portalToast = toast;

  /* ---------------- confetti ---------------- */
  function confetti(burst) {
    if (reduce) return;
    var canvas = document.getElementById("confetti");
    if (!canvas) {
      canvas = document.createElement("canvas");
      canvas.id = "confetti";
      document.body.appendChild(canvas);
    }
    var ctx = canvas.getContext("2d");
    var dpr = window.devicePixelRatio || 1;
    canvas.width = innerWidth * dpr;
    canvas.height = innerHeight * dpr;

    var colours = ["#ffc53d", "#0073d1", "#35d0ff", "#128a4b", "#ff7a3d", "#ffffff"];
    var pieces = [];
    for (var i = 0; i < (burst || 110); i++) {
      pieces.push({
        x: canvas.width / 2 + (Math.random() - 0.5) * canvas.width * 0.5,
        y: canvas.height * 0.32 + (Math.random() - 0.5) * 80,
        vx: (Math.random() - 0.5) * 11 * dpr,
        vy: (Math.random() * -12 - 3) * dpr,
        size: (Math.random() * 6 + 4) * dpr,
        spin: (Math.random() - 0.5) * 0.3,
        angle: Math.random() * Math.PI,
        colour: colours[(Math.random() * colours.length) | 0],
        life: 1
      });
    }

    var gravity = 0.32 * dpr;
    function frame() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      var alive = false;
      pieces.forEach(function (p) {
        p.vy += gravity;
        p.x += p.vx;
        p.y += p.vy;
        p.angle += p.spin;
        p.life -= 0.006;
        if (p.life <= 0 || p.y > canvas.height + 40) return;
        alive = true;
        ctx.save();
        ctx.translate(p.x, p.y);
        ctx.rotate(p.angle);
        ctx.globalAlpha = Math.max(0, p.life);
        ctx.fillStyle = p.colour;
        ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.6);
        ctx.restore();
      });
      if (alive) requestAnimationFrame(frame);
      else ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
    requestAnimationFrame(frame);
  }
  window.portalConfetti = confetti;

  /* ---------------- rewards from the query string ---------------- */
  function initRewards() {
    var params = new URLSearchParams(location.search);
    var xp = parseInt(params.get("xp") || "0", 10);
    var levelup = params.get("levelup");
    if (!xp && !levelup) return;

    if (xp) {
      toast("✨", "+" + xp + " XP", "Quest complete");
      confetti(90);
    }

    if (levelup) {
      var overlay = document.getElementById("levelup");
      if (overlay) {
        overlay.hidden = false;
        overlay.style.display = "grid";
        var num = overlay.querySelector(".levelup-badge");
        if (num) num.textContent = levelup;
        setTimeout(function () { confetti(160); }, 260);

        function dismiss() {
          overlay.hidden = true;
          overlay.style.display = "none";
        }
        var btn = overlay.querySelector("[data-close-levelup]");
        if (btn) btn.addEventListener("click", dismiss);
        overlay.addEventListener("click", function (e) {
          if (e.target === overlay) dismiss();
        });
        document.addEventListener("keydown", function (e) {
          if (e.key === "Escape") dismiss();
        });
      }
    }

    // Clean the URL so a refresh does not replay the celebration.
    history.replaceState(null, "", location.pathname);
  }

  /* ---------------- badge pop for freshly earned badges ---------------- */
  function initBadges() {
    if (reduce) return;
    var earned = document.querySelectorAll(".badge-tile.earned");
    earned.forEach(function (el, i) {
      setTimeout(function () {
        el.classList.add("pop");
        setTimeout(function () { el.classList.remove("pop"); }, 700);
      }, 300 + i * 90);
    });
  }

  /* ---------------- celebrate a completed programme ---------------- */
  function initGoalCelebration() {
    var done = document.querySelectorAll("[data-complete='1']");
    if (!done.length) return;
    setTimeout(function () {
      toast("🏆", "Programme complete", done[0].dataset.name || "");
      confetti(120);
    }, 700);
  }

  initReveal();
  initBars();
  initRewards();
  initBadges();
  initGoalCelebration();
})();
