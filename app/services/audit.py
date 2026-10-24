"""Hash-chained audit log: hash = sha256(prev_hash + canonical JSON of the row)."""
import hashlib
import json

GENESIS = "genesis"


def canonical(row: dict) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def chain_hash(prev_hash: str | None, row: dict) -> str:
    return hashlib.sha256(((prev_hash or GENESIS) + canonical(row)).encode()).hexdigest()


def verify_chain(rows: list[dict]) -> bool:
    """rows: oldest first, each with 'prev_hash', 'hash' and its content fields."""
    prev = None
    for r in rows:
        content = {k: v for k, v in r.items() if k not in ("prev_hash", "hash")}
        if r.get("prev_hash") != prev or r["hash"] != chain_hash(prev, content):
            return False
        prev = r["hash"]
    return True

# TODO(Harsha): log(...) that reads the last hash and inserts an audit_log row in the caller's transaction.
