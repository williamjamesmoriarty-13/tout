// Teste le comportement de la page du tableau de bord dans un navigateur simulé (jsdom).
// Usage : python3 -c "import dashboard as d; open('page.html','w').write(d.PAGE.replace('__NONCE__','n'))"  puis  node dev/test_dashboard_ui.js page.html
const { JSDOM } = require("jsdom");
const fs = require("fs");
let failures = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failures++;
  console.log((ok ? "OK  " : "FAIL") + " " + label + (ok ? "" : " -> " + JSON.stringify(got)));
};
const tick = (ms = 20) => new Promise((r) => setTimeout(r, ms));

const verdict = (id, v, extra = {}) => Object.assign({
  id, recorded_at: "2026-10-19T06:00:00+00:00", action: "Restart", target: "student-service", verdict: v,
  mode: "dry-run", attempt: 1, invariants_violated: [], justification: "ligne " + id, result: "skipped",
  reason: "r", cause_key: v === "DENY" ? "cause:postgres" : null, cause_group: v === "DENY" ? "cause:postgres|1" : null, incident_id: "i",
}, extra);

(async () => {
  const sources = [];
  const notifications = [];
  const fetchLog = [];
  const dom = new JSDOM(fs.readFileSync(process.argv[2], "utf8"), {
    runScripts: "dangerously", pretendToBeVisual: true, url: "http://localhost:8088/",
    beforeParse(window) {
      class FakeES {                       // faux EventSource : on déclenche les événements à la main
        constructor(url) { this.url = url; this.l = {}; sources.push(this); }
        addEventListener(t, f) { (this.l[t] = this.l[t] || []).push(f); }
        emit(t, data) { (this.l[t] || []).forEach((f) => f({ data: data === undefined ? "" : JSON.stringify(data) })); }
      }
      window.EventSource = FakeES;
      window.fetch = async (url) => {
        fetchLog.push(url);
        const body = url.startsWith("/api/summary") ? { hours: 24, verdicts: { ALLOW: 3, DENY: 9 }, notifications: { sent: 1, disabled: 2 } }
          : url.startsWith("/api/groups") ? { groups: [{ cause_group: "g", cause_key: "cause:postgres", targets: ["student-service", "enrollment-service"], last_seen: "2026-10-19T06:00:30+00:00", denies: 3, notification_status: "sent", notification_message: "<b>Cause : postgres</b>" }] }
          : { id: 5, justification: "détail", proposal: { a: "<script>1</script>" } };
        return { ok: true, status: 200, json: async () => body };
      };
      window.Notification = class { constructor(t, o) { notifications.push([t, o.body]); } static requestPermission() { return Promise.resolve("granted"); } };
      window.Notification.permission = "default";
    },
  });
  const w = dom.window, $ = (id) => w.document.getElementById(id);
  await tick();
  const es = sources[0];

  check("la page ouvre UN flux vers /api/stream", [sources.length, es.url], [1, "/api/stream?tail=50"]);
  es.emit("open"); check("indicateur « en direct »", [$("conn").textContent, $("conn").className], ["en direct", "pill live"]);

  // lot initial (historique), avant « ready »
  es.emit("verdict", verdict(1, "ALLOW")); es.emit("verdict", verdict(2, "DENY")); es.emit("verdict", verdict(3, "DENY", { cause_group: "cause:student-service|2", cause_key: "cause:student-service" }));
  check("3 lignes dans le flux, dans l'ordre", [...$("feed").children].map((r) => r.dataset.id), ["1", "2", "3"]);
  check("une ligne DENY est marquée et colorée", [$("feed").children[1].className.includes("DENY"), $("feed").children[1].querySelector(".v-DENY") !== null], [true, true]);
  check("la ligne affiche la cause et la justification", $("feed").children[1].textContent.includes("[cause:postgres]") && $("feed").children[1].textContent.includes("ligne 2"), true);
  check("l'historique initial ne clignote pas (pas « new ») ", $("feed").querySelectorAll(".new").length, 0);
  es.emit("ready"); await tick();
  check("après « ready » : résumé et groupes chargés", [fetchLog.includes("/api/summary"), fetchLog.includes("/api/groups")], [true, true]);
  check("compteurs 24 h et alertes", [$("n-allow").textContent, $("n-deny").textContent, $("n-notif").textContent], ["3", "9", "3"]);
  check("tableau des causes : cause, services, statut de l'alerte", [$("groups").querySelectorAll("tr").length, $("groups").textContent.includes("cause:postgres"), $("groups").textContent.includes("student-service, enrollment-service"), $("groups").querySelector(".st-sent") !== null], [1, true, true, true]);

  // nouveaux verdicts en direct
  es.emit("verdict", verdict(4, "ALLOW"));
  check("un nouveau verdict en direct est mis en évidence", $("feed").lastChild.classList.contains("new"), true);

  // filtres
  $("f-allow").checked = false; $("f-allow").dispatchEvent(new w.Event("input"));
  check("filtre ALLOW décoché : les ALLOW disparaissent", [...$("feed").children].filter((r) => r.style.display !== "none").map((r) => r.dataset.verdict), ["DENY", "DENY"]);
  $("f-allow").checked = true; $("f-allow").dispatchEvent(new w.Event("input"));
  $("f-text").value = "STUDENT-service"; $("f-text").dispatchEvent(new w.Event("input"));
  check("filtre texte (insensible à la casse)", [...$("feed").children].filter((r) => r.style.display !== "none").length, 4);
  $("f-text").value = "introuvable"; $("f-text").dispatchEvent(new w.Event("input"));
  check("filtre sans résultat", [...$("feed").children].filter((r) => r.style.display !== "none").length, 0);
  $("f-text").value = ""; $("f-text").dispatchEvent(new w.Event("input"));

  // sécurité : du texte hostile ne crée jamais d'élément
  es.emit("verdict", verdict(5, "DENY", { justification: '<img src=x onerror="window.pwn=1"><script>window.pwn=2</script>', target: "<b>x</b>", cause_key: "cause:<i>y</i>", cause_group: "cause:<i>y</i>|9" }));
  const hostile = $("feed").lastChild;
  check("texte hostile : affiché tel quel, aucun élément injecté", [hostile.querySelector("img, script, b, i"), hostile.textContent.includes('<img src=x onerror="window.pwn=1">')], [null, true]);
  await tick(); check("texte hostile : aucun code exécuté", w.pwn, undefined);

  // détail au clic
  hostile.dispatchEvent(new w.Event("click")); await tick();
  check("clic sur une ligne : détail demandé et affiché en texte", [fetchLog.some((u) => u.startsWith("/api/verdict?id=5")), $("detail").style.display, $("detail").textContent.includes('"<script>1</script>"'), $("detail").querySelector("script")], [true, "block", true, null]);
  check("le message d'alerte d'un groupe est affiché en texte", [$("groups").querySelector("b"), $("groups").textContent.includes("<b>Cause : postgres</b>")], [null, true]);

  // notifications du navigateur
  es.emit("verdict", verdict(6, "DENY", { cause_group: "cause:nouveau|3", cause_key: "cause:nouveau" }));
  check("notifications désactivées par défaut : aucune", notifications.length, 0);
  $("bell").dispatchEvent(new w.Event("click")); await tick();
  check("activation : permission demandée, bouton mis à jour", $("bell").textContent, "Notifications activées");
  es.emit("verdict", verdict(7, "DENY", { cause_group: "cause:autre|4", cause_key: "cause:autre" }));
  w.Notification.permission = "granted";
  es.emit("verdict", verdict(8, "DENY", { cause_group: "cause:autre2|5", cause_key: "cause:autre2" }));
  es.emit("verdict", verdict(9, "DENY", { cause_group: "cause:autre2|5", cause_key: "cause:autre2" }));
  check("une notification par NOUVELLE cause seulement", notifications.map((n) => n[0]), ["Moteur : cause:autre2"]);

  // pannes
  es.emit("problem"); check("base d'historique indisponible : signalé", $("err").textContent, "base d'historique indisponible");
  es.emit("error"); check("flux coupé : « reconnexion » affichée", [$("conn").textContent.includes("reconnexion"), $("conn").className], [true, "pill down"]);

  // plafond de lignes
  for (let i = 100; i < 1700; i++) es.emit("verdict", verdict(i, "ALLOW"));
  check("le flux garde au plus 1500 lignes", $("feed").children.length, 1500);

  console.log(failures ? "\nDES TESTS ÉCHOUENT" : "\nTOUS LES TESTS PASSENT");
  process.exit(failures ? 1 : 0);
})();
