# AWS ECS Deployment

Deploy AgentBox on AWS ECS Fargate with the orchestrator and worker services.

## Services

| Service | CPU | Memory | Image |
|---------|-----|--------|-------|
| **Orchestrator** | 0.5 vCPU | 1 GB | `agentbox-orchestrator:latest` |
| **Worker** | 2 vCPU | 4 GB | `agentbox-worker:latest` |

## Prerequisites

### 1. ECR repositories

```bash
aws ecr create-repository --repository-name agentbox-orchestrator
aws ecr create-repository --repository-name agentbox-worker
```

### 2. MemoryDB cluster

Redis 7.x with TLS enabled. Single-shard is fine to start.

### 3. S3 bucket

For git storage (e.g. `agentbox-repos-prod`).

### 4. Secrets Manager

Populate the following secrets:

| Secret | Value |
|--------|-------|
| `agentbox/REDIS_URL` | `rediss://clustercfg.xxx.memorydb.us-east-1.amazonaws.com:6379` |
| `agentbox/REDIS_USERNAME` | MemoryDB ACL username |
| `agentbox/REDIS_PASSWORD` | MemoryDB auth token |
| `agentbox/JWT_JWKS_URI` | Keycloak JWKS endpoint |
| `agentbox/JWT_ISSUER` | Keycloak realm issuer URL |
| `agentbox/JWT_AUDIENCE` | Expected JWT audience |
| `agentbox/ORCHESTRATOR_URL` | Internal ALB URL (e.g. `http://internal-alb:8000`) |
| `agentbox/GIT_S3_BUCKET` | S3 bucket name |

### 5. IAM roles

| Role | Purpose |
|------|---------|
| `ecsTaskExecutionRole` | Standard ECS execution (ECR pull + Secrets Manager read) |
| `agentbox-orchestrator-task-role` | No extra permissions needed (Redis via network) |
| `agentbox-worker-task-role` | S3 read/write to the git bucket |

### 6. CloudWatch Log Groups

```bash
aws logs create-log-group --log-group-name /ecs/agentbox-orchestrator
aws logs create-log-group --log-group-name /ecs/agentbox-worker
```

### 7. VPC and Security Groups

| Security Group | Inbound | Outbound |
|---------------|---------|----------|
| Orchestrator SG | 8000 from ALB | Redis + workers |
| Worker SG | 8000 from orchestrator SG | S3 + internet |

## Build and push images

```bash
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com

# Orchestrator
docker build -f Dockerfile.orchestrator \
  -t ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/agentbox-orchestrator:latest .
docker push ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/agentbox-orchestrator:latest

# Worker
docker build -f Dockerfile.worker \
  -t ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/agentbox-worker:latest .
docker push ${AWS_ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/agentbox-worker:latest
```

## Register task definitions

Task definitions are in `deploy/`:

```bash
aws ecs register-task-definition \
  --cli-input-json file://deploy/orchestrator-task-definition.json

aws ecs register-task-definition \
  --cli-input-json file://deploy/worker-task-definition.json
```

Replace `${AWS_ACCOUNT_ID}` in the task definition files with your actual
account ID before registering.

## Create and update services

```bash
# Create cluster (first time)
aws ecs create-cluster --cluster-name agentbox

# Create services (first time)
aws ecs create-service \
  --cluster agentbox \
  --service-name orchestrator \
  --task-definition agentbox-orchestrator \
  --desired-count 2 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-xxx],assignPublicIp=DISABLED}"

aws ecs create-service \
  --cluster agentbox \
  --service-name worker \
  --task-definition agentbox-worker \
  --desired-count 2 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-xxx],assignPublicIp=DISABLED}"

# Update existing services (redeploy)
aws ecs update-service --cluster agentbox --service orchestrator \
  --task-definition agentbox-orchestrator --force-new-deployment
aws ecs update-service --cluster agentbox --service worker \
  --task-definition agentbox-worker --force-new-deployment
```

## Worker auto-registration

Workers self-register with the orchestrator on startup via
`AGENTBOX_ORCHESTRATOR_URL`. In Fargate with `awsvpc` networking, each task
gets a private IP. Options for service discovery:

- **ECS Service Connect** — stable DNS names via Cloud Map
- **Task private IP** — works if orchestrator can reach workers on the same VPC
- **Cloud Map** — register task IPs in Route 53 private hosted zone

The heartbeat loop retries registration every 15s. If the orchestrator is
unavailable at startup, workers will register once it becomes reachable.

## Health checks

| Service | Endpoint | Interval | Retries |
|---------|----------|----------|---------|
| Orchestrator | `GET /health` | 30s | 3 |
| Worker | `GET /internal/health` | 30s | 3 |

Workers return 503 after 5 consecutive heartbeat failures (~75s), triggering
ECS task replacement.

## Notes

- Worker needs `/dev/shm` (2 GB) for Chromium — configured via
  `linuxParameters.sharedMemorySize` in the task definition
- Worker `startPeriod` is 30s (Xvfb + Chromium startup time)
- Orchestrator is stateless — scale horizontally behind ALB
- Workers are stateful (sandboxes live in memory) — scale by adding tasks,
  not replacing existing ones

## See also

- [Deployment overview](deployment.md) — all deployment modes
- [Scaling](../operations/scaling.md) — orchestrator + worker scaling
- [Configuration](../reference/config.md) — environment variables
