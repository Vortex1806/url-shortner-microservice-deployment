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

| Service | Port | Responsibility |
|---|---|---|
| `api-gateway` | 8000 | Single entry point, routes all external traffic |
| `shortener-svc` | 8001 | Owns Postgres, creates short codes |
| `redirect-svc` | 8002 | Resolves codes (calls shortener-svc via REST), publishes click events |
| `analytics-svc` | 8003 | Consumes click events async, tracks per-code counts |
| `notification-svc` | 8004 | Consumes click events async, fires milestone alerts |

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
curl -L http://localhost:8000/aB3xY9

# check stats
curl http://localhost:8000/api/stats/aB3xY9

# check notifications (fires every 3 clicks in this local config)
curl http://localhost:8000/api/notifications
```

## Next steps

1. Push this to a new git repo
2. Write k8s manifests (Deployment/Service/ConfigMap per service, Postgres + Redis as StatefulSets or managed equivalents)
3. Terraform: VPC + EKS + ECR/DockerHub auth
4. CI pipeline: build → tag → push → update image tag in k8s manifests → commit
5. ArgoCD: Application CR pointing at the k8s manifest path, auto-sync
# url-shortner-microservice-deployment
