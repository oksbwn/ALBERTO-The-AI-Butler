# Creating Your First Specialist Agent

While Alberto's **Master Coordinator** acts as your central assistant, you can create dedicated **Specialist Agents** optimized for specific domains—such as code review, document summarization, home automation, or deep research.

![Agents List](../assets/screenshots/agents/agent-list.png){: .doc-screenshot }
<p class="doc-caption">Figure 2.4: Specialist agent preset management screen.</p>

---

## 1. Anatomy of a Specialist Agent

In Alberto, every agent preset is defined by 5 primary properties:

1. **Identifier & Name:** A unique slug (e.g., `research_specialist`) and display title.
2. **Flavor:** The behavioral archetype:
    - `agent`: Standard ReAct conversational agent.
    - `router`: Deterministic intent classification node.
    - `evaluator`: Grades outputs or enforces compliance before returning results.
3. **Model Binding:** The LLM model powering this agent (e.g., `openai:gpt-4o` or `ollama:llama3.2:3b`). Different agents can use different models depending on cost or privacy requirements.
4. **System Prompt:** Core instructions, persona constraints, and output schema guidelines.
5. **Assigned Tools:** The specific whitelist of tools this specialist is authorized to invoke.

---

## 2. Step-by-Step: Creating a Research Specialist

Let's build a dedicated **Research Specialist** that can search documents and synthesize findings.

### Step 1: Open Agents Screen

1. In the sidebar, expand **Automate** and click **Agents**.
2. Click the **New agent** button in the top right.

### Step 2: Configure the Agent

In the agent configuration editor:

- **Name:** `research_analyst`
- **Flavor:** `agent`
- **Model:** Select your configured model (e.g. `openai:gpt-4o-mini` or `ollama:llama3.2:3b`).
- **System Prompt:**
  ```markdown
  You are Alberto's dedicated Research Analyst.
  Your task is to analyze documents, extract empirical facts, and cite sources.
  Always format citations using bullet points with title and chunk reference.
  Never invent facts that are not backed by retrieved knowledge or verified tools.
  ```

### Step 3: Assign Tools

In the **Tools** section:
1. Check the `knowledge_search` tool (allowing this agent to perform hybrid vector + lexical search).
2. Check the `calculator` tool (for mathematical evaluations).

### Step 4: Save & Test

Click **Save Agent**. Your new agent is immediately available for:
- Manual testing in the **Automate &rarr; Playground**.
- Conversational delegation from the **Master Coordinator**.
- Insertion as an `agent` node in the **Visual Workflow Canvas**.
