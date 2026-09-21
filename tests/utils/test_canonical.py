import hashlib

from knowledge_gap_agent.utils.canonical import canonical_json, sha256_hex


def test_canonical_json_is_order_independent_and_compact():
    assert canonical_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'
    assert canonical_json({"a": 1, "b": 2}) == canonical_json({"b": 2, "a": 1})


def test_sha256_hex_canonicalizes_mapping_and_is_stable_lowercase_64_hex():
    value = {"b": 2, "a": 1}
    digest = sha256_hex(value)
    assert digest == sha256_hex({"a": 1, "b": 2})
    assert digest == hashlib.sha256(canonical_json(value).encode()).hexdigest()
    assert len(digest) == 64
    assert digest == digest.lower()
    assert all(char in "0123456789abcdef" for char in digest)
