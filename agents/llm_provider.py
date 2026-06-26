"""
LLM Provider Abstraction Layer
Supports: Gemini (google-genai), OpenAI, Anthropic, Ollama (local)
Settings are persisted in SQLite via the settings module.
"""
from __future__ import annotations
import json
import os
import requests
from typing import Any

# ─── Provider call implementations ────────────────────────────────────────────

def _call_gemini(messages: list[dict], model: str, api_key: str,
                 temperature: float, max_tokens: int,
                 response_schema: dict | None = None) -> str:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=api_key)

    # Convert messages to Gemini format
    contents = []
    system_instruction = None
    for m in messages:
        role = m["role"]
        content = m["content"]
        if role == "system":
            system_instruction = content
        elif role == "user":
            contents.append(types.Content(role="user", parts=[types.Part(text=content)]))
        elif role == "assistant":
            contents.append(types.Content(role="model", parts=[types.Part(text=content)]))

    config_kwargs: dict[str, Any] = {
        "temperature": temperature,
        "max_output_tokens": max_tokens,
    }
    if system_instruction:
        config_kwargs["system_instruction"] = system_instruction
    if response_schema:
        config_kwargs["response_mime_type"] = "application/json"

    config = types.GenerateContentConfig(**config_kwargs)
    response = client.models.generate_content(model=model, contents=contents, config=config)
    return response.text or ""


def _call_openai(messages: list[dict], model: str, api_key: str,
                 temperature: float, max_tokens: int,
                 response_schema: dict | None = None) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_schema:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


def _call_anthropic(messages: list[dict], model: str, api_key: str,
                    temperature: float, max_tokens: int,
                    response_schema: dict | None = None) -> str:
    import anthropic as ant
    client = ant.Anthropic(api_key=api_key)
    system_msg = ""
    filtered = []
    for m in messages:
        if m["role"] == "system":
            system_msg = m["content"]
        else:
            filtered.append(m)
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_msg,
        messages=filtered,
        temperature=temperature,
    )
    return resp.content[0].text if resp.content else ""


def _call_ollama(messages: list[dict], model: str, base_url: str,
                 temperature: float, max_tokens: int,
                 response_schema: dict | None = None) -> str:
    url = f"{base_url.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    if response_schema:
        payload["format"] = "json"
    resp = requests.post(url, json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()["message"]["content"]


# ─── Public interface ──────────────────────────────────────────────────────────

def call_llm(
    messages: list[dict],
    response_schema: dict | None = None,
    settings: dict | None = None,
) -> str:
    """
    Call the configured LLM provider.
    `settings` dict should have keys: provider, model_name, api_key,
    ollama_base_url, temperature, max_tokens, use_builtin.
    Falls back to env vars if settings is None.
    """
    if settings is None:
        settings = {}

    # Support both 'model' and 'model_name' keys for forward compatibility
    provider = settings.get("provider", "openai")
    model = settings.get("model_name") or settings.get("model", "gpt-4o-mini")
    temperature = float(settings.get("temperature", 0.1))
    max_tokens = int(settings.get("max_tokens", 2048))

    # Support 'google' as alias for 'gemini'
    if provider in ("gemini", "google"):
        api_key = settings.get("api_key") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY / GEMINI_API_KEY not set. Configure it in Settings.")
        return _call_gemini(messages, model, api_key, temperature, max_tokens, response_schema)

    elif provider == "openai":
        api_key = settings.get("api_key") or os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set. Configure it in Settings.")
        return _call_openai(messages, model, api_key, temperature, max_tokens, response_schema)

    elif provider == "anthropic":
        api_key = settings.get("api_key") or os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set. Configure it in Settings.")
        return _call_anthropic(messages, model, api_key, temperature, max_tokens, response_schema)

    elif provider == "ollama":
        base_url = settings.get("ollama_base_url") or settings.get("ollama_url") or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        return _call_ollama(messages, model, base_url, temperature, max_tokens, response_schema)

    else:
        raise ValueError(f"Unknown provider: {provider}")


def parse_json_response(text: str) -> dict:
    """Extract JSON from LLM response, stripping markdown fences if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last fence lines
        lines = [l for l in lines if not l.startswith("```")]
        text = "\n".join(lines).strip()
    return json.loads(text)
