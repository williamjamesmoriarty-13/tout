# Modifications requises dans university-app

## Fichier concerné : `university-app/templates/network-policies.yaml`

Un seul ajout : autoriser Prometheus (namespace `monitoring`) à scraper
chaque service applicatif en Ingress.

Ajoute ce bloc `ingress` dans la politique de chaque service ci-dessous.

---

### student-service-policy

Trouve la NetworkPolicy `student-service-policy` et ajoute cette règle Ingress
(en plus de celles déjà existantes) :

```yaml
  # Prometheus monitoring peut scraper /metrics
  - from:
      - namespaceSelector:
          matchLabels:
            kubernetes.io/metadata.name: monitoring
        podSelector:
          matchLabels:
            app.kubernetes.io/name: prometheus
    ports:
      - port: 5001
```

---

### enrollment-service-policy

```yaml
  - from:
      - namespaceSelector:
          matchLabels:
            kubernetes.io/metadata.name: monitoring
        podSelector:
          matchLabels:
            app.kubernetes.io/name: prometheus
    ports:
      - port: 5003
```

---

### teacher-admin-service-policy

```yaml
  - from:
      - namespaceSelector:
          matchLabels:
            kubernetes.io/metadata.name: monitoring
        podSelector:
          matchLabels:
            app.kubernetes.io/name: prometheus
    ports:
      - port: 8080
```

---

## Aucune autre modification nécessaire

- `frontend` et `postgres` : pas de métriques exposées → pas de changement.
- Les Deployments, HPA, Services : inchangés.
- Le label `kubernetes.io/metadata.name: monitoring` est automatiquement
  posé par Kubernetes sur tout namespace → pas besoin de label manuel.
