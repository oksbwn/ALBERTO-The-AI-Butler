# Real-World Workflow Examples

This section walks through three verified production workflow examples built with Alberto Automate.

---

## Example 1: Daily Intelligence Briefing

Automatically scans ingested news, queries local vector knowledge, summarizes key developments, and sends a formatted briefing to Telegram every weekday at 08:00 AM.

```mermaid
graph LR
    Cron[Cron: 0 8 * * 1-5] --> Fetch[Tool: Brave Search / RSS]
    Fetch --> VectorSearch[Tool: Search Local Documents]
    VectorSearch --> SummarizeAgent[Agent: Intelligence Analyst]
    SummarizeAgent --> FormatMD[Deterministic: Markdown Format]
    FormatMD --> Telegram[Channel: Send Telegram Message]
```

### Node Configuration:
1. **Cron Trigger:** `0 8 * * 1-5` (Runs Monday through Friday at 08:00 AM).
2. **Tool Node (`knowledge_search`):** Query: `"Project updates AND pending reviews"`, limit: `5`.
3. **Agent Node (`intelligence_analyst`):**
   - System Prompt: *"Synthesize the retrieved project notes and news into a 3-bullet morning briefing."*
4. **Channel Delivery Node:** Target: Telegram Bot (`telegram:send_message`), Chat ID: `{{user.telegram_chat_id}}`.

---

## Example 2: Autonomous Pull Request Code Auditor

Triggered via GitHub webhook on new pull requests, analyzes changed files, runs security checks, and posts a review comment.

```mermaid
graph LR
    Webhook[Webhook: GitHub PR Opened] --> Filter{Check: Target == 'main'}
    Filter -->|Yes| GitDiff[Tool: Git MCP Fetch Diff]
    GitDiff --> CodeAuditor[Agent: Senior Code Auditor]
    CodeAuditor --> EvalGate{Evaluator: Score >= 8/10?}
    EvalGate -->|Yes| PostApproval[Tool: GitHub API Post Review]
    EvalGate -->|No| RequestChanges[Tool: GitHub API Request Changes]
```

### Key Safety Gates:
- The `GitHub API Post Review` tool is rated `destructive`—requiring human approval before Alberto submits public comments on external repositories.

---

## Example 3: Smart Home Anomaly Detection & Alert

Monitors Home Assistant sensor webhooks, evaluates energy consumption anomalies, and asks for confirmation before toggling devices.

```mermaid
graph LR
    SensorHook[Webhook: Home Assistant] --> ThresholdCheck{Power > 3000W?}
    ThresholdCheck -->|Yes| DiagnosisAgent[Agent: Home Automation Butler]
    DiagnosisAgent --> ApprovalGate[HITL: Confirm Appliance Shutdown]
    ApprovalGate -->|Approved| SwitchOff[Tool: HA Turn Off Switch]
    ApprovalGate -->|Denied| LogEvent[Tool: Record Log]
```
