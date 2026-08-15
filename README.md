# URL Shortener Platform

A 5-service microservices platform built to practice GitOps end-to-end: Docker → Kubernetes → ArgoCD → CI. Infra automation (Terraform + EKS) is the next phase, not yet built — this README covers everything working today, running fully on a local `kind` cluster.

---

## 1. Application

A URL shortener with independent, loosely-coupled services instead of one monolith — built specifically to demonstrate real microservice patterns (sync REST calls, async pub/sub fan-out, single data owner) at a small, understandable scale.

| Service            | Port | Responsibility                                                                                                                     | Config source           |
| ------------------ | ---- | ---------------------------------------------------------------------------------------------------------------------------------- | ----------------------- |
| `api-gateway`      | 8000 | Single entry point, routes all external traffic to the right service                                                               | ConfigMap               |
| `shortener-svc`    | 8000 | Owns Postgres, creates short codes, exposes internal resolve endpoint                                                              | Secret (`DATABASE_URL`) |
| `redirect-svc`     | 8000 | Resolves a code by calling `shortener-svc` over REST, issues the redirect, publishes a click event                                 | ConfigMap               |
| `analytics-svc`    | 8000 | Subscribes to click events, maintains per-code click counts in Redis                                                               | ConfigMap               |
| `notification-svc` | 8000 | Subscribes to click events, fires a milestone alert every N clicks (reads the shared count from Redis rather than keeping its own) | ConfigMap               |

**Data stores:** Postgres (owned exclusively by `shortener-svc`) and Redis (used both as a cache-free pub/sub bus between services, and as shared counter storage for `analytics-svc`).

---

## 2. Architecture

```
                         ┌──────────────┐
   client ─── Ingress ─► │ api-gateway  │
                         └──────┬───────┘
                                │
             ┌──────────────────┼──────────────────┐
             ▼                  ▼                   │
      ┌──────────────┐   ┌──────────────┐           │
      │ shortener-svc │   │ redirect-svc │◄──────────┘
      │ (owns Postgres)│  │ calls shortener-svc via REST
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
              │    │ (click counts,│ │ (milestone alerts,│
              │    │  redis-backed)│ │  reads shared count)│
              │    └──────────────┘ └────────────────┘
              ▼
           Postgres
```

**Why this demonstrates real microservice patterns, not just 5 containers:**

- **Sync REST**: gateway → every service; `redirect-svc` → `shortener-svc`
- **Async pub/sub**: `redirect-svc` publishes a click event and doesn't know or care who's listening — `analytics-svc` and `notification-svc` independently consume the same stream
- **Single data owner**: only `shortener-svc` touches Postgres directly; nobody else reaches into its DB
- **Service discovery via DNS**: services find each other by plain Kubernetes Service name (`shortener-svc`, `redis`, etc.) — no external registry (e.g. Eureka) needed, k8s provides this natively

---

## 3. How it works — request flow

1. Client calls `POST /api/shorten` on `api-gateway` → proxied to `shortener-svc` → generates a random 6-char code, stores `{code, original_url}` in Postgres
2. Client calls `GET /<code>` on `api-gateway` → proxied to `redirect-svc` → `redirect-svc` calls `shortener-svc`'s internal resolve endpoint to get the original URL → issues an HTTP redirect → publishes a `{code, timestamp}` event to Redis channel `clicks`
3. `analytics-svc` and `notification-svc` are both subscribed to `clicks` in a background thread — on every event, `analytics-svc` increments a Redis hash counter, `notification-svc` reads that same counter and fires an alert if it just crossed a multiple of `MILESTONE_EVERY`
4. Client can call `GET /api/stats/<code>` (current click count) or `GET /api/notifications` (recent milestone alerts) at any time

---

## 4. Repo structure

```
url-shortener-platform/
├── api-gateway/                 # FastAPI app + Dockerfile
├── shortener-svc/
├── redirect-svc/
├── analytics-svc/
├── notification-svc/
├── docker-compose.yml            # local testing without k8s
├── kind-cluster-local-setup/
│   └── kind-config.yaml           # kind cluster config with ingress port mappings
├── k8s/base/                     # every k8s manifest — this is what ArgoCD watches
│   ├── namespace.yaml
│   ├── configmap.yaml
│   ├── secret.yaml
│   ├── ingress.yaml
│   ├── postgres/
│   ├── redis/
│   └── <service>/deployment.yaml + service.yaml   (x5)
├── argocd/
│   ├── application.yaml           # ArgoCD Application CR — points at this repo's k8s/base
│   └── ingress.yaml                # exposes ArgoCD UI at https://argocd.localhost
└── .github/workflows/
    └── ci.yml                      # path-filtered build/push/patch pipeline
```

---

## 5. Run with Docker Compose (fastest, no Kubernetes)

```bash
docker compose up --build
```

Test:

```bash
# create a short URL
curl -X POST http://localhost:8000/api/shorten -H "Content-Type: application/json" -d '{"url": "https://google.com"}'
# -> {"code": "aB3xY9", "short_url": "/aB3xY9", ...}

# hit it a few times
curl -L http://localhost:8000/aB3xY9

# check stats
curl http://localhost:8000/api/stats/aB3xY9

# check notifications
curl http://localhost:8000/api/notifications
```

---

## 6. Run locally on Kubernetes (kind) — full GitOps loop

### Prerequisites

- Docker Desktop running, with enough allocated disk (Settings → Resources → Virtual disk limit — 64GB+ recommended; ArgoCD alone needs meaningful space)
- `kind`, `kubectl` installed (`brew install kind kubectl` on Mac)
- Images already pushed to DockerHub (see CI section below) — or build+load manually into kind if testing before CI exists

### Step 1 — Create the cluster (with ingress port mappings)

```bash
kind create cluster --name url-shortener-dev --config kind-cluster-local-setup/kind-config.yaml
kubectl config use-context kind-url-shortener-dev
kubectl get nodes
```

Confirm the node shows `Ready`.

### Step 2 — Install ingress-nginx

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=120s
```

### Step 3 — Deploy the app

```bash
kubectl apply -f k8s/base/namespace.yaml
kubectl apply -f k8s/base/configmap.yaml
kubectl apply -f k8s/base/secret.yaml
kubectl apply -f k8s/base/postgres/
kubectl apply -f k8s/base/redis/
kubectl apply -f k8s/base/shortener-svc/
kubectl apply -f k8s/base/redirect-svc/
kubectl apply -f k8s/base/analytics-svc/
kubectl apply -f k8s/base/notification-svc/
kubectl apply -f k8s/base/api-gateway/
kubectl apply -f k8s/base/ingress.yaml
kubectl get pods -n url-shortener
```

All 7 pods should reach `1/1 Running`.

### Step 4 — Test via ingress (no port-forward needed)

```bash
curl -X POST http://localhost/api/shorten -H "Content-Type: application/json" -d '{"url": "https://google.com"}'
curl -L http://localhost/<code>
curl http://localhost/api/stats/<code>
curl http://localhost/api/notifications
```

---

## 7. Kubernetes architecture for this project

| Resource kind                                  | Used for                                                                                        | Notes                                                                                                                                                   |
| ---------------------------------------------- | ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Namespace`                                    | `url-shortener` groups every app resource                                                       | Created once, first                                                                                                                                     |
| `ConfigMap`                                    | Shared non-secret values: service URLs, `REDIS_HOST`, `MILESTONE_EVERY`                         | Read via `envFrom.configMapRef` by all 5 app services except `shortener-svc`                                                                            |
| `Secret`                                       | `DATABASE_URL` (has a password in it)                                                           | Read via `envFrom.secretRef`, only by `shortener-svc`                                                                                                   |
| `Deployment` (x7: postgres, redis, 5 services) | Defines the container image, replica count, resource requests/limits, readiness/liveness probes | Self-healing — k8s restarts a crashed container automatically                                                                                           |
| `Service` (x7, ClusterIP)                      | Stable DNS name + IP for each Deployment's pods                                                 | Pods are disposable and get new IPs on restart; Services are how everything finds everything else, replacing what a tool like Eureka would otherwise do |
| `Ingress` (x2: app + ArgoCD)                   | Routes external HTTP traffic into the cluster                                                   | `api-gateway-ingress` routes `/` on `localhost` to `api-gateway`; `argocd-server-ingress` routes `argocd.localhost` to ArgoCD's own service             |

**Deliberately not used:** no StatefulSet — Postgres and Redis run as plain Deployments, each with a `PersistentVolumeClaim` (1Gi, `ReadWriteOnce`) mounted for data storage. This means data survives pod restarts (proven — see PVC section below), but since both are single-replica by design, a StatefulSet wasn't needed. On real EKS, these would move to managed RDS/ElastiCache instead of in-cluster PVCs, for proper backups and multi-AZ durability.

**`enableServiceLinks: false`** is set on every Deployment's pod spec. Without it, Kubernetes auto-injects legacy `<SERVICE>_PORT` / `<SERVICE>_HOST` env vars into every pod in the namespace — this collided with the app's own `REDIS_PORT` env var and crashed a service on boot. Worth knowing: any app env var name that happens to match a Service name is at risk of this exact collision.

### Persistent storage (Postgres + Redis)

Both `postgres` and `redis` mount a `PersistentVolumeClaim` (1Gi, `ReadWriteOnce`, kind's default `standard` StorageClass) at their data directory, so data survives pod restarts — not just container restarts within the same pod, but full pod deletion/recreation.

```
k8s/base/postgres/pvc.yaml   # 1Gi PVC
k8s/base/redis/pvc.yaml      # 1Gi PVC
```

`postgres`'s Deployment sets `PGDATA=/var/lib/postgresql/data/pgdata` — a subfolder inside the mount, not the mount root. This avoids Postgres refusing to initialize on some volume provisioners that leave a `lost+found` directory at the root.

**Proof it works:**

```bash
curl -X POST http://localhost/api/shorten -H "Content-Type: application/json" -d '{"url": "https://google.com"}'
# note the returned code

kubectl delete pod -n url-shortener -l app=postgres
kubectl get pods -n url-shortener -w
# wait for postgres to reach 1/1 Running again

curl -L http://localhost/<the-code>
# resolves correctly — data survived the pod being deleted and recreated
```

**Limitation:** `ReadWriteOnce` means the volume can only be mounted by one pod at a time — acceptable since both are single-replica, but this is exactly why it doesn't scale past 1 replica for either, and why real production infra uses RDS/ElastiCache instead.

---

## 8. ArgoCD setup

### Install

```bash
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl get pods -n argocd -w
```

Wait for every pod to reach `Running` (6 components, ~1-2 min).

### Point it at this repo

```bash
kubectl apply -f argocd/application.yaml
```

`argocd/application.yaml` — key fields:

- `source.repoURL` / `path: k8s/base` — where ArgoCD pulls manifests from
- `source.directory.recurse: true` — **required**, otherwise ArgoCD only reads files directly in `k8s/base/` and misses everything in subfolders (postgres, redis, all 5 services)
- `syncPolicy.automated.prune: true` — deletes cluster resources that were removed from git
- `syncPolicy.automated.selfHeal: true` — reverts any manual `kubectl` change back to match git

### Expose the UI (no port-forward needed)

```bash
kubectl apply -f argocd/ingress.yaml
```

Then open `https://argocd.localhost` directly — `*.localhost` hostnames resolve to `127.0.0.1` automatically in modern browsers, no `/etc/hosts` edit needed.

### Get the admin password

```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
```

Login as `admin` with that password.

### Prove the GitOps loop actually works

```bash
# manually break something outside of git
kubectl scale deployment shortener-svc -n url-shortener --replicas=3
kubectl get pods -n url-shortener -w
```

Within ArgoCD's default 3-minute poll interval, it reverts back to `replicas: 1` on its own — because git still says `1` and `selfHeal: true` forces the cluster to match git, not the other way around.

---

## 9. CI pipeline setup

### GitHub repo secrets required

Settings → Secrets and variables → Actions → New repository secret:

- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN` — a DockerHub **access token** (DockerHub → Account Settings → Security → New Access Token, Read & Write scope), not your account password

### What `.github/workflows/ci.yml` does, on every push to `main`

1. Diffs the last commit against its parent to see which top-level folders changed
2. Filters that list down to only the 5 known service folder names
3. For each changed service **only**: builds the image, tags it with the short git SHA, pushes to DockerHub, then `sed`-patches that service's `k8s/base/<service>/deployment.yaml` to point at the new tag
4. Commits the manifest change(s) back to `main` in a single commit (avoids push races between parallel jobs)
5. If nothing under any service folder changed (e.g. a README-only commit), every build step is skipped — zero unnecessary builds

Untouched services are never rebuilt, never repushed, and their `deployment.yaml` is never touched — ArgoCD's diff only sees the one resource that actually changed, and only that one Deployment gets redeployed.

### Note on CI's own commits

The workflow pushes back to `main` using the default `GITHUB_TOKEN`, which does **not** re-trigger another workflow run — this is expected GitHub behavior (loop prevention), not a bug.

### End-to-end test of the whole loop

1. Edit one line in a single service's code (e.g. `notification-svc/main.py`)
2. Push to `main` (directly or via PR merge)
3. Watch the Actions tab — confirm only that one service's job actually ran
4. Within ~3 minutes, watch `kubectl get pods -n url-shortener -w` or the ArgoCD UI — only that one Deployment restarts with the new image tag

---

## 10. Real bugs found and fixed during development

Worth documenting these as-is — each is a genuine distributed-systems failure mode that Kubernetes' lack of startup-ordering guarantees exposes, not a typo or config mistake:

- **`enableServiceLinks: false`** required on every Deployment. Without it, Kubernetes auto-injects legacy `<SERVICE>_PORT`/`<SERVICE>_HOST` env vars into every pod in the namespace — this collided with the app's own `REDIS_PORT` env var and crashed `redirect-svc` on boot.
- **Redis Pub/Sub consumer crash on boot.** Both `analytics-svc` and `notification-svc` originally crashed once at startup if their pod came up before Redis was ready to accept connections — the background subscriber thread died with an unhandled exception, but the FastAPI server stayed healthy, so `/health` stayed green while the consumer was silently dead. Fixed with a `while True: try/except: sleep(3)` retry loop around the subscribe/listen call.
- **`shortener-svc` stale DB connections after Postgres pod restart.** SQLAlchemy's default connection pool doesn't test a connection before reusing it — after Postgres restarted (e.g. from a pod delete or a rollout), `shortener-svc` kept trying to reuse dead pooled connections and failed with `server closed the connection unexpectedly`. Fixed with `pool_pre_ping=True` on the engine (tests + transparently replaces stale connections) plus an explicit retry wrapper around session creation (handles the case where Postgres isn't accepting connections at all yet, not just stale-but-open ones).
- **`shortener-svc` schema not re-created after a fresh Postgres volume.** `Base.metadata.create_all()` only runs once, at app startup — it assumes the app and DB always come up together. Since Kubernetes gives no such guarantee (pods restart independently), a Postgres restart onto an empty/new volume left `shortener-svc` pointing at a DB with no `urls` table until the app itself was also restarted. Wrapped `create_all()` in a retry loop for the boot-ordering case; a production system would use explicit migrations (Alembic, Flyway) run as a deploy step instead of implicit schema creation on app boot.

## 11. Known limitations (intentional, documented rather than fixed)

- **`notification-svc`'s alert log** (the in-memory `notifications` list) would produce duplicate alerts if scaled to 2+ replicas, since each pod keeps its own copy. The click _count_ itself reads from Redis (shared, correct); the alert _log_ itself was left in-memory as a documented next step rather than adding leader-election complexity for a throwaway project.
- **Redis Pub/Sub, not Streams** — messages still aren't persisted; a subscriber that isn't connected at publish time misses that message permanently, with no error surfaced anywhere. A system needing guaranteed delivery would use Redis Streams, RabbitMQ, or Kafka instead.
- **`ReadWriteOnce` PVCs** limit Postgres/Redis to a single replica each — acceptable here, but the real reason production systems use RDS/ElastiCache instead of in-cluster PVCs.

---

## 12. Not yet done / next steps

- [ ] Terraform: VPC + EKS cluster + node groups + IAM (IRSA for ArgoCD/CI) — next phase
- [ ] Swap `ingress-nginx` → AWS Load Balancer Controller + real ALB (EKS-only, doesn't work on kind)
- [ ] GitHub webhook → ArgoCD for instant sync instead of 3-minute polling (needs a public ArgoCD endpoint, only viable once on real EKS)
- [ ] Move `notification-svc`'s alert log into Redis to fully remove the in-memory limitation
- [ ] Explicit migration tool (Alembic) for `shortener-svc` instead of `create_all()` on boot
