# Alberto Release & Operations Manual

This document provides operational instructions and reference details for the Alberto release pipeline, quality gates, and container distribution.

---

## 1. Versioning Conventions

Alberto strictly follows [Semantic Versioning 2.0.0](https://semver.org/):

- **Format:** `MAJOR.MINOR.PATCH` (e.g. `0.1.0`)
  - **`MAJOR`:** Incompatible breaking changes or fundamental architectural shifts.
  - **`MINOR`:** Backward-compatible features, new agent capabilities, or significant non-breaking improvements.
  - **`PATCH`:** Backward-compatible bug fixes, performance improvements, and security patches.
- **Git Release Tags:** Prefixed with `v`, matching the exact semantic version (e.g., `v0.1.0`, `v0.2.0`, `v1.0.0`).

---

## 2. Canonical Version Management (`version.json`)

`version.json` at the repository root is the **single source of truth** for Alberto's release version:

```json
{
  "version": "0.1.0",
  "tag": "v0.1.0"
}
```

### Invariants & Rules

1. Normal development commits **never** alter `version.json`.
2. Only `./release.sh` modifies `version.json` upon passing all quality gates.
3. `version` and `tag` must remain strictly consistent (`tag == "v" + version`).
4. Backend runtime dynamically resolves this version via `alberto.__version__` and exposes it via `/v1/meta/version` and `/readyz`.

---

## 3. Local Release Automation (`release.sh`)

`./release.sh` is the single supported entry point for creating official releases.

### Usage

```bash
# Patch release (e.g. 0.1.0 -> 0.1.1)
./release.sh patch

# Minor release (e.g. 0.1.0 -> 0.2.0)
./release.sh minor

# Major release (e.g. 0.1.0 -> 1.0.0)
./release.sh major

# Dry-run validation (simulates release without making any changes)
./release.sh patch --dry-run
```

### Preflight Safeguards

Before modifying any file, `./release.sh` verifies:
1. **Branch Restriction:** Must be executed on the `master` branch. Detached HEAD and other branches are rejected immediately.
2. **Working Tree Status:** Uncommitted files (modified, untracked, or staged) are permitted. If present, they are reported and will be validated and included in the release commit.
3. **Remote Synchronization:** Remote `origin` must exist, and local `master` must not be behind `origin/master`.
4. **Tag Availability:** The proposed release tag must not exist locally or on `origin`.
5. **Quality Verification:** Executes `./tests/check.sh` completely over the working tree before touching `version.json`.

### Release Execution Sequence

When all checks pass:
1. Calculates the next semantic version.
2. Updates `version.json`.
3. Stages all changes (`git add -A`), including `version.json` and any uncommitted workspace changes.
4. Creates an annotated Git commit: `chore(release): vX.Y.Z`.
5. Creates an annotated Git tag: `vX.Y.Z`.
6. Executes an atomic push of branch and tag to `origin`: `git push --atomic origin master vX.Y.Z`.

---

## 4. Quality Gate Hierarchy (`tests/`)

Alberto's quality checks are modular and reusable across local workstations and CI:

```text
tests/
├── lint.sh      # Ruff (backend) + tsc --noEmit & ESLint (frontend)
├── run.sh       # Pytest (backend, 596 tests) + Vitest (frontend)
└── check.sh     # Sequential runner: lint.sh -> run.sh -> Next.js build
```

Run the complete gate locally at any time:

```bash
./tests/check.sh
```

---

## 5. CI/CD Architecture (GitHub Actions)

Alberto separates continuous integration and release delivery into two dedicated pipelines to eliminate redundant concurrent runs:

### 1. Continuous Integration (`.github/workflows/ci.yml`)

- **Trigger:** Pushes to branches and pull requests.
- **Deduplication:** Automatically skips commits with message starting with `chore(release):` since the release pipeline will run on the tag.
- **Workflow:** Runs `./tests/check.sh` in a clean Ubuntu runner. Does NOT build or publish Docker images.

### 2. Release & Publish Pipeline (`.github/workflows/release.yml`)

- **Trigger:** Strictly triggered by version tags matching `v[0-9]+.[0-9]+.[0-9]+*`.
- **Workflow:**
  1. **Quality Gate:** Re-executes `./tests/check.sh`.
  2. **Independent CI Verification:**
     - Validates semver tag syntax.
     - Verifies `tag` in `version.json` matches git tag.
     - Verifies tagged commit is an ancestor of `master`.
     - Validates that the git tag is an annotated tag.
  3. **Docker Build:** Builds unified multi-stage Docker image with Buildx caching.
  4. **Container Smoke Testing:**
     - Starts container with mounted test volume.
     - Probes FastAPI readiness (`/readyz`).
     - Verifies Next.js frontend responds (`:3000`).
     - Verifies `/data` persistent structure initialization.
     - Tests graceful container termination (`SIGTERM`).
  5. **GHCR Publishing:**
     - Publishes to `ghcr.io/<owner>/alberto:vX.Y.Z`, `latest`, and `sha-<commit>`.

---

## 6. Single Docker Image Architecture

Alberto is packaged as **ONE** unified container image containing both FastAPI backend and Next.js frontend.

### Exposed Ports
- `3000`: Web UI console (Next.js server-side proxies `/api/alberto/*` to backend).
- `8000`: Direct FastAPI backend API and documentation (`/docs`, `/readyz`).

### Persistent Storage (`/data`)
All persistent state must be mapped to `/data`:
- `/data/db/` - SQLite application databases and checkpointers.
- `/data/chroma/` - ChromaDB persistent vector collections.
- `/data/memory/` - Long-term agent memory markdown files.
- `/data/logs/` - Execution and operational logs.
- `/data/config/` - Runtime configuration overrides.

### Building the Docker Image Locally

Build context must be repository root:

```bash
docker build -f docker/Dockerfile -t alberto:latest .
```

### Pull and Run Commands

Pulling the published image:

```bash
docker pull ghcr.io/oksbwn/alberto:v0.1.0
```

Running with Docker Compose:

```bash
docker compose up -d
```

Running directly with Docker:

```bash
docker run -d \
  --name alberto \
  -p 3000:3000 \
  -p 8000:8000 \
  -v alberto_data:/data \
  -e ALBERTO_JWT_SECRET="your-secure-random-32-character-secret" \
  -e OPENAI_API_KEY="sk-..." \
  ghcr.io/oksbwn/alberto:v0.1.0
```

---

## 7. Rollback Procedure

Because Alberto utilizes semantic versioned container tags and external persistent data:

1. Stop the active container:
   ```bash
   docker stop alberto && docker rm alberto
   ```
2. Pull the desired previous validated release tag:
   ```bash
   docker pull ghcr.io/oksbwn/alberto:v0.1.0
   ```
3. Start the container with the existing `/data` mount:
   ```bash
   docker run -d \
     --name alberto \
     -p 3000:3000 \
     -p 8000:8000 \
     -v alberto_data:/data \
     ghcr.io/oksbwn/alberto:v0.1.0
   ```
4. Verify health:
   ```bash
   curl http://localhost:8000/readyz
   ```

---

## 8. Common Release Failures & Recovery

| Failure Scenario | Root Cause | Recovery Action |
|---|---|---|
| `Branch changed unexpectedly / not master` | Attempted release on feature or detached branch. | Switch to master (`git checkout master`), pull latest, and retry. |
| `Local master is not synchronized` | Commits exist locally or remotely that are unmerged. | Run `git pull origin master` or resolve diverge before releasing. |
| `Quality checks failed in tests/check.sh` | Lint or test failure. | Fix code issue locally, run `./tests/check.sh` until green, then retry. |
| `Tag already exists` | Version was already tagged. | Run with higher increment (`minor` or `patch`) or check existing tags. |
| `Atomic push rejected by remote` | Remote branch protection or partial network rejection. | Follow safe fallback instructions output by `release.sh`. |
