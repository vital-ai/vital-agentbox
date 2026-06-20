# AWS Deployment

ECS Fargate task definitions for AgentBox.

## Services

| Service | CPU | Memory | Image |
|---------|-----|--------|-------|
| **Orchestrator** | 0.5 vCPU | 1 GB | `agentbox-orchestrator:latest` |
| **Worker** | 2 vCPU | 4 GB | `agentbox-worker:latest` |

## Prerequisites

1. **ECR repositories** — create `agentbox-orchestrator` and `agentbox-worker`
2. **MemoryDB cluster** — Redis 7.x, TLS enabled, single-shard is fine to start
3. **S3 bucket** — for git storage (e.g. `agentbox-repos-prod`)
4. **Secrets Manager** — populate the secrets referenced in the task definitions:
   - `agentbox/REDIS_URL` — `rediss://clustercfg.xxx.memorydb.us-east-1.amazonaws.com:6379`
   - `agentbox/REDIS_USERNAME` — MemoryDB ACL username
   - `agentbox/REDIS_PASSWORD` — MemoryDB auth token
   - `agentbox/JWT_JWKS_URI` — Keycloak JWKS endpoint
   - `agentbox/JWT_ISSUER` — Keycloak realm issuer URL
   - `agentbox/JWT_AUDIENCE` — expected JWT audience
   - `agentbox/ORCHESTRATOR_URL` — internal ALB URL (e.g. `http://internal-alb:8000`)
   - `agentbox/GIT_S3_BUCKET` — S3 bucket name
5. **IAM roles**:
   - `ecsTaskExecutionRole` — standard ECS execution role (ECR pull + Secrets Manager read)
   - `agentbox-orchestrator-task-role` — no extra permissions needed (Redis via network)
   - `agentbox-worker-task-role` — S3 read/write to the git bucket (Mode 1/2 only)
6. **CloudWatch Log Groups** — `/ecs/agentbox-orchestrator` and `/ecs/agentbox-worker`
7. **VPC + Security Groups**:
   - Orchestrator SG: inbound 8000 from ALB, outbound to Redis + workers
   - Worker SG: inbound 8000 from orchestrator SG, outbound to S3 + internet

## Deployment

```bash
# Build and push images
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com

docker build -f Dockerfile.orchestrator -t ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/agentbox-orchestrator:latest .
docker push ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/agentbox-orchestrator:latest

docker build -f Dockerfile.worker -t ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/agentbox-worker:latest .
docker push ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/agentbox-worker:latest

# Register task definitions
aws ecs register-task-definition --cli-input-json file://deploy/orchestrator-task-definition.json
aws ecs register-task-definition --cli-input-json file://deploy/worker-task-definition.json

# Update services (assumes services already created)
aws ecs update-service --cluster agentbox --service orchestrator --task-definition agentbox-orchestrator --force-new-deployment
aws ecs update-service --cluster agentbox --service worker --task-definition agentbox-worker --force-new-deployment
```

## Worker Auto-Registration

Workers self-register with the orchestrator on startup via `AGENTBOX_ORCHESTRATOR_URL`.
The worker's `AGENTBOX_WORKER_HOST` defaults to the container's hostname. In Fargate with
`awsvpc` networking, the task gets a private IP — use ECS Service Connect or Cloud Map
for stable DNS names, or let workers register with their task private IP (works if
orchestrator can reach them on the same VPC).

## Notes

- Worker needs `/dev/shm` (2 GB) for Chromium — configured via `linuxParameters.sharedMemorySize`
- Worker `startPeriod` is 30s (Xvfb + Chromium startup)
- Orchestrator is stateless — scale horizontally behind ALB
- Workers are stateful (sandboxes live in memory) — scale by adding tasks, not replacing
