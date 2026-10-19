# Installation de l'OTel Operator — 01-setup-cluster.sh

## Où l'insérer

Dans `scripts/01-setup-cluster.sh`, après l'installation du chart
`university-monitoring` et avant toute vérification finale.
Repère la ligne qui fait `helm upgrade --install university-monitoring ...`
et ajoute ce bloc JUSTE APRÈS :

```bash
# ── OpenTelemetry Operator ─────────────────────────────────────────────
echo "→ Installation de l'OTel Operator..."

# 1. CRDs (cert-manager requis — k3d l'inclut via Traefik, sinon installer séparément)
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update open-telemetry

# 2. Operator dans son namespace dédié
helm upgrade --install opentelemetry-operator open-telemetry/opentelemetry-operator \
  --namespace opentelemetry-operator-system \
  --create-namespace \
  --version 0.65.0 \
  --set manager.collectorImage.repository="otel/opentelemetry-collector-contrib" \
  --set admissionWebhooks.certManager.enabled=false \
  --set admissionWebhooks.autoGenerateCert.enabled=true \
  --wait --timeout 120s

# 3. Ressource Instrumentation (déployée dans university-app)
#    L'Operator lit cette CR et injecte le SDK dans les pods annotés.
kubectl apply -f university-monitoring/templates/otel-instrumentation/instrumentation.yaml
```

## Annotations à ajouter dans university-app

Dans les Deployments de tes 3 services (dans `spec.template.metadata.annotations`) :

**student-service/deployment.yaml** et **enrollment-service/deployment.yaml** :
```yaml
annotations:
  instrumentation.opentelemetry.io/inject-python: "true"
```

**teacher-admin-service/deployment.yaml** :
```yaml
annotations:
  instrumentation.opentelemetry.io/inject-java: "true"
```

## Point ambigu à noter

k3d n'installe pas cert-manager par défaut. L'option
`admissionWebhooks.autoGenerateCert.enabled=true` contourne ce besoin
en générant un certificat auto-signé — suffisant pour un environnement
de dev. En prod, préférer cert-manager.

## Ordre de déploiement recommandé

1. `helm upgrade --install university-app ...`
2. `helm upgrade --install university-monitoring ...`
3. OTel Operator (commandes ci-dessus)
4. Vérifier : `kubectl get instrumentation -n university-app`
5. Redémarrer les pods pour déclencher l'injection :
   `kubectl rollout restart deployment -n university-app`
