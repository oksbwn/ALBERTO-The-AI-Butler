# Local Models: Ollama & vLLM

Alberto is built with a local-first philosophy: running models locally guarantees data privacy, removes recurring API costs, and allows the Butler to function during internet outages.

---

## 1. Setting Up Ollama

[Ollama](https://ollama.ai) is the easiest way to run local models on macOS, Linux, and Windows.

### Installation & Pulling Models

```bash
# Install Ollama (Linux/macOS)
curl -fsSL https://ollama.ai/install.sh | sh

# Pull models
ollama pull llama3.2:3b        # 2.0 GB VRAM requirement (runs on almost any laptop)
ollama pull qwen2.5-coder:7b   # 4.5 GB VRAM requirement (excellent code reasoning)
ollama pull mistral:7b         # 4.1 GB VRAM requirement
```

### Auto-Discovery in Alberto

1. Navigate to **Settings &rarr; Models & Providers**.
2. Enter the Ollama URL: `http://127.0.0.1:11434`.
3. Click **Discover Models**.
4. Alberto queries `GET /api/tags`, automatically detects installed models, context windows, and quantization levels, and registers them in your project catalog.

---

## 2. Setting Up vLLM (High-Throughput Local Inference)

For dedicated Linux GPU servers (NVIDIA RTX 3090, 4090, A100, or Apple Silicon), [vLLM](https://github.com/vllm-project/vllm) provides high concurrency and PagedAttention memory management.

### Starting vLLM Server

```bash
pip install vllm
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3.1-8B-Instruct \
  --port 8000 \
  --gpu-memory-utilization 0.90 \
  --max-model-len 32768
```

### Registering vLLM in Alberto

1. In **Settings &rarr; Models & Providers**, add a new **OpenAI-Compatible** provider.
2. Endpoint URL: `http://<server-ip>:8000/v1`.
3. API Key: `none` (or your chosen bearer token).
4. Model Name: `meta-llama/Llama-3.1-8B-Instruct`.

---

## 3. Performance Tuning & Quantization

To maximize tokens-per-second (TPS) on consumer hardware:

- **GPU Offloading:** Ensure Ollama is configured to offload 100% of layers to your GPU:
  ```bash
  # Check GPU usage during inference
  nvidia-smi  # on NVIDIA
  sudo powermetrics --samplers gpu_power # on macOS
  ```
- **Context Window Sizing:** Keep context windows between 4096 and 8192 tokens for local models unless necessary, as attention memory scales quadratically.
- **Quantization:** Prefer `Q4_K_M` or `Q5_K_M` GGUF quantizations for optimal balance of perplexity and inference speed.
