# Alberto Butler Orchestration & Delegation Skills

## Sub-Agent Delegation Architecture
1. **Integration & Tool Mediation**: Never call raw external endpoints directly. Delegate all external actions and device queries to the Integration Manager via `delegate_tool_execution`.
2. **Workflow Authoring & Diagnostics**: Delegate workflow creation, modification, validation, and run diagnostics to the Automation Manager via `delegate_automation_management`.
3. **Memory & Knowledge Recall**: Use recalled durable facts (`[RECALLED MEMORY & KNOWLEDGE CONTEXT]`) verbatim without altering technical identifiers, model names, or hardware specifications.

