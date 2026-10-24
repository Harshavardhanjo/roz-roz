"""Agent-only settings (model, limits, timeouts). Secrets and URLs stay in app.config.settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    local_agent_model: str = "claude-haiku-5-5"
    local_agent_max_tokens: int = 1024
    anthropic_base_url: str = "https://api.anthropic.com"

    liaison_max_tool_calls: int = 6
    liaison_timeout_s: float = 10.0
    treasurer_max_tool_calls: int = 4
    # Below the backend's 8 s outer timeout (app/services/treasurer.py) so the agent_run row is always closed.
    treasurer_timeout_s: float = 7.5

    tools_timeout_s: float = 8.0
    max_retry_after_s: float = 1.0


agent_settings = AgentSettings()
