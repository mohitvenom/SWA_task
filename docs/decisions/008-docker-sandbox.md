# 008 - Docker Sandbox Subsystem

## Context
In Phase 8, ForgeAI required a secure execution environment to run commands (like tests, linters, or builds) against an AI-modified repository. Running untrusted LLM-generated commands directly on the host system is unacceptable due to security risks, including arbitrary code execution, host filesystem modification, and resource exhaustion.

## Decision
We implemented a `SandboxManager` abstraction backed by a disposable Docker container implementation (`DockerSandboxManager` and `DockerSandbox`).
- **Dependency Choice**: We used Python's native `asyncio.create_subprocess_exec` to invoke the local `docker` CLI. This avoids adding a complex, blocking third-party dependency (`docker-py`) while guaranteeing true async execution and minimal coupling.
- **Security Defaults**:
  - `network_enabled=False` by default to prevent data exfiltration or reverse shells.
  - `--security-opt=no-new-privileges` and `--cap-drop=ALL` are applied to prevent privilege escalation.
  - Containers do not use privileged mode and do not mount the host Docker socket.
  - Only the explicit task workspace root is mounted into the container as a volume.
- **Resource Constraints**:
  - CPU and memory limits are strictly applied via Docker flags.
  - Execution timeouts are enforced by asyncio `wait_for`.
  - Output bytes (stdout/stderr) are explicitly bounded and truncated by the Python stream readers to prevent memory exhaustion attacks.
- **Disposability**: Sandboxes are created for a task and aggressively destroyed afterward.

## Rationale
- **Isolation**: Docker provides a standard, understood layer of isolation. While container breakout vulnerabilities exist, it significantly raises the barrier to entry compared to direct host execution.
- **Portability**: Interacting via the CLI makes the sandbox logic easily portable and debuggable.
- **Defense in Depth**: We apply multiple layers of limits (Docker daemon limits + Python-level timeouts/stream truncations) so that a failure in one layer doesn't bring down the orchestrator.

## Consequences
- We now have the foundational infrastructure to allow agents to safely run tests or commands.
- The system must have the Docker daemon running to utilize the sandbox, though the application will still start and run unit tests cleanly without it.
- Developers must configure sensible defaults for their local environment (e.g., `FORGEAI_SANDBOX_CPU_LIMIT`).

## Limitations and Future Considerations
- Docker is not a perfect security boundary for multi-tenant hostile workloads (e.g., gVisor or Firecracker VMs offer stronger isolation). For local/single-tenant AI agents, it is sufficient.
- The UID/GID mapping between the host workspace and the container requires careful handling on POSIX systems to avoid permission denied errors when modifying files.
