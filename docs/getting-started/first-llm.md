# Configuring Your First LLM

Alberto is model-agnostic. You can connect local inference servers ([Ollama](https://ollama.ai), [vLLM](https://github.com/vllm-project/vllm)), or remote proprietary providers (OpenAI, Anthropic Claude, Google Gemini).

![Models and Providers](../assets/screenshots/settings/models-providers.png){: .doc-screenshot }
<p class="doc-caption">Figure 2.3: Models & Providers settings panel with local model discovery and provider credentials.</p>

---

## 1. Option A: Local Ollama (Recommended for Privacy)

Running models locally with Ollama ensures zero data egress from your network.

### Step 1: Ensure Ollama is Running

Pull a recommended model on your host machine:

```bash
# Recommended general-purpose model
ollama pull llama3.2:3b

# Recommended coding & reasoning model
ollama pull qwen2.5-coder:7b
```

Verify Ollama is responding:
```bash
curl http://localhost:11434/api/tags
```

### Step 2: Configure Ollama in Alberto

1. In the Alberto console, navigate to **Settings** (bottom of the sidebar).
2. Under the **Models & Providers** tab:
   - Ensure the Ollama endpoint URL is set to `http://127.0.0.1:11434` (or `http://host.docker.internal:11434` if running in Docker).
   - Click **Discover Models**. Alberto queries `/api/tags` and populates the local model catalog.
3. Select `ollama:llama3.2:3b` as your **Default Project Model**.
4. Click **Save Settings**.

---

## 2. Option B: Cloud Providers (OpenAI, Anthropic, Gemini)

If you prefer cloud models with higher parameter capacity, configure your API keys.

### Configuring Cloud Credentials

1. Open **Settings &rarr; Models & Providers**.
2. Scroll to the **Cloud Providers** section:
    - **OpenAI:** Enter your API key (`sk-proj-DEMO...`). Alberto registers models such as `gpt-4o` and `gpt-4o-mini`.
    - **Anthropic:** Enter your API key (`sk-ant-api03-DEMO...`). Alberto registers models such as `claude-3-5-sonnet-20241022` and `claude-3-5-haiku`.
    - **Google Gemini:** Enter your API key (`AIzaSyDEMO...`). Alberto registers `gemini-1.5-pro` and `gemini-2.0-flash`.
3. Set your preferred default model (e.g. `openai:gpt-4o-mini`).
4. Click **Save Settings**.

---

## 3. Verifying Model Assignment

To verify that the model is functioning properly:

1. Click on **Assistant** or **Home** in the sidebar.
2. In the top-right model dropdown of the chat view, confirm your newly registered model appears.
3. Send a test prompt:
   ```text
   Hello! State your model name and available tools.
   ```
4. Observe the streaming response.
