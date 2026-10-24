from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/rozroz"
    public_base_url: str = "http://localhost:8000"
    # Comma-separated list of origins allowed by CORS (the Next.js app).
    web_origin: str = "http://localhost:3000"
    tools_token: str = "change-me"
    admin_token: str = "change-me-admin"
    # true: serve the contract 2 / 3 example payloads (app/stub_api.py) instead of the real API.
    use_stubs: bool = False
    # In-process payday job. Off on serverless hosts, where Vercel Cron calls /api/cron/payday instead.
    enable_scheduler: bool = True
    # Vercel sends "Authorization: Bearer <CRON_SECRET>" on cron calls; the endpoint refuses everything else.
    cron_secret: str = ""
    # Set automatically by Vercel ("1"): no long-lived process, so no connection pool and no in-process scheduler.
    vercel: str = ""
    # Pin "today" (YYYY-MM-DD) for rehearsals and tests; empty = the real date in IST.
    today_override: str | None = None

    grantex_api_key: str = ""
    grantex_agent_id: str = ""

    wa_phone_number_id: str = ""
    wa_access_token: str = ""
    wa_app_secret: str = ""
    wa_verify_token: str = "change-me"
    wa_graph_version: str = "v21.0"
    # The Indian WhatsApp Business number helpers message, digits with country code (e.g. 9198xxxxxxxx).
    wa_business_number: str = ""

    elevenlabs_api_key: str = ""
    elevenlabs_stt_model: str = "scribe_v1"

    # off: the backend runs the treasurer steps itself. agenticorg | local: try the agent first (8 s), then fall back.
    agent_runtime: str = "off"
    agenticorg_base_url: str = ""
    agenticorg_api_key: str = ""
    liaison_agent_id: str = ""
    treasurer_agent_id: str = ""
    anthropic_api_key: str = ""

    # Demo seed (seed/demo_seed.py).
    demo_helper_e164: str = "+910000000001"
    demo_helper2_e164: str = "+910000000002"

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, url: str) -> str:
        """Accept Render's 'postgres://' / 'postgresql://' URLs as-is; SQLAlchemy needs the psycopg 3 driver named."""
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url

    @property
    def serverless(self) -> bool:
        return self.vercel == "1"

    @property
    def web_origins(self) -> list[str]:
        return [o.strip() for o in self.web_origin.split(",") if o.strip()]


settings = Settings()
