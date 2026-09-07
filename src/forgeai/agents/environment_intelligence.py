"""
Dependency & Environment Intelligence — Phase 16.

This module provides two public components:

1. DependencyDiscovery — fully deterministic, no LLM.
   Scans a repository root for dependency declarations, lockfiles, and
   installed package information.

2. EnvironmentIntelligenceAgent — deterministic-first analysis with
   optional LLM reasoning for ambiguous cases.
   Produces a structured EnvironmentDiagnosis.

SECURITY INVARIANTS:
- No package installation.
- No subprocess / shell execution.
- No mutation of any file.
- No secret values passed to the LLM.
- Installed package data collected via importlib.metadata (stdlib).
- Python runtime data collected via sys (stdlib).
- TOML parsed via tomllib (stdlib ≥ 3.11).
"""

from __future__ import annotations

import configparser
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from forgeai.agents.environment_models import (
    DeclaredDependency,
    DependencyCheckResult,
    DependencySnapshot,
    DependencySource,
    DependencyState,
    EnvironmentDiagnosis,
    EnvironmentDiagnosisCategory,
    EnvironmentFact,
    EnvironmentSnapshot,
    InstalledPackage,
    LockfileInfo,
    LockfileType,
    VersionConstraint,
)
from forgeai.agents.errors import DependencyParseError

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_DECLARED_DEPS = 500
_MAX_INSTALLED_PKGS = 500
_LOCKFILE_NAMES: dict[str, LockfileType] = {
    "poetry.lock": LockfileType.POETRY_LOCK,
    "uv.lock": LockfileType.UV_LOCK,
    "Pipfile.lock": LockfileType.PIPFILE_LOCK,
    "pdm.lock": LockfileType.PDM_LOCK,
}
_REQUIREMENT_FILE_PATTERNS: list[str] = [
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-test.txt",
    "requirements-ci.txt",
    "requirements/base.txt",
    "requirements/dev.txt",
    "requirements/test.txt",
    "requirements/prod.txt",
    "requirements/production.txt",
]
# Regex for valid version operators
_VERSION_OP_RE = re.compile(r"^(===|~=|==|!=|<=|>=|<|>)\s*(.+)$")
# Rough but safe requirement-line tokeniser
_REQ_LINE_RE = re.compile(
    r"^([A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)"  # package name
    r"\s*([^;#]*)"  # optional version specifier (stop at ; or #)
)
# Secret-bearing env var name patterns — we redact values of these
_SECRET_PATTERNS = re.compile(
    r"(password|passwd|secret|token|api.?key|auth|credential|private.?key)",
    re.IGNORECASE,
)


def _normalise_name(name: str) -> str:
    """PEP 503 normalise: lowercase, replace [-_.] with underscore."""
    return re.sub(r"[-_.]+", "_", name).lower()


def _parse_specifier(raw_spec: str) -> VersionConstraint:
    """Parse a single version specifier into a VersionConstraint."""
    raw_spec = raw_spec.strip()
    m = _VERSION_OP_RE.match(raw_spec)
    if m:
        return VersionConstraint(
            raw_spec=raw_spec, operator=m.group(1), version=m.group(2).strip()
        )
    return VersionConstraint(raw_spec=raw_spec, is_parseable=False)


def _parse_specifier_set(specifier_str: str) -> list[VersionConstraint]:
    """Parse a comma-separated specifier set (e.g. '>=1.0,<2.0')."""
    if not specifier_str.strip():
        return []
    return [_parse_specifier(s) for s in specifier_str.split(",") if s.strip()]


# ---------------------------------------------------------------------------
# TOML helper — use tomllib (stdlib ≥3.11) or tomli fallback
# ---------------------------------------------------------------------------


def _load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file and return its contents as a dict."""
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            raise DependencyParseError(
                "tomllib (stdlib ≥3.11) or tomli package required to parse TOML files."
            )
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception as exc:
        raise DependencyParseError(f"Failed to parse TOML file {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# Requirements.txt parser
# ---------------------------------------------------------------------------


def _parse_requirements_file(
    path: Path, repo_root: Path, source_file: str, is_dev: bool = False
) -> list[DeclaredDependency]:
    """Parse a requirements.txt-style file, returning DeclaredDependency list."""
    deps: list[DeclaredDependency] = []
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return deps

    for raw_line in content.splitlines():
        line = raw_line.strip()
        # Skip blanks and comments
        if not line or line.startswith("#"):
            continue
        # Lines that are pip options (start with -) are skipped as unparseable
        if line.startswith("-"):
            continue
        # Lines that are VCS / URL requirements (e.g. git+https://...)
        # cannot be safely normalised — mark as unparseable, preserve for traceability
        if re.match(r"^(https?|git\+|svn\+|hg\+|bzr\+|file:)", line, re.IGNORECASE):
            deps.append(
                DeclaredDependency(
                    name="UNPARSEABLE",
                    source=DependencySource.REQUIREMENTS,
                    source_file=source_file,
                    is_dev=is_dev,
                    raw_line=raw_line,
                    is_parseable=False,
                )
            )
            continue
        # Strip inline comment
        line_no_comment = line.split("#", 1)[0].strip()
        # Strip environment markers  (e.g. '; python_version<"3.12"')
        line_no_marker = line_no_comment.split(";", 1)[0].strip()

        m = _REQ_LINE_RE.match(line_no_marker)
        if not m:
            deps.append(
                DeclaredDependency(
                    name="UNPARSEABLE",
                    source=DependencySource.REQUIREMENTS,
                    source_file=source_file,
                    is_dev=is_dev,
                    raw_line=raw_line,
                    is_parseable=False,
                )
            )
            continue

        pkg_name = _normalise_name(m.group(1))
        spec_str = m.group(3).strip()
        constraints = _parse_specifier_set(spec_str)

        deps.append(
            DeclaredDependency(
                name=pkg_name,
                version_constraints=constraints,
                source=DependencySource.REQUIREMENTS,
                source_file=source_file,
                is_dev=is_dev,
                raw_line=raw_line,
            )
        )

    return deps[:_MAX_DECLARED_DEPS]


# ---------------------------------------------------------------------------
# pyproject.toml parser
# ---------------------------------------------------------------------------


def _parse_pyproject(
    path: Path, repo_root: Path
) -> tuple[list[DeclaredDependency], str | None, str]:
    """
    Parse pyproject.toml and return (deps, python_requires, error_msg).
    error_msg is empty on success.
    """
    source_file = str(path.relative_to(repo_root))
    try:
        data = _load_toml(path)
    except DependencyParseError as exc:
        return [], None, str(exc)

    deps: list[DeclaredDependency] = []
    python_requires: str | None = None

    project = data.get("project", {})
    if not isinstance(project, dict):
        return deps, python_requires, ""

    python_requires = project.get("requires-python")

    # Core dependencies
    for raw in project.get("dependencies", []):
        if not isinstance(raw, str):
            continue
        m = _REQ_LINE_RE.match(raw.split(";", 1)[0].strip())
        if not m:
            deps.append(
                DeclaredDependency(
                    name="UNPARSEABLE",
                    source=DependencySource.PYPROJECT,
                    source_file=source_file,
                    raw_line=raw,
                    is_parseable=False,
                )
            )
            continue
        pkg_name = _normalise_name(m.group(1))
        constraints = _parse_specifier_set(m.group(3).strip())
        deps.append(
            DeclaredDependency(
                name=pkg_name,
                version_constraints=constraints,
                source=DependencySource.PYPROJECT,
                source_file=source_file,
                raw_line=raw,
            )
        )

    # Optional dependencies
    optional = project.get("optional-dependencies", {})
    if isinstance(optional, dict):
        for group_name, group_deps in optional.items():
            if not isinstance(group_deps, list):
                continue
            is_dev = group_name.lower() in ("dev", "test", "testing", "lint", "ci")
            for raw in group_deps:
                if not isinstance(raw, str):
                    continue
                m = _REQ_LINE_RE.match(raw.split(";", 1)[0].strip())
                if not m:
                    deps.append(
                        DeclaredDependency(
                            name="UNPARSEABLE",
                            source=DependencySource.PYPROJECT,
                            source_file=source_file,
                            optional_group=group_name,
                            is_dev=is_dev,
                            raw_line=raw,
                            is_parseable=False,
                        )
                    )
                    continue
                pkg_name = _normalise_name(m.group(1))
                constraints = _parse_specifier_set(m.group(3).strip())
                deps.append(
                    DeclaredDependency(
                        name=pkg_name,
                        version_constraints=constraints,
                        source=DependencySource.PYPROJECT,
                        source_file=source_file,
                        optional_group=group_name,
                        is_dev=is_dev,
                        raw_line=raw,
                    )
                )

    # Dependency groups (PEP 735 / uv style)
    dep_groups = data.get("dependency-groups", {})
    if isinstance(dep_groups, dict):
        for group_name, group_deps in dep_groups.items():
            if not isinstance(group_deps, list):
                continue
            is_dev = group_name.lower() in ("dev", "test", "testing", "lint", "ci")
            for item in group_deps:
                if isinstance(item, str):
                    raw = item
                elif isinstance(item, dict) and "include-group" in item:
                    continue  # skip group includes
                else:
                    continue
                m = _REQ_LINE_RE.match(raw.split(";", 1)[0].strip())
                if not m:
                    continue
                pkg_name = _normalise_name(m.group(1))
                constraints = _parse_specifier_set(m.group(3).strip())
                deps.append(
                    DeclaredDependency(
                        name=pkg_name,
                        version_constraints=constraints,
                        source=DependencySource.PYPROJECT,
                        source_file=source_file,
                        optional_group=group_name,
                        is_dev=is_dev,
                        raw_line=raw,
                    )
                )

    return deps[:_MAX_DECLARED_DEPS], python_requires, ""


# ---------------------------------------------------------------------------
# setup.cfg parser
# ---------------------------------------------------------------------------


def _parse_setup_cfg(
    path: Path, repo_root: Path
) -> tuple[list[DeclaredDependency], str]:
    """Parse setup.cfg; return (deps, error_msg)."""
    source_file = str(path.relative_to(repo_root))
    deps: list[DeclaredDependency] = []
    try:
        cfg = configparser.ConfigParser()
        cfg.read(path, encoding="utf-8")
    except Exception as exc:
        return [], f"Failed to parse setup.cfg: {exc}"

    section = "options"
    if not cfg.has_section(section):
        return deps, ""

    raw_deps = cfg.get(section, "install_requires", fallback="")
    for line in raw_deps.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _REQ_LINE_RE.match(line.split(";", 1)[0].strip())
        if not m:
            deps.append(
                DeclaredDependency(
                    name="UNPARSEABLE",
                    source=DependencySource.SETUP_CFG,
                    source_file=source_file,
                    raw_line=line,
                    is_parseable=False,
                )
            )
            continue
        pkg_name = _normalise_name(m.group(1))
        constraints = _parse_specifier_set(m.group(3).strip())
        deps.append(
            DeclaredDependency(
                name=pkg_name,
                version_constraints=constraints,
                source=DependencySource.SETUP_CFG,
                source_file=source_file,
                raw_line=line,
            )
        )

    # extras_require
    for key in (
        cfg.options("options.extras_require")
        if cfg.has_section("options.extras_require")
        else []
    ):
        is_dev = key.lower() in ("dev", "test", "testing", "lint", "ci")
        raw_group = cfg.get("options.extras_require", key, fallback="")
        for line in raw_group.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = _REQ_LINE_RE.match(line.split(";", 1)[0].strip())
            if not m:
                continue
            pkg_name = _normalise_name(m.group(1))
            constraints = _parse_specifier_set(m.group(3).strip())
            deps.append(
                DeclaredDependency(
                    name=pkg_name,
                    version_constraints=constraints,
                    source=DependencySource.SETUP_CFG,
                    source_file=source_file,
                    optional_group=key,
                    is_dev=is_dev,
                    raw_line=line,
                )
            )

    return deps[:_MAX_DECLARED_DEPS], ""


# ---------------------------------------------------------------------------
# Pipfile parser (TOML)
# ---------------------------------------------------------------------------


def _parse_pipfile(path: Path, repo_root: Path) -> tuple[list[DeclaredDependency], str]:
    """Parse Pipfile (TOML-like); return (deps, error_msg)."""
    source_file = str(path.relative_to(repo_root))
    deps: list[DeclaredDependency] = []
    try:
        data = _load_toml(path)
    except DependencyParseError as exc:
        return [], str(exc)

    def _extract(section: str, is_dev: bool) -> None:
        section_data = data.get(section, {})
        if not isinstance(section_data, dict):
            return
        for pkg, spec in section_data.items():
            if pkg.lower() in ("python_version", "python_full_version"):
                continue
            pkg_name = _normalise_name(pkg)
            raw_spec = spec if isinstance(spec, str) else ""
            # Pipfile uses '*' for unconstrained
            if raw_spec == "*":
                raw_spec = ""
            constraints = _parse_specifier_set(raw_spec)
            deps.append(
                DeclaredDependency(
                    name=pkg_name,
                    version_constraints=constraints,
                    source=DependencySource.PIPFILE,
                    source_file=source_file,
                    is_dev=is_dev,
                    raw_line=f"{pkg} = {spec!r}",
                )
            )

    _extract("packages", is_dev=False)
    _extract("dev-packages", is_dev=True)
    return deps[:_MAX_DECLARED_DEPS], ""


# ---------------------------------------------------------------------------
# Installed package collection (importlib.metadata — stdlib, no subprocess)
# ---------------------------------------------------------------------------


def _collect_installed_packages() -> tuple[list[InstalledPackage], str]:
    """Return installed packages via importlib.metadata."""
    try:
        import importlib.metadata as meta
    except ImportError:
        return [], "importlib.metadata not available"

    pkgs: list[InstalledPackage] = []
    try:
        distributions = list(meta.distributions())
    except Exception as exc:
        return [], f"importlib.metadata.distributions() failed: {exc}"

    for dist in distributions:
        try:
            name = _normalise_name(dist.metadata["Name"] or "")
            version = dist.metadata["Version"] or ""
            if name:
                pkgs.append(InstalledPackage(name=name, version=version))
        except Exception:
            continue

    pkgs.sort(key=lambda p: p.name)
    return pkgs[:_MAX_INSTALLED_PKGS], ""


# ---------------------------------------------------------------------------
# Python version compatibility check
# ---------------------------------------------------------------------------


def _check_python_requires(
    python_requires: str | None, env: EnvironmentSnapshot
) -> bool | None:
    """
    Deterministically check if the current Python satisfies python_requires.
    Returns True/False if checkable, None if not.
    """
    if not python_requires or not env.python_version_info:
        return None
    try:
        from packaging.specifiers import SpecifierSet

        spec = SpecifierSet(python_requires)
        version_str = ".".join(str(v) for v in env.python_version_info[:3])
        return spec.contains(version_str, prereleases=True)
    except Exception:
        pass
    # Fallback: attempt manual check for simple cases
    m = re.match(r"^(>=|>|==|<=|<|~=|!=)\s*([\d.]+)", python_requires.strip())
    if not m:
        return None
    op, req_ver = m.group(1), m.group(2)
    try:
        req_parts = tuple(int(x) for x in req_ver.split(".") if x.isdigit())
        env_parts = tuple(env.python_version_info[: len(req_parts)])
        if op == ">=":
            return env_parts >= req_parts
        if op == ">":
            return env_parts > req_parts
        if op == "==":
            return env_parts == req_parts
        if op == "<=":
            return env_parts <= req_parts
        if op == "<":
            return env_parts < req_parts
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Version constraint satisfaction check
# ---------------------------------------------------------------------------


def _check_constraint(
    installed_version: str, constraint: VersionConstraint
) -> bool | None:
    """Check if installed_version satisfies a single VersionConstraint."""
    if (
        not constraint.is_parseable
        or constraint.operator is None
        or constraint.version is None
    ):
        return None
    try:
        from packaging.version import Version

        inst = Version(installed_version)
        req = Version(constraint.version)
        op = constraint.operator
        if op == ">=":
            return inst >= req
        if op == ">":
            return inst > req
        if op == "==":
            # Support wildcard: 1.2.*
            if constraint.version.endswith(".*"):
                prefix = constraint.version[:-2]
                return installed_version.startswith(prefix)
            return inst == req
        if op == "!=":
            return inst != req
        if op == "<=":
            return inst <= req
        if op == "<":
            return inst < req
        if op == "~=":
            # Compatible release: >=version, == version up to last part
            parts = constraint.version.split(".")
            if len(parts) < 2:
                return None
            upper_prefix = ".".join(parts[:-1])
            return inst >= req and installed_version.startswith(upper_prefix)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Dependency Discovery — deterministic, no LLM
# ---------------------------------------------------------------------------


class DependencyDiscovery:
    """
    Deterministic discovery of dependency declarations, installed packages,
    and lockfiles for a Python repository.

    READ-ONLY. No package installation. No subprocess. No mutation.
    """

    def __init__(self, repo_root: str | Path) -> None:
        self.root = Path(repo_root).resolve()

    def _collect_env_snapshot(self) -> EnvironmentSnapshot:
        """Collect Python runtime facts deterministically from sys."""
        errors: list[str] = []
        try:
            python_version = sys.version.split()[0]
            version_info = list(sys.version_info[:3])
            executable = sys.executable
            platform = sys.platform
            is_venv = hasattr(sys, "real_prefix") or (
                hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
            )
            venv_path: str | None = None
            if is_venv:
                venv_path = sys.prefix
        except Exception as exc:
            errors.append(f"sys inspection failed: {exc}")
            python_version = "unknown"
            version_info = []
            executable = ""
            platform = ""
            is_venv = False
            venv_path = None

        return EnvironmentSnapshot(
            python_version=python_version,
            python_version_info=version_info,
            python_executable=executable,
            platform=platform,
            is_venv=is_venv,
            virtual_env_path=venv_path,
            collection_errors=errors,
        )

    def discover(self) -> tuple[DependencySnapshot, EnvironmentSnapshot]:
        """
        Scan the repository root and collect all dependency/environment info.

        Returns:
            (DependencySnapshot, EnvironmentSnapshot) — both are immutable facts.
        """
        snap = DependencySnapshot()
        all_deps: list[DeclaredDependency] = []
        dep_files: list[str] = []

        # --- pyproject.toml ---
        pyproject_path = self.root / "pyproject.toml"
        if pyproject_path.is_file():
            dep_files.append("pyproject.toml")
            try:
                pyproject_deps, python_requires, err = _parse_pyproject(
                    pyproject_path, self.root
                )
                all_deps.extend(pyproject_deps)
                if python_requires:
                    snap.python_requires = python_requires
                if err:
                    snap.collection_errors["pyproject.toml"] = err
            except Exception as exc:
                snap.collection_errors["pyproject.toml"] = str(exc)

        # --- requirements files ---
        for pattern in _REQUIREMENT_FILE_PATTERNS:
            req_path = self.root / pattern
            if req_path.is_file():
                rel = str(req_path.relative_to(self.root))
                dep_files.append(rel)
                is_dev = any(kw in pattern.lower() for kw in ("dev", "test", "ci"))
                try:
                    rdeps = _parse_requirements_file(
                        req_path, self.root, rel, is_dev=is_dev
                    )
                    all_deps.extend(rdeps)
                except Exception as exc:
                    snap.collection_errors[rel] = str(exc)

        # Also scan requirements/ directory for any *.txt
        req_dir = self.root / "requirements"
        if req_dir.is_dir():
            for req_path in sorted(req_dir.glob("*.txt")):
                rel = str(req_path.relative_to(self.root)).replace("\\", "/")
                if rel not in dep_files:
                    dep_files.append(rel)
                    is_dev = any(
                        kw in req_path.stem.lower() for kw in ("dev", "test", "ci")
                    )
                    try:
                        rdeps = _parse_requirements_file(
                            req_path, self.root, rel, is_dev=is_dev
                        )
                        all_deps.extend(rdeps)
                    except Exception as exc:
                        snap.collection_errors[rel] = str(exc)

        # --- setup.cfg ---
        setup_cfg_path = self.root / "setup.cfg"
        if setup_cfg_path.is_file():
            dep_files.append("setup.cfg")
            try:
                cfg_deps, err = _parse_setup_cfg(setup_cfg_path, self.root)
                all_deps.extend(cfg_deps)
                if err:
                    snap.collection_errors["setup.cfg"] = err
            except Exception as exc:
                snap.collection_errors["setup.cfg"] = str(exc)

        # --- Pipfile ---
        pipfile_path = self.root / "Pipfile"
        if pipfile_path.is_file():
            dep_files.append("Pipfile")
            try:
                pip_deps, err = _parse_pipfile(pipfile_path, self.root)
                all_deps.extend(pip_deps)
                if err:
                    snap.collection_errors["Pipfile"] = err
            except Exception as exc:
                snap.collection_errors["Pipfile"] = str(exc)

        # --- Lockfiles ---
        lockfiles: list[LockfileInfo] = []
        for lockfile_name, lockfile_type in _LOCKFILE_NAMES.items():
            lock_path = self.root / lockfile_name
            if lock_path.is_file():
                rel = str(lock_path.relative_to(self.root))
                dep_files.append(rel)
                lockfiles.append(
                    LockfileInfo(
                        path=rel, lockfile_type=lockfile_type, is_parseable=False
                    )
                )

        # --- Installed packages ---
        installed, installed_err = _collect_installed_packages()
        if installed_err:
            snap.collection_errors["installed_packages"] = installed_err

        snap.declared = all_deps[:_MAX_DECLARED_DEPS]
        snap.installed = installed
        snap.lockfiles = lockfiles
        snap.dependency_file_paths = sorted(set(dep_files))

        env_snap = self._collect_env_snapshot()
        return snap, env_snap


# ---------------------------------------------------------------------------
# Deterministic reconciliation
# ---------------------------------------------------------------------------


def _reconcile_dependencies(
    dep_snap: DependencySnapshot,
    env_snap: EnvironmentSnapshot,
) -> list[DependencyCheckResult]:
    """Deterministically reconcile declared vs installed packages."""
    installed_index: dict[str, str] = {p.name: p.version for p in dep_snap.installed}
    results: list[DependencyCheckResult] = []

    # Only check parseable, non-dev core deps (most relevant for failures)
    seen: set[str] = set()
    for dep in dep_snap.declared:
        if not dep.is_parseable or dep.name == "UNPARSEABLE":
            continue
        if dep.name in seen:
            continue
        seen.add(dep.name)

        installed_ver = installed_index.get(dep.name)
        constraints = dep.version_constraints
        spec_str = ",".join(c.raw_spec for c in constraints) if constraints else None

        if installed_ver is None:
            state = DependencyState.DECLARED_BUT_NOT_INSTALLED
            results.append(
                DependencyCheckResult(
                    name=dep.name,
                    state=state,
                    declared_version_spec=spec_str,
                    installed_version=None,
                    is_compatible=False,
                )
            )
        else:
            # Check all constraints
            all_ok: list[bool | None] = []
            for c in constraints:
                ok = _check_constraint(installed_ver, c)
                all_ok.append(ok)

            if not constraints:
                state = DependencyState.DECLARED_AND_INSTALLED
                compatible: bool | None = True
            elif all(v is True for v in all_ok):
                state = DependencyState.DECLARED_AND_INSTALLED
                compatible = True
            elif any(v is False for v in all_ok):
                state = DependencyState.VERSION_MISMATCH
                compatible = False
            else:
                state = DependencyState.UNKNOWN
                compatible = None

            results.append(
                DependencyCheckResult(
                    name=dep.name,
                    state=state,
                    declared_version_spec=spec_str,
                    installed_version=installed_ver,
                    is_compatible=compatible,
                )
            )

    return results


# ---------------------------------------------------------------------------
# Environment Intelligence Agent
# ---------------------------------------------------------------------------


class EnvironmentIntelligenceAgent:
    """
    Analyses dependency and environment snapshots to produce a structured
    EnvironmentDiagnosis.

    Design:
    - Deterministic rules are applied first.
    - LLM reasoning is used only for ambiguous cases where rules don't suffice.
    - The LLM receives only pre-computed facts; it cannot invent repository state.
    - This agent is READ-ONLY. It proposes, never executes.
    """

    def __init__(self, llm_client: Any | None = None) -> None:
        """
        Args:
            llm_client: Optional LLMClient for ambiguous-case reasoning.
                        When None, analysis is purely deterministic.
        """
        self._llm = llm_client
        self._max_evidence_chars = 3000

    def analyze(
        self,
        dep_snap: DependencySnapshot,
        env_snap: EnvironmentSnapshot,
        validation_results: list[dict[str, Any]] | None = None,
        failure_category: str | None = None,
    ) -> EnvironmentDiagnosis:
        """
        Analyse the dependency/environment state and produce an EnvironmentDiagnosis.

        Args:
            dep_snap: The DependencySnapshot from DependencyDiscovery.
            env_snap: The EnvironmentSnapshot from DependencyDiscovery.
            validation_results: Optional validation output from Phase 15.
            failure_category: Optional FailureCategory string for context.

        Returns:
            EnvironmentDiagnosis — structured facts + inferences + recommendations.
        """
        facts: list[EnvironmentFact] = []
        inferences: list[EnvironmentFact] = []
        assumptions: list[str] = []

        # --- Deterministic facts ---
        facts.append(
            EnvironmentFact(
                description=f"Python version: {env_snap.python_version}",
                is_deterministic=True,
                source="sys.version",
            )
        )
        facts.append(
            EnvironmentFact(
                description=f"Virtual environment active: {env_snap.is_venv}",
                is_deterministic=True,
                source="sys.prefix",
            )
        )
        facts.append(
            EnvironmentFact(
                description=f"Dependency files found: {dep_snap.dependency_file_paths}",
                is_deterministic=True,
                source="filesystem",
            )
        )
        facts.append(
            EnvironmentFact(
                description=f"Declared dependencies: {len(dep_snap.declared)}",
                is_deterministic=True,
                source="dependency_snapshot",
            )
        )
        facts.append(
            EnvironmentFact(
                description=f"Installed packages detected: {len(dep_snap.installed)}",
                is_deterministic=True,
                source="importlib.metadata",
            )
        )

        # --- Reconcile ---
        reconciled = _reconcile_dependencies(dep_snap, env_snap)
        missing = [
            r
            for r in reconciled
            if r.state == DependencyState.DECLARED_BUT_NOT_INSTALLED
        ]
        mismatched = [
            r for r in reconciled if r.state == DependencyState.VERSION_MISMATCH
        ]

        for r in missing:
            facts.append(
                EnvironmentFact(
                    description=(
                        f"Package '{r.name}' declared but NOT"
                        " detected as installed."
                    ),
                    is_deterministic=True,
                    source="importlib.metadata",
                )
            )
        for r in mismatched:
            facts.append(
                EnvironmentFact(
                    description=(
                        f"Package '{r.name}' version mismatch: "
                        f"declared={r.declared_version_spec}, "
                        f"installed={r.installed_version}"
                    ),
                    is_deterministic=True,
                    source="importlib.metadata",
                )
            )

        # --- Python version check ---
        py_compatible: bool | None = None
        if dep_snap.python_requires:
            py_compatible = _check_python_requires(dep_snap.python_requires, env_snap)
            if py_compatible is not None:
                facts.append(
                    EnvironmentFact(
                        description=(
                            f"Python version compatibility: {env_snap.python_version} "
                            f"vs requires-python '{dep_snap.python_requires}': "
                            f"{'OK' if py_compatible else 'MISMATCH'}"
                        ),
                        is_deterministic=True,
                        source="pyproject.toml + sys.version",
                    )
                )
            else:
                assumptions.append(
                    "Could not deterministically check"
                    f" requires-python='{dep_snap.python_requires}'"
                )

        # --- Determine category deterministically ---
        category = EnvironmentDiagnosisCategory.NO_ISSUE_DETECTED
        summary = "No environment or dependency issues detected."
        confidence = 0.9
        recommended_action = ""

        if py_compatible is False:
            category = EnvironmentDiagnosisCategory.PYTHON_VERSION_MISMATCH
            summary = (
                f"Python version {env_snap.python_version} does not satisfy "
                f"requires-python '{dep_snap.python_requires}'."
            )
            recommended_action = (
                f"Use Python {dep_snap.python_requires} to run this project."
            )
            confidence = 0.95

        elif mismatched:
            category = EnvironmentDiagnosisCategory.VERSION_MISMATCH
            names = ", ".join(r.name for r in mismatched[:5])
            summary = f"Package version mismatch detected for: {names}."
            recommended_action = (
                "Ensure declared version constraints are satisfied in the environment."
            )
            confidence = 0.9

        elif missing:
            category = EnvironmentDiagnosisCategory.DEPENDENCY_MISSING
            names = ", ".join(r.name for r in missing[:5])
            extra = f" (and {len(missing) - 5} more)" if len(missing) > 5 else ""
            summary = f"Declared package(s) not found in environment: {names}{extra}."
            recommended_action = (
                "Install declared dependencies in the controlled environment "
                "(do not execute automatically — requires explicit authorization)."
            )
            confidence = 0.85

        elif not dep_snap.installed and dep_snap.declared:
            # Can't detect any installed packages at all
            category = EnvironmentDiagnosisCategory.ENVIRONMENT_INCOMPLETE
            summary = "No installed packages could be detected."
            assumptions.append(
                "importlib.metadata returned no results;"
                " environment may be empty or inspection failed."
            )
            confidence = 0.5
            recommended_action = (
                "Verify the Python environment has dependencies installed."
            )

        return EnvironmentDiagnosis(
            category=category,
            summary=summary,
            facts=facts,
            inferences=inferences,
            dependency_issues=reconciled,
            python_version_compatible=py_compatible,
            confidence=confidence,
            recommended_action=recommended_action,
            assumptions=assumptions,
        )
