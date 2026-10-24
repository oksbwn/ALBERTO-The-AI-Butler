# Event Flow & Streaming Architecture

Alberto delivers conversational responses, execution logs, and workflow status updates using real-time streaming architectures.

---

## 1. Server-Sent Events (SSE) Protocol

Instead of heavy bi-directional WebSockets, Alberto uses standard HTTP **Server-Sent Events (`text/event-stream`)** via `sse-starlette`:

- Operates seamlessly through standard HTTP reverse proxies without special connection-upgrading configurations.
- Automatic browser reconnection handling with last-event-id tracking.
- Lower overhead than WebSocket handshakes for request-response patterns.

### Event Format

Streaming responses emit structured JSON events:

```http
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive

event: token
data: {"content": "Hello", "node": "coordinator"}

event: token
data: {"content": " Alex,", "node": "coordinator"}

event: tool_start
data: {"tool": "weather_get_forecast", "input": {"city": "Berlin"}}

event: tool_end
data: {"tool": "weather_get_forecast", "output": {"temperature_c": 14.2}}

event: done
data: {"session_id": "ses_01j7xyz", "total_tokens": 148, "latency_ms": 620}
```

---

## 2. Asynchronous Background Task Queue

Alberto avoids requiring external Redis or Celery dependencies for task queues by embedding an asynchronous SQLite-backed task queue (`queue.py` and `worker.py`).

### Queue Architecture

```mermaid
graph LR
    API[FastAPI Endpoint] -->|enqueue_job()| SQLiteQueue[(queue.sqlite)]
    Worker[In-Process Worker Loop] -->|poll_and_lock()| SQLiteQueue
    Worker -->|Execute Task| TaskHandler[Task Handlers]
    TaskHandler --> DocumentIngestion[Document Ingestion & Embedding]
    TaskHandler --> MemoryCurator[Autonomous Memory Curator]
    TaskHandler --> ScheduledRuns[Scheduled Workflow Runs]
```

### Guaranteed Delivery & Retries
- **Atomicity:** Tasks are leased using SQLite row-level locks (`SELECT ... UPDATE locked_until = now() + timeout`).
- **Exponential Backoff:** If a task raises an exception, the worker reschedules the task with exponential jitter (`retry_count = retry_count + 1`).
- **Dead-Letter Queue:** After 5 failed attempts, the job transitions to `status = 'failed'` with the full exception stack trace stored in the database for operator review.
