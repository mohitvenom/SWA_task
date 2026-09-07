# 001 - Modular Monolith

## Context
We are establishing the foundational architecture for ForgeAI. We need to decide whether to build the system as a collection of microservices or as a monolithic application.

## Decision
We will build ForgeAI as a **modular monolith** using a single Python codebase, rather than microservices.

## Rationale
- **Simplicity**: Operating, deploying, and debugging a single application is much simpler.
- **Velocity**: Cross-module refactoring in a single codebase is trivial, allowing faster iteration during the early stages.
- **Performance**: Intra-process communication is faster than network calls, ensuring low latency during high-frequency agent actions.
- **Clear Boundaries**: By enforcing strict module boundaries (e.g., enforcing clean dependency rules using typed interfaces), we achieve the same separation of concerns promised by microservices without the operational overhead.
- **Future Migration**: If certain components (like the Sandbox manager) eventually need to scale independently, the modular architecture allows them to be extracted into separate services seamlessly.
