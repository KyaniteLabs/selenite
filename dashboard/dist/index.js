/* Selenite dashboard tab. Hand-written plain JS (no build step) against the web
 * dashboard SDK on window.__HERMES_PLUGIN_SDK__, same pattern as memory-wiki.
 * Reads the shared backend at /api/plugins/selenite/. MIT. */
(() => {
  var SDK = window.__HERMES_PLUGIN_SDK__;
  var React = SDK.React;
  var h = React.createElement;
  var useState = SDK.hooks.useState, useEffect = SDK.hooks.useEffect, useCallback = SDK.hooks.useCallback;
  var C = SDK.components;
  var Card = C.Card, CardHeader = C.CardHeader, CardTitle = C.CardTitle, CardContent = C.CardContent, Badge = C.Badge, Button = C.Button;
  var API = "/api/plugins/selenite";
  var LOAD = { clear: "Clear", rising: "Rising", high: "High" };
  /* Every control is at least 44px square (WCAG 2.5.5 / Apple HIG touch size), whatever the host's button size. */
  var TAP = { minHeight: 44, minWidth: 44 };
  /* The selected window must not rely on the host theme's variant colours, which can match. */
  /* The theme paints default and outline buttons alike, so the picked window inverts to the page's own text colour with a solid border: visible in any theme. */
  var PICKED = { minHeight: 44, minWidth: 44, fontWeight: 700, background: "transparent", color: "inherit", border: "2px solid currentColor", boxShadow: "none" };

  function post(path, body) {
    return SDK.fetchJSON(API + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : void 0 });
  }

  // Rows wrap on a narrow screen instead of squeezing the name to a few letters.
  var ROW = { display: "flex", flexWrap: "wrap", alignItems: "center", gap: "4px 12px" };
  var GROW = { flex: "1 1 12rem", minWidth: 0, overflowWrap: "anywhere" };
  // Plain names for the fake-gate kinds; the code stays in the badge's tooltip.
  var KIND = { "F1-ack": "Agent OK", "F2-relay": "Relay hop", "F3-ownership-limbo": "Ownership limbo",
    "F4-ceremony": "Ceremony", "F5-parking-lot": "Parked", "F6-stale-wait": "Stale wait" };

  function ago(ts) {
    if (!ts) return "never";
    return new Date(ts * 1e3).toLocaleString(void 0, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  }

  function Stat(props) {
    return h(Card, null, h(CardContent, { className: "pt-6 space-y-1" },
      h("div", { className: "text-xs uppercase tracking-wide text-muted-foreground" }, props.label),
      h("div", { className: "text-3xl font-semibold tracking-tight" }, props.n == null ? 0 : props.n)));
  }

  /* Fake gates: waits one agent put on another that will end up on your desk. Read-only, counts and titles only. */
  function FakeGates(props) {
    var f = useState(null), fg = f[0], setFg = f[1];
    var e = useState(null), err = e[0], setErr = e[1];
    var days = Math.min(props.days, 90);
    useEffect(function () {
      SDK.fetchJSON(API + "/fake-gates/overview?days=" + days)
        .then(function (r) { setFg(r); setErr(null); })
        .catch(function (x) { setErr((x && x.message) || "the board audit is not answering"); });
    }, [days]);
    var body;
    if (err) body = h("p", { role: "alert", className: "text-sm text-muted-foreground" }, "Fake gates unavailable: " + err);
    else if (!fg) body = h("p", { className: "text-sm text-muted-foreground" }, "Auditing boards…");
    else {
      var cards = fg.cards || [];
      body = h("div", { className: "space-y-3" },
        h("p", { className: "text-sm" }, (fg.summary && fg.summary.headline) || "No blocked cards found.",
          h("span", { className: "text-muted-foreground" }, " Mode: " + fg.mode + ".")),
        cards.length === 0 ? h("p", { className: "text-sm text-muted-foreground" }, "No fake gates on the boards.")
          : h("ol", { className: "space-y-2" }, cards.slice(0, 10).map(function (c) {
              return h("li", { key: c.id, className: "text-sm", style: ROW },
                h("span", { style: GROW }, c.title || c.id),
                h(Badge, { variant: "outline", title: c.label }, KIND[c.label] || c.label),
                h("span", { className: "text-xs text-muted-foreground" }, c.age_h == null ? "" : Math.round(c.age_h) + "h"),
                c.action ? h("p", { className: "text-xs text-muted-foreground", style: { flexBasis: "100%", margin: 0 } }, c.action) : null);
            })));
    }
    return h(Card, null, h(CardHeader, { className: "pb-3" }, h(CardTitle, { className: "text-base" }, "Fake gates between agents")), h(CardContent, null, body));
  }

  /* Cleanse: the ranked list of what to clear next, read-only over the stack. */
  function Cleanse(props) {
    var c = useState(null), cl = c[0], setCl = c[1];
    var e = useState(null), err = e[0], setErr = e[1];
    var r = useState(false), running = r[0], setRunning = r[1];
    var fetchIt = useCallback(function () {
      SDK.fetchJSON(API + "/cleanse").then(function (x) { setCl(x.cleanse || false); setErr(null); },
        function (x) { setErr((x && x.message) || "the latest cleanse did not load"); });
    }, []);
    useEffect(fetchIt, [fetchIt]);
    function run() {
      setRunning(true);
      post("/cleanse?days=" + props.days).then(function (x) { setCl(x.cleanse || false); setErr(null); },
        function (x) { setErr((x && x.message) || "Selenite could not run a cleanse"); })
        .finally(function () { setRunning(false); });
    }
    var finds = (cl && cl.findings) || [];
    var body;
    if (err) body = h("p", { role: "alert", className: "text-sm text-muted-foreground" }, "Cleanse unavailable: " + err);
    else if (cl === null) body = h("p", { className: "text-sm text-muted-foreground" }, "Loading the latest cleanse…");
    else if (!cl) body = h("p", { className: "text-sm text-muted-foreground" }, "Not run yet. Cleanse sweeps your skills, plugins, hooks, approvals, gates and runbooks, read-only, and ranks what to clear by how often it interrupts you.");
    else if (!finds.length) body = h("p", { className: "text-sm" }, "Nothing to clear. Every stone Selenite checks is clean.");
    else {
      var top = finds[0];
      body = h("div", { className: "space-y-3" },
        h("p", { className: "text-sm text-muted-foreground" }, (cl.total || finds.length) + " findings, swept " + (cl.generated ? new Date(cl.generated).toLocaleString() : "recently") + "."),
        h("div", { className: "rounded-md border border-border p-3 space-y-1 text-sm" },
          h("div", { className: "flex items-center gap-2" }, h("span", { className: "font-medium mr-auto" }, "Clear next"), h(Badge, { variant: "outline" }, top.stone)),
          h("p", null, top.problem),
          h("p", { className: "text-muted-foreground" }, "Where: ", h("code", null, top.where)),
          h("p", null, "Fix: " + top.fix)),
        finds.length > 1 && h("ol", { className: "space-y-2", "aria-label": "Next in line" }, finds.slice(1, 6).map(function (f, i) {
          return h("li", { key: i + ":" + f.stone + ":" + f.where, className: "flex items-center gap-3 text-sm" },
            h(Badge, { variant: "outline" }, f.stone),
            h("span", { className: "mr-auto", style: { minWidth: 0, overflowWrap: "anywhere" } }, f.problem),
            h("span", { className: "text-xs text-muted-foreground" }, Number(f.interruptions) > 0 ? "×" + f.interruptions : ""));
        })));
    }
    return h(Card, null,
      h(CardHeader, { className: "pb-3" }, h(CardTitle, { className: "text-base" }, "What to clear next")),
      h(CardContent, { className: "space-y-3" }, body,
        h(Button, { size: "sm", variant: "outline", style: TAP, disabled: running, onClick: run }, running ? "Sweeping…" : "Run cleanse")));
  }

  /* Evolve: the latest proposal to sharpen Selenite, drafted from the ledger. Reviewed as a pull request; nothing changes silently. */
  function Evolve(props) {
    var o = useState(null), prop = o[0], setProp = o[1];
    var e = useState(null), err = e[0], setErr = e[1];
    var d = useState(false), drafting = d[0], setDrafting = d[1];
    var f = useState(false), fresh = f[0], setFresh = f[1];
    useEffect(function () {
      SDK.fetchJSON(API + "/proposal").then(function (x) { setProp(x.proposal || false); setErr(null); },
        function (x) { setErr((x && x.message) || "the latest proposal did not load"); });
    }, []);
    function draft() {
      setDrafting(true); setFresh(false);
      post("/proposal?days=" + props.days).then(function (x) {
        if (x.error) setErr(x.error); else { setProp(x.proposal || false); setErr(null); setFresh(true); }
      }, function (x) { setErr((x && x.message) || "Selenite could not draft a proposal"); })
        .finally(function () { setDrafting(false); });
    }
    var body = err ? h("p", { role: "alert", className: "text-sm text-muted-foreground" }, "Evolve unavailable: " + err)
      : prop === null ? h("p", { className: "text-sm text-muted-foreground" }, "Loading the latest proposal…")
      : !prop ? h("p", { className: "text-sm text-muted-foreground" }, "No proposal yet. A proposal turns the ledger into ways to sharpen Selenite. You review it as a pull request; nothing changes silently.")
      : h("details", { className: "text-sm", open: fresh || undefined },
          h("summary", { style: { cursor: "pointer", minHeight: 44, display: "flex", alignItems: "center" } }, prop.name + ", drafted " + ago(prop.mtime)),
          h("pre", { className: "mt-2 rounded-md border border-border p-3 text-xs", style: { whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 360, overflow: "auto" } }, prop.text));
    return h(Card, null,
      h(CardHeader, { className: "pb-3" }, h(CardTitle, { className: "text-base" }, "Evolve")),
      h(CardContent, { className: "space-y-3" },
        fresh && prop ? h("p", { role: "status", className: "text-sm" }, "Drafted " + prop.name + ". Review it below; nothing changes until you merge it.") : null,
        body,
        h(Button, { size: "sm", variant: "outline", style: TAP, disabled: drafting, onClick: draft }, drafting ? "Drafting…" : "Draft proposal")));
  }

  function SelenitePage() {
    var s = useState(30), days = s[0], setDays = s[1];
    var o = useState(null), data = o[0], setData = o[1];
    var e = useState(null), error = e[0], setError = e[1];
    var p = useState(null), pending = p[0], setPending = p[1];
    var u = useState(null), undo = u[0], setUndo = u[1];
    var load = useCallback(function () {
      SDK.fetchJSON(API + "/overview?days=" + days)
        .then(function (r) { setData(r); setError(null); })
        .catch(function (err) { setError((err && err.message) || "Selenite's backend is not answering"); });
    }, [days]);
    useEffect(load, [load]);

    /* "fix" and "reopen" are both just ledger rows, so a mark is always undoable: the latest one wins. */
    function mark(kind, key) {
      setPending(key);
      post("/events", { kind: kind, key: key, note: kind === "fix" ? "marked fixed in the dashboard" : "reopened in the dashboard" })
        .then(function () { setUndo(kind === "fix" ? key : null); load(); },
          function (err) { setError((err && err.message) || (kind === "fix" ? "Could not log that fix" : "Could not reopen that gate")); })
        .finally(function () { setPending(null); });
    }

    var head = h("div", { className: "flex flex-wrap items-center gap-3" },
      h("div", { className: "mr-auto" },
        h("h1", { className: "text-xl font-semibold" }, "Selenite"),
        h("p", { className: "text-sm text-muted-foreground" }, "The steps, waits and checks that keep landing on you, and what to clear next.")),
      [7, 30, 90].map(function (d) {
        var on = d === days;
        return h(Button, { key: d, size: "sm", variant: on ? "default" : "outline", "aria-pressed": on, style: on ? PICKED : TAP, onClick: function () { setDays(d); } },
          on ? h("span", { "aria-hidden": true }, "✓ ") : null, d + "d");
      }));

    var warn = error && h("div", { role: "alert", className: "flex items-center gap-3 rounded-md border border-border p-3 text-sm" },
      h("span", { className: "mr-auto" }, data ? "Selenite stopped answering. Showing the last data it sent. (" + error + ")" : error),
      h(Button, { size: "sm", variant: "outline", style: TAP, onClick: load }, "Retry"));

    var undone = undo && h("div", { role: "status", className: "flex items-center gap-3 rounded-md border border-border p-3 text-sm" },
      h("span", { className: "mr-auto" }, "Marked ", h("code", null, undo), " fixed."),
      h(Button, { size: "sm", variant: "outline", style: TAP, disabled: pending === undo, onClick: function () { mark("reopen", undo); } }, "Undo"));

    if (!data) return h("div", { className: "space-y-6" }, head, warn || h("p", { className: "text-sm text-muted-foreground" }, "Loading…"));
    if (!data.has_ledger) return h("div", { className: "space-y-6" }, head, warn, h(Card, null, h(CardContent, { className: "pt-6 text-sm text-muted-foreground" },
      "Nothing logged yet. Selenite adds a row each time an agent hands you a step it could have done. Past transcripts are not copied in. To see what they cost you, ask any agent to run /frictionless evolve: it counts them into a private report and drafts a proposal.")), h(Cleanse, { days: days }), h(FakeGates, { days: days }), h(Evolve, { days: days }));

    var t = data.totals || {}, gates = data.gates || [];
    var loadLabel = LOAD[data.load] || LOAD.clear;
    return h("div", { className: "space-y-6" }, head, warn, undone,
      h(Card, null, h(CardContent, { className: "pt-6 flex flex-wrap items-center gap-3 text-sm" },
        h("span", { className: "font-medium" }, "Load: ", h("span", { "aria-live": "polite" }, loadLabel)),
        h("span", { className: "text-muted-foreground" }, (data.calm_24h || 0) + ((data.calm_24h === 1) ? " Calm trigger" : " Calm triggers") + " in the last 24 hours"))),
      h("div", { className: "grid gap-4 grid-cols-2 xl:grid-cols-4" },
        h(Stat, { label: "Human gates", n: t.gates }), h(Stat, { label: "Approval prompts", n: t.approvals }),
        h(Stat, { label: "Calm triggers", n: t.calm }), h(Stat, { label: "Fixes landed", n: t.fixes })),
      h(Card, null,
        h(CardHeader, { className: "pb-3" }, h(CardTitle, { className: "text-base" }, "Recurring gates")),
        h(CardContent, null, gates.length === 0
          ? h("p", { className: "text-sm text-muted-foreground" }, data.one_off_gates ? "Nothing asked twice in this window." : "No human gates in this window.")
          : h("ol", { className: "space-y-2" }, gates.slice(0, 10).map(function (g) {
              var name = g.title || g.key;
              return h("li", { key: g.key, className: "text-sm", style: ROW },
                g.title ? h("span", { style: GROW, title: g.key }, g.title) : h("code", { style: GROW, title: g.key }, g.key),
                h("span", { className: "text-xs text-muted-foreground" }, "asked " + g.n + "×, last " + ago(g.last)),
                g.fixed ? h(Badge, { variant: "outline" }, "fixed") : null,
                g.fixed
                  ? h(Button, { size: "sm", variant: "ghost", style: TAP, "aria-label": "Reopen " + name, disabled: pending === g.key, onClick: function () { mark("reopen", g.key); } }, "Reopen")
                  : h(Button, { size: "sm", variant: "ghost", style: TAP, "aria-label": "Mark " + name + " fixed", disabled: pending === g.key, onClick: function () { mark("fix", g.key); } }, "Mark fixed"));
            })),
          data.one_off_gates ? h("p", { className: "mt-3 text-xs text-muted-foreground" }, data.one_off_gates + (data.one_off_gates === 1 ? " gate" : " gates") + " asked only once, not shown.") : null)),
      h(Cleanse, { days: days }),
      h(FakeGates, { days: days }),
      h(Evolve, { days: days }));
  }

  window.__HERMES_PLUGINS__.register("selenite", SelenitePage);
})();
