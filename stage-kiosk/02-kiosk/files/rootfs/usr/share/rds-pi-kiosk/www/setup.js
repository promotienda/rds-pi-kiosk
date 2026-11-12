"use strict";
var code = "", timer = null;
function $(id) { return document.getElementById(id); }
function show(id, on) { $(id).classList.toggle("hide", !on); }
function post(path, body) {
  body.code = code;
  return fetch(path, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) }).then(function (r) {
      return r.json().then(function (j) { j._status = r.status; return j; });
    });
}
function status(id, cls, text) {
  var el = $(id); el.className = "status " + cls; el.textContent = text;
}
function busy(p) { return p && (p.state === "queued" || p.state === "running"); }

function fill(v, first) {
  $("ver").textContent = v.version || "";
  $("sub").textContent = "Screen " + (v.hostname || "") + (v.mode === "rds" ? " · managed by RDS" : "");
  if (first) {
    $("url").value = v.url || "";
    $("rotation").value = v.rotation || "0";
    var z = String(v.zoom || "1.0"); if (z === "1") z = "1.0";
    if (![].some.call($("zoom").options, function (o) { return o.value === z; })) {
      var o = document.createElement("option"); o.textContent = z; $("zoom").appendChild(o);
    }
    $("zoom").value = z;
  }
  var p = v.pair || {};
  if (p.state && p.state !== "idle") {
    status("pairstatus", p.state === "error" ? "err" : p.state === "done" ? "ok" : "run", p.message || p.state);
  }
  $("pair").disabled = busy(p) || v.mode === "rds";
  $("warn").textContent = (v.warnings && v.warnings.length) ? "kiosk.txt: " + v.warnings.join("; ") : "";
  clearTimeout(timer);
  if (busy(p)) timer = setTimeout(refresh, 3000);
}
function refresh() { post("/api/settings", {}).then(function (v) { if (v._status === 200) fill(v, false); }); }

function unlock() {
  code = $("code").value.trim();
  post("/api/settings", {}).then(function (v) {
    if (v._status !== 200) { status("loginerr", "err", v.error || "Error"); return; }
    show("login", false); show("main", true); fill(v, true);
  }).catch(function () { status("loginerr", "err", "The screen did not answer."); });
}
$("unlock").addEventListener("click", unlock);
$("code").addEventListener("keydown", function (e) { if (e.key === "Enter") unlock(); });

$("save").addEventListener("click", function () {
  var vals = { URL: $("url").value.trim(), ROTATION: $("rotation").value, ZOOM: $("zoom").value };
  post("/api/settings", { values: vals }).then(function (v) {
    if (v._status === 202) status("savestatus", "ok", "Saved. The screen restarts its browser in a few seconds.");
    else if (v.fields) status("savestatus", "err", Object.keys(v.fields).map(function (k) { return k + ": " + v.fields[k]; }).join("; "));
    else status("savestatus", "err", v.error || "Error");
  });
});
$("reload").addEventListener("click", function () {
  post("/api/reload", {}).then(function () { status("savestatus", "ok", "Reloading the screen."); });
});
$("pair").addEventListener("click", function () {
  if (!confirm("Install the RDS agent and hand this screen to RDS? Your own URL stops showing until you set MODE=free in kiosk.txt.")) return;
  post("/api/pair", {}).then(function (v) {
    if (v._status === 202) { status("pairstatus", "run", "Starting…"); setTimeout(refresh, 1500); }
    else status("pairstatus", "err", v.error || "Error");
  });
});

var m = /code=([A-Za-z0-9-]+)/.exec(location.hash);
if (m) { $("code").value = m[1]; history.replaceState(null, "", "/"); unlock(); }
