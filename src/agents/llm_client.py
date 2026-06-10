from __future__ import annotations

import logging
import os
from typing import Protocol

LOGGER = logging.getLogger(__name__)

DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
MAX_LOG_ERROR_LENGTH = 200


class PartyAnswerLLM(Protocol):
    def generate_party_answer(self, *, party_name: str, question: str, evidence_context: str) -> str | None:
        """Generate a grounded party answer, or return None when LLM is unavailable."""


def _env_flag_enabled(raw_value: str | None) -> bool:
    return (raw_value or "").strip().lower() in {"1", "true", "yes", "on"}


def format_llm_error(exc: Exception) -> str:
    message = str(exc).replace("\n", " ").strip()
    if len(message) > MAX_LOG_ERROR_LENGTH:
        message = message[: MAX_LOG_ERROR_LENGTH - 3].rstrip() + "..."
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


class OpenAIPartyAnswerClient:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        raw_disable_llm = os.getenv("DISABLE_LLM")
        raw_api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY")
        raw_model = model if model is not None else os.getenv("OPENAI_MODEL")

        self.disable_llm = _env_flag_enabled(raw_disable_llm)
        self.api_key = (raw_api_key or "").strip()
        self.model = raw_model.strip() if raw_model and raw_model.strip() else DEFAULT_OPENAI_MODEL

        LOGGER.info(
            "LLM config: DISABLE_LLM=%r interpreted as %s.",
            raw_disable_llm,
            self.disable_llm,
        )
        if self.disable_llm:
            LOGGER.info("LLM disabled by DISABLE_LLM=%s; using deterministic fallback.", raw_disable_llm)
            return

        if not self.api_key:
            LOGGER.warning("OPENAI_API_KEY is not set; using deterministic fallback instead of LLM.")
            return

        if not raw_model or not raw_model.strip():
            LOGGER.info("OPENAI_MODEL is not set; using default OpenAI model: %s", self.model)
        LOGGER.info("LLM enabled; using OpenAI model: %s", self.model)

    def generate_party_answer(self, *, party_name: str, question: str, evidence_context: str) -> str | None:
        if self.disable_llm:
            return None
        if not self.api_key:
            return None

        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.api_key)
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"Du svarar som {party_name}, ett svenskt politiskt parti. "
                            "Använd endast givna officiella källutdrag. "
                            "Hitta inte på politik som inte stöds av källorna. "
                            "Om stödet är svagt, säg det. "
                            "Svara på svenska med 4-8 meningar. "
                            "Ange inga fejkade källhänvisningar."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Fråga: {question}\n\n"
                            "Officiella källutdrag:\n"
                            f"{evidence_context}\n\n"
                            "Svara kort och sakligt som partiet."
                        ),
                    },
                ],
                temperature=0.2,
            )
            answer = response.choices[0].message.content
            return answer.strip() if answer else None
        except Exception as exc:  # pragma: no cover - exact SDK/network failures vary.
            LOGGER.warning("LLM answer generation failed; using deterministic fallback: %s", format_llm_error(exc))
            return None
