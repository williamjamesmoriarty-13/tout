# Moteur de vérification de sûreté (paquet de déploiement)

```
app/                          moteur, diagnostic, historique, alertes, tableau de bord + leurs tests
  moteur.py                   boucle principale, invariants 1 à 6, exécuteur
  diagnostic.py               détection de dégradation et cause racine (graphe de dépendances)
  causes.py  notifier.py      regroupement par cause racine, alertes WhatsApp (Twilio)
  audit.py                    historique durable dans Postgres
  dashboard.py                tableau de bord (lecture seule, flux en direct)
  Dockerfile  requirements.txt
university-moteur/            chart Helm (moteur + tableau de bord)
scripts/                      installation (voir ci-dessous)
dev/                          outils de contrôle facultatifs (rendu du chart, test de l'interface)
```

## Ordre d'installation
1. Base de données (une fois) :
   - `bash scripts/init_compat.sh`
   - `ENGINE_DB_PASSWORD='...' bash scripts/setup_engine_db.sh`      (rôle engine_ro, lecture du schéma)
   - `ENGINE_AUDIT_PASSWORD='...' DASHBOARD_DB_PASSWORD='...' bash scripts/setup_audit_db.sh`  (historique + 2 rôles)
2. Tests, dans `app/` : `for t in test_*.py; do python3 $t | tail -1; done`
3. `helm lint university-moteur` puis `helm template university-moteur -n university-moteur | less`
4. Déploiement (dry-run par défaut) :
   ```
   ENGINE_DB_PASSWORD=... ENGINE_AUDIT_PASSWORD=... DASHBOARD_DB_PASSWORD=... \
   [TWILIO_ACCOUNT_SID=... TWILIO_AUTH_TOKEN=... TWILIO_WHATSAPP_FROM=whatsapp:+14155238886 WHATSAPP_TO=whatsapp:+261...] \
   [K3D_CLUSTER=<nom>] bash scripts/setup-moteur.sh
   ```
5. Suivre : `kubectl logs -n university-moteur deploy/moteur -f`
6. Tableau de bord : `kubectl port-forward -n university-moteur svc/moteur-dashboard 8088:80` puis http://localhost:8088
7. Mode réel (le moteur agit pour de bon) : relancer avec `DRY_RUN=false CONFIRM_LIVE=yes`.

## À savoir
- **Alertes WhatsApp** : une par cause racine (pas une par refus). Un groupe se referme après 10 min de silence.
  Sur le sandbox Twilio, un message libre n'est livré que dans les 24 h qui suivent un message de ton numéro
  vers le sandbox (renvoie « join <code> » pour rouvrir la fenêtre). Sans identifiants Twilio, le texte est
  quand même enregistré avec le statut `disabled`.
- **Historique** : chaque verdict et chaque alerte dans `moteur_schema` (Postgres). Aucune purge automatique.
  Si la base est injoignable, 500 lignes attendent en mémoire ; un redémarrage du moteur les perd.
- **Tableau de bord** : sans authentification, uniquement par port-forward. Il n'a aucun droit sur l'API Kubernetes.
- Nouvelle version du code : changer `TAG`. Les patchs du moteur portent le field manager `moteur` : un
  `helm upgrade` de l'application peut demander `--force-conflicts`.
- Si `university-app` ou `monitoring` ont des NetworkPolicy en entrée, y autoriser `university-moteur`
  (Postgres 5432, Prometheus 9090). Pour diagnostiquer : `--set networkPolicy.enabled=false`.
- Contrôles facultatifs : `python3 dev/check_chart.py` (rendu et validation du chart) et
  `node dev/test_dashboard_ui.js page.html` (voir l'en-tête du fichier).
