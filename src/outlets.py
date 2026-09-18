"""Named API outlets: per-node API entry points.

configs/outlets.json lists the OpenAI-compatible endpoints a review node may
use. Each entry names its configuration through environment variables so
secrets never live in the JSON:

    {
      "key": "asking",
      "title": "AskSage",
      "base_url_env": "ASKSAGE_BASE_URL",
      "base_url_default": "https://api.asksage.ai/v1",
      "model_env": "ASKSAGE_MODEL",
      "model_default": "gpt-5.1-gov",
      "api_key_env": "ASKSAGE_API_KEY",
      "api_key_default": ""
    }

Resolution order per field: environment variable first, then the JSON
default. Before resolving, local keys are loaded once from every *.env file
under secrets/ (python-dotenv, override=False so the process environment
still wins). build_client(key) returns a client exposing chat_completion(...)
with the same shape llm_client.LLMClient exposes, so
pub_pipeline.ProviderAdapter wraps it unchanged. Unknown keys return None
and the caller falls back to the run-wide client.

ASCII/English only. No threads, no I/O beyond reading the registry.
"""

import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTLETS_PATH = os.path.join(BASE_DIR, "..", "configs", "outlets.json")
SECRETS_DIR = os.path.join(BASE_DIR, "..", "secrets")

_secrets_loaded = False


def _load_secrets():
    """Load local outlet keys from secrets/*.env once (idempotent).

    Keys live in the ignored secrets/ folder so they never enter the repo.
    Real environment variables are NOT overridden: python-dotenv's
    override=False keeps process-level values (e.g. injected by Docker)
    winning over the file.
    """
    global _secrets_loaded
    if _secrets_loaded:
        return
    _secrets_loaded = True
    try:
        from dotenv import load_dotenv
    except Exception:  # noqa: BLE001 - missing dotenv: rely on real env only
        return
    if not os.path.isdir(SECRETS_DIR):
        return
    try:
        for name in sorted(os.listdir(SECRETS_DIR)):
            if name.endswith(".env"):
                load_dotenv(os.path.join(SECRETS_DIR, name), override=False)
    except OSError:
        pass


def load_outlets():
    """Return the raw registry dict with graceful degradation."""
    if not os.path.isfile(OUTLETS_PATH):
        return {"schema_version": 1, "outlets": []}
    try:
        with open(OUTLETS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"schema_version": 1, "outlets": []}
    if not isinstance(data, dict):
        return {"schema_version": 1, "outlets": []}
    outlets = data.get("outlets")
    data["outlets"] = [o for o in (outlets or []) if isinstance(o, dict)]
    return data


def outlet_keys():
    """Return the ordered outlet keys."""
    return [o.get("key") for o in (load_outlets().get("outlets") or [])]


def outlet_titles():
    """Return {key: title} for the registry."""
    return {
        o.get("key"): (o.get("title") or o.get("key"))
        for o in (load_outlets().get("outlets") or [])
    }


def resolve_outlet(key):
    """Resolve one outlet to concrete connection values, or None.

    Returns {"key", "title", "base_url", "model", "api_key"} with the
    environment variable winning over the JSON default for every field.
    Local secrets under secrets/ are loaded first (see _load_secrets).
    """
    _load_secrets()
    for outlet in (load_outlets().get("outlets") or []):
        if outlet.get("key") != key:
            continue

        def _field(value_key, default_key):
            env_name = (outlet.get(value_key) or "").strip()
            value = os.getenv(env_name, "").strip() if env_name else ""
            if value:
                return value
            return (outlet.get(default_key) or "").strip()

        return {
            "key": key,
            "title": outlet.get("title") or key,
            "base_url": _field("base_url_env", "base_url_default"),
            "model": _field("model_env", "model_default"),
            "api_key": _field("api_key_env", "api_key_default"),
        }
    return None


class OutletClient:
    """Minimal OpenAI-compatible client for one named outlet.

    Exposes chat_completion(messages, temperature, max_tokens,
    model_override, timeout) so pub_pipeline.ProviderAdapter can wrap it
    exactly like llm_client.LLMClient. No automatic fallback: a node pinned
    to an outlet fails loudly if that outlet is unreachable.
    """

    def __init__(self, config):
        if not config or not config.get("base_url"):
            raise ValueError("Outlet has no base_url configured.")
        from openai import OpenAI

        self.key = config.get("key") or "outlet"
        self.title = config.get("title") or self.key
        self.base_url = config["base_url"]
        self.model = config.get("model") or ""
        self.api_key = config.get("api_key") or "sk-outlet"
        try:
            self.timeout = float(os.getenv("LLM_REQUEST_TIMEOUT", "240"))
        except ValueError:
            self.timeout = 240.0
        self.client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout,
        )

    def chat_completion(
        self,
        messages,
        temperature=0.1,
        max_tokens=4000,
        model_override=None,
        timeout=None,
    ):
        from llm_client import normalize_model_output

        response = self.client.chat.completions.create(
            model=model_override or self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout if timeout is not None else self.timeout,
        )
        message = response.choices[0].message
        return normalize_model_output(
            message.content,
            getattr(message, "reasoning_content", None),
            max_tokens,
        )


def build_client(key):
    """Return an OutletClient for key, or None when the key is unknown."""
    config = resolve_outlet(key)
    if config is None:
        return None
    return OutletClient(config)