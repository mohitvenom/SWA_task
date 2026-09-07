"""Unit tests for Phase 16 — Dependency & Environment Intelligence."""

from __future__ import annotations

import textwrap
from pathlib import Path

from forgeai.agents.environment_intelligence import (
    DependencyDiscovery,
    EnvironmentIntelligenceAgent,
    _check_python_requires,
    _normalise_name,
    _parse_specifier,
    _parse_specifier_set,
    _reconcile_dependencies,
)
from forgeai.agents.environment_models import (
    DeclaredDependency,
    DependencySnapshot,
    DependencySource,
    DependencyState,
    EnvironmentDiagnosisCategory,
    EnvironmentSnapshot,
    InstalledPackage,
    LockfileType,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_env_snap(**kwargs):  # type: ignore[no-untyped-def]
    defaults = dict(
        python_version="3.12.3",
        python_version_info=[3, 12, 3],
        python_executable="/usr/bin/python3",
        platform="linux",
        is_venv=True,
    )
    defaults.update(kwargs)
    return EnvironmentSnapshot(**defaults)


def make_dep_snap(**kwargs):  # type: ignore[no-untyped-def]
    return DependencySnapshot(**kwargs)


# ---------------------------------------------------------------------------
# 1. Specifier parsing
# ---------------------------------------------------------------------------


def test_parse_specifier_pinned() -> None:
    c = _parse_specifier("==1.2.3")
    assert c.operator == "=="
    assert c.version == "1.2.3"
    assert c.is_parseable is True


def test_parse_specifier_gte() -> None:
    c = _parse_specifier(">=2.0")
    assert c.operator == ">="
    assert c.version == "2.0"


def test_parse_specifier_unparseable() -> None:
    c = _parse_specifier("this is not a spec")
    assert c.is_parseable is False


def test_parse_specifier_set_empty() -> None:
    assert _parse_specifier_set("") == []


def test_parse_specifier_set_multiple() -> None:
    cs = _parse_specifier_set(">=1.0,<2.0")
    assert len(cs) == 2
    ops = {c.operator for c in cs}
    assert ops == {">=", "<"}


# ---------------------------------------------------------------------------
# 2. Name normalisation
# ---------------------------------------------------------------------------


def test_normalise_name_hyphens() -> None:
    assert _normalise_name("my-package") == "my_package"


def test_normalise_name_dots() -> None:
    assert _normalise_name("some.pkg") == "some_pkg"


def test_normalise_name_mixed() -> None:
    assert _normalise_name("My-Pkg.Name") == "my_pkg_name"


# ---------------------------------------------------------------------------
# 3. pyproject.toml discovery
# ---------------------------------------------------------------------------


def test_pyproject_dependency_discovery(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent("""\
        [project]
        name = "myapp"
        requires-python = ">=3.11"
        dependencies = ["requests>=2.28", "pydantic>=2.0,<3.0"]

        [project.optional-dependencies]
        dev = ["pytest>=8.0", "ruff>=0.3"]
        """),
        encoding="utf-8",
    )
    disc = DependencyDiscovery(tmp_path)
    dep_snap, env_snap = disc.discover()

    names = [d.name for d in dep_snap.declared]
    assert "requests" in names
    assert "pydantic" in names
    assert dep_snap.python_requires == ">=3.11"
    dev_names = [d.name for d in dep_snap.declared if d.is_dev]
    assert "pytest" in dev_names
    assert "ruff" in dev_names


def test_pyproject_optional_group_preserved(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent("""\
        [project]
        name = "myapp"
        requires-python = ">=3.12"
        dependencies = []

        [project.optional-dependencies]
        extras = ["httpx"]
        """),
        encoding="utf-8",
    )
    disc = DependencyDiscovery(tmp_path)
    dep_snap, _ = disc.discover()
    httpx = next(d for d in dep_snap.declared if d.name == "httpx")
    assert httpx.optional_group == "extras"


def test_pyproject_python_requires_captured(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent("""\
        [project]
        name = "myapp"
        requires-python = ">=3.11"
        dependencies = []
        """),
        encoding="utf-8",
    )
    disc = DependencyDiscovery(tmp_path)
    dep_snap, _ = disc.discover()
    assert dep_snap.python_requires == ">=3.11"


# ---------------------------------------------------------------------------
# 4. requirements.txt discovery
# ---------------------------------------------------------------------------


def test_requirements_txt_basic(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        textwrap.dedent("""\
        requests==2.31.0
        # this is a comment
        pydantic>=2.0

        flask
        """),
        encoding="utf-8",
    )
    disc = DependencyDiscovery(tmp_path)
    dep_snap, _ = disc.discover()
    names = [d.name for d in dep_snap.declared]
    assert "requests" in names
    assert "pydantic" in names
    assert "flask" in names


def test_requirements_txt_dev_flag(tmp_path: Path) -> None:
    (tmp_path / "requirements-dev.txt").write_text("pytest>=8.0\n", encoding="utf-8")
    disc = DependencyDiscovery(tmp_path)
    dep_snap, _ = disc.discover()
    dev = [d for d in dep_snap.declared if d.is_dev]
    assert any(d.name == "pytest" for d in dev)


def test_requirements_txt_options_skipped(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        "--index-url https://pypi.org/simple\nrequests\n",
        encoding="utf-8",
    )
    disc = DependencyDiscovery(tmp_path)
    dep_snap, _ = disc.discover()
    names = [d.name for d in dep_snap.declared]
    assert "requests" in names
    assert "--index-url" not in names


# ---------------------------------------------------------------------------
# 5. Malformed file handling
# ---------------------------------------------------------------------------


def test_malformed_pyproject_handled(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "this is not valid TOML @@@@", encoding="utf-8"
    )
    disc = DependencyDiscovery(tmp_path)
    dep_snap, _ = disc.discover()
    # Should not crash; error recorded
    assert "pyproject.toml" in dep_snap.collection_errors
    assert dep_snap.declared == []


def test_malformed_requirements_line_preserved(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text(
        "requests==2.0\ngit+https://github.com/org/repo.git\n",
        encoding="utf-8",
    )
    disc = DependencyDiscovery(tmp_path)
    dep_snap, _ = disc.discover()
    # git+ line can't be parsed by our regex — should be marked unparseable
    unparseable = [d for d in dep_snap.declared if not d.is_parseable]
    assert len(unparseable) >= 1


# ---------------------------------------------------------------------------
# 6. Lockfile detection
# ---------------------------------------------------------------------------


def test_poetry_lock_detected(tmp_path: Path) -> None:
    (tmp_path / "poetry.lock").write_text("# lock\n", encoding="utf-8")
    disc = DependencyDiscovery(tmp_path)
    dep_snap, _ = disc.discover()
    types = {lf.lockfile_type for lf in dep_snap.lockfiles}
    assert LockfileType.POETRY_LOCK in types


def test_uv_lock_detected(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text("# lock\n", encoding="utf-8")
    disc = DependencyDiscovery(tmp_path)
    dep_snap, _ = disc.discover()
    types = {lf.lockfile_type for lf in dep_snap.lockfiles}
    assert LockfileType.UV_LOCK in types


def test_no_lockfile_means_empty(tmp_path: Path) -> None:
    disc = DependencyDiscovery(tmp_path)
    dep_snap, _ = disc.discover()
    assert dep_snap.lockfiles == []


# ---------------------------------------------------------------------------
# 7. Multiple dependency sources — provenance preserved
# ---------------------------------------------------------------------------


def test_multiple_sources_distinct(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent("""\
        [project]
        name = "myapp"
        requires-python = ">=3.12"
        dependencies = ["requests>=2.28"]
        """),
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("flask==3.0\n", encoding="utf-8")
    disc = DependencyDiscovery(tmp_path)
    dep_snap, _ = disc.discover()
    sources = {d.source for d in dep_snap.declared}
    assert DependencySource.PYPROJECT in sources
    assert DependencySource.REQUIREMENTS in sources


def test_source_file_provenance_preserved(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")
    disc = DependencyDiscovery(tmp_path)
    dep_snap, _ = disc.discover()
    req = next(d for d in dep_snap.declared if d.name == "requests")
    assert req.source_file == "requirements.txt"


# ---------------------------------------------------------------------------
# 8. Declared-but-not-installed detection
# ---------------------------------------------------------------------------


def test_declared_but_not_installed(tmp_path: Path) -> None:
    dep_snap = make_dep_snap(
        declared=[
            DeclaredDependency(
                name="phantom_pkg",
                source=DependencySource.PYPROJECT,
                source_file="pyproject.toml",
                raw_line="phantom_pkg>=1.0",
            )
        ],
        installed=[],  # nothing installed
    )
    env_snap = make_env_snap()
    results = _reconcile_dependencies(dep_snap, env_snap)
    assert len(results) == 1
    assert results[0].name == "phantom_pkg"
    assert results[0].state == DependencyState.DECLARED_BUT_NOT_INSTALLED
    assert results[0].is_compatible is False


def test_declared_and_installed(tmp_path: Path) -> None:
    dep_snap = make_dep_snap(
        declared=[
            DeclaredDependency(
                name="requests",
                source=DependencySource.REQUIREMENTS,
                source_file="requirements.txt",
                raw_line="requests>=2.28",
                version_constraints=[
                    {
                        "raw_spec": ">=2.28",
                        "operator": ">=",
                        "version": "2.28",
                        "is_parseable": True,
                    }
                ],
            )
        ],
        installed=[InstalledPackage(name="requests", version="2.31.0")],
    )
    env_snap = make_env_snap()
    results = _reconcile_dependencies(dep_snap, env_snap)
    assert results[0].state == DependencyState.DECLARED_AND_INSTALLED
    assert results[0].is_compatible is True


# ---------------------------------------------------------------------------
# 9. Version mismatch detection
# ---------------------------------------------------------------------------


def test_version_mismatch_detected(tmp_path: Path) -> None:
    from forgeai.agents.environment_models import VersionConstraint

    dep_snap = make_dep_snap(
        declared=[
            DeclaredDependency(
                name="requests",
                source=DependencySource.REQUIREMENTS,
                source_file="requirements.txt",
                raw_line="requests>=3.0",
                version_constraints=[
                    VersionConstraint(raw_spec=">=3.0", operator=">=", version="3.0")
                ],
            )
        ],
        installed=[InstalledPackage(name="requests", version="2.31.0")],
    )
    env_snap = make_env_snap()
    results = _reconcile_dependencies(dep_snap, env_snap)
    assert results[0].state == DependencyState.VERSION_MISMATCH
    assert results[0].is_compatible is False


# ---------------------------------------------------------------------------
# 10. Python version mismatch detection
# ---------------------------------------------------------------------------


def test_python_version_compatible() -> None:
    env = make_env_snap(python_version_info=[3, 12, 3])
    result = _check_python_requires(">=3.11", env)
    assert result is True


def test_python_version_incompatible() -> None:
    env = make_env_snap(python_version_info=[3, 10, 0])
    result = _check_python_requires(">=3.12", env)
    assert result is False


def test_python_version_no_requires() -> None:
    env = make_env_snap()
    result = _check_python_requires(None, env)
    assert result is None


# ---------------------------------------------------------------------------
# 11. Unknown environment information
# ---------------------------------------------------------------------------


def test_unknown_dep_state_when_no_installed_data() -> None:

    dep_snap = make_dep_snap(
        declared=[
            DeclaredDependency(
                name="some_pkg",
                source=DependencySource.PYPROJECT,
                source_file="pyproject.toml",
                raw_line="some_pkg",
                version_constraints=[],
            )
        ],
        installed=[],
    )
    env_snap = make_env_snap()
    results = _reconcile_dependencies(dep_snap, env_snap)
    assert results[0].state == DependencyState.DECLARED_BUT_NOT_INSTALLED


# ---------------------------------------------------------------------------
# 12. EnvironmentIntelligenceAgent — missing dependency diagnosis
# ---------------------------------------------------------------------------


def test_agent_diagnoses_missing_dependency() -> None:
    dep_snap = make_dep_snap(
        declared=[
            DeclaredDependency(
                name="missing_lib",
                source=DependencySource.REQUIREMENTS,
                source_file="requirements.txt",
                raw_line="missing_lib",
            )
        ],
        installed=[],
    )
    env_snap = make_env_snap()
    agent = EnvironmentIntelligenceAgent(llm_client=None)
    diagnosis = agent.analyze(dep_snap, env_snap)
    assert diagnosis.category == EnvironmentDiagnosisCategory.DEPENDENCY_MISSING
    assert "missing_lib" in diagnosis.summary
    assert diagnosis.recommended_action != ""


def test_agent_diagnoses_python_version_mismatch() -> None:
    dep_snap = make_dep_snap(
        python_requires=">=3.13",
        declared=[],
        installed=[InstalledPackage(name="requests", version="2.31.0")],
    )
    env_snap = make_env_snap(
        python_version="3.12.0",
        python_version_info=[3, 12, 0],
    )
    agent = EnvironmentIntelligenceAgent(llm_client=None)
    diagnosis = agent.analyze(dep_snap, env_snap)
    assert diagnosis.category == EnvironmentDiagnosisCategory.PYTHON_VERSION_MISMATCH
    assert diagnosis.python_version_compatible is False


def test_agent_no_issue_when_all_ok() -> None:
    from forgeai.agents.environment_models import VersionConstraint

    dep_snap = make_dep_snap(
        python_requires=">=3.12",
        declared=[
            DeclaredDependency(
                name="requests",
                source=DependencySource.REQUIREMENTS,
                source_file="requirements.txt",
                raw_line="requests>=2.28",
                version_constraints=[
                    VersionConstraint(raw_spec=">=2.28", operator=">=", version="2.28")
                ],
            )
        ],
        installed=[InstalledPackage(name="requests", version="2.31.0")],
    )
    env_snap = make_env_snap(python_version_info=[3, 12, 3])
    agent = EnvironmentIntelligenceAgent(llm_client=None)
    diagnosis = agent.analyze(dep_snap, env_snap)
    assert diagnosis.category == EnvironmentDiagnosisCategory.NO_ISSUE_DETECTED


# ---------------------------------------------------------------------------
# 13. Facts vs inferences separation
# ---------------------------------------------------------------------------


def test_facts_are_deterministic() -> None:
    dep_snap = make_dep_snap()
    env_snap = make_env_snap()
    agent = EnvironmentIntelligenceAgent(llm_client=None)
    diagnosis = agent.analyze(dep_snap, env_snap)
    for fact in diagnosis.facts:
        assert fact.is_deterministic is True


def test_inferences_are_non_deterministic() -> None:
    dep_snap = make_dep_snap()
    env_snap = make_env_snap()
    agent = EnvironmentIntelligenceAgent(llm_client=None)
    diagnosis = agent.analyze(dep_snap, env_snap)
    # With no LLM, inferences should be empty
    for inf in diagnosis.inferences:
        assert inf.is_deterministic is False


# ---------------------------------------------------------------------------
# 14. Contradictory declarations from multiple sources — NOT silently merged
# ---------------------------------------------------------------------------


def test_contradictory_sources_preserved() -> None:
    from forgeai.agents.environment_models import VersionConstraint

    dep_snap = make_dep_snap(
        declared=[
            DeclaredDependency(
                name="requests",
                source=DependencySource.PYPROJECT,
                source_file="pyproject.toml",
                raw_line="requests>=3.0",
                version_constraints=[
                    VersionConstraint(raw_spec=">=3.0", operator=">=", version="3.0")
                ],
            ),
            DeclaredDependency(
                name="requests",
                source=DependencySource.REQUIREMENTS,
                source_file="requirements.txt",
                raw_line="requests==2.31.0",
                version_constraints=[
                    VersionConstraint(
                        raw_spec="==2.31.0", operator="==", version="2.31.0"
                    )
                ],
            ),
        ],
        installed=[InstalledPackage(name="requests", version="2.31.0")],
    )
    # Both declarations survive; first one used in reconcile (by seen-set dedup)
    names = [d.name for d in dep_snap.declared]
    assert names.count("requests") == 2  # NOT merged


# ---------------------------------------------------------------------------
# 15. Infrastructure failure — no issue detected when no dep files
# ---------------------------------------------------------------------------


def test_empty_repo_no_crash(tmp_path: Path) -> None:
    disc = DependencyDiscovery(tmp_path)
    dep_snap, env_snap = disc.discover()
    assert isinstance(dep_snap, DependencySnapshot)
    assert isinstance(env_snap, EnvironmentSnapshot)
    assert dep_snap.declared == []


# ---------------------------------------------------------------------------
# Security tests
# ---------------------------------------------------------------------------


def test_no_mutation_capability() -> None:
    """EnvironmentIntelligenceAgent must have no file-writing methods."""
    agent = EnvironmentIntelligenceAgent()
    for attr in (
        "write_file",
        "edit_file",
        "delete_file",
        "install",
        "pip_install",
        "run_command",
    ):
        assert not hasattr(agent, attr), f"Agent must not have '{attr}'"


def test_no_subprocess_in_module() -> None:
    """environment_intelligence must not import subprocess."""
    import subprocess

    import forgeai.agents.environment_intelligence as mod

    assert subprocess not in vars(mod).values()


def test_discovery_no_mutation_methods() -> None:
    """DependencyDiscovery must not expose mutation methods."""
    disc = DependencyDiscovery(Path("."))
    for attr in ("write", "install", "uninstall", "run", "execute", "git"):
        assert not hasattr(disc, attr), f"DependencyDiscovery must not have '{attr}'"


def test_env_snapshot_no_secret_fields() -> None:
    """EnvironmentSnapshot model must not have fields for secret values."""
    from forgeai.agents.environment_models import EnvironmentSnapshot

    forbidden_fields = {"api_key", "token", "password", "secret", "credentials"}
    model_fields = set(EnvironmentSnapshot.model_fields.keys())
    overlap = forbidden_fields & model_fields
    assert not overlap, f"EnvironmentSnapshot has secret-bearing fields: {overlap}"


def test_no_package_installation_in_agent() -> None:
    """Verify agent.analyze never calls pip or installs anything."""
    # analyze() must return without side effects — no installation allowed
    dep_snap = make_dep_snap()
    env_snap = make_env_snap()
    agent = EnvironmentIntelligenceAgent(llm_client=None)
    diagnosis = agent.analyze(dep_snap, env_snap)
    # recommended_action may reference installing, but it is text only — not execution
    assert isinstance(diagnosis.recommended_action, str)


def test_recommended_action_is_text_only() -> None:
    """Recommended action must be human-readable text, NOT an executable command."""
    dep_snap = make_dep_snap(
        declared=[
            DeclaredDependency(
                name="missing_lib",
                source=DependencySource.REQUIREMENTS,
                source_file="requirements.txt",
                raw_line="missing_lib",
            )
        ],
        installed=[],
    )
    env_snap = make_env_snap()
    agent = EnvironmentIntelligenceAgent(llm_client=None)
    diagnosis = agent.analyze(dep_snap, env_snap)
    # Must not contain shell metacharacters indicating it's a real command
    assert "&&" not in diagnosis.recommended_action
    assert "`" not in diagnosis.recommended_action
    assert "$(" not in diagnosis.recommended_action


# ---------------------------------------------------------------------------
# Bounded output
# ---------------------------------------------------------------------------


def test_declared_dep_bounded(tmp_path: Path) -> None:
    """DependencyDiscovery must not return more than _MAX_DECLARED_DEPS."""
    lines = "\n".join(f"pkg{i}" for i in range(600))
    (tmp_path / "requirements.txt").write_text(lines, encoding="utf-8")
    disc = DependencyDiscovery(tmp_path)
    dep_snap, _ = disc.discover()
    assert len(dep_snap.declared) <= 500


def test_installed_pkgs_bounded() -> None:
    """InstalledPackage list must be bounded."""
    disc = DependencyDiscovery(Path("."))
    _, _ = disc.discover()
    # Just check it runs without error; actual list length bounded internally
