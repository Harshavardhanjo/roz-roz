from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/rozroz"
    public_base_url: str = "http://localhost:8000"
    web_origin: str = "http://localhost:3000"
    tools_token: str = "change-me"
    # While true, web endpoints return the contract 2 example payloads (see app/stubs.py).
    use_stubs: bool = True

    grantex_api_key: str = ""
    grantex_agent_id: str = ""

    wa_phone_number_id: str = ""
    wa_access_token: str = ""
    wa_app_secret: str = ""
    wa_verify_token: str = "change-me"
    wa_graph_version: str = "v21.0"

    elevenlabs_api_key: str = ""
    elevenlabs_stt_model: str = "scribe_v1"

    agent_runtime: str = "local"  # "agenticorg" once access is confirmed
    agenticorg_base_url: str = ""
    agenticorg_api_key: str = ""
    liaison_agent_id: str = ""
    treasurer_agent_id: str = ""
    anthropic_api_key: str = ""


settings = Settings()
