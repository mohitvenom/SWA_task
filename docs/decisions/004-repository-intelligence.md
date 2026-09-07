# 004 - Repository Intelligence

## Context
In Phase 4, ForgeAI required the ability to scan and understand the structure, languages, and dependencies of a software repository before any planning or modifications occur. The agent must receive a high-fidelity, deterministic view of the codebase that ignores irrelevant files and extracts useful structural information (like classes, functions, and entry points).

## Decision
We implemented a deterministic, AST-based repository scanner (`RepositoryScanner`) rather than relying on LLM-based full-repository summarization or embeddings/vector databases. 
- **File Ignore Logic**: Uses `pathspec` to read `.gitignore` and enforces hardcoded rules against `.git`, virtual environments, and `.env` files.
- **Language Detection**: Simple, lightweight extension-to-language mappings.
- **AST Parsing**: For Python files, uses the built-in `ast` module to extract classes, functions, async functions, imports, and heuristics for test and entry point detection.
- **Output**: Generates a strongly-typed `RepositorySnapshot` containing all deterministic metadata.

## Rationale
- **Determinism**: The same codebase yields the exact same snapshot every time, which is critical for reproducible agent debugging and evaluation.
- **Performance & Cost**: AST parsing and file-walking locally costs $0 and runs in milliseconds, compared to embedding an entire repository or sending thousands of files to an LLM context window.
- **Security**: Explicitly bypassing `.env` and avoiding code execution (e.g. `import module`) ensures that malicious or untrusted repositories don't leak secrets or execute arbitrary code during the scan phase.

## Consequences
- We must maintain language-specific AST analyzers. Currently, only Python is supported for structural extraction. Other languages will only get basic file-level metadata.
- We added `pathspec` as a standard dependency to properly mimic `.gitignore` behavior without re-inventing complex globbing logic.
