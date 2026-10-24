# Contributing Guidelines & Coding Standards

We welcome contributions to Alberto. To ensure high code quality, predictability, and maintainability across both Python and TypeScript codebases, all contributors are expected to follow these guidelines.

---

## 1. Engineering Principles

- **Simplicity First:** Write the minimum code required to solve the problem. Avoid speculative abstractions or premature generalizations.
- **Surgical Edits:** Touch only what must be changed. Do not reformat unrelated adjacent code.
- **No Unvetted Dependencies:** Avoid adding new packages to `requirements.txt` or `package.json` when standard library or existing dependencies can achieve the goal.
- **Verified Implementation:** Every bug fix or feature addition must include a runnable test reproducing the issue or verifying the capability.

---

## 2. Python Backend Standards

- **Formatter & Linter:** `ruff` is used for linting and code formatting:
  ```bash
  ruff check backend/
  ruff format backend/
  ```
- **Type Annotations:** Full type annotations are required. Validate with `pyright`:
  ```bash
  pyright backend/alberto
  ```
- **Pydantic v2:** All API request bodies and tool parameters must use Pydantic v2 models with field descriptions.

---

## 3. TypeScript & Frontend Standards

- **Next.js & React:** Use React 18 functional components with React Hooks.
- **Styling:** Vanilla CSS utilizing the established design tokens (`var(--bg-1)`, `var(--accent)`, `var(--fg-0)`). Avoid arbitrary ad-hoc inline styles when tokens exist.
- **Testing:** New interactive components should include Vitest tests in `frontend/`.

---

## 4. Conventional Commits

Commit messages must follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

- `feat(agents): add structured subagent delegation contract`
- `fix(tools): handle timeouts gracefully in MCP stdio client`
- `docs(api): document OpenAPI schema for /v1/assistant/chat`
- `test(e2e): add Playwright test for workflow canvas zoom`
