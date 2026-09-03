/* ============================================================
   Instant filtering, search and table sorting.
   Progressive enhancement: the server already rendered the correct
   result set, this just makes further filtering immediate.
   ============================================================ */
(function () {
  "use strict";

  /* ---------------------------------------------------------
     Live card filtering
     --------------------------------------------------------- */
  function initFilter() {
    var root = document.querySelector("[data-filter-root]");
    if (!root) return;

    var cards = Array.prototype.slice.call(root.querySelectorAll("[data-search]"));
    if (!cards.length) return;

    var chips = Array.prototype.slice.call(document.querySelectorAll("[data-chip]"));
    var input = document.getElementById("filterInput");
    var countEl = document.getElementById("resultCount");
    var emptyEl = document.getElementById("emptyState");
    var clearBtn = document.getElementById("clearFilters");
    var submitBtn = document.querySelector("[data-filter-submit]");

    // JS is running, so the no-JS submit button is redundant.
    if (submitBtn) submitBtn.hidden = true;

    var cat = (document.querySelector("[data-chip].on") || {}).dataset
      ? document.querySelector("[data-chip].on").dataset.chip
      : "All";

    function apply(pushUrl) {
      var q = (input && input.value || "").trim().toLowerCase();
      var shown = 0;

      cards.forEach(function (card) {
        var okCat = cat === "All" || card.dataset.cat === cat;
        var okText = !q || card.dataset.search.indexOf(q) !== -1;
        var visible = okCat && okText;
        card.hidden = !visible;
        if (visible) shown++;
      });

      if (countEl) countEl.textContent = shown;
      if (emptyEl) emptyEl.hidden = shown !== 0;
      if (clearBtn) clearBtn.hidden = cat === "All" && !q;

      // Keep the URL shareable and the back button meaningful, without reloading.
      if (pushUrl) {
        var params = new URLSearchParams();
        if (cat !== "All") params.set("cat", cat);
        if (q) params.set("q", input.value.trim());
        var qs = params.toString();
        history.replaceState(null, "", qs ? "?" + qs : location.pathname);
      }
    }

    chips.forEach(function (chip) {
      chip.addEventListener("click", function (e) {
        e.preventDefault();
        chips.forEach(function (c) { c.classList.remove("on"); });
        chip.classList.add("on");
        cat = chip.dataset.chip;
        apply(true);
      });
    });

    if (input) {
      input.addEventListener("input", function () { apply(true); });
      // Enter would post the form and reload; filtering already happened.
      input.form.addEventListener("submit", function (e) { e.preventDefault(); });
      input.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && input.value) { input.value = ""; apply(true); }
      });
    }

    if (clearBtn) {
      clearBtn.addEventListener("click", function (e) {
        e.preventDefault();
        if (input) input.value = "";
        chips.forEach(function (c) { c.classList.toggle("on", c.dataset.chip === "All"); });
        cat = "All";
        apply(true);
        if (input) input.focus();
      });
    }

    apply(false);
  }

  /* ---------------------------------------------------------
     Click-to-sort tables
     --------------------------------------------------------- */
  function cellValue(row, index) {
    var cell = row.cells[index];
    if (!cell) return "";
    var raw = (cell.dataset.sort !== undefined ? cell.dataset.sort : cell.textContent).trim();
    var num = parseFloat(raw.replace(/[$,%\s]/g, ""));
    return isNaN(num) ? raw.toLowerCase() : num;
  }

  function initSort() {
    document.querySelectorAll("table[data-sortable]").forEach(function (table) {
      var head = table.tHead;
      var body = table.tBodies[0];
      if (!head || !body) return;

      Array.prototype.forEach.call(head.rows[0].cells, function (th, index) {
        if (th.dataset.nosort !== undefined) return;
        th.classList.add("sortable");
        th.tabIndex = 0;

        function sort() {
          var asc = th.dataset.dir !== "asc";
          Array.prototype.forEach.call(head.rows[0].cells, function (other) {
            delete other.dataset.dir;
            other.classList.remove("sorted-asc", "sorted-desc");
          });
          th.dataset.dir = asc ? "asc" : "desc";
          th.classList.add(asc ? "sorted-asc" : "sorted-desc");

          var rows = Array.prototype.slice.call(body.rows);
          rows.sort(function (a, b) {
            var x = cellValue(a, index), y = cellValue(b, index);
            if (x < y) return asc ? -1 : 1;
            if (x > y) return asc ? 1 : -1;
            return 0;
          });
          rows.forEach(function (r) { body.appendChild(r); });
        }

        th.addEventListener("click", sort);
        th.addEventListener("keydown", function (e) {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); sort(); }
        });
      });
    });
  }

  /* ---------------------------------------------------------
     Keyboard shortcut: "/" focuses the filter box
     --------------------------------------------------------- */
  function initShortcut() {
    document.addEventListener("keydown", function (e) {
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
      var tag = (document.activeElement.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select") return;
      var input = document.getElementById("filterInput");
      if (input) { e.preventDefault(); input.focus(); input.select(); }
    });
  }

  /* ---------------------------------------------------------
     Sign-in arrival overlay (dashboard, once per sign-in)
     --------------------------------------------------------- */
  function initArrival() {
    var overlay = document.getElementById("arrival");
    if (!overlay) return;

    function dismiss() {
      overlay.classList.add("out");
      setTimeout(function () { overlay.remove(); }, 450);
    }

    var btn = document.getElementById("arrivalGo");
    if (btn) btn.addEventListener("click", dismiss);
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) dismiss();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") dismiss();
    });
    setTimeout(dismiss, 6000);

    // Count the awarded XP up from zero.
    var xpEl = document.getElementById("arrivalXp");
    if (xpEl) {
      var to = parseInt(xpEl.dataset.to, 10) || 0;
      var start = performance.now();
      (function step(now) {
        var p = Math.min(1, (now - start) / 900);
        xpEl.textContent = "+" + Math.round(to * (1 - Math.pow(1 - p, 3)));
        if (p < 1) requestAnimationFrame(step);
      })(start);
    }
  }

  initFilter();
  initSort();
  initShortcut();
  initArrival();
})();
