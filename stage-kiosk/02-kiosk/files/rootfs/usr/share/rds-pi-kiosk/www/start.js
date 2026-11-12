"use strict";
// On-screen start page. With a URL set: wait for the network, then go there.
// Without one: the welcome screen. Never gives up and never shows a dead end.
var t0 = Date.now(), local = null, leaving = false, errorSince = 0, pairClicked = 0;
function $(id) { return document.getElementById(id); }
function show(id, on) { $(id).classList.toggle("hide", !on); }
function getJSON(u, opt) {
  return fetch(u, opt).then(function (r) { return r.json(); });
}
// The root helper picks a request up a second or two after the click; until
// then the status file still says idle, so count a fresh click as busy.
function pairBusy(p) {
  return (p && (p.state === "queued" || p.state === "running")) || Date.now() - pairClicked < 10000;
}

function render(L) {
  $("ver").textContent = L.version || "";
  $("host").textContent = L.hostname || "";
  $("code").textContent = (L.code || "").replace(/^(.{4})(.+)$/, "$1-$2");
  var lan = L.setup_page !== "off";
  if (L.setup_urls && L.setup_urls.length && lan) {
    $("setupurl").textContent = L.setup_urls[0].replace(/\/$/, "");
    var q = $("qr");
    if (q.dataset.ip !== L.ips[0]) { q.dataset.ip = L.ips[0]; q.src = "/api/qr.svg?ip=" + encodeURIComponent(L.ips[0]); }
    show("qr", true);
  } else {
    $("setupurl").textContent = lan ? "Waiting for the network…" : "The setup page is off (SETUP_PAGE=off)";
    show("qr", false);
  }
  var p = L.pair || {}, st = $("pairstatus");
  if (p.state && p.state !== "idle") {
    st.className = "status " + (p.state === "error" ? "err" : p.state === "done" ? "ok" : "run");
    st.innerHTML = "";
    if (pairBusy(p)) { var s = document.createElement("span"); s.className = "spin"; st.appendChild(s); }
    st.appendChild(document.createTextNode(p.message || p.state));
  } else { st.className = "status hide"; }
  $("pairbtn").disabled = pairBusy(p);
  $("pairbtn").textContent = p.state === "error" ? "Try again" : "Pair with RDS";

  var starting = !!L.url && !pairBusy(p);
  show("starting", starting);
  show("welcome", !starting);
  if (starting) {
    var host = L.url; try { host = new URL(L.url).host; } catch (e) {}
    $("startmsg").textContent = "Starting " + host;
    $("starthost").textContent = (Date.now() - t0 > 15000) ? "Waiting for the network…" : "";
  }
}

function tick() {
  if (leaving) return;
  getJSON("/api/local").then(function (L) {
    local = L; render(L);
    var p = L.pair || {};
    if (!L.url || pairBusy(p)) return null;
    if (p.state === "error") {               // MODE=rds failed: say why, then show the URL anyway
      if (!errorSince) errorSince = Date.now();
      if (Date.now() - errorSince < 30000) return null;
    }
    return getJSON("/api/netcheck").then(function (n) {
      var waited = Date.now() - t0;
      // At least 6 s so the setup address can be read; at most 2 min of waiting.
      if ((n.ok && waited > 6000) || waited > 120000) { leaving = true; location.replace(L.url); }
    });
  }).catch(function () {}).then(function () { if (!leaving) setTimeout(tick, 2000); });
}

$("pairbtn").addEventListener("click", function () {
  if (!local) return;
  pairClicked = Date.now();
  $("pairbtn").disabled = true;
  fetch("/api/pair", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code: local.code }) }).catch(function () {});
});
tick();
