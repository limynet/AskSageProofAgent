"""
LLM Client Module with a Two-Outlet Provider Architecture.

This module provides the LLM access layer for the manuscript-review app.
The product exposes exactly two outlets, implemented as a small provider
registry (a dict of provider name to config) so that adding a third outlet
later is a single registry entry:

  Outlet 1 - "local":  the Bonsai-1.7B endpoint served by a llama-server
                       process (deepgrove llama.cpp fork) exposing an
                       OpenAI-compatible API.
  Outlet 2 - "custom": a user-configured, generic OpenAI-compatible endpoint.
                       The base URL, API key and model name are all injected
                       via environment variables. AskSage is just one possible
                       value a user might configure here; it is not hardcoded.

All configuration is read from configs/.env via python-dotenv, then falls
back to the real environment variables. Environment variables always WIN over
the .env file because Docker injects them at runtime.

Public API (source-compatible with existing callers):
  - LLMClient(model_type="local")
  - chat_completion(messages, temperature, max_tokens, model_override) -> str
  - test_connection() -> bool
  - get_model_info() -> Dict[str, str]
  - create_llm_client() -> LLMClient  (module-level factory, defaults to "local")
"""
import os
import logging
from typing import Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI

# Configure logging with plain ASCII messages only (no emoji).
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Path to the project .env file (relative to this module).
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "configs", ".env")

# Default model name served by the local Bonsai llama-server endpoint.
DEFAULT_LOCAL_MODEL = "bonsai-1.7b"

# Provider registry. Each entry holds the display name, the environment
# variable names for base URL / model / API key, and their default values.
# To add a third outlet, append one entry here and the rest of the module
# picks it up automatically.
PROVIDERS: Dict[str, Dict[str, str]] = {
    "local": {
        "display": "Bonsai-1.7B (local llama-server)",
        "base_url_env": "LOCAL_API_BASE",
        "model_env": "LOCAL_MODEL",
        "api_key_env": "LOCAL_API_KEY",
        "base_url_default": "http://localhost:8080/v1",
        "model_default": DEFAULT_LOCAL_MODEL,
        "api_key_default": "sk-local",
    },
    "custom": {
        "display": "Custom OpenAI-compatible endpoint",
        "base_url_env": "CUSTOM_API_BASE",
        "model_env": "CUSTOM_MODEL",
        "api_key_env": "CUSTOM_API_KEY",
        "base_url_default": "",
        "model_default": "",
        "api_key_default": "",
    },
}


def _load_env() -> None:
    """Load configs/.env into os.environ without overriding existing vars.

    Existing environment variables take precedence because python-dotenv
    does not override them by default, which is exactly the desired
    precedence: Docker-injected variables win over the .env file.
    """
    load_dotenv(_ENV_PATH)


def _get_config(provider: str, key: str) -> str:
    """Resolve a provider config value from env with its default fallback."""
    cfg = PROVIDERS[provider]
    env_var = cfg[key + "_env"]
    default = cfg[key + "_default"]
    return os.getenv(env_var, default)


def normalize_model_output(
    content: Optional[str],
    reasoning_content: Optional[str],
    max_tokens: int,
) -> str:
    """Normalize a reasoning-model completion into a clean string.

    Maple is a reasoning model whose output may contain a thinking prefix.
    Rules applied, in order:
      1. If content is empty/whitespace, fall back to the tail of
         reasoning_content (last max(200, max_tokens // 4) characters).
      2. If content contains "</think>", return only the text after the
         LAST occurrence, stripped.
      3. If content contains a "<think>" block that is never closed, strip
         the leading "<think>"-prefixed region up to the last "</think>"
         if present; otherwise return the content unchanged.

    Args:
        content: The primary message content (may be None).
        reasoning_content: The reasoning/thinking content (may be None).
        max_tokens: The max_tokens used for the request, used to size the
            reasoning tail fallback.

    Returns:
        The normalized output string.
    """
    if content is None:
        content = ""

    if not content.strip():
        reasoning = reasoning_content or ""
        if reasoning.strip():
            return reasoning.strip()[-max(200, max_tokens // 4):]
        return ""

    if "</think>" in content:
        return content.split("</think>")[-1].strip()

    # Handle an unclosed "<think>" block: strip up to the last "</think>"
    # if one exists, otherwise return content unchanged.
    if content.lstrip().startswith("<think>"):
        last_close = content.rfind("</think>")
        if last_close != -1:
            return content[last_close + len("</think>"):].strip()

    return content


class LLMClient:
    """Unified LLM client with automatic fallback between the two outlets.

    Args:
        model_type: The outlet name, either "local" or "custom".
            Defaults to "local".
    """

    def __init__(self, model_type: str = "local"):
        _load_env()
        if model_type not in PROVIDERS:
            raise ValueError(
                "Unsupported model type: {0}. Supported outlets: {1}".format(
                    model_type, ", ".join(PROVIDERS.keys())
                )
            )
        self.model_type = model_type
        self._validate_config(model_type)
        # Two timeouts with different jobs. CONNECT is for reachability
        # probes (the UI "Test connection" button): short, so an unreachable
        # engine fails fast and the UI can show an actionable error instead
        # of hanging. REQUEST is for real generation: a local CPU model can
        # legitimately take minutes on a large chunk, so it defaults long.
        # Both are overridable by environment variables.
        self.connect_timeout = float(os.getenv("LLM_CONNECT_TIMEOUT", "8"))
        self.timeout = float(os.getenv("LLM_REQUEST_TIMEOUT", "240"))
        self._setup_client(model_type)
        self.fallback_enabled = True
        self._fallback_used = False

    def _validate_config(self, model_type: str) -> None:
        """Validate that the selected outlet is fully configured.

        For the "custom" outlet, a missing base URL, model, or API key is
        rejected here with a clear ValueError naming the exact missing
        variable, instead of failing later with an opaque SDK error.
        """
        if model_type != "custom":
            return
        missing = [
            name
            for name in ("CUSTOM_API_BASE", "CUSTOM_MODEL", "CUSTOM_API_KEY")
            if not os.getenv(name, "").strip()
        ]
        if missing:
            raise ValueError(
                "Custom outlet is not fully configured. Missing variable(s): "
                + ", ".join(missing)
            )

    def _setup_client(self, model_type: str) -> None:
        """Build the OpenAI-compatible client for the given outlet."""
        cfg = PROVIDERS[model_type]
        base_url = _get_config(model_type, "base_url")
        api_key = _get_config(model_type, "api_key")
        self.model = _get_config(model_type, "model")
        self.base_url = base_url
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=self.timeout,
            # Disable SDK-level retries. A failed connection is surfaced
            # immediately so the caller (and the UI) can report it and move
            # on to the fallback outlet without extra latency.
            max_retries=0,
        )
        logger.info(
            "Initialized outlet '%s' (%s) with model '%s'",
            model_type,
            cfg["display"],
            self.model,
        )

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 4000,
        model_override: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> str:
        """Send a chat completion request with automatic fallback.

        When the "local" outlet fails (connection error, timeout, HTTP
        error), a warning is logged and the same request is retried through
        the "custom" outlet, but only if the custom outlet is fully
        configured. If it is not configured, the original error is re-raised
        with a message explaining both what failed and that no fallback is
        configured. A request that already fell back never falls back again.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            temperature: Sampling temperature (0.0-1.0).
            max_tokens: Maximum tokens to generate.
            model_override: Override the default model name.
            timeout: Per-request timeout in seconds. None uses the request
                timeout; connection probes pass the shorter connect timeout.

        Returns:
            The normalized generated text response.

        Raises:
            Exception: If both the primary outlet and the fallback fail.
        """
        model = model_override or self.model
        logger.info("Using outlet '%s' with model '%s'", self.model_type, model)

        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout if timeout is not None else self.timeout,
            )
            message = response.choices[0].message
            result = normalize_model_output(
                message.content,
                getattr(message, "reasoning_content", None),
                max_tokens,
            )
            logger.info("Request via outlet '%s' succeeded", self.model_type)
            return result

        except Exception as exc:
            logger.error(
                "Request via outlet '%s' failed: %s", self.model_type, exc
            )
            if self._try_fallback(messages, temperature, max_tokens, model):
                return self.chat_completion(
                    messages, temperature, max_tokens, model_override
                )
            raise

    def _try_fallback(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        model: str,
    ) -> bool:
        """Decide whether a fallback retry should be attempted.

        The fallback only happens when the primary outlet is "local", the
        fallback is enabled, the custom outlet is fully configured, and the
        request has not already fallen back (guards against infinite
        recursion).

        Args:
            messages: The original messages.
            temperature: The temperature used for the request.
            max_tokens: The max_tokens used for the request.
            model: The resolved model name.

        Returns:
            True if the fallback retry should be attempted, False otherwise.
        """
        if self.model_type != "local" or not self.fallback_enabled:
            return False
        if self._fallback_used:
            logger.error("Fallback already used; not retrying again")
            return False
        if not self._custom_configured():
            raise Exception(
                "Request via outlet 'local' failed: {0} and no fallback is "
                "configured because the 'custom' outlet is not fully "
                "configured.".format(model)
            )
        logger.warning(
            "Falling back from outlet 'local' to outlet 'custom' for model '%s'",
            model,
        )
        self._fallback_used = True
        self.model_type = "custom"
        self._setup_client("custom")
        return True

    def _custom_configured(self) -> bool:
        """Return True if the custom outlet is fully configured."""
        return all(
            os.getenv(name, "").strip()
            for name in ("CUSTOM_API_BASE", "CUSTOM_MODEL", "CUSTOM_API_KEY")
        )

    def test_connection(self) -> bool:
        """Test whether the selected LLM outlet is accessible.

        Uses the short connect timeout so an unreachable engine fails fast.

        The check accepts any non-empty reply. Requiring a specific phrase
        made the probe fail against models that answer the question instead
        of echoing the instruction (for example "Test successful." with a
        trailing period, or "The test was successful"), which reported a
        healthy engine as offline.
        """
        try:
            response = self.chat_completion(
                messages=[{"role": "user", "content": "Say 'test successful'"}],
                max_tokens=1000,
                timeout=self.connect_timeout,
            )
            return bool((response or "").strip())
        except Exception as exc:
            logger.error("Connection test failed: %s", exc)
            return False

    def get_model_info(self) -> Dict[str, str]:
        """Return non-sensitive model configuration info.

        SECURITY RULE: This method must NEVER include the API key or any
        credential. Only display-oriented fields are returned; credentials
        are deliberately excluded.
        """
        fallback_target = (
            "custom"
            if self.model_type == "local" and self._custom_configured()
            else ""
        )
        return {
            "model_type": self.model_type,
            "model_name": self.model,
            "base_url": self.base_url,
            "fallback_enabled": str(
                self.model_type == "local"
                and self.fallback_enabled
                and self._custom_configured()
            ),
            "fallback_target": fallback_target,
            "gguf_variant": os.getenv("LOCAL_GGUF_VARIANT", "Q1_0"),
        }


def create_llm_client() -> LLMClient:
    """Factory function creating an LLM client for the default outlet.

    Returns:
        An LLMClient configured for the "local" outlet.
    """
    return LLMClient(model_type="local")
