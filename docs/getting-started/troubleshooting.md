# Troubleshooting Setup & Installation

This document provides diagnostic steps and resolutions for common issues encountered during initial deployment.

---

## 1. Port Collisions (Port 8000 or 3000 In Use)

### Symptom:
`uvicorn` or Next.js fails to bind with `Address already in use` or `EADDRINUSE: address already in use :::3000`.

### Resolution:
Identify and terminate the competing process, or override the port settings.

=== "Linux & macOS"
    ```bash
    # Identify process on port 8000
    lsof -i :8000
    kill -9 <PID>

    # Or override the port
    ALBERTO_PORT=8080 uvicorn alberto.main:app --port 8080
    ```

=== "Windows (PowerShell)"
    ```powershell
    Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in 8000, 3000 }
    # Or start on alternative ports
    $env:PORT="3005"; npm run dev -- -p 3005
    ```

---

## 2. Database Locks & SQLite WAL Issues

### Symptom:
`sqlite3.OperationalError: database is locked` or aiosqlite timeout.

### Resolution:
1. Ensure the SQLite file is on a local filesystem, not a network-mounted drive (e.g., NFS or SMB without POSIX locking).
2. Check if a lingering background process is holding a transaction:
   ```bash
   # Check active database connections
   fuser data/db/alberto.db
   ```
3. Enable WAL checkpointing:
   ```bash
   sqlite3 data/db/alberto.db "PRAGMA journal_mode=WAL;"
   ```

---

## 3. Ollama Connection Failures in Docker

### Symptom:
Alberto reports `Failed to connect to http://127.0.0.1:11434` or `Connection refused`.

### Resolution:
Inside a Docker container, `127.0.0.1` refers to the container itself, not the host machine.
1. Use `http://host.docker.internal:11434` as the Ollama URL.
2. In `docker-compose.yml`, verify `extra_hosts` has `"host.docker.internal:host-gateway"`.
3. Verify that `ALBERTO_EGRESS_ALLOW_PRIVATE_HOSTS` includes `"host.docker.internal"`.
4. On Linux hosts, start Ollama with `OLLAMA_HOST=0.0.0.0:11434`.

---

## 4. Node Module Execution Policy on Windows

### Symptom:
`npm : File C:\Program Files\nodejs\npm.ps1 cannot be loaded because running scripts is disabled on this system.`

### Resolution:
PowerShell blocks unsigned `.ps1` wrapper scripts by default.
1. Use the `.cmd` binaries directly:
   ```powershell
   npm.cmd install
   npm.cmd run dev
   ```
2. Or set execution policy for the current PowerShell process:
   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   ```

---

## 5. ChromaDB Vector Store Ingestion Errors

### Symptom:
FastEmbed model download hangs or Chroma throws dimension mismatch errors.

### Resolution:
1. Ensure write access to `ALBERTO_FASTEMBED_CACHE_DIR` (default: `./data/models/fastembed`).
2. If changing embedding models, drop and recreate the Chroma collection to ensure all vectors have identical dimensional sizes (384 for `bge-small-en-v1.5`).
