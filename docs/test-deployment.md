# SCRUM-33 — Test deployment

## Goal
- A test page is reachable using a URL.
- Deployments happen automatically when a PR is merged to `main`.

## Temporary scope
This setup publishes a **placeholder/smoke-test page only**, not the real BizPartnerCheck app. It deliberately does not alter the team's current PostgreSQL Compose file or add application features.

## Requirements
- A Linux server or VM reachable by GitHub Actions (SSH port 22), with Docker Engine + Docker Compose plugin installed.
- SSH access for a deployment account that can run `docker compose`.
- Inbound TCP port 8080 (or configured `TEST_HTTP_PORT`) allowed from the reviewer. A domain and TLS are recommended for later stages.
- Organization/repository administrator to configure the GitHub Actions secrets below.

## Secrets (GitHub → repository Settings → Secrets and variables → Actions)
- `TEST_HOST`: hostname or IP of the VM
- `TEST_USER`: SSH deployment user
- `TEST_SSH_PRIVATE_KEY`: SSH private key of that user (do not commit)
- `TEST_SSH_HOST_KEY`: verified SSH host key line for the VM (from trusted admin; don't blindly accept an unverified scan)
- `TEST_URL`: e.g., `http://<VM_HOST>:8080/`

## Deployment behavior
On every push to `main` and on manual `workflow_dispatch`:
1. Validate `infra/test/compose.yml`.
2. Copy smoke-test files to the VM using SSH.
3. Run Docker Compose remotely.
4. Request `TEST_URL` and fail if the page is not reachable.

## Local smoke test (needs Docker)
From the repository root:
```sh
docker compose -f infra/test/compose.yml up -d
```
Open http://localhost:8080/ and verify the placeholder appears.
Stop with:
```sh
docker compose -f infra/test/compose.yml down
```

## Acceptance checklist
- [ ] GitHub Actions deployment workflow succeeds on `main`.
- [ ] `TEST_URL` loads from another device/network.
- [ ] Change placeholder text in a feature branch, merge PR into `main`, verify the updated text appears at `TEST_URL` automatically.

## Next phase
Replace the placeholder with built frontend/backend containers under the agreed FastAPI + React + Docker Compose architecture; add domain and HTTPS with Caddy. Coordinate with other owners before modifying shared Compose files.
