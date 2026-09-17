"""
Test suite for the refactored two-outlet LLM client.

Runnable as a plain Python script (no pytest dependency):
    .\\.venv\\Scripts\\python.exe test_llm.py

Tests:
  1. Config validation - custom outlet raises ValueError when unset.
  2. Model info safety - get_model_info() exposes no secret-like values.
  3. Thinking-block stripping - normalize_model_output() unit tests.
  4. Live local connection (optional, skipped when unreachable).
  5. Live custom connection (optional, skipped when unconfigured).

Exit code is 0 if no test FAILED, 1 if any FAILED. SKIPPED never causes a
non-zero exit.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from llm_client import LLMClient, normalize_model_output

# Record results as a list of (name, status) tuples.
RESULTS = []


def record(name: str, status: str) -> None:
    """Record a test result and print it."""
    RESULTS.append((name, status))
    print("[{0}] {1}".format(status, name))


def test_config_validation() -> None:
    """Test 1: custom outlet raises ValueError when env vars are unset."""
    name = "Test 1: custom outlet config validation"
    # Snapshot any existing values so we can restore them afterward.
    saved = {k: os.environ.get(k) for k in ("CUSTOM_API_BASE", "CUSTOM_MODEL", "CUSTOM_API_KEY")}
    for k in saved:
        os.environ.pop(k, None)
    try:
        LLMClient(model_type="custom")
        record(name, "FAIL")
        print("    Expected ValueError but none was raised.")
    except ValueError as exc:
        msg = str(exc)
        if any(v in msg for v in ("CUSTOM_API_BASE", "CUSTOM_MODEL", "CUSTOM_API_KEY")):
            record(name, "PASS")
            print("    ValueError named a missing variable: {0}".format(msg))
        else:
            record(name, "FAIL")
            print("    ValueError did not name a missing variable: {0}".format(msg))
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_model_info_safety() -> None:
    """Test 2: get_model_info() exposes no secret-like values."""
    name = "Test 2: model info secret safety"
    client = LLMClient(model_type="local")
    info = client.get_model_info()

    secret_like_keys = [k for k in info if "key" in k.lower() or "token" in k.lower()]
    if secret_like_keys:
        record(name, "FAIL")
        print("    Secret-like keys present: {0}".format(secret_like_keys))
        return

    api_key = os.getenv("LOCAL_API_KEY", "sk-local")
    leaked_values = [v for v in info.values() if v == api_key]
    if leaked_values:
        record(name, "FAIL")
        print("    A value equals the configured API key.")
        return

    record(name, "PASS")
    print("    No secret-like keys or values in get_model_info().")


def test_thinking_stripping() -> None:
    """Test 3: normalize_model_output() unit tests without network."""
    cases = [
        (
            "3a: plain content passes through",
            "Hello world",
            None,
            4000,
            "Hello world",
        ),
        (
            "3b: content with </think> returns only the tail",
            "think about it</think>Final answer",
            None,
            4000,
            "Final answer",
        ),
        (
            "3c: empty content with reasoning returns reasoning tail",
            "",
            "x" * 500,
            4000,
            "x" * 500,
        ),
        (
            "3d: empty content with no reasoning returns empty string",
            "",
            None,
            4000,
            "",
        ),
    ]
    for label, content, reasoning, max_tokens, expected in cases:
        result = normalize_model_output(content, reasoning, max_tokens)
        if result == expected:
            record(label, "PASS")
        else:
            record(label, "FAIL")
            print("    Expected: {0!r}".format(expected))
            print("    Got:      {0!r}".format(result))


def test_live_local() -> None:
    """Test 4: live local connection (optional, must not fail the suite)."""
    name = "Test 4: live local connection"
    try:
        client = LLMClient(model_type="local")
        ok = client.test_connection()
        if ok:
            record(name, "PASS")
        else:
            record(name, "SKIPPED")
            print("    SKIPPED: local llama-server not reachable.")
    except Exception as exc:
        record(name, "SKIPPED")
        print("    SKIPPED: local llama-server not reachable: {0}".format(exc))


def test_live_custom() -> None:
    """Test 5: live custom connection (optional, skipped when unconfigured)."""
    name = "Test 5: live custom connection"
    configured = all(
        os.getenv(k, "").strip()
        for k in ("CUSTOM_API_BASE", "CUSTOM_MODEL", "CUSTOM_API_KEY")
    )
    if not configured:
        record(name, "SKIPPED")
        print("    SKIPPED: custom outlet not configured.")
        return
    try:
        client = LLMClient(model_type="custom")
        ok = client.test_connection()
        if ok:
            record(name, "PASS")
        else:
            record(name, "SKIPPED")
            print("    SKIPPED: custom endpoint not reachable.")
    except Exception as exc:
        record(name, "SKIPPED")
        print("    SKIPPED: custom endpoint not reachable: {0}".format(exc))


def main() -> int:
    """Run all tests and print a summary."""
    print("=" * 60)
    print("LLM Client Test Suite (two-outlet architecture)")
    print("=" * 60)

    test_config_validation()
    test_model_info_safety()
    test_thinking_stripping()
    test_live_local()
    test_live_custom()

    print()
    print("=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    failed = 0
    for name, status in RESULTS:
        print("  {0}: {1}".format(status, name))
        if status == "FAIL":
            failed += 1

    print("=" * 60)
    if failed:
        print("RESULT: FAILED ({0} failure(s))".format(failed))
        return 1
    print("RESULT: ALL PASSED (skips do not count as failures)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
