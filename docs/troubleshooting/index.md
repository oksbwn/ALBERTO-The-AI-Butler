# Diagnostic Procedures & Troubleshooting

This section provides operational diagnostic procedures organized by subsystem to help diagnose and resolve runtime errors.

---

## 1. Assistant & Conversation Diagnostics

### Symptom: Chat hangs or model returns empty response.
- **Diagnostics:**
  1. Check backend console logs for timeout or API key errors.
  2. If using Ollama, test connectivity directly:
     ```bash
     curl http://localhost:11434/api/generate -d '{"model": "llama3.2:3b", "prompt": "hi", "stream": false}'
     ```
  3. Verify that your default model in **Settings &rarr; Models & Providers** matches a model present on the host.

### Symptom: "Context window exceeded"
- **Diagnostics:**
  1. The conversation history or retrieved document chunks exceeded the model's context capacity.
  2. In **Settings &rarr; Advanced &rarr; Versioning**, decrease `Conversation History Window` from 50 to 20 turns.
  3. In **Knowledge &rarr; Vector Store**, decrease search retrieval limit from 10 to 4 chunks.

---

## 2. Automate Workflow Diagnostics

### Symptom: Workflow stuck in `interrupted` status.
- **Cause:** A node within the workflow executed a tool rated `destructive` and is awaiting user approval.
- **Resolution:**
  1. Navigate to **Automate &rarr; Workflows** and open the active run.
  2. Review the pending approval dialog and click **Approve** or **Cancel**.
  3. Alternatively, grant automatic approval in **Settings &rarr; Guardrails & Egress** if running in a trusted headless environment.

### Symptom: "Node execution failed: Invalid upstream variable"
- **Cause:** A node template references a variable (e.g. `{{payload.user_id}}`) that was not emitted by the preceding node.
- **Resolution:**
  1. Open the workflow canvas.
  2. Select the failed node in the right inspector.
  3. In the variable picker dropdown, select an available upstream output key.

---

## 3. Database & Concurrency Diagnostics

### Symptom: `sqlite3.OperationalError: database is locked`
- **Cause:** Multiple concurrent writer processes or unfinalized transactions.
- **Resolution:**
  1. Verify WAL mode is enabled:
     ```bash
     sqlite3 data/db/alberto.db "PRAGMA journal_mode;"
     # Should return: wal
     ```
  2. Ensure the SQLite timeout is at least 10000ms in `alberto/db/__init__.py`.

---

## 4. MCP Subprocess Diagnostics

### Symptom: "Failed to connect to MCP server: Command failed"
- **Cause:** The subprocess command (e.g. `npx`, `uvx`) is not installed or not in system `PATH`.
- **Resolution:**
  1. Test running the command manually in your terminal.
  2. Ensure Node.js (`npx`) or Python (`uvx`) is present in the environment running the Alberto backend.
