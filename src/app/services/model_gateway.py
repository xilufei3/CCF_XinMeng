import json
from dataclasses import dataclass
from typing import Any

import httpx

from src.app.config import settings


@dataclass(frozen=True)
class ModelRuntimeConfig:
    api_base: str
    api_key: str
    timeout_sec: int
    intent_model_name: str
    intent_temperature: float
    intent_max_tokens: int
    reply_model_name: str
    reply_temperature: float
    reply_max_tokens: int


def build_model_runtime_config() -> ModelRuntimeConfig:
    return ModelRuntimeConfig(
        api_base=settings.model_api_base.rstrip("/"),
        api_key=settings.model_api_key,
        timeout_sec=settings.model_timeout_sec,
        intent_model_name=settings.intent_model_name,
        intent_temperature=settings.intent_temperature,
        intent_max_tokens=settings.intent_max_tokens,
        reply_model_name=settings.reply_model_name,
        reply_temperature=settings.reply_temperature,
        reply_max_tokens=settings.reply_max_tokens,
    )


class ModelGateway:
    def __init__(self, cfg: ModelRuntimeConfig) -> None:
        self.cfg = cfg

    async def _chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        force_json: bool = False,
    ) -> str:
        if not self.cfg.api_key:
            raise RuntimeError("MODEL_API_KEY is empty; please configure model_api_key in .env")

        url = f"{self.cfg.api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if force_json:
            payload["response_format"] = {"type": "json_object"}

        timeout = httpx.Timeout(timeout=float(self.cfg.timeout_sec))
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        try:
            content = data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise RuntimeError(f"invalid model response schema: {data}") from exc

        if isinstance(content, str):
            return content
        if isinstance(content, list):
            # Compatible with multimodal-style content list.
            texts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text")
                    if isinstance(text, str):
                        texts.append(text)
            if texts:
                return "\n".join(texts)
        raise RuntimeError(f"unsupported model content payload: {content}")

    @staticmethod
    def _extract_text_from_delta_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text" and isinstance(item.get("text"), str):
                        texts.append(item["text"])
                    elif isinstance(item.get("content"), str):
                        texts.append(item["content"])
            return "".join(texts)
        return ""

    async def stream_reply_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ):
        if not self.cfg.api_key:
            raise RuntimeError("MODEL_API_KEY is empty; please configure model_api_key in .env")

        url = f"{self.cfg.api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.cfg.reply_model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.cfg.reply_temperature,
            "max_tokens": self.cfg.reply_max_tokens,
            "stream": True,
        }

        timeout = httpx.Timeout(timeout=float(self.cfg.timeout_sec))
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                resp.raise_for_status()

                buffer = ""
                async for piece in resp.aiter_text():
                    if not piece:
                        continue
                    buffer += piece
                    normalized = buffer.replace("\r\n", "\n")

                    while True:
                        split_at = normalized.find("\n\n")
                        if split_at == -1:
                            break
                        block = normalized[:split_at]
                        normalized = normalized[split_at + 2 :]

                        for line in block.split("\n"):
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if not data:
                                continue
                            if data == "[DONE]":
                                return
                            try:
                                payload = json.loads(data)
                            except Exception:
                                continue

                            choices = payload.get("choices")
                            if not isinstance(choices, list) or not choices:
                                continue
                            first = choices[0] if isinstance(choices[0], dict) else {}
                            delta = first.get("delta") if isinstance(first, dict) else None
                            if not isinstance(delta, dict):
                                continue
                            text = self._extract_text_from_delta_content(delta.get("content"))
                            if text:
                                yield text

                    buffer = normalized

    async def generate_intent_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        raw = await self._chat_completion(
            model=self.cfg.intent_model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.cfg.intent_temperature,
            max_tokens=self.cfg.intent_max_tokens,
            force_json=True,
        )
        return parse_json_payload(raw)

    async def generate_reply_text(self, *, system_prompt: str, user_prompt: str) -> str:
        return await self._chat_completion(
            model=self.cfg.reply_model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.cfg.reply_temperature,
            max_tokens=self.cfg.reply_max_tokens,
            force_json=False,
        )


def parse_json_payload(text: str) -> dict[str, Any]:
    # First pass: direct JSON
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass

    # Fallback: extract first {...} segment
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        chunk = text[start : end + 1]
        payload = json.loads(chunk)
        if isinstance(payload, dict):
            return payload
    raise ValueError(f"cannot parse json payload from model text: {text}")


_gateway: ModelGateway | None = None


def get_model_gateway() -> ModelGateway:
    global _gateway
    if _gateway is None:
        _gateway = ModelGateway(build_model_runtime_config())
    return _gateway
