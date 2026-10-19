#!/usr/bin/env python3
"""
Exporte l'historique Prometheus utile au moteur en CSV (un fichier par métrique).

Usage :
    kubectl port-forward -n monitoring svc/prometheus 9090:9090 &
    python3 export_prometheus.py --hours 16 --step 30

Sortie : dossier ./export/ avec un CSV par requête, au format long
(timestamp_utc, labels, value). Aucune dépendance externe.
"""
import argparse
import csv
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

NS = 'namespace="university-app"'

QUERIES = {
    "p95_latency": (
        'histogram_quantile(0.95, sum by (job, le) (rate(flask_http_request_duration_seconds_bucket[2m]))) '
        'or histogram_quantile(0.95, sum by (job, le) (rate(http_server_requests_seconds_bucket[2m])))'
    ),
    "request_rate": (
        'sum by (job) (rate(flask_http_request_total[2m])) '
        'or sum by (job) (rate(http_server_requests_seconds_count[2m]))'
    ),
    "error_rate_5xx": (
        'sum by (job) (rate(flask_http_request_total{status=~"5.."}[2m])) '
        'or sum by (job) (rate(http_server_requests_seconds_count{status=~"5.."}[2m]))'
    ),
    "replicas_ready": f'kube_deployment_status_replicas_ready{{{NS}}}',
    "replicas_spec": f'kube_deployment_spec_replicas{{{NS}}}',
    "hpa_current_replicas": f'kube_horizontalpodautoscaler_status_current_replicas{{{NS}}}',
    "cpu_usage_per_pod": (
        f'sum by (pod) (rate(container_cpu_usage_seconds_total{{{NS}, container!="", container!="POD"}}[2m]))'
    ),
    "cpu_requests_per_pod": (
        f'sum by (pod) (kube_pod_container_resource_requests{{{NS}, resource="cpu"}})'
    ),
    "container_restarts": f'kube_pod_container_status_restarts_total{{{NS}}}',
    "servicegraph_rate": (
        'sum by (client, server, failed) (rate(traces_service_graph_request_total[2m]))'
    ),
    "servicegraph_client_p95": (
        'histogram_quantile(0.95, sum by (client, server, le) '
        '(rate(traces_service_graph_request_client_seconds_bucket[2m])))'
    ),
    "servicegraph_server_p95": (
        'histogram_quantile(0.95, sum by (client, server, le) '
        '(rate(traces_service_graph_request_server_seconds_bucket[2m])))'
    ),
}


def query_range(base_url, promql, start, end, step):
    params = urllib.parse.urlencode(
        {"query": promql, "start": start, "end": end, "step": step}
    )
    with urllib.request.urlopen(f"{base_url}/api/v1/query_range?{params}", timeout=60) as r:
        body = json.load(r)
    if body.get("status") != "success":
        raise RuntimeError(body.get("error", "réponse en échec"))
    return body["data"]["result"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:9090")
    ap.add_argument("--hours", type=float, default=16, help="durée à exporter, en heures")
    ap.add_argument("--step", type=int, default=30, help="pas en secondes")
    ap.add_argument("--out", default="export")
    args = ap.parse_args()

    end = int(time.time())
    start = end - int(args.hours * 3600)
    os.makedirs(args.out, exist_ok=True)
    print(f"Période : {datetime.fromtimestamp(start, timezone.utc):%Y-%m-%d %H:%M} → "
          f"{datetime.fromtimestamp(end, timezone.utc):%Y-%m-%d %H:%M} UTC, pas {args.step}s")

    for name, promql in QUERIES.items():
        try:
            series = query_range(args.url, promql, start, end, args.step)
        except Exception as e:  # on continue : une métrique absente ne doit pas tout bloquer
            print(f"  {name:26s} ERREUR : {str(e)[:100]}")
            continue
        path = os.path.join(args.out, f"{name}.csv")
        rows = 0
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp_utc", "labels", "value"])
            for s in series:
                labels = json.dumps(s["metric"], sort_keys=True)
                for ts, val in s["values"]:
                    iso = datetime.fromtimestamp(float(ts), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    w.writerow([iso, labels, val])
                    rows += 1
        print(f"  {name:26s} {len(series):3d} séries, {rows:6d} points")


if __name__ == "__main__":
    main()