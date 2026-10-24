"""Write app/agents/tool_schemas.json from the Pydantic tool models, so agent schemas never drift from contract 3."""

import json
from pathlib import Path

from app.schemas import TOOL_ARGS


def main() -> None:
    schemas = [{"name": name, "parameters": model.model_json_schema()} for name, model in TOOL_ARGS.items()]
    out = Path(__file__).resolve().parent.parent / "app" / "agents" / "tool_schemas.json"
    out.write_text(json.dumps(schemas, indent=2, ensure_ascii=False))
    print(f"wrote {len(schemas)} tools to {out}")


if __name__ == "__main__":
    main()
