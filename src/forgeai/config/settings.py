from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    omniroute_base_url: str | None = None
    omniroute_api_key: str | None = None
    omniroute_default_model: str | None = None

    github_token: str | None = None
    database_url: str | None = None

    agent_max_iterations: int = 10

    coding_max_iterations: int = 30
    coding_max_tool_calls: int = 100
    coding_max_repair_iterations: int = 5
    coding_max_changed_files: int = 20
    coding_max_validation_output: int = 10000
    coding_auto_commit: bool = False
    coding_run_validation: bool = True
    review_enabled: bool = True
    review_max_iterations: int = 3

    sandbox_image: str = "python:3.12-slim"
    sandbox_cpu_limit: float = 1.0
    sandbox_memory_limit_mb: int = 512
    sandbox_timeout_seconds: int = 30
    sandbox_network_enabled: bool = False
    sandbox_max_output_bytes: int = 1048576

    git_max_diff_bytes: int = 50000

    memory_enabled: bool = False
    memory_db_path: str = "~/.forgeai/memory.db"
    memory_max_execution_records: int = 100

    model_config = SettingsConfigDict(
        env_prefix="FORGEAI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
