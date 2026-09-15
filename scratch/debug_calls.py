import asyncio
from pathlib import Path
from forgeai.orchestrator import ApplicationOrchestrator
from forgeai.api.main import _build_orchestrator

async def main():
    import logging
    logging.basicConfig(level=logging.INFO)
    orch = _build_orchestrator()
    workspace = Path("scratch/test_workspace")
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / ".git").mkdir(exist_ok=True)
    # mock git slightly to pretend it's clean
    try:
        res = await orch.execute_task("Create a Python file that checks whether a number is even or odd", workspace)
        print("Result:", res)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    asyncio.run(main())
