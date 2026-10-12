import os
import shutil
from prometheus_client import CollectorRegistry, multiprocess

# 1. Configurer et préparer le répertoire partagé pour le multiprocessus
os.environ.setdefault("PROMETHEUS_MULTIPROC_DIR", "/tmp/prometheus_multiproc_dir")
multiproc_dir = os.environ["PROMETHEUS_MULTIPROC_DIR"]

if os.path.exists(multiproc_dir):
    shutil.rmtree(multiproc_dir)
os.makedirs(multiproc_dir, exist_ok=True)

# 2. Initialiser le registre global Prometheus
registry = CollectorRegistry()
multiprocess.MultiProcessCollector(registry)

# 3. Charger l'application Flask
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003)
    
