/* ============================================================
   Floating assistant. Posts to /ask/api/ and renders the reply
   inline, so asking a question never reloads the page.
   ============================================================ */
(function () {
  "use strict";

  var fab = document.getElementById("askFab");
  var panel = document.getElementById("askPanel");
  if (!fab || !panel) return;

  var log = document.getElementById("askLog");
  var form = document.getElementById("askForm");
  var input = document.getElementById("askInput");
  var closeBtn = document.getElementById("askClose");
  var clearBtn = document.getElementById("askClear");
  var suggest = document.getElementById("askSuggest");

  /* ---------------- CSRF ---------------- */
  function csrf() {
    var m = document.cookie.match(/(^|;)\s*csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[2]);
    var field = document.querySelector("input[name=csrfmiddlewaretoken]");
    return field ? field.value : "";
  }

  /* ---------------- open / close ---------------- */
  function open() {
    panel.hidden = false;
    panel.style.display = "flex";
    fab.classList.add("on");
    scrollToEnd();
    setTimeout(function () { input.focus(); }, 60);
    try { sessionStorage.setItem("askOpen", "1"); } catch (e) {}
  }

  function close() {
    panel.hidden = true;
    panel.style.display = "none";
    fab.classList.remove("on");
    try { sessionStorage.setItem("askOpen", "0"); } catch (e) {}
  }

  function toggle() { (panel.style.display === "none" ? open : close)(); }

  fab.addEventListener("click", toggle);
  if (closeBtn) closeBtn.addEventListener("click", close);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && panel.style.display !== "none") close();
  });

  // Stay open across navigation, so a conversation survives clicking a link.
  try {
    if (sessionStorage.getItem("askOpen") === "1") open();
  } catch (e) { /* private mode */ }

  /* ---------------- rendering ---------------- */
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function scrollToEnd() { log.scrollTop = log.scrollHeight; }

  function addBubble(cls, html) {
    var empty = log.querySelector(".ask-empty");
    if (empty) empty.remove();
    var el = document.createElement("div");
    el.className = "bubble " + cls;
    el.innerHTML = html;
    log.appendChild(el);
    scrollToEnd();
    return el;
  }

  function renderAnswer(turn) {
    var label = turn.engine === "claude" ? "Claude" : "portal data";
    var links = (turn.links || []).map(function (l) {
      return '<a href="' + esc(l.url) + '">' + esc(l.label) + " &rsaquo;</a>";
    }).join("");
    return esc(turn.a) +
      ' <span class="engine-tag ' + esc(turn.engine) + '">' + label + "</span>" +
      (links ? '<div class="bubble-links">' + links + "</div>" : "");
  }

  /* ---------------- asking ---------------- */
  var busy = false;

  function send(question) {
    if (busy || !question) return;
    busy = true;

    addBubble("you", esc(question));
    var thinking = addBubble("bot typing", "<span></span><span></span><span></span>");
    input.value = "";

    var body = new URLSearchParams();
    body.set("q", question);

    fetch(form.dataset.url || "/ask/api/", {
      method: "POST",
      headers: {
        "X-CSRFToken": csrf(),
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "XMLHttpRequest"
      },
      body: body.toString(),
      credentials: "same-origin"
    })
      .then(function (r) { return r.json(); })
      .then(function (turn) {
        thinking.classList.remove("typing");
        thinking.innerHTML = turn.error
          ? esc(turn.error)
          : renderAnswer(turn);
        scrollToEnd();
      })
      .catch(function () {
        thinking.classList.remove("typing");
        thinking.textContent =
          "I could not reach the portal just then. Try again in a moment.";
      })
      .then(function () { busy = false; });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    send(input.value.trim());
  });

  if (suggest) {
    suggest.addEventListener("click", function (e) {
      var chip = e.target.closest(".ask-chip");
      if (chip) send(chip.textContent.trim());
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      var body = new URLSearchParams();
      body.set("clear", "1");
      fetch("/ask/api/", {
        method: "POST",
        headers: {
          "X-CSRFToken": csrf(),
          "Content-Type": "application/x-www-form-urlencoded"
        },
        body: body.toString(),
        credentials: "same-origin"
      }).then(function () {
        log.innerHTML =
          '<div class="ask-empty"><div class="chat-ic">&#128172;</div>' +
          '<p class="small muted">Ask about your numbers.</p></div>';
      });
    });
  }

  scrollToEnd();
})();
