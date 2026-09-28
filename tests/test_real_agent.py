"""Offline contract tests for the optional NarrativeHealth adapter (no credentials)."""
from unittest.mock import patch

import httpx
import pytest

from app.config import Settings
from app.real_agent import ask_real_llm, estimate_max_cost


def settings(**overrides):
    defaults = dict(
        agent_api_key="test-key", real_agent_enabled=True,
        database_url="postgresql://readonly@db/narrative", llm_primary_base_url="https://primary.example/v1",
        llm_primary_api_key="key-not-real", llm_primary_model="model-1",
        llm_secondary_base_url="https://secondary.example/v1", llm_secondary_api_key="other-not-real",
        llm_secondary_model="model-2",
        llm_max_input_usd_per_million=1, llm_max_output_usd_per_million=2,
    )
    return Settings(_env_file=None, **(defaults | overrides))


def test_estimate_reserves_all_rounds():
    cfg = settings(llm_max_input_tokens=1000, llm_max_output_tokens=100,
                   llm_max_input_usd_per_million=1, llm_max_output_usd_per_million=2)
    assert estimate_max_cost(cfg) == pytest.approx(8 * (1000 + 200) / 1_000_000)


def test_fallback_tool_round_and_total_usage():
    calls = []

    def handler(request):
        body = __import__("json").loads(request.content)
        calls.append((str(request.url), body))
        if "primary.example" in str(request.url):
            return httpx.Response(503, json={"error": "failed"})
        if len([c for c in calls if "secondary.example" in c[0]]) == 1:
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": None,
                "tool_calls": [{"id": "tool-1", "type": "function", "function": {"name": "get_coin_health", "arguments": '{"symbol":"BTC"}'}}]}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10}})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "BTC dựa trên dữ liệu ngày gần nhất."}}],
            "usage": {"prompt_tokens": 125, "completion_tokens": 25}})

    real_client = httpx.Client

    def client_factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    with patch("app.real_agent.httpx.Client", side_effect=client_factory), patch(
        "app.real_agent._db_tool", return_value={"symbol": "BTC", "date": "2026-09-01", "health_score": 55}
    ) as db_tool:
        result = ask_real_llm("Điểm BTC?", [], settings())

    db_tool.assert_called_once()
    assert result["tokens_in"] == 225 and result["tokens_out"] == 35
    assert result["provider"] == "secondary"
    assert any(msg["role"] == "tool" for msg in calls[-1][1]["messages"])
    assert len(calls) == 4  # two primary errors, two secondary responses
    assert result["answer"].startswith("BTC")


def test_missing_config_does_not_contact_network():
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="provider"):
        ask_real_llm("hi", [], settings(llm_primary_model="", llm_secondary_model=""))


def completion(content="Hello", usage=None, calls=None):
    message = {"role": "assistant", "content": content}
    if calls is not None:
        message["tool_calls"] = calls
    body = {"choices": [{"message": message}]}
    if usage is not None:
        body["usage"] = usage
    return body


def run_mock(handler, cfg=None):
    real_client = httpx.Client
    with patch("app.real_agent.httpx.Client", side_effect=lambda **kw: real_client(
        transport=httpx.MockTransport(handler), **kw
    )):
        return ask_real_llm("Điểm BTC?", [], cfg or settings())


def test_missing_usage_is_charged_not_free():
    from app.real_agent import _attempt_ceiling
    cfg = settings()
    result = run_mock(lambda r: httpx.Response(200, json=completion()), cfg)
    assert result["usage_complete"] is False
    assert result["cost_usd"] == pytest.approx(_attempt_ceiling(cfg))


def test_both_providers_fail_accounts_attempts_without_leaking_secret():
    from app.real_agent import AgentFailure, _attempt_ceiling
    cfg = settings()
    with pytest.raises(AgentFailure) as error:
        run_mock(lambda r: httpx.Response(500, text="secret upstream response"), cfg)
    assert "secret upstream response" not in str(error.value)
    assert error.value.cost_usd == pytest.approx(2 * _attempt_ceiling(cfg))


def test_final_synthesis_has_no_null_tools():
    bodies = []
    import json

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if len(bodies) < 4:
            return httpx.Response(200, json=completion(None, {"prompt_tokens": 1, "completion_tokens": 1}, [
                {"id": f"t{len(bodies)}", "type": "function", "function": {"name": "unknown", "arguments": "{}"}}
            ]))
        return httpx.Response(200, json=completion("No data"))

    with patch("app.real_agent.psycopg.connect", side_effect=AssertionError("No DB for unknown tool")):
        assert run_mock(handler)["answer"] == "No data"
    assert len(bodies) == 4
    assert "tools" not in bodies[-1] and "tool_choice" not in bodies[-1]
    assert bodies[-1]["messages"][-1]["role"] == "tool"


def test_excess_parallel_tools_do_not_touch_db():
    from app.real_agent import AgentFailure
    calls = [{"id": str(i), "function": {"name": "get_coin_health", "arguments": '{"symbol":"BTC"}'}} for i in range(5)]
    with patch("app.real_agent._db_tool") as tool, pytest.raises(AgentFailure):
        run_mock(lambda r: httpx.Response(200, json=completion(None, calls=calls)))
    tool.assert_not_called()


def test_context_limit_is_checked_before_paid_attempt():
    from app.real_agent import AgentFailure
    with pytest.raises(AgentFailure) as error:
        run_mock(lambda r: pytest.fail("Must not contact provider"), settings(llm_max_input_tokens=1000))
    assert error.value.cost_usd == 0


def test_invalid_config_and_secret_redaction():
    from pydantic import ValidationError
    for overrides in (
        {"llm_primary_base_url": "http://insecure.example"},
        {"llm_primary_base_url": "https://host/v1/chat/completions"},
        {"llm_secondary_model": ""},
        {"llm_max_output_usd_per_million": None},
        {"llm_max_output_usd_per_million": -1},
        {"database_url": "not-a-postgres-url-with-secret"},
    ):
        with pytest.raises(ValidationError) as error:
            settings(**overrides)
        assert "not-a-postgres-url-with-secret" not in str(error.value)
    assert "key-not-real" not in repr(settings())


def test_db_is_readonly_and_queries_are_parameterized():
    from unittest.mock import MagicMock
    from app.real_agent import _db_tool
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = {"symbol": "BTC", "date": "2026-09-01"}
    with patch("app.real_agent.psycopg.connect") as connect:
        connect.return_value.__enter__.return_value = connection
        malicious = "X'; DROP TABLE coins; --"
        _db_tool("get_coin_health", {"symbol": malicious}, "postgresql://unused")
    assert connection.read_only is True
    query, params = cursor.execute.call_args.args
    assert malicious.upper() not in query
    assert params == (malicious.upper(),)
    assert "%s" in query and "public.coins" in query
    assert cursor.execute.call_args_list[0].args[0].startswith("SET LOCAL statement_timeout")


def test_tool_output_remains_valid_json_on_overflow():
    import json
    from app.real_agent import _tool_text
    assert "error" in json.loads(_tool_text({"reason": "x" * 5000}))


def test_reservation_refund_idempotent_and_month_rollover(fake_redis, monkeypatch):
    from app.cost_guard import CostGuard
    guard = CostGuard(fake_redis, 1)
    monkeypatch.setattr(CostGuard, "current_month", staticmethod(lambda: "2026-09"))
    receipt = guard.reserve("u", .8, global_budget=1)
    monkeypatch.setattr(CostGuard, "current_month", staticmethod(lambda: "2026-10"))
    guard.settle(receipt, .2)
    guard.settle(receipt, .2)
    assert guard.spent("u", "2026-09") == pytest.approx(.2)
    assert guard.spent("u", "2026-10") == 0
    assert float(fake_redis.get("global-cost:2026-09")) == pytest.approx(.2)
    assert fake_redis.get("global-cost:2026-10") is None


def test_global_budget_cannot_be_bypassed_with_new_user(fake_redis):
    from app.cost_guard import CostGuard
    from fastapi import HTTPException
    guard = CostGuard(fake_redis, 10)
    receipt = guard.reserve("first", .8, global_budget=1)
    with pytest.raises(HTTPException) as error:
        guard.reserve("new-user", .8, global_budget=1)
    assert error.value.status_code == 402
    guard.settle(receipt, .1)
    guard.reserve("new-user", .8, global_budget=1)


def test_overage_is_recorded_instead_of_discarded(fake_redis):
    from app.cost_guard import CostGuard
    from fastapi import HTTPException
    guard = CostGuard(fake_redis, 1)
    receipt = guard.reserve("u", .5, global_budget=1)
    guard.settle(receipt, 1.2)
    assert guard.spent("u") == pytest.approx(1.2)
    with pytest.raises(HTTPException):
        guard.reserve("different-user", .01, global_budget=1)


def test_concurrent_reservations_share_budget(fake_redis):
    from concurrent.futures import ThreadPoolExecutor
    from app.cost_guard import CostGuard
    from fastapi import HTTPException
    guard = CostGuard(fake_redis, 1)

    def reserve(i):
        try:
            return guard.reserve(str(i), .6, global_budget=1)
        except HTTPException:
            return None

    with ThreadPoolExecutor(max_workers=5) as pool:
        outcomes = list(pool.map(reserve, range(10)))
    assert sum(x is not None for x in outcomes) == 1


def test_http_real_mode_records_partial_failure_and_preserves_history(client, fake_redis, auth_headers, monkeypatch):
    from app import main
    from app.real_agent import AgentFailure
    from app.cost_guard import CostGuard
    monkeypatch.setattr(main, "get_settings", lambda: settings())
    with patch("app.real_agent.ask_real_llm", side_effect=AgentFailure("redacted", .01, 10, 2)):
        response = client.post("/ask", json={"question": "BTC?"}, headers=auth_headers)
    assert response.status_code == 502
    assert CostGuard(fake_redis, 10).spent("sv-test") == pytest.approx(.01)
    assert main.app.dependency_overrides[main.get_store]().get_history("sv-test") == []


def test_http_auth_and_budget_reject_before_llm(client, fake_redis, auth_headers, monkeypatch):
    from app import main
    from app.cost_guard import CostGuard
    monkeypatch.setattr(main, "get_settings", lambda: settings())
    with patch("app.real_agent.ask_real_llm") as call:
        assert client.post("/ask", json={"question": "BTC?"}).status_code == 401
        fake_redis.set(CostGuard._key("sv-test"), "999")
        assert client.post("/ask", json={"question": "BTC?"}, headers=auth_headers).status_code == 402
    call.assert_not_called()


def test_http_real_success_and_redis_history(client, fake_redis, auth_headers, monkeypatch):
    from app import main
    from app.cost_guard import CostGuard
    monkeypatch.setattr(main, "get_settings", lambda: settings())
    result = {"answer": "BTC: dữ liệu ngày 2026-09-01", "cost_usd": .001,
              "tokens_in": 100, "tokens_out": 10, "provider": "primary",
              "usage_complete": True, "tools_used": ["get_coin_health"]}
    with patch("app.real_agent.ask_real_llm", return_value=result) as call:
        first = client.post("/ask", json={"question": "BTC?"}, headers=auth_headers)
        second = client.post("/ask", json={"question": "Ngày nào?"}, headers=auth_headers)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["provider"] == "primary"
    assert second.json()["history_length"] == 2
    assert len(call.call_args.args[1]) == 2
    assert CostGuard(fake_redis, 10).spent("sv-test") == pytest.approx(.002)


def test_slow_or_broken_db_does_not_leak_credentials():
    import psycopg
    import json
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        if count == 1:
            return httpx.Response(200, json=completion(None, calls=[{
                "id": "t1", "type": "function", "function": {
                    "name": "get_coin_health", "arguments": '{"symbol":"BTC"}'}}]))
        body = json.loads(request.content)
        assert "db-secret-do-not-leak" not in json.dumps(body)
        assert "unavailable" in body["messages"][-1]["content"]
        return httpx.Response(200, json=completion("DB unavailable, no data."))
    with patch("app.real_agent._db_tool", side_effect=psycopg.OperationalError("db-secret-do-not-leak")):
        assert "unavailable" in run_mock(handler)["answer"]


def test_mock_settings_and_driver_are_independent():
    # Mock is default; no provider or DB is necessary.
    cfg = Settings(_env_file=None, agent_api_key="offline", real_agent_enabled=False)
    assert cfg.real_agent_enabled is False


def test_lifespan_validates_and_closes_cleanly():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
