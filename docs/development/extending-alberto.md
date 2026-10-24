# Extending Alberto

This guide walks through extending Alberto by implementing custom built-in tools, adding new REST API endpoints, and registering new workflow canvas node types.

---

## 1. Implementing a Custom Built-in Tool

Built-in tools live in `backend/alberto/tools/`.

### Step 1: Define the Tool Function
Create a Python file in `backend/alberto/tools/system_info.py`:

```python
from pydantic import BaseModel, Field
import platform
import psutil

class SystemInfoInput(BaseModel):
    include_memory: bool = Field(default=True, description="Whether to include RAM stats.")

def get_system_diagnostics(include_memory: bool = True) -> dict:
    """Returns local host CPU and memory utilization."""
    data = {
        "os": platform.system(),
        "cpu_percent": psutil.cpu_percent(interval=0.1),
    }
    if include_memory:
        data["ram_percent"] = psutil.virtual_memory().percent
    return data
```

### Step 2: Register in Tool Manager
In `backend/alberto/services/tool_manager.py`:

```python
from alberto.tools.system_info import get_system_diagnostics, SystemInfoInput

register_system_tool(
    name="get_system_diagnostics",
    description="Inspects host CPU and RAM utilization.",
    func=get_system_diagnostics,
    args_schema=SystemInfoInput,
    danger_level="read_only"
)
```

Once registered, any agent or workflow node can execute this tool.

---

## 2. Adding a New FastAPI Router

To expose a new REST endpoint:

1. Create a router file: `backend/alberto/routers/reports.py`:
   ```python
   from fastapi import APIRouter, Depends
   from alberto.deps import get_current_user

   router = APIRouter(prefix="/v1/reports", tags=["reports"])

   @router.get("/summary")
   async def get_summary_report(user = Depends(get_current_user)):
       return {"report_id": "rep_01", "status": "generated"}
   ```
2. Mount the router in `backend/alberto/main.py`:
   ```python
   from alberto.routers import reports
   app.include_router(reports.router)
   ```
3. Run `backend/.venv/Scripts/python.exe docs/scripts/generate_api_reference.py` to automatically refresh documentation for your new endpoint.

---

## 3. Adding a New Workflow Node Type

To introduce a new node type to the visual Automate canvas:

1. **Frontend Type Definition (`frontend/lib/data.ts`):**
   Add metadata to `NODE_META`:
   ```typescript
   custom_formatter: {
     label: "Custom Formatter",
     category: "transform",
     icon: "code",
     color: "var(--accent)"
   }
   ```
2. **Backend Execution Handler (`backend/alberto/nodes/`):**
   Implement the step execution logic:
   ```python
   async def execute_custom_formatter(node_config: dict, state: dict) -> dict:
       input_val = state.get("payload", "")
       return {"formatted_output": f"*** {input_val} ***"}
   ```
3. Register the execution handler in `backend/alberto/services/runs.py`.
