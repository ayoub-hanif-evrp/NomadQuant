"""Local-only Ollama client built on the standard library.

The base URL must be loopback. Proxies and redirects are disabled so a request
cannot leave the machine by accident.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import Message
from typing import IO, Any

from nomadquant.config import DEFAULT_OLLAMA_URL, validate_ollama_base_url

MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class OllamaError(RuntimeError):
    """Base class for provider failures."""


class OllamaUnavailableError(OllamaError):
    """The local Ollama server could not be reached."""


class OllamaResponseError(OllamaError):
    """Ollama answered, but the answer is unusable."""


@dataclass(frozen=True)
class CallMetrics:
    model: str
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None


class OllamaProvider:
    def __init__(
        self, base_url: str = DEFAULT_OLLAMA_URL, *, default_timeout: float = 120.0
    ) -> None:
        self.base_url = validate_ollama_base_url(base_url)
        self.default_timeout = default_timeout
        self.last_call: CallMetrics | None = None
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def list_models(self, timeout: float = 5.0) -> list[str]:
        return sorted(item["name"] for item in self.list_model_details(timeout=timeout))

    def list_model_details(self, timeout: float = 5.0) -> list[dict[str, Any]]:
        payload = self._request("GET", "/api/tags", None, timeout)
        models = payload.get("models")
        if not isinstance(models, list):
            raise OllamaResponseError("Ollama /api/tags returned no model list.")
        details: list[dict[str, Any]] = []
        for item in models:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            details.append(
                {
                    "name": item["name"],
                    "digest": str(item.get("digest") or ""),
                    "size": item.get("size") if isinstance(item.get("size"), int) else None,
                    "modified_at": str(item.get("modified_at") or ""),
                    "family": _model_family(item),
                    "parameter_size": _model_parameter_size(item),
                }
            )
        return details

    def model_digest(self, model: str, timeout: float = 5.0) -> str:
        """Return the installed model digest from /api/tags, or empty string."""
        for item in self.list_model_details(timeout=timeout):
            if item["name"] == model and item["digest"]:
                return str(item["digest"])
        return ""

    def health(self, timeout: float = 2.0) -> dict[str, Any]:
        """Never raises. Reports reachability and installed models."""
        started = time.monotonic()
        try:
            models = self.list_models(timeout=timeout)
        except OllamaError as exc:
            return {
                "available": False,
                "base_url": self.base_url,
                "models": [],
                "latency_ms": _elapsed_ms(started),
                "error": str(exc),
            }
        return {
            "available": True,
            "base_url": self.base_url,
            "models": models,
            "latency_ms": _elapsed_ms(started),
            "error": "",
        }

    def chat_json(
        self,
        model: str,
        messages: list[dict[str, str]],
        schema_hint: dict[str, Any] | None = None,
        timeout: float | None = None,
        *,
        num_ctx: int | None = None,
    ) -> dict[str, Any]:
        """Send a non-streaming chat and return the validated JSON object reply."""
        if not model.strip():
            raise OllamaError("A model name is required.")
        options: dict[str, Any] = {"temperature": 0}
        if num_ctx is not None:
            if num_ctx not in {4096, 8192, 16384}:
                raise OllamaError("num_ctx must be 4096, 8192, or 16384.")
            options["num_ctx"] = num_ctx
        body = {
            "model": model,
            "messages": messages,
            "stream": False,
            "format": schema_hint if schema_hint else "json",
            # Prefer concrete JSON answers over private thinking traces.
            "think": False,
            "options": options,
        }
        started = time.monotonic()
        payload = self._request(
            "POST", "/api/chat", body, self.default_timeout if timeout is None else timeout
        )
        latency = _elapsed_ms(started)
        message = payload.get("message")
        content = _message_text(message)
        if not content:
            raise OllamaResponseError("Ollama reply contained no message content.")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            extracted = _extract_json_object(content)
            if extracted is None:
                raise OllamaResponseError("Model reply was not valid JSON.") from None
            parsed = extracted
        if not isinstance(parsed, dict):
            raise OllamaResponseError("Model reply must be a JSON object.")
        _check_required(parsed, schema_hint)
        self.last_call = CallMetrics(
            model=model,
            latency_ms=latency,
            prompt_tokens=_int_or_none(payload.get("prompt_eval_count")),
            completion_tokens=_int_or_none(payload.get("eval_count")),
        )
        return parsed

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None, timeout: float
    ) -> dict[str, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310 - scheme and host validated above
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise OllamaResponseError(f"Ollama returned HTTP {exc.code} for {path}.") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise OllamaUnavailableError(
                f"Ollama is unreachable at {self.base_url} ({type(reason).__name__}). "
                "Start it with `ollama serve`."
            ) from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise OllamaResponseError("Ollama response exceeded the size limit.")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OllamaResponseError("Ollama returned a non-JSON body.") from exc
        if not isinstance(parsed, dict):
            raise OllamaResponseError("Ollama returned an unexpected body.")
        return parsed


def _model_family(item: dict[str, Any]) -> str:
    details = item.get("details")
    if isinstance(details, dict):
        family = details.get("family")
        if isinstance(family, str):
            return family
    return ""


def _model_parameter_size(item: dict[str, Any]) -> str:
    details = item.get("details")
    if isinstance(details, dict):
        size = details.get("parameter_size")
        if isinstance(size, str):
            return size
    return ""


def _check_required(parsed: dict[str, Any], schema_hint: dict[str, Any] | None) -> None:
    if not schema_hint:
        return
    required = schema_hint.get("required")
    if isinstance(required, list):
        missing = [key for key in required if isinstance(key, str) and key not in parsed]
        if missing:
            raise OllamaResponseError("Model reply is missing keys: " + ", ".join(missing))


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _message_text(message: object) -> str:
    if not isinstance(message, dict):
        return ""
    for key in ("content", "thinking", "reasoning"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None
