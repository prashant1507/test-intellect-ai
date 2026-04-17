from pathlib import Path

from pydantic import field_validator
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
        "use_keycloak",
        mode="before",
    )
    @classmethod
    def _coerce_bool(cls, v: object) -> bool:
        return _env_bool(v)

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
    paste_mode_priorities: str = ""
    memory_similarity_threshold: float = 0.92


settings = Settings()
