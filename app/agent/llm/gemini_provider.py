"""Google Gemini via the official `google-genai` SDK, using native function calling.

Function calling is *manual*: automatic function calling is disabled, so Gemini only proposes
calls and the agent loop (app/agent/agent.py) validates, authorises and executes them. The
model's response `Content` is replayed verbatim on the next round, which preserves the
function-call ids and thought signatures that Gemini 3 models require.
"""

import json
import logging
from typing import Any

from google import genai
from google.genai import errors, types

from app.agent.llm.base import (
    AssistantText,
    LLMProvider,
    ModelTurn,
    ToolCall,
    ToolResults,
    ToolSpec,
    TranscriptItem,
    Usage,
    UserText,
)
from app.core.config import Settings
from app.core.errors import LLMUnavailableError

log = logging.getLogger(__name__)

REFUSAL_TEXT = "Sorry, I can't help with that request. If you think this is a mistake, I can open a ticket with our support team."
_BLOCKED = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"}
_MALFORMED = {"MALFORMED_FUNCTION_CALL", "UNEXPECTED_TOOL_CALL"}
_RETRY_STATUS = [429, 500, 502, 503, 504]


def _enum_name(value: Any) -> str | None:
    return None if value is None else getattr(value, "name", str(value))


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, settings: Settings, client: genai.Client | None = None):
        self.settings = settings
        self.model = settings.gemini_model
        self._config_cache: dict[int, types.GenerateContentConfig] = {}
        self._local_ids = 0
        if client is None:
            key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
            client = genai.Client(
                api_key=key,
                http_options=types.HttpOptions(
                    timeout=int(settings.gemini_timeout_seconds * 1000),  # SDK expects milliseconds
                    retry_options=types.HttpRetryOptions(
                        attempts=1 + settings.gemini_max_retries, http_status_codes=_RETRY_STATUS
                    ),
                ),
            )
        self.client = client

    # ---- request building ----

    def _config(self, system: str, tools: list[ToolSpec]) -> types.GenerateContentConfig:
        key = hash((system, tuple(t.name for t in tools)))
        if key not in self._config_cache:
            thinking = (
                types.ThinkingConfig(thinking_level=self.settings.gemini_thinking_level)
                if self.settings.gemini_thinking_level
                else None
            )
            self._config_cache[key] = types.GenerateContentConfig(
                system_instruction=system,
                tools=[
                    types.Tool(
                        function_declarations=[
                            types.FunctionDeclaration(name=t.name, description=t.description, parameters_json_schema=t.input_schema)
                            for t in tools
                        ]
                    )
                ],
                # Never let the SDK execute functions itself: the agent owns validation and auth.
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="AUTO")),
                max_output_tokens=self.settings.gemini_max_output_tokens,
                thinking_config=thinking,
            )
        return self._config_cache[key]

    @staticmethod
    def _to_contents(transcript: list[TranscriptItem]) -> list[types.Content]:
        contents: list[types.Content] = []
        for item in transcript:
            if isinstance(item, UserText):
                contents.append(types.Content(role="user", parts=[types.Part.from_text(text=item.text)]))
            elif isinstance(item, AssistantText):
                contents.append(types.Content(role="model", parts=[types.Part.from_text(text=item.text)]))
            elif isinstance(item, ToolResults):
                parts = [
                    types.Part(
                        function_response=types.FunctionResponse(
                            id=o.call.provider_call_id,
                            name=o.call.name,
                            # JSON round-trip guarantees a plain, serialisable dict.
                            response=json.loads(json.dumps(o.to_model_payload(), default=str)),
                        )
                    )
                    for o in item.outcomes  # all results of one round go back in ONE content
                ]
                # The Gemini API accepts only "user"/"model" roles; function responses go in a
                # user turn (verified live: role="tool" is rejected with HTTP 400).
                contents.append(types.Content(role="user", parts=parts))
            else:  # ModelTurn: replay exactly as received (ids, thought signatures)
                contents.append(item.raw)
        while contents and contents[0].role != "user":  # history window may start mid-dialogue
            contents.pop(0)
        return contents

    # ---- call ----

    def complete(self, system: str, transcript: list[TranscriptItem], tools: list[ToolSpec]) -> ModelTurn:
        contents = self._to_contents(transcript)
        config = self._config(system, tools)
        try:
            response = self.client.models.generate_content(model=self.model, contents=contents, config=config)
        except errors.ClientError as e:
            log.warning("Gemini client error %s %s", e.code, e.status)
            if e.code == 429:
                raise LLMUnavailableError("Gemini rate limit or quota exceeded.", details={"reason": "rate_limited"}) from e
            if e.code in (401, 403):
                raise LLMUnavailableError("Gemini rejected the API key.", details={"reason": "auth"}) from e
            if e.code == 404:
                raise LLMUnavailableError(f"Gemini model '{self.model}' not found.", details={"reason": "model_not_found"}) from e
            raise LLMUnavailableError(f"Gemini rejected the request ({e.code}).", details={"reason": "bad_request"}) from e
        except errors.APIError as e:  # 5xx after SDK retries
            log.warning("Gemini server error %s %s", e.code, e.status)
            raise LLMUnavailableError(f"Gemini server error ({e.code}).", details={"reason": "server_error"}) from e
        except Exception as e:  # timeouts and connection failures come from the HTTP layer
            log.warning("Gemini request failed: %s", type(e).__name__)
            raise LLMUnavailableError("Could not reach Gemini.", details={"reason": "unreachable"}) from e
        return self._parse(response)

    def _parse(self, response: types.GenerateContentResponse) -> ModelTurn:
        meta = response.usage_metadata
        usage = Usage()
        if meta is not None:
            usage.input_tokens = meta.prompt_token_count
            out = [n for n in (meta.candidates_token_count, meta.thoughts_token_count) if n is not None]
            usage.output_tokens = sum(out) if out else None
        model = getattr(response, "model_version", None) or self.model

        candidates = response.candidates or []
        if not candidates:  # prompt blocked before generation
            return self._refusal(usage, model)
        cand = candidates[0]
        finish = _enum_name(cand.finish_reason)
        if finish in _BLOCKED:
            return self._refusal(usage, model)
        if finish in _MALFORMED:
            raise LLMUnavailableError("Gemini produced a malformed function call.", details={"reason": "malformed"})

        parts = (cand.content.parts or []) if cand.content else []
        text = "".join(p.text for p in parts if p.text and not p.thought).strip()  # never surface thoughts
        calls = []
        for p in parts:
            if p.function_call is None:
                continue
            fc = p.function_call
            self._local_ids += 1
            calls.append(ToolCall(fc.id or f"gemini_{self._local_ids}", fc.name or "", dict(fc.args or {}), provider_call_id=fc.id))

        if finish == "MAX_TOKENS" and calls:
            raise LLMUnavailableError("Gemini response was truncated mid function call.", details={"reason": "truncated"})
        if not text and not calls:
            raise LLMUnavailableError("Gemini returned an empty response.", details={"reason": "empty"})
        return ModelTurn(text, calls, "tool_use" if calls else (finish or "STOP").lower(), model, usage, raw=cand.content)

    def _refusal(self, usage: Usage, model: str) -> ModelTurn:
        raw = types.Content(role="model", parts=[types.Part.from_text(text=REFUSAL_TEXT)])
        return ModelTurn(REFUSAL_TEXT, [], "refusal", model, usage, raw=raw)
