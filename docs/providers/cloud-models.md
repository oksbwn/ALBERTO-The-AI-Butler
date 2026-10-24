# Cloud Models: OpenAI, Anthropic & Gemini

When local hardware constraints or complex reasoning tasks require frontier capabilities, Alberto connects to cloud providers via secure encrypted credential vaults.

---

## 1. Provider Configuration

Configure cloud provider credentials under **Settings &rarr; Models & Providers**:

```ini
# Environment Variable Overrides (optional)
OPENAI_API_KEY=sk-proj-DEMO...
ANTHROPIC_API_KEY=sk-ant-api03-DEMO...
GOOGLE_API_KEY=AIzaSyDEMO...
```

All credentials entered through the UI are encrypted with AES-GCM-256 using the master key at `data/config/master.key` and stored in the SQLite `secrets` table.

---

## 2. Supported Cloud Models

### OpenAI
- `gpt-4o`: Flagship multimodal model with native JSON tool calling.
- `gpt-4o-mini`: High-speed, cost-effective reasoning engine recommended for fast routing.
- `o1-preview` / `o1-mini`: Advanced mathematical and algorithmic reasoning models.

### Anthropic Claude
- `claude-3-5-sonnet-20241022`: Frontier coding and structured extraction capabilities.
- `claude-3-5-haiku-20241022`: Low-latency conversational subagent model.

### Google Gemini
- `gemini-1.5-pro`: Large context window (up to 2,000,000 tokens) suitable for large document analysis.
- `gemini-2.0-flash` / `gemini-1.5-flash`: Real-time streaming conversational models.

---

## 3. Streaming and Fallback Behavior

- **SSE Streaming:** Cloud provider responses are token-streamed directly to the client via Server-Sent Events, keeping Time-To-First-Token (TTFT) under 400ms.
- **Circuit Breaking & Retries:** If a cloud provider encounters rate limiting (`HTTP 429`) or temporary gateway errors (`HTTP 502/503`), Alberto's `tenacity` retry loop retries with exponential backoff (1s, 2s, 4s).
- **Graceful Fallbacks:** If the primary cloud provider is unreachable, Alberto can automatically fall back to a registered local model (e.g. `ollama:llama3.2`) to maintain basic assistant availability.
