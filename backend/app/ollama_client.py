import logging
import os
from typing import Dict, List, Optional

import requests
from requests import RequestException


logger = logging.getLogger(__name__)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "").strip()
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gpt-oss:120b-cloud")
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "").strip()

DEFAULT_SYSTEM_PROMPT = (
    "You analyze soil boring logs and geotechnical data to answer questions accurately."
)

UNAVAILABLE_MSG = (
    "AI service unavailable: cannot reach Ollama. "
    "Set OLLAMA_URL (e.g., http://localhost:11434/api/chat) or disable AI features."
)
NOT_CONFIGURED_MSG = "AI service unavailable: OLLAMA_URL is not configured."


class AIUnavailableError(Exception):
    """Raised when the AI backend is not configured or cannot be reached."""


def ask_strict(
    question: str,
    context: Optional[str] = None,
    history: Optional[List[Dict[str, str]]] = None,
    timeout: int = 60,
    system: Optional[str] = None,
) -> str:
    """Ask the model; raise AIUnavailableError instead of returning an error string."""
    if not OLLAMA_URL:
        raise AIUnavailableError(NOT_CONFIGURED_MSG)

    system_text = system or DEFAULT_SYSTEM_PROMPT
    messages: List[Dict[str, str]] = [{"role": "system", "content": system_text}]
    if context:
        messages.append({"role": "user", "content": context})
    for turn in history or []:
        role = turn.get("role")
        content = turn.get("content") or ""
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})

    headers = {"Authorization": f"Bearer {OLLAMA_API_KEY}"} if OLLAMA_API_KEY else None
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "messages": messages, "stream": False},
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except (RequestException, ValueError) as exc:
        logger.warning("Ollama request failed: %s", exc)
        raise AIUnavailableError(UNAVAILABLE_MSG) from exc
    return ((data.get("message") or {}).get("content") or "").strip()


def ask(
    question: str,
    context: Optional[str] = None,
    history: Optional[List[Dict[str, str]]] = None,
    timeout: int = 60,
    system: Optional[str] = None,
) -> str:
    """Friendly variant: returns a readable message when the AI is unavailable."""
    try:
        return ask_strict(question, context, history, timeout, system)
    except AIUnavailableError as exc:
        return str(exc)
