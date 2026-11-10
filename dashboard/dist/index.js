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
              return h("li", { key: c.id, className: "flex items-center gap-3 text-sm" },
                h("span", { className: "mr-auto truncate" }, c.title || c.id),
                h(Badge, { variant: "outline" }, c.label),
                h("span", { className: "text-xs text-muted-foreground" }, c.age_h == null ? "" : Math.round(c.age_h) + "h"));
            })));
    }
    return h(Card, null, h(CardHeader, { className: "pb-3" }, h(CardTitle, { className: "text-base" }, "Fake gates between agents")), h(CardContent, null, body));
  }

  function SelenitePage() {
    var s = useState(30), days = s[0], setDays = s[1];
    var o = useState(null), data = o[0], setData = o[1];
    var e = useState(null), error = e[0], setError = e[1];
    var p = useState(null), pending = p[0], setPending = p[1];
    var load = useCallback(function () {
      SDK.fetchJSON(API + "/overview?days=" + days)
        .then(function (r) { setData(r); setError(null); })
        .catch(function (err) { setError((err && err.message) || "Selenite's backend is not answering"); });
    }, [days]);
    useEffect(load, [load]);

    function markFixed(key) {
      setPending(key);
      SDK.fetchJSON(API + "/events", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: "fix", key: key, note: "marked fixed in the dashboard" }) })
        .then(load, function (err) { setError((err && err.message) || "Could not log that fix"); })
        .finally(function () { setPending(null); });
    }

    var head = h("div", { className: "flex flex-wrap items-center gap-3" },
      h("div", { className: "mr-auto" },
        h("h1", { className: "text-xl font-semibold" }, "Selenite"),
        h("p", { className: "text-sm text-muted-foreground" }, "The steps, waits and checks that keep landing on you, and what to clear next.")),
      [7, 30, 90].map(function (d) {
        return h(Button, { key: d, size: "sm", variant: d === days ? "default" : "outline", "aria-pressed": d === days, onClick: function () { setDays(d); } }, d + "d");
      }));

    var warn = error && h("div", { role: "alert", className: "flex items-center gap-3 rounded-md border border-border p-3 text-sm" },
      h("span", { className: "mr-auto" }, data ? "Selenite stopped answering. Showing the last data it sent. (" + error + ")" : error),
      h(Button, { size: "sm", variant: "outline", onClick: load }, "Retry"));

    if (!data) return h("div", { className: "space-y-6" }, head, warn || h("p", { className: "text-sm text-muted-foreground" }, "Loading…"));
    if (!data.has_ledger) return h("div", { className: "space-y-6" }, head, warn, h(Card, null, h(CardContent, { className: "pt-6 text-sm text-muted-foreground" },
      "Nothing logged yet. Selenite adds a row each time an agent hands you a step it could have done. To backfill from past transcripts, ask any agent to run /frictionless cleanse.")), h(FakeGates, { days: days }));

    var t = data.totals || {}, gates = data.gates || [];
    var loadLabel = LOAD[data.load] || LOAD.clear;
    return h("div", { className: "space-y-6" }, head, warn,
      h(Card, null, h(CardContent, { className: "pt-6 flex flex-wrap items-center gap-3 text-sm" },
        h("span", { className: "font-medium" }, "Load: ", h("span", { "aria-live": "polite" }, loadLabel)),
        h("span", { className: "text-muted-foreground" }, (data.calm_24h || 0) + " Calm triggers in the last 24 hours"))),
      h("div", { className: "grid gap-4 grid-cols-2 xl:grid-cols-4" },
        h(Stat, { label: "Human gates", n: t.gates }), h(Stat, { label: "Approval prompts", n: t.approvals }),
        h(Stat, { label: "Calm triggers", n: t.calm }), h(Stat, { label: "Fixes landed", n: t.fixes })),
      h(Card, null,
        h(CardHeader, { className: "pb-3" }, h(CardTitle, { className: "text-base" }, "Recurring gates")),
        h(CardContent, null, gates.length === 0
          ? h("p", { className: "text-sm text-muted-foreground" }, "No human gates in this window.")
          : h("ol", { className: "space-y-2" }, gates.slice(0, 10).map(function (g) {
              return h("li", { key: g.key, className: "flex items-center gap-3 text-sm" },
                h("code", { className: "mr-auto truncate" }, g.key),
                h("span", { className: "text-xs text-muted-foreground" }, "asked " + g.n + "×, last " + ago(g.last)),
                g.fixed ? h(Badge, { variant: "outline" }, "fixed")
                  : h(Button, { size: "sm", variant: "ghost", "aria-label": "Mark " + g.key + " fixed", disabled: pending === g.key, onClick: function () { markFixed(g.key); } }, "Mark fixed"));
            })))),
      h(FakeGates, { days: days }));
  }

  window.__HERMES_PLUGINS__.register("selenite", SelenitePage);
})();
