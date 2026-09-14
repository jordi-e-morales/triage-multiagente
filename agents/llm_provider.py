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


# ─── Ollama con esquema estricto y medición (demo de triage) ──────────────────

class ContextoInsuficiente(RuntimeError):
    """El prompt no cabe en la ventana de contexto configurada.

    Ollama, si el prompt excede `num_ctx`, lo recorta por el principio SIN
    avisar: el agente respondería sin haber leído parte del expediente. Aquí
    preferimos fallar ruidosamente (y fallar al preparar, no en escena).
    """


def call_ollama_estructurado(
    messages: list[dict],
    schema: dict,
    model: str,
    base_url: str,
    num_ctx: int,
    temperature: float = 0.2,
    max_tokens: int = 800,
    timeout_s: int = 600,
) -> dict:
    """
    Llama a Ollama exigiendo que la salida cumpla `schema` (JSON Schema).

    Diferencia con `_call_ollama`: allí se pide `format: "json"`, que solo
    garantiza JSON válido, no las claves correctas (en la prueba del cluster el
    modelo escribió "component" en vez de "componente"). Pasar el esquema
    completo hace que Ollama restrinja la generación a esa estructura.

    Devuelve el texto y las métricas que reporta Ollama, que son las que usa el
    presupuesto de tokens y la UI:
        texto, prompt_tokens, completion_tokens,
        carga_ms (subir el modelo a memoria), prefill_ms, generacion_ms, total_ms
    """
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "format": schema,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            # Ventana de contexto explícita. Si no se fija, Ollama usa un
            # valor por omisión chico y recorta sin avisar.
            "num_ctx": num_ctx,
        },
    }
    resp = requests.post(f"{base_url.rstrip('/')}/api/chat", json=payload, timeout=timeout_s)
    resp.raise_for_status()
    r = resp.json()

    ns_a_ms = 1e-6
    prompt_tokens = int(r.get("prompt_eval_count", 0))
    resultado = {
        "texto": r["message"]["content"],
        "prompt_tokens": prompt_tokens,
        "completion_tokens": int(r.get("eval_count", 0)),
        "carga_ms": int(r.get("load_duration", 0) * ns_a_ms),
        "prefill_ms": int(r.get("prompt_eval_duration", 0) * ns_a_ms),
        "generacion_ms": int(r.get("eval_duration", 0) * ns_a_ms),
        "total_ms": int(r.get("total_duration", 0) * ns_a_ms),
        # done_reason == "length": se acabó max_tokens antes de terminar; el
        # JSON viene cortado. Mejor decirlo así que como "JSON inválido".
        "truncada": r.get("done_reason") == "length",
    }

    # Si el prompt ocupó la ventana casi completa, lo más probable es que
    # Ollama haya recortado. No hay un campo explícito que lo diga, así que se
    # usa este margen conservador.
    if prompt_tokens + max_tokens > num_ctx:
        raise ContextoInsuficiente(
            f"prompt de {prompt_tokens} tokens + {max_tokens} de respuesta no caben en num_ctx={num_ctx}"
        )
    return resultado


def parse_json_response(text: str) -> dict:
    """Extract JSON from LLM response, stripping markdown fences if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last fence lines
        lines = [l for l in lines if not l.startswith("```")]
        text = "\n".join(lines).strip()
    return json.loads(text)
