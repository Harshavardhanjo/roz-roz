"""Agent-only settings (model, limits, timeouts). Secrets and URLs stay in app.config.settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    local_agent_model: str = "claude-haiku-5-5"
    local_agent_max_tokens: int = 1024
    anthropic_base_url: str = "https://api.anthropic.com"

    liaison_max_tool_calls: int = 6
    # Covers a create_* call that runs the treasurer inside it (tools_timeout_s) plus the model turns around it, and
    # stays well under Vercel's 60 s function limit together with download and STT.
    liaison_timeout_s: float = 30.0
    treasurer_max_tool_calls: int = 4
    # Below the backend's 8 s outer timeout (app/services/treasurer.py) so the agent_run row is always closed.
    treasurer_timeout_s: float = 7.5

    # Above the backend's 8 s treasurer budget plus its code fallback: a create_* tool call runs the treasurer inline,
    # and timing out first would create the request but reply "not understood" (and the helper would ask again).
    tools_timeout_s: float = 15.0
    max_retry_after_s: float = 1.0


agent_settings = AgentSettings()
