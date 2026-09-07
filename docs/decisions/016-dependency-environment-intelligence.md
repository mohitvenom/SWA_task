# 016 — Dependency & Environment Intelligence

## Status
Accepted

## Context
Phases 1–15 built ForgeAI's full pipeline through Task Intelligence, Planning, Test Strategy, Coding, Validation, and Failure Diagnosis. Phase 15 demonstrated an important gap: the `FailureDiagnosisAgent` classifies `ENVIRONMENT_ERROR` as a category, but lacks deterministic, structured knowledge about *why* an environment failure occurred. A `ModuleNotFoundError` during validation is indistinguishable without knowing whether the package is declared, installed, or version-constrained. This leads to false code repair attempts for environment problems.

## Decision
Introduce a read-only **Dependency & Environment Intelligence** layer (Phase 16) comprising:

1. **`DependencyDiscovery`** — a fully deterministic scanner that reads `pyproject.toml`, `requirements*.txt`, `setup.cfg`, and `Pipfile` to extract declared dependencies and detects lockfiles. Uses `importlib.metadata` (stdlib) for installed package inspection and `sys` for runtime facts.
2. **`EnvironmentIntelligenceAgent`** — applies deterministic reconciliation rules first, then optionally passes summarised facts (not raw env values) to an LLM for ambiguous interpretation.
3. **Domain models** — `DependencySnapshot`, `EnvironmentSnapshot`, `EnvironmentDiagnosis`, `DependencyCheckResult`, `EnvironmentFact` — with explicit `is_deterministic` fields separating facts from inferences.

## Why a Separate Concern
Dependency management introduces distinct concerns from application code:
- **Provenance**: a dependency declared in `pyproject.toml` and another in `requirements.txt` are different facts from different sources and must remain distinguishable.
- **State space**: DECLARED ≠ INSTALLED ≠ LOCKED. Each transition involves a separate authority.
- **Supply-chain safety**: recommending or auto-installing unvetted packages is a security risk requiring explicit authorisation.
- **Determinism**: most dependency facts are recoverable without LLM inference — version strings, file presence, Python version.

## Why Deterministic Discovery is Preferred
LLMs cannot reliably read filesystem state. Facts like "requests==2.28 is declared in pyproject.toml" and "requests is not installed" are deterministically verifiable. Asking the LLM to determine these facts introduces hallucination risk and violates the ForgeAI invariant: *LLMs propose; the application determines facts*.

## Why LLM Reasoning is Scoped
The LLM is permitted only to interpret ambiguous patterns — e.g., "given that package X is declared but not installed and the error contains `ModuleNotFoundError: No module named 'X'`, does this indicate a dependency problem?" — when deterministic rules do not provide sufficient confidence. The LLM receives only pre-computed `EnvironmentFact` objects, not raw environment variable values, raw TOML, or raw package lists.

## Why the Phase is Read-Only
Phase 16 **detects and reports**. It does not:
- Install packages
- Modify `pyproject.toml`, `requirements.txt`, or any lockfile
- Execute `pip`, `uv`, `poetry`, or any package manager
- Mutate any environment configuration
- Execute arbitrary shell commands

This is intentional. Package installation is a privileged, supply-chain-sensitive action that requires explicit authorisation in a future phase.

## Why Dependency Installation is Excluded
- Supply-chain risk: an LLM recommending `pip install unknown-package-from-somewhere` could introduce malicious code.
- Environment integrity: automatic installation without isolation (e.g., sandbox) could corrupt the development environment.
- Authorization gap: the CodingAgent is the mutation authority; no other component may install or mutate.

## Dependency Provenance
Every `DeclaredDependency` carries `source` (enum: PYPROJECT, REQUIREMENTS, LOCKFILE, SETUP_CFG, PIPFILE, OTHER) and `source_file` (relative path). Multiple declarations of the same package from different files remain as separate objects, making contradictions visible rather than silently merged.

## Environment Failures vs Code Failures
| Signal | Classification |
|--------|---------------|
| Package declared, not installed | `DEPENDENCY_MISSING` |
| Package version constraint violated | `VERSION_MISMATCH` |
| Python version < requires-python | `PYTHON_VERSION_MISMATCH` |
| Docker/harness unreachable | `INFRASTRUCTURE_FAILURE` |
| No dependency signal | falls through to Phase 15 `FailureDiagnosis` |

## Phase 15 Integration
`FailureDiagnosisAgent` receives `EnvironmentDiagnosis` as supplementary context. When `EnvironmentDiagnosis.category` is `DEPENDENCY_MISSING` or `VERSION_MISMATCH`, the agent should classify the failure as `ENVIRONMENT_ERROR` and suppress code repair proposals — preventing `CodingAgent` from mutating application files for an environment problem.

## Phase 14 Integration
`TestStrategy.validation_commands` may include environment checks. `EnvironmentDiagnosis` can be referenced alongside `TestStrategy.validation_goals` to provide richer context when validation fails.

## Secrets Protection
- `EnvironmentSnapshot` contains no fields for API keys, tokens, passwords, or secret values.
- Environment variable *values* are never captured.
- The `RepositoryIgnorer`'s sensitive-file list (`.env`, `.env.*`) is respected.
- The LLM is given only `EnvironmentFact` objects describing computed facts, not raw file contents.

## Known Limitations
1. `setup.py` is not parsed (AST execution risk); its presence is noted via `important_files` but not parsed.
2. Lockfile contents are detected but not fully parsed in this phase (`is_parseable = False`); only lockfile *type* and *presence* are established.
3. `importlib.metadata` reflects the currently active Python environment, which may differ from the target sandbox environment.
4. Complex PEP 508 markers (`;python_version<"3.12"`) are stripped rather than evaluated.
5. No transitive dependency resolution is performed.
6. `packaging` library is used for version comparison where available; a fallback manual comparison handles simple cases.
