# AWS ECS Fargate + GitHub Actions Deployment Design

Date: 2026-06-19

## 1. Goal

Deploy `open-domain-mcp` to AWS with GitHub Actions CI/CD.

The deployment target is a cost-conscious ECS Fargate environment in `ap-east-2`
serving the FastAPI web dashboard at `https://opendomain.bwtseng.com`.

The repository will contain the application deployment artifacts:

- `Dockerfile`
- `.dockerignore`
- GitHub Actions workflow
- ECS task definition template
- AWS deployment documentation

AWS infrastructure will be created with AWS CLI, not Terraform/CDK. The CLI
commands and resulting resource names will be documented so the environment can
be understood, operated, and removed manually if needed.

## 2. Confirmed Inputs

- AWS Region: `ap-east-2` Asia Pacific (Taipei)
- Domain: `bwtseng.com`
- Hostname: `opendomain.bwtseng.com`
- DNS provider: Route 53 hosted zone for `bwtseng.com`
- TLS: AWS Certificate Manager certificate for `opendomain.bwtseng.com`
- Compute: ECS Fargate
- Image registry: ECR
- Vector data persistence: EFS mounted into the ECS task
- Graph database: RDS MariaDB
- GitHub repository: `b5336789/open-domain-mcp`
- GitHub Actions AWS auth: OIDC IAM role, no long-lived AWS access key
- Cost posture: public subnets for ALB and ECS tasks, no NAT Gateway

## 3. Application Runtime Requirements

The app is a Python package with a React/Vite dashboard.

Frontend build output is written into the Python package:

```text
web/ npm run build -> src/opendomainmcp/api/static
```

The container runs the existing console script:

```text
opendomainmcp-web
```

Runtime environment:

- `ODM_WEB_HOST=0.0.0.0`
- `ODM_WEB_PORT=8000`
- `ODM_DATA_DIR=/data/opendomain`
- `ODM_GRAPH_DB_HOST=<rds endpoint>`
- `ODM_GRAPH_DB_PORT=3306`
- `ODM_GRAPH_DB_USER=opendomain`
- `ODM_GRAPH_DB_PASSWORD=<from Secrets Manager>`
- `ODM_GRAPH_DB_NAME=opendomain_graph`

Optional model/API settings remain environment-driven:

- `ANTHROPIC_API_KEY`
- `ANTHROPIC_BASE_URL`
- `OPENAI_API_KEY`
- `VOYAGE_API_KEY`

Credentials must not be committed to the repository.

## 4. AWS Architecture

The target architecture:

- VPC dedicated to this app.
- Two public subnets in different availability zones.
- Internet Gateway and public route table.
- Public Application Load Balancer.
- ALB listener on port `80` redirects to `443`.
- ALB listener on port `443` uses an ACM certificate.
- Target group forwards to ECS tasks on container port `8000`.
- ECS Fargate service runs `opendomainmcp-web`.
- ECS tasks receive public IPs to avoid NAT Gateway cost.
- EFS persists Chroma/vector data and runtime settings under `/data/opendomain`.
- RDS MariaDB stores the entity graph.
- CloudWatch Logs receives container logs.
- Route 53 alias maps `opendomain.bwtseng.com` to the ALB.

Security groups:

- ALB security group allows public inbound `80` and `443`.
- ECS security group allows inbound `8000` only from the ALB security group.
- RDS security group allows inbound `3306` only from the ECS security group.
- EFS security group allows inbound `2049` only from the ECS security group.
- ECS outbound remains open so the app can call model APIs and download local
  model artifacts when required.

Tradeoff: ECS tasks are placed in public subnets and assigned public IPs. This
avoids NAT Gateway cost. The ALB remains the only intended public entry point
because the ECS security group accepts app traffic only from the ALB security
group.

## 5. AWS Resource Names

Use this prefix unless an existing AWS naming collision requires a suffix:

```text
open-domain-mcp
```

Resource names:

- VPC: `open-domain-mcp-vpc`
- ECR repository: `open-domain-mcp`
- ECS cluster: `open-domain-mcp`
- ECS service: `open-domain-mcp-web`
- ALB: `open-domain-mcp-alb`
- Target group: `open-domain-mcp-web`
- EFS: tag `Name=open-domain-mcp-efs`
- RDS DB instance: `open-domain-mcp-db`
- RDS DB name: `opendomain_graph`
- RDS app user: `opendomain`
- CloudWatch log group: `/ecs/open-domain-mcp-web`
- Secrets Manager RDS password: `open-domain-mcp/rds/password`
- GitHub OIDC deploy role: `open-domain-mcp-github-deploy`

Deletion protection should be enabled for RDS. A final snapshot should be kept
unless the user explicitly requests disposable infrastructure.

## 6. Repository Artifacts

### Dockerfile

The Dockerfile will use a multi-stage build:

1. Node build stage:
   - Work in `web/`.
   - Run `npm ci`.
   - Run `npm run build`.
   - The Vite config writes files to `src/opendomainmcp/api/static`.
2. Python runtime stage:
   - Use Python 3.11 or newer.
   - Copy the source tree after frontend static assets exist.
   - Install the package.
   - Expose port `8000`.
   - Start `opendomainmcp-web`.

The image should not include `.opendomain`, local virtualenvs, git metadata,
Node modules from the host, or test caches.

### GitHub Actions Workflow

Create `.github/workflows/deploy-aws.yml`.

Triggers:

- `push` to `main`
- `workflow_dispatch`

Workflow permissions:

- `id-token: write`
- `contents: read`

Flow:

1. Check out source.
2. Set up Python 3.11.
3. Install `.[dev]`.
4. Run `pytest`.
5. Set up Node.
6. Run `npm ci` and `npm run build` in `web/`.
7. Configure AWS credentials through OIDC.
8. Log in to ECR.
9. Build Docker image.
10. Push image tags:
    - commit SHA
    - `latest`
11. Render ECS task definition with the new image.
12. Deploy ECS service.
13. Wait for service stability.

GitHub variables:

- `AWS_REGION=ap-east-2`
- `AWS_ROLE_ARN=<created deploy role arn>`
- `ECR_REPOSITORY=open-domain-mcp`
- `ECS_CLUSTER=open-domain-mcp`
- `ECS_SERVICE=open-domain-mcp-web`
- `ECS_TASK_DEFINITION=deploy/aws/task-definition.json`
- `ECS_CONTAINER_NAME=opendomainmcp-web`

### ECS Task Definition Template

Create `deploy/aws/task-definition.json`.

It will define:

- Fargate compatibility.
- `awsvpc` network mode.
- CPU and memory sized conservatively for the first deployment.
- Container name `opendomainmcp-web`.
- Container port `8000`.
- CloudWatch log configuration.
- EFS volume.
- Mount point `/data/opendomain`.
- Environment variables for non-secret runtime settings.
- ECS secrets for RDS password and optional API keys.

### Deployment Documentation

Create `docs/deploy/aws-ecs-fargate.md`.

It will document:

- Prerequisites.
- AWS CLI provisioning commands.
- Created resource IDs and names.
- GitHub repository variables/secrets.
- DNS and ACM behavior.
- First deploy flow.
- Health checks.
- Rollback.
- Manual teardown order.

## 7. AWS Provisioning Flow

Provisioning will be done with AWS CLI in `ap-east-2`.

Steps:

1. Verify caller identity and region access.
2. Verify the Route 53 hosted zone for `bwtseng.com`.
3. Request an ACM certificate for `opendomain.bwtseng.com`.
4. Create the ACM DNS validation record in Route 53.
5. Wait for the certificate to become `ISSUED`.
6. Create VPC, Internet Gateway, route table, and two public subnets.
7. Create security groups.
8. Create ECR repository.
9. Create EFS file system, access point, and mount targets.
10. Create the RDS subnet group.
11. Create the RDS MariaDB instance.
12. Store the generated RDS password in Secrets Manager.
13. Create ECS task execution role and task role.
14. Create GitHub OIDC IAM role restricted to `b5336789/open-domain-mcp`.
15. Create CloudWatch log group.
16. Build and push an initial image from the local workspace.
17. Register the ECS task definition.
18. Create the ALB, target group, HTTP redirect listener, and HTTPS listener.
19. Create ECS service behind the target group.
20. Create Route 53 alias `opendomain.bwtseng.com` pointing to the ALB.
21. Verify health and first page/API response.

The local initial image push is needed so ECS has an image to start before the
first GitHub Actions deployment runs.

## 8. Health Checks And Verification

ALB target group health check:

```text
GET /api/health
```

Expected response:

```json
{"status":"ok"}
```

Verification after provisioning:

- ECR repository contains an initial image.
- ECS service reaches stable state.
- ALB target group reports a healthy target.
- `https://opendomain.bwtseng.com/api/health` returns status `ok`.
- Route 53 alias resolves to the ALB.
- GitHub Actions can assume the OIDC deploy role.
- A manual `workflow_dispatch` deploy succeeds.

## 9. Rollback

Application rollback:

- Redeploy an earlier ECS task definition revision, or
- Update the service to an earlier ECR image tag.

Infrastructure rollback:

- Because infrastructure is not managed by IaC, teardown is manual and must be
  documented in reverse dependency order.

Data rollback:

- RDS deletion protection is enabled.
- RDS final snapshot is kept unless explicitly disabled.
- EFS is not deleted during normal app rollback.

## 10. Error Handling And Operational Notes

The application fails loudly when it cannot connect to MariaDB during
`build_context()`. This is expected and useful: ECS tasks should fail health
checks if RDS is unavailable or credentials are wrong.

The first startup may download local embedding model artifacts if the local
embedder is used. ECS outbound access is therefore required.

Secrets are injected at runtime through ECS/Secrets Manager, not stored in the
task definition file as plaintext.

If `ap-east-2` lacks an expected service capability for this account, the
implementation should stop and report the exact AWS CLI failure rather than
silently switching regions.

## 11. Out Of Scope

- Terraform/CDK/CloudFormation management of infrastructure.
- Cloud vector database migration.
- Multi-environment staging/production promotion.
- Autoscaling policy tuning beyond a conservative initial ECS service.
- Application authentication or user login.
- CI checks beyond existing Python tests and frontend build.
