"""Shared deterministic functions used by app, store and clients (single source of truth for validation)."""
import hashlib, json

SALT = "rfg-m1"


def price_for(i: int) -> int:
    return 100 + (i * 7919) % 900


def chk(tx_id: str) -> str:
    return hashlib.sha1((SALT + tx_id).encode()).hexdigest()[:8]


def item_index(tx_id: str, cache_keys: int) -> int:
    return int(hashlib.sha1(("i" + tx_id).encode()).hexdigest()[:6], 16) % cache_keys


def validate_tx(tx_id: str, body: bytes, cache_keys: int):
    """Return (valid, detail). HTTP 200 is NOT enough: payload must come from the primary path
    and carry the correct read-your-write value and the correct cached price."""
    try:
        j = json.loads(body)
    except Exception:
        return False, "bad_json"
    if j.get("id") != tx_id:
        return False, "id_mismatch"
    if j.get("source") != "primary":
        return False, "source=" + str(j.get("source"))
    if j.get("value") != chk(tx_id):
        return False, "value_mismatch"
    if j.get("price") != price_for(item_index(tx_id, cache_keys)):
        return False, "price_mismatch"
    return True, "ok"
