# ForgeAI

ForgeAI is an autonomous software engineering agent capable of taking a natural-language engineering task, planning the implementation, executing it within a secure sandbox, running tests, and submitting a GitHub pull request.

**Note: This project is currently in Phase 14.**
Phase 14 introduces the Test Strategy layer to design structured, automated test specifications mapped directly to user acceptance criteria. The autonomous agents, LLM integrations, and sandbox capabilities are partially implemented.

## Architecture Overview
The project is built as a modular monolith using Python 3.12+, FastAPI, and Pydantic.
See [Architecture Documentation](docs/architecture.md) for more details.

## Local Setup

1. **Create and activate a virtual environment**:
   ```bash
   python -m venv venv
   source venv/Scripts/activate  # On Windows
   ```

2. **Install dependencies**:
   ```bash
   pip install -e .[dev]
   ```

3. **Environment variables**:
   Copy the example config:
   ```bash
   cp .env.example .env
   ```

## Running the API

Start the FastAPI application locally:
```bash
uvicorn forgeai.api.main:app --reload
```
The API will be available at `http://127.0.0.1:8000`. You can check the health endpoint at `http://127.0.0.1:8000/health`.

## Development Commands

- **Run tests**:
  ```bash
  pytest
  ```

- **Lint code**:
  ```bash
  ruff check .
  ```

- **Type checking**:
  ```bash
  mypy .
  ```
