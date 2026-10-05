import pytest

from companyos.agents.planning import Plan, PlannedTask, has_cycle, validate_plan
from companyos.observability import redact_secrets
from companyos.providers.llm import estimate_cost, local_embeddings
from companyos.security import SecretBox, csrf_matches, csrf_token_for, hash_password, verify_password
from companyos.services.knowledge import split_text

ROLES = {"market_researcher", "product_manager", "copywriter", "reviewer"}


def task(key: str, role: str = "product_manager", depends_on: list[str] | None = None) -> PlannedTask:
    return PlannedTask(
        key=f"t_{key}",
        title=f"Task {key}",
        role=role,
        instructions="Do the work properly.",
        depends_on=[f"t_{item}" for item in depends_on or []],
    )


def test_valid_plan_has_no_errors() -> None:
    plan = Plan(
        summary="ok",
        tasks=[task("a", "market_researcher"), task("b", depends_on=["a"]), task("c", "copywriter", ["a"])],
    )
    assert validate_plan(plan, ROLES) == []


def test_plan_detects_unknown_roles_dependencies_and_cycles() -> None:
    errors = validate_plan(Plan(summary="x", tasks=[task("a", "ceo"), task("b", depends_on=["zzz"])]), ROLES)
    assert any("unknown role" in error for error in errors)
    assert any("unknown task" in error for error in errors)
    cyclic = Plan(summary="x", tasks=[task("a", depends_on=["b"]), task("b", depends_on=["a"])])
    assert validate_plan(cyclic, ROLES) == ["Dependencies contain a cycle"]


def test_plan_rejects_automatic_roles() -> None:
    errors = validate_plan(Plan(summary="x", tasks=[task("a", "reviewer")]), ROLES)
    assert errors and "applied automatically" in errors[0]


def test_has_cycle() -> None:
    assert not has_cycle({"a": [], "b": ["a"], "c": ["a", "b"]})
    assert has_cycle({"a": ["c"], "b": ["a"], "c": ["b"]})


def test_password_hashing() -> None:
    hashed = hash_password("a-very-strong-password")
    assert hashed != "a-very-strong-password"
    assert verify_password(hashed, "a-very-strong-password")
    assert not verify_password(hashed, "wrong")


def test_csrf_token_is_bound_to_session() -> None:
    token = csrf_token_for("session-a")
    assert csrf_matches("session-a", token)
    assert not csrf_matches("session-b", token)
    assert not csrf_matches("session-a", None)


def test_secret_box_roundtrip_and_rotation() -> None:
    old_key = "Jq7sYd8vCw2h5m0ZqXGJ3fZ4tq0n7f3qk9QxR4m1bG8="
    new_key = "w8l0xRZb3o4k2G6yZ2X0k3qV7m9cN1pQ5sT8uY2aB4E="
    ciphertext = SecretBox([old_key]).encrypt("sk-test-secret")
    assert b"sk-test-secret" not in ciphertext
    assert SecretBox([new_key, old_key]).decrypt(ciphertext) == "sk-test-secret"
    with pytest.raises(RuntimeError):
        SecretBox([new_key]).decrypt(ciphertext)


def test_log_redaction() -> None:
    event = redact_secrets(
        None, "info", {"event": "x", "api_key": "sk-1", "nested": {"password": "p", "ok": 1}}
    )
    assert event["api_key"] == "[REDACTED]"
    assert event["nested"] == {"password": "[REDACTED]", "ok": 1}


def test_cost_estimation() -> None:
    assert estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000) == pytest.approx(0.75)
    assert estimate_cost("unknown-model", 1000, 1000) == 0


def test_text_chunking_and_local_embeddings() -> None:
    chunks = split_text("line\n" * 1000)
    assert len(chunks) > 1
    vectors = local_embeddings(["pricing strategy", "pricing strategy", "database"])
    assert len(vectors[0]) == 1536
    assert vectors[0] == vectors[1]
    assert vectors[0] != vectors[2]
