"""GeminiProvider with a fake google-genai client: request shape, parsing, error mapping, and
end-to-end agent behaviour (including provider failure after a state-changing tool ran).
No network access or API key is needed."""

import httpx
import pytest
from google.genai import errors, types

from app.agent.llm.base import AssistantText, ToolCall, ToolOutcome, ToolResults, ToolSpec, UserText
from app.agent.llm.gemini_provider import REFUSAL_TEXT, GeminiProvider
from app.agent.llm.offline_provider import OfflineProvider
from app.agent.tools.base import ToolResult
from app.container import ConfigurationError, build_providers
from app.core.config import Settings
from app.core.errors import LLMUnavailableError
from app.models import PasswordResetRequest
from app.models.enums import Route
from tests.conftest import as_user

SETTINGS = Settings(_env_file=None, gemini_api_key="test-key", ai_provider="gemini")
TOOLS = [ToolSpec("get_subscription", "Get plan", {"type": "object", "properties": {}, "additionalProperties": False, "required": []})]


class FakeModels:
    """Returns (or raises) scripted items in order and records every request."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests: list[dict] = []

    def generate_content(self, *, model, contents, config):
        self.requests.append({"model": model, "contents": list(contents), "config": config})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, *script):
        self.models = FakeModels(*script)


def response(*parts, finish="STOP", usage=(12, 5)):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)), finish_reason=finish)],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=usage[0], candidates_token_count=usage[1])
        if usage
        else None,
    )


def text(t, thought=False):
    return types.Part(text=t, thought=thought or None)


def call(name, args=None, id_="fc_1"):
    return types.Part(function_call=types.FunctionCall(id=id_, name=name, args=args or {}))


def provider(*script):
    client = FakeClient(*script)
    return GeminiProvider(SETTINGS, client=client), client.models


# ---------------- request shape ----------------


def test_request_uses_manual_function_calling_and_groups_tool_results():
    p, models = provider(response(text("ok")))
    outcomes = [
        ToolOutcome(ToolCall("a", "get_subscription", {}, provider_call_id="fc_a"), result=ToolResult(True, {"v": 1}, "s")),
        ToolOutcome(ToolCall("b", "list_invoices", {}, provider_call_id=None), error="boom"),
    ]
    p.complete("SYSTEM", [AssistantText("orphan"), UserText("hi"), AssistantText("hello"), UserText("plan?"), ToolResults(outcomes)], TOOLS)

    req = models.requests[0]
    cfg = req["config"]
    assert req["model"] == SETTINGS.gemini_model
    assert cfg.system_instruction == "SYSTEM"
    assert cfg.automatic_function_calling.disable is True  # the SDK never executes tools itself
    assert [f.name for f in cfg.tools[0].function_declarations] == ["get_subscription"]
    roles = [c.role for c in req["contents"]]
    assert roles == ["user", "model", "user", "user"]  # leading model turn dropped; results go in a user turn
    fr = [part.function_response for part in req["contents"][-1].parts]
    assert [(r.id, r.name) for r in fr] == [("fc_a", "get_subscription"), (None, "list_invoices")]
    assert fr[1].response == {"ok": False, "error": "boom"}


def test_model_content_is_replayed_verbatim():
    signed = types.Part(function_call=types.FunctionCall(id="fc_1", name="get_subscription", args={}), thought_signature=b"sig")
    p, models = provider(response(signed), response(text("done")))
    turn = p.complete("S", [UserText("plan?")], TOOLS)
    outcome = ToolOutcome(turn.tool_calls[0], result=ToolResult(True, {}, "s"))
    p.complete("S", [UserText("plan?"), turn, ToolResults([outcome])], TOOLS)
    replayed = models.requests[1]["contents"][1]
    assert replayed.parts[0].thought_signature == b"sig"


# ---------------- parsing ----------------


def test_parses_parallel_function_calls_and_usage():
    p, _ = provider(response(text("Checking."), call("get_subscription", id_="fc_1"), call("list_invoices", id_=None)))
    turn = p.complete("S", [UserText("x")], TOOLS)
    assert [c.name for c in turn.tool_calls] == ["get_subscription", "list_invoices"]
    assert turn.tool_calls[0].provider_call_id == "fc_1"
    assert turn.tool_calls[1].provider_call_id is None and turn.tool_calls[1].id.startswith("gemini_")
    assert (turn.usage.input_tokens, turn.usage.output_tokens) == (12, 5)


def test_thoughts_are_never_surfaced_and_missing_usage_stays_none():
    p, _ = provider(response(text("internal reasoning", thought=True), text("Answer."), usage=None))
    turn = p.complete("S", [UserText("x")], TOOLS)
    assert turn.text == "Answer."
    assert turn.usage.input_tokens is None and turn.usage.output_tokens is None


@pytest.mark.parametrize("finish", ["SAFETY", "PROHIBITED_CONTENT"])
def test_blocked_response_becomes_safe_refusal(finish):
    p, _ = provider(response(text("x"), finish=finish))
    turn = p.complete("S", [UserText("x")], TOOLS)
    assert turn.text == REFUSAL_TEXT and turn.tool_calls == []


def test_prompt_blocked_without_candidates():
    p, _ = provider(types.GenerateContentResponse(candidates=[]))
    assert p.complete("S", [UserText("x")], TOOLS).text == REFUSAL_TEXT


@pytest.mark.parametrize(
    "resp, reason",
    [
        (response(finish="MALFORMED_FUNCTION_CALL"), "malformed"),
        (response(), "empty"),
        (response(call("get_subscription"), finish="MAX_TOKENS"), "truncated"),
    ],
)
def test_unusable_responses_raise(resp, reason):
    p, _ = provider(resp)
    with pytest.raises(LLMUnavailableError) as exc:
        p.complete("S", [UserText("x")], TOOLS)
    assert exc.value.details["reason"] == reason


@pytest.mark.parametrize(
    "error, reason",
    [
        (errors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}), "rate_limited"),
        (errors.ClientError(403, {"error": {"code": 403, "message": "bad key", "status": "PERMISSION_DENIED"}}), "auth"),
        (errors.ClientError(404, {"error": {"code": 404, "message": "no model", "status": "NOT_FOUND"}}), "model_not_found"),
        (errors.ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}}), "server_error"),
        (httpx.ReadTimeout("timed out"), "unreachable"),
    ],
)
def test_provider_errors_map_to_llm_unavailable(error, reason):
    p, _ = provider(error)
    with pytest.raises(LLMUnavailableError) as exc:
        p.complete("S", [UserText("x")], TOOLS)
    assert exc.value.details["reason"] == reason
    assert "test-key" not in str(exc.value.message)


# ---------------- configuration ----------------


def test_gemini_mode_without_key_fails_fast():
    with pytest.raises(ConfigurationError, match="GEMINI_API_KEY"):
        build_providers(Settings(_env_file=None, ai_provider="gemini"))
    assert build_providers(Settings(_env_file=None, ai_provider="auto"))[0].name == "offline"
    primary, fallback = build_providers(SETTINGS)
    assert (primary.name, fallback.name) == ("gemini", "offline")


def test_api_key_is_not_exposed_by_settings_repr():
    assert "test-key" not in repr(SETTINGS) and "test-key" not in str(SETTINGS.model_dump())


# ---------------- end to end through the agent ----------------


def _container(make_container, *script, fallback=True):
    client = FakeClient(*script)
    c = make_container(GeminiProvider(SETTINGS, client=client), fallback=OfflineProvider() if fallback else None)
    return c, client.models


def test_gemini_selects_kb_tool_and_cites(make_container, session):
    c, models = _container(
        make_container,
        response(call("search_knowledge_base", {"query": "refund policy"})),
        response(text("Full refund within 14 days of your first payment [KB-1].")),
    )
    result = c.chat_service(session).send_message(1, "What is your refund policy?")
    assert result.reply.route == Route.KNOWLEDGE_BASE
    assert result.reply.citations == [1]
    assert result.reply.provider == "gemini" and result.reply.model_calls == 2
    assert (result.reply.input_tokens, result.reply.output_tokens) == (24, 10)
    assert len(models.requests) == 2


def test_failure_after_state_change_does_not_repeat_it(make_container, session):
    c, _ = _container(
        make_container,
        response(call("send_password_reset")),
        errors.ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}}),
    )
    result = c.chat_service(session).send_message(1, "Reset my password")
    assert result.reply.degraded is True and result.reply.fallback_reason == "server_error"
    assert result.reply.provider == "offline"
    assert "I've sent a password reset link" in result.reply.content  # reports what actually happened
    assert session.query(PasswordResetRequest).count() == 1  # and did not do it twice


def test_unavailable_without_fallback_returns_503(make_container, settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    c, _ = _container(
        make_container,
        errors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}),
        fallback=False,
    )
    with TestClient(create_app(settings, container=c)) as client:
        r = client.post("/api/v1/chat", json={"message": "hi"}, headers=as_user(1))
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "llm_unavailable"
