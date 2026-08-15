# URL Shortener Platform

5-service microservices architecture, Python/FastAPI, built for GitOps practice (Terraform → EKS → ArgoCD → CI auto-tagging).

## Architecture

```
                    ┌──────────────┐
   client ────────► │ api-gateway  │  (single entry point)
                    └──────┬───────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                   │
 ┌──────────────┐   ┌──────────────┐           │
 │ shortener-svc │   │ redirect-svc │◄──────────┘
 │ (owns Postgres)│  │  calls shortener-svc via REST
 └───────┬───────┘   └──────┬───────┘
         │                  │ publishes "clicks" event
         │                  ▼
         │            ┌───────────┐
         │            │   Redis   │  (pub/sub bus)
         │            └─────┬─────┘
         │           ┌──────┴──────┐
         │           ▼             ▼
         │    ┌──────────────┐ ┌────────────────┐
         │    │ analytics-svc│ │ notification-svc│
         │    │ (click counts)│ │ (milestone alerts)│
         │    └──────────────┘ └────────────────┘
         ▼
      Postgres
```

## Services

| Service            | Port | Responsibility                                                        |
| ------------------ | ---- | --------------------------------------------------------------------- |
| `api-gateway`      | 8000 | Single entry point, routes all external traffic                       |
| `shortener-svc`    | 8001 | Owns Postgres, creates short codes                                    |
| `redirect-svc`     | 8002 | Resolves codes (calls shortener-svc via REST), publishes click events |
| `analytics-svc`    | 8003 | Consumes click events async, tracks per-code counts                   |
| `notification-svc` | 8004 | Consumes click events async, fires milestone alerts                   |

## Why this shows "scale"

- **Sync REST** between gateway → services and redirect-svc → shortener-svc
- **Async pub/sub** via Redis: redirect-svc doesn't know or care who's listening — analytics-svc and notification-svc both independently consume the same event stream
- **Data ownership**: only shortener-svc touches Postgres directly; nobody else reaches into its DB

## Run locally (before touching k8s)

```bash
docker compose up --build
```

Test:

```bash
# create a short URL
curl -X POST http://localhost:8000/api/shorten -H "Content-Type: application/json" -d '{"url": "https://google.com"}'
# -> {"code": "aB3xY9", "short_url": "/aB3xY9", ...}

# hit it a few times
curl -L http://localhost:8000/MIu7L1

# check stats
curl http://localhost:8000/api/stats/MIu7L1

# check notifications (fires every 3 clicks in this local config)
curl http://localhost:8000/api/notifications
```

Kind Cluster usage
brew install kind
kind create cluster --name url-shortener-dev
kubectl config use-context kind-url-shortener-dev
kubectl get nodes

## Running on Kubernetes (local, kind)

All 7 workloads (postgres, redis, 5 app services) run as Deployments + ClusterIP Services in the `url-shortener` namespace on a local `kind` cluster.

### Setup

```bash
kind create cluster --name url-shortener-dev
kubectl apply -f k8s/base/namespace.yaml
kubectl apply -f k8s/base/configmap.yaml
kubectl apply -f k8s/base/secret.yaml
kubectl apply -f k8s/base/postgres/
kubectl apply -f k8s/base/redis/
```

### Build and load each service image into kind

For each service (`shortener-svc`, `redirect-svc`, `analytics-svc`, `notification-svc`, `api-gateway`):

```bash
docker build -t <service-name>:local ./<service-name>
kind load docker-image <service-name>:local --name url-shortener-dev
kubectl apply -f k8s/base/<service-name>/
```

### Test end-to-end

```bash
kubectl port-forward -n url-shortener svc/api-gateway 8000:8000
```

Then run the same curl commands as the local docker-compose section above, against `localhost:8000`.

### Notes / known limitations

- **No persistent volumes** on postgres/redis — data resets if those pods restart. Fine for a throwaway/demo project, would need PVCs for anything real.
- **`enableServiceLinks: false`** is set on every Deployment. Without it, Kubernetes auto-injects legacy `<SERVICE>_PORT`/`<SERVICE>_HOST` env vars into every pod in the namespace, which collided with this app's own `REDIS_PORT` env var and crashed `redirect-svc` on boot. Worth knowing — any app-level env var name that matches a Service name is at risk of this collision.
- **`notification-svc` keeps click counts in local process memory** (`local_counts` dict), not in Redis like `analytics-svc` does. This means its counter resets on pod restart and won't stay consistent if scaled to multiple replicas. Left as-is since this is a throwaway project, but in a real service this state would need to live in Redis or a shared store — stateless services shouldn't hold state in memory that k8s can wipe out by rescheduling the pod.

## Next steps

1. Push this to a new git repo
2. Write k8s manifests (Deployment/Service/ConfigMap per service, Postgres + Redis as StatefulSets or managed equivalents)
3. Terraform: VPC + EKS + ECR/DockerHub auth
4. CI pipeline: build → tag → push → update image tag in k8s manifests → commit
5. ArgoCD: Application CR pointing at the k8s manifest path, auto-sync

# url-shortner-microservice-deployment
