# Markdown Memory & File Curation

In addition to SQLite and vector indexes, Alberto supports **Markdown Memory** (`backend/alberto/services/markdown_memory.py`). This allows long-term knowledge to be inspected, backed up, and manually edited as plaintext `.md` files.

---

## 1. Directory Structure

Markdown memories are stored under the project data path:

```text
data/projects/{project_id}/memory/
├── profile.md          # Personal user profile, core preferences, and guidelines
├── projects.md         # Active development projects and operational priorities
├── infrastructure.md   # Network layout, server addresses, and smart home IDs
└── scratchpad.md       # Temporary working notes and pending tasks
```

---

## 2. Automatic Curation & File Sync

When conversational facts are committed, Alberto's `MarkdownCurator` formats them into structured Markdown sections:

```markdown
# User Profile: Alex

- **Preferred Language:** Python, TypeScript
- **Timezone:** America/New_York (UTC-5)
- **Role:** Lead Engineer on Alberto AI Butler

## Declared Preferences
- Always generate unit tests alongside new functions.
- Prioritize concise caveman-style technical explanations over marketing prose.
```

### Manual Editing and Two-Way Sync
Because these files are stored directly on the local filesystem, operators can:
1. Open and edit them using any editor (VS Code, Obsidian, Vim).
2. Commit them to private git repositories for version control.
3. Call `/v1/memory/sync` to immediately re-index updated markdown files into vector and graph databases.
