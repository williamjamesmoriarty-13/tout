"""Vérifie le chart rendu : schémas Kubernetes (strict), droits RBAC (moindre privilège), Pod Security
'restricted', cohérence avec le code du moteur et du tableau de bord, variantes de valeurs.

Outil de développement (pip install kubernetes-validate pyyaml). Il rend le chart avec gotpl.py, un mini
moteur de gabarits : pour la vérité, lance aussi `helm lint` et `helm template`.
Usage : python3 dev/check_chart.py        (PKG=/autre/chemin pour viser une autre copie du paquet)
"""
import copy, glob, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import yaml
import kubernetes_validate as kv
import gotpl

PKG = os.environ.get("PKG", os.path.dirname(HERE))
VALUES = yaml.safe_load(open(f"{PKG}/university-moteur/values.yaml"))
SRC = open(f"{PKG}/university-moteur/templates/moteur.yaml").read()
OK = True


def check(label, got, want=True):
    global OK
    good = got == want
    OK &= good
    print(("OK  " if good else "FAIL"), label, "" if good else f"-> {got!r}")


def render(values=None, ns="university-moteur"):
    v = copy.deepcopy(VALUES)
    for k, val in (values or {}).items():
        gotpl.deep_set(v, k, val)
    out = gotpl.render(SRC, v, {"Namespace": ns, "Name": "university-moteur"})
    return [d for d in yaml.safe_load_all(out) if d]


def named(docs, kind, name):
    return next(d for d in docs if d["kind"] == kind and d["metadata"]["name"] == name)


docs = render()
by_kind = lambda kind: [d for d in docs if d["kind"] == kind]

# ---- 1. schémas Kubernetes, mode strict (champ inconnu = erreur), plusieurs versions
for version in ("1.28", "1.30", "1.32"):
    errors = []
    for d in docs:
        try:
            kv.validate(d, version, strict=True)
        except Exception as e:
            errors.append(f"{d['kind']}/{d['metadata']['name']}: {str(e)[:150]}")
    check(f"schémas valides en Kubernetes {version}", errors, [])

# ---- 2. ressources attendues
check("11 ressources", sorted((d["kind"], d["metadata"]["name"]) for d in docs), sorted([
    ("ServiceAccount", "moteur"), ("Role", "moteur"), ("RoleBinding", "moteur"),
    ("Role", "moteur-lecture-decideur"), ("RoleBinding", "moteur-lecture-decideur"),
    ("Deployment", "moteur"), ("NetworkPolicy", "moteur"),
    ("ServiceAccount", "moteur-dashboard"), ("Deployment", "moteur-dashboard"),
    ("Service", "moteur-dashboard"), ("NetworkPolicy", "moteur-dashboard")]))
check("tout dans le namespace de la release (sauf les Role/RoleBinding des autres namespaces)",
      all(d["metadata"]["namespace"] == "university-moteur" for d in docs if d["kind"] not in ("Role", "RoleBinding")))
check("aucun ClusterRole ni droit sur tout le cluster", not any(d["kind"].startswith("Cluster") for d in docs))

# ---- 3. les deux pods : durcissement et Pod Security 'restricted'
pods = {n: named(docs, "Deployment", n)["spec"]["template"]["spec"] for n in ("moteur", "moteur-dashboard")}
for name, pod in pods.items():
    ctr, psc = pod["containers"][0], pod["securityContext"]
    check(f"{name} : non-root avec uid fixe, seccomp RuntimeDefault", (psc["runAsNonRoot"], psc["runAsUser"], psc["seccompProfile"]["type"]), (True, 10001, "RuntimeDefault"))
    check(f"{name} : pas d'escalade, capacités retirées, racine en lecture seule",
          (ctr["securityContext"]["allowPrivilegeEscalation"], ctr["securityContext"]["capabilities"]["drop"], ctr["securityContext"]["readOnlyRootFilesystem"]), (False, ["ALL"], True))
    check(f"{name} : seul un emptyDir en /tmp", ([list(v.keys() - {"name"}) for v in pod["volumes"]], ctr["volumeMounts"][0]["mountPath"]), ([["emptyDir"]], "/tmp"))
    check(f"{name} : pas d'accès à l'hôte", not any(pod.get(k) for k in ("hostNetwork", "hostPID", "hostIPC")) and not any("hostPort" in p for p in ctr.get("ports", [])))
    check(f"{name} : ressources bornées", sorted(ctr["resources"]), ["limits", "requests"])
    dep = named(docs, "Deployment", name)
    check(f"{name} : 1 réplica, selector cohérent", (dep["spec"]["replicas"], dep["spec"]["selector"]["matchLabels"].items() <= dep["spec"]["template"]["metadata"]["labels"].items()), (1, True))
    check(f"{name} : image", ctr["image"], "docker.io/darbi/university-moteur:0.1.0")
mot = named(docs, "Deployment", "moteur")
check("moteur : stratégie Recreate (jamais deux moteurs)", mot["spec"]["strategy"]["type"], "Recreate")
check("moteur : jeton de compte de service monté (il parle à l'API)", pods["moteur"].get("automountServiceAccountToken", True), True)

# ---- 4. tableau de bord : aucun accès à l'API, exposition interne seulement
dash = pods["moteur-dashboard"]; dctr = dash["containers"][0]
check("dashboard : aucun jeton Kubernetes monté (pod et compte de service)", (dash["automountServiceAccountToken"], named(docs, "ServiceAccount", "moteur-dashboard")["automountServiceAccountToken"]), (False, False))
check("dashboard : commande", dctr["command"], ["python", "dashboard.py"])
check("dashboard : sondes par exec sur la boucle locale (indépendantes de la NetworkPolicy)", all("exec" in dctr[p] and "127.0.0.1" in dctr[p]["exec"]["command"][-1] for p in ("readinessProbe", "livenessProbe")))
svc = named(docs, "Service", "moteur-dashboard")["spec"]
check("service interne seulement (ClusterIP 80 -> http)", (svc["type"], svc["ports"][0]["port"], svc["ports"][0]["targetPort"]), ("ClusterIP", 80, "http"))
check("service : le sélecteur vise bien les pods du dashboard", svc["selector"], {"app.kubernetes.io/name": "moteur-dashboard"})
dash_dep_labels = named(docs, "Deployment", "moteur-dashboard")["spec"]["template"]["metadata"]["labels"]
check("service : le port cible existe dans le conteneur", [p["name"] for p in dctr["ports"]], ["http"])

# ---- 5. configuration : chaque variable posée est lue par le code, aucun secret en clair
def env_names_read(path, patterns):
    return set(n for p in patterns for n in re.findall(p, open(path).read()))
read_moteur = env_names_read(f"{PKG}/app/moteur.py", [r'(?:os\.environ\.get|_env_int|_env_float|_env_bool)\(\s*"([A-Z_]+)"'])
read_dash = env_names_read(f"{PKG}/app/dashboard.py", [r'\be\("([A-Z_]+)"', r'os\.environ\.get\("([A-Z_]+)"'])
env_m = {e["name"]: e for e in mot["spec"]["template"]["spec"]["containers"][0]["env"]}
env_d = {e["name"]: e for e in dctr["env"]}
check("moteur : toutes les variables du chart sont lues par le code", sorted(set(env_m) - read_moteur), [])
check("dashboard : toutes les variables du chart sont lues par le code", sorted(set(env_d) - read_dash), [])
for label, env in (("moteur", env_m), ("dashboard", env_d)):
    secret_like = [n for n in env if re.search(r"PASSWORD|TOKEN|SECRET|WHATSAPP_TO|ACCOUNT_SID", n)]
    check(f"{label} : mots de passe, jeton et numéros viennent d'un Secret, jamais en clair", [n for n in secret_like if "valueFrom" not in env[n]], [])
check("moteur : mot de passe de la base dans le Secret attendu", env_m["DB_PASSWORD"]["valueFrom"]["secretKeyRef"], {"name": "moteur-db", "key": "password"})
check("moteur : historique et Twilio facultatifs (le pod démarre sans eux)",
      all(env_m[n]["valueFrom"]["secretKeyRef"].get("optional") is True for n in ("AUDIT_DB_USER", "AUDIT_DB_PASSWORD", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_FROM", "WHATSAPP_TO")))
check("moteur : l'historique utilise le rôle d'écriture, le dashboard celui de lecture",
      (env_m["AUDIT_DB_USER"]["valueFrom"]["secretKeyRef"]["name"], env_d["DASH_DB_USER"]["valueFrom"]["secretKeyRef"]["name"]), ("moteur-audit", "moteur-dashboard-db"))
check("trois Secrets distincts", len({env_m["DB_USER"]["valueFrom"]["secretKeyRef"]["name"], env_m["AUDIT_DB_USER"]["valueFrom"]["secretKeyRef"]["name"], env_d["DASH_DB_USER"]["valueFrom"]["secretKeyRef"]["name"]}), 3)
check("moteur : DRY_RUN vaut 'true' par défaut", env_m["DRY_RUN"]["value"], "true")
check("moteur : fichier de vie identique à la sonde", env_m["HEARTBEAT_FILE"]["value"] in mot["spec"]["template"]["spec"]["containers"][0]["livenessProbe"]["exec"]["command"][-1], True)

# ---- 6. droits RBAC : simulation d'autorisation
rules = {(r["metadata"]["namespace"], r["metadata"]["name"]): r["rules"] for r in by_kind("Role")}
bindings = {}
for b in by_kind("RoleBinding"):
    for s in b["subjects"]:
        bindings.setdefault((s["namespace"], s["name"]), set()).add((b["metadata"]["namespace"], b["roleRef"]["name"]))
def allowed(subject, ns, group, resource, name, verb):
    for key in bindings.get(subject, set()):
        if key[0] != ns: continue
        for r in rules[key]:
            if group in r["apiGroups"] and resource in r["resources"] and verb in r["verbs"] \
               and (not r.get("resourceNames") or name in r["resourceNames"]):
                return True
    return False
ME, DASH = ("university-moteur", "moteur"), ("university-moteur", "moteur-dashboard")
APP, DEC = "university-app", "university-decideur"
needed = [(ME, APP, "apps", "deployments", s, v) for s in VALUES["watchedServices"] for v in ("get", "patch")] + \
         [(ME, APP, "autoscaling", "horizontalpodautoscalers", s, "get") for s in VALUES["watchedServices"]] + \
         [(ME, DEC, "", "pods", "decideur-abc", "get"), (ME, DEC, "", "pods", None, "list"), (ME, DEC, "", "pods/log", "decideur-abc", "get")]
check("tous les appels du moteur à l'API sont autorisés", [n for n in needed if not allowed(*n)], [])
forbidden = [(ME, APP, "", "secrets", "postgres-credentials", "get"), (ME, APP, "apps", "deployments", "student-service", "delete"),
             (ME, APP, "apps", "deployments", "student-service", "update"), (ME, APP, "apps", "deployments", "frontend", "patch"),
             (ME, APP, "apps", "statefulsets", "postgres", "patch"), (ME, APP, "", "pods", "x", "delete"), (ME, APP, "", "pods", "x", "get"),
             (ME, "kube-system", "apps", "deployments", "student-service", "patch"), (ME, "monitoring", "", "secrets", "x", "get"),
             (ME, DEC, "", "secrets", "x", "get"), (ME, DEC, "apps", "deployments", "decideur", "patch"), (ME, DEC, "", "pods", "x", "delete")]
check("moindre privilège : aucune de ces actions n'est permise au moteur", [f for f in forbidden if allowed(*f)], [])
check("le tableau de bord n'a AUCUN droit sur l'API Kubernetes", DASH not in bindings, True)

# ---- 7. NetworkPolicy
port_sets = lambda np: [sorted(p["port"] for p in r["ports"]) for r in np["spec"]["egress"]]
npm, npd = named(docs, "NetworkPolicy", "moteur"), named(docs, "NetworkPolicy", "moteur-dashboard")
check("moteur : aucune entrée ; sorties DNS, Prometheus, Postgres, API Kubernetes",
      ("ingress" not in npm["spec"], "Ingress" in npm["spec"]["policyTypes"], port_sets(npm)), (True, True, [[53, 53], [9090], [5432], [443, 6443]]))
check("dashboard : aucune entrée ; sorties DNS et Postgres seulement",
      ("ingress" not in npd["spec"], "Ingress" in npd["spec"]["policyTypes"], port_sets(npd)), (True, True, [[53, 53], [5432]]))
check("les politiques ciblent les bons pods", (npm["spec"]["podSelector"]["matchLabels"], npd["spec"]["podSelector"]["matchLabels"]),
      ({"app.kubernetes.io/name": "moteur"}, {"app.kubernetes.io/name": "moteur-dashboard"}))

# ---- 8. variantes de valeurs
d2 = render({"networkPolicy.enabled": False})
check("networkPolicy.enabled=false : plus aucune NetworkPolicy", [d["kind"] for d in d2].count("NetworkPolicy"), 0)
d3 = render({"dashboard.enabled": False})
check("dashboard.enabled=false : ni dashboard, ni service, ni sa politique réseau", (len(d3), sorted(d["metadata"]["name"] for d in d3 if "dashboard" in d["metadata"]["name"])), (7, []))
d3b = render({"dashboard.enabled": False, "networkPolicy.enabled": False})
check("les deux désactivés : 6 ressources", len(d3b), 6)
d4 = render({"config.dryRun": "false", "extraEnv": {"BASELINE_MIN_SAMPLES": "10", "DB_MIN_CLIENTS": "3"}})
e4 = {e["name"]: e.get("value") for e in named(d4, "Deployment", "moteur")["spec"]["template"]["spec"]["containers"][0]["env"]}
check("dryRun false et extraEnv pris en compte (en chaînes)", (e4["DRY_RUN"], e4["BASELINE_MIN_SAMPLES"], e4["DB_MIN_CLIENTS"]), ("false", "10", "3"))
check("extraEnv lisible par le moteur", {"BASELINE_MIN_SAMPLES", "DB_MIN_CLIENTS"} <= read_moteur)
d5 = render({"watchedServices": ["student-service"]})
check("watchedServices restreint les droits", [d for d in d5 if d["kind"] == "Role" and d["metadata"]["namespace"] == APP][0]["rules"][0]["resourceNames"], ["student-service"])
check("le namespace suit la release", {d["metadata"]["namespace"] for d in render(ns="autre") if d["kind"] == "Deployment"}, {"autre"})
check("tag numérique conservé tel quel", named(render({"image.tag": "1.10"}), "Deployment", "moteur")["spec"]["template"]["spec"]["containers"][0]["image"].endswith(":1.10"))
d6 = render({"dashboard.port": 9090})
dd6 = named(d6, "Deployment", "moteur-dashboard")["spec"]["template"]["spec"]["containers"][0]
check("changer le port du dashboard le change partout (conteneur, variable, sondes)", (dd6["ports"][0]["containerPort"], {e["name"]: e.get("value") for e in dd6["env"]}["DASH_PORT"], ":9090/" in dd6["livenessProbe"]["exec"]["command"][-1]), (9090, "9090", True))

# ---- 9. Dockerfile et dépendances
df = open(f"{PKG}/app/Dockerfile").read()
local = {os.path.basename(p)[:-3] for p in glob.glob(f"{PKG}/app/*.py") if not os.path.basename(p).startswith("test_")}
imported = set()
for mod in ("moteur", "dashboard"):
    imported |= set(re.findall(r"^\s*(?:import|from)\s+(\w+)", open(f"{PKG}/app/{mod}.py").read(), re.M))
needed_modules = {"moteur", "dashboard"} | (imported & local)
copied = set(re.search(r"COPY ((?:\w+\.py ?)+)\./?", df).group(1).replace(".py", "").split())
check("le Dockerfile copie tous les modules importés", sorted(needed_modules - copied), [])
check("le Dockerfile ne copie pas les tests", not any(t.startswith("test_") for t in copied))
check("Dockerfile : python 3.12-slim, uid 10001, USER non root", ("FROM python:3.12-slim" in df, "--uid 10001" in df, "USER 10001" in df), (True,) * 3)
reqs = open(f"{PKG}/app/requirements.txt").read()
tiers = {"kubernetes": "kubernetes", "requests": "requests", "psycopg2": "psycopg2-binary"}
check("dépendances tierces importées présentes dans requirements.txt",
      [m for m, pkg in tiers.items() if re.search(rf"\b{m}\b", " ".join(open(f'{PKG}/app/{x}.py').read() for x in local)) and pkg not in reqs], [])

print("\nTOUS LES CONTRÔLES PASSENT" if OK else "\nDES CONTRÔLES ÉCHOUENT")
sys.exit(0 if OK else 1)
