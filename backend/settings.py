from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV = Path(__file__).resolve().parent.parent / ".env"


def _env_bool(v: object) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("0", "false", "no", "off", ""):
            return False
        if s in ("1", "true", "yes", "on"):
            return True
        return bool(s)
    return bool(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV,
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=False,
    )

    @field_validator(
        "jira_link_inward_is_requirement",
        "jira_verify_ssl",
        "mock",
        "show_memory_ui",
        "show_audit_ui",
        "show_jira_mode_ui",
        "show_paste_requirements_mode_ui",
        "show_auto_tests_ui",
        "use_keycloak",
        "llm_requirement_images_enabled",
        "automation_spike_prerun",
        "automation_post_analysis",
        "automation_write_run_html",
        mode="before",
    )
    @classmethod
    def _coerce_bool(cls, v: object) -> bool:
        return _env_bool(v)

    @model_validator(mode="after")
    def at_least_one_requirement_mode(self) -> "Settings":
        if not (
            self.show_jira_mode_ui
            or self.show_paste_requirements_mode_ui
            or self.show_auto_tests_ui
        ):
            self.show_jira_mode_ui = True
        return self

    jira_url: str = ""
    jira_username: str = ""
    jira_password: str = ""
    jira_verify_ssl: bool = True
    jira_test_project_key: str = ""
    jira_test_issue_type: str = "Test"
    jira_test_link_type: str = "Relates"
    jira_link_inward_is_requirement: bool = True
    jira_linked_work_issue_types: str = ""
    mock: bool = False
    show_memory_ui: bool = True
    show_audit_ui: bool = True
    show_jira_mode_ui: bool = True
    show_paste_requirements_mode_ui: bool = True
    use_keycloak: bool = False
    keycloak_url: str = ""
    keycloak_internal_url: str = ""
    keycloak_realm: str = ""
    keycloak_client_id: str = ""
    keycloak_client_secret: str = ""
    keycloak_idle_timeout_minutes: int = 5
    llm_url: str = ""
    llm_model: str = ""
    llm_access_token: str = ""
    llm_requirement_images_enabled: bool = False
    llm_requirement_images_max_count: int = 5
    llm_requirement_images_max_total_mb: int = 200
    paste_mode_priorities: str = ""
    memory_similarity_threshold: float = 0.92
    show_auto_tests_ui: bool = True
    automation_post_analysis: bool = True
    automation_write_run_html: bool = True
    automation_default_timeout_ms: int = 30_000
    automation_parallel_execution: int = 1
    automation_db_path: str = "data/automation/selectors.db"
    automation_artifacts_dir: str = "data/automation/runs"
    automation_reports_dir: str = "data/automation/reports"
    automation_retention_days: int = 20
    automation_spike_prerun: bool = True
    @field_validator("automation_db_path", mode="before")
    @classmethod
    def _automation_db_path(cls, v: object) -> str:
        s = (str(v or "").strip() or "data/automation/selectors.db").strip()
        p = Path(s)
        if p.is_absolute():
            return s
        return str((Path(__file__).resolve().parent.parent / s).resolve())
    @field_validator("automation_artifacts_dir", mode="before")
    @classmethod
    def _automation_artifacts_dir(cls, v: object) -> str:
        s = (str(v or "").strip() or "data/automation/runs").strip()
        p = Path(s)
        if p.is_absolute():
            return s
        return str((Path(__file__).resolve().parent.parent / s).resolve())
    @field_validator("automation_reports_dir", mode="before")
    @classmethod
    def _automation_reports_dir(cls, v: object) -> str:
        s = (str(v or "").strip() or "data/automation/reports").strip()
        p = Path(s)
        if p.is_absolute():
            return s
        return str((Path(__file__).resolve().parent.parent / s).resolve())
    @field_validator("automation_default_timeout_ms", mode="before")
    @classmethod
    def _automation_timeout(cls, v: object) -> int:
        n = int(v or 30_000)
        return min(max(n, 1000), 600_000)
    @field_validator("automation_parallel_execution", mode="before")
    @classmethod
    def _automation_parallel(cls, v: object) -> int:
        n = int(v or 1)
        return min(max(n, 1), 4)
    @field_validator("automation_retention_days", mode="before")
    @classmethod
    def _automation_retention_days(cls, v: object) -> int:
        if v is None or (isinstance(v, str) and not str(v).strip()):
            return 20
        n = int(v)
        return min(max(n, 0), 3650)


settings = Settings()
