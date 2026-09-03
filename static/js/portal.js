/* ============================================================
   App-bar behaviour: dropdown menus, notifications, command palette,
   auto-submitting filters and delete confirmation.
   Vanilla JS, no dependencies.
   ============================================================ */
(function () {
  "use strict";

  /* ---------------- dropdown menus ---------------- */
  function initMenus() {
    var triggers = Array.prototype.slice.call(document.querySelectorAll("[data-menu]"));
    if (!triggers.length) return;

    function closeAll(except) {
      triggers.forEach(function (t) {
        var menu = document.getElementById(t.dataset.menu);
        if (menu && menu !== except) menu.hidden = true;
      });
    }

    triggers.forEach(function (trigger) {
      var menu = document.getElementById(trigger.dataset.menu);
      if (!menu) return;
      trigger.addEventListener("click", function (e) {
        e.stopPropagation();
        var wasOpen = !menu.hidden;
        closeAll();
        menu.hidden = wasOpen;
      });
      menu.addEventListener("click", function (e) { e.stopPropagation(); });
    });

    document.addEventListener("click", function () { closeAll(); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeAll();
    });
  }

  /* ---------------- clear notifications ---------------- */
  function initNotifications() {
    var btn = document.getElementById("clearNotifs");
    if (!btn) return;
    btn.addEventListener("click", function () {
      var list = document.getElementById("notifList");
      var empty = document.getElementById("notifEmpty");
      if (list) list.innerHTML = "";
      if (empty) empty.hidden = false;
      var count = document.querySelector(".dot-count");
      if (count) count.remove();
    });
  }

  /* ---------------- count-up numbers ---------------- */
  function initCountUp() {
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    document.querySelectorAll(".countup").forEach(function (el, i) {
      var to = parseFloat(el.dataset.to) || 0;
      if (reduce) { el.textContent = Math.round(to).toLocaleString(); return; }
      setTimeout(function () {
        var start = performance.now();
        (function step(now) {
          var p = Math.min(1, (now - start) / 900);
          var eased = 1 - Math.pow(1 - p, 3);
          el.textContent = Math.round(to * eased).toLocaleString();
          if (p < 1) requestAnimationFrame(step);
        })(start);
      }, 90 + i * 70);
    });
  }

  /* ---------------- command palette ---------------- */
  function initPalette() {
    var backdrop = document.getElementById("palette");
    var input = document.getElementById("paletteInput");
    var list = document.getElementById("paletteList");
    var dataEl = document.getElementById("paletteData");
    if (!backdrop || !input || !list || !dataEl) return;

    // Primary source: the JSON the server rendered.
    var items = [];
    try {
      items = JSON.parse((dataEl.textContent || "").trim() || "[]");
    } catch (err) {
      items = [];
    }

    // Fallback: build the index from the nav itself, so the palette is never
    // empty even if the JSON payload is missing or stale.
    if (!items.length) {
      items = Array.prototype.map.call(
        document.querySelectorAll(".tabs-inner a"),
        function (a) {
          return { label: a.textContent.trim(), hint: "page", url: a.getAttribute("href") };
        }
      );
    }

    var shown = items.slice();
    var cursor = 0;

    function esc(s) {
      return String(s).replace(/[&<>"]/g, function (c) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
      });
    }

    function render() {
      if (!shown.length) {
        list.innerHTML = '<li class="palette-none">No matches</li>';
        return;
      }
      list.innerHTML = shown.map(function (item, i) {
        return '<li class="' + (i === cursor ? "on" : "") + '" data-url="' + esc(item.url) + '">' +
               "<span>" + esc(item.label) + '</span><span class="hint">' + esc(item.hint) + "</span></li>";
      }).join("");
    }

    function filter() {
      var q = input.value.trim().toLowerCase();
      shown = q ? items.filter(function (i) {
        return (i.label + " " + i.hint).toLowerCase().indexOf(q) !== -1;
      }) : items.slice();
      cursor = 0;
      render();
    }

    // Visibility is driven by an inline style as well as the hidden attribute:
    // an author `display` rule beats the hidden attribute, and inline styles
    // beat both, so this holds even against a stale cached stylesheet.
    function isOpen() { return backdrop.style.display !== "none"; }

    function open() {
      backdrop.hidden = false;
      backdrop.style.display = "grid";
      input.value = "";
      filter();
      input.focus();
    }

    function close() {
      backdrop.hidden = true;
      backdrop.style.display = "none";
    }

    close();   // guarantee a closed starting state

    function go() {
      var item = shown[cursor];
      if (item) location.href = item.url;
    }

    var trigger = document.getElementById("omniOpen");
    if (trigger) trigger.addEventListener("click", open);

    document.addEventListener("keydown", function (e) {
      // Cmd/Ctrl+K opens; plain "k" does too when not typing.
      var typing = /^(input|textarea|select)$/i.test(document.activeElement.tagName);
      if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) {
        e.preventDefault(); open(); return;
      }
      if (!isOpen()) {
        if ((e.key === "k" || e.key === "K") && !typing && !e.metaKey && !e.ctrlKey && !e.altKey) {
          e.preventDefault(); open();
        }
        return;
      }
      if (e.key === "Escape") { e.preventDefault(); close(); }
      else if (e.key === "ArrowDown") { e.preventDefault(); cursor = Math.min(cursor + 1, shown.length - 1); render(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); cursor = Math.max(cursor - 1, 0); render(); }
      else if (e.key === "Enter") { e.preventDefault(); go(); }
    });

    input.addEventListener("input", filter);
    list.addEventListener("click", function (e) {
      var li = e.target.closest("li");
      if (li && li.dataset.url) location.href = li.dataset.url;
    });
    backdrop.addEventListener("click", function (e) {
      if (e.target === backdrop) close();
    });
  }

  /* ---------------- auto-submitting selects ---------------- */
  function initAutoFilters() {
    document.querySelectorAll("[data-autofilter]").forEach(function (select) {
      select.addEventListener("change", function () {
        if (select.form) select.form.submit();
      });
    });
  }

  /* ---------------- collapsible sidebar ---------------- */
  function initSidebar() {
    var btn = document.getElementById("sideCollapse");
    var side = document.getElementById("sidebar");
    if (!btn || !side) return;

    // Remember the choice across pages.
    try {
      if (localStorage.getItem("sidebarMini") === "1") side.classList.add("mini");
    } catch (e) { /* private mode - just skip persistence */ }

    btn.addEventListener("click", function () {
      var mini = side.classList.toggle("mini");
      try { localStorage.setItem("sidebarMini", mini ? "1" : "0"); } catch (e) {}
    });
  }

  /* ---------------- delete confirmation ---------------- */
  function initConfirm() {
    document.querySelectorAll("form[data-confirm]").forEach(function (form) {
      form.addEventListener("submit", function (e) {
        if (!window.confirm(form.dataset.confirm)) e.preventDefault();
      });
    });
  }

  initMenus();
  initNotifications();
  initCountUp();
  initPalette();
  initAutoFilters();
  initConfirm();
  initSidebar();
})();
