#!/usr/bin/env python3
"""
Test script for Bonsai 1.7B LLM via Ollama API.
Verifies inference capability and basic performance metrics.
"""

import requests
import json
import time

# Configuration
OLLAMA_BASE_URL = "http://localhost:11434"
MODEL_NAME = "hf.co/prism-ml/Bonsai-1.7B-gguf"

def test_connection():
    """Test if Ollama API is accessible."""
    print("Testing Ollama API connection...")
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get("models", [])
            bonsai_models = [m for m in models if MODEL_NAME in m.get("name", "")]
            if bonsai_models:
                print(f"✓ Connection successful")
                print(f"✓ Bonsai model found: {bonsai_models[0]['name']}")
                print(f"  - Size: {bonsai_models[0]['size'] / 1024 / 1024:.1f} MB")
                print(f"  - Parameters: {bonsai_models[0]['details']['parameter_size']}")
                return True
            else:
                print("✗ Bonsai model not found")
                return False
        else:
            print(f"✗ Connection failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

def test_inference():
    """Test basic inference capability."""
    print("\nTesting inference capability...")
    prompts = [
        "What is 2 + 2? Answer in one word.",
        "Write a haiku about AI.",
        "Summarize 'The quick brown fox jumps over the lazy dog' in one sentence."
    ]

    for i, prompt in enumerate(prompts, 1):
        print(f"\nTest {i}: {prompt}")
        try:
            start_time = time.time()
            response = requests.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": MODEL_NAME,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "num_ctx": 2048,
                        "temperature": 0.7,
                        "top_p": 0.9
                    }
                },
                timeout=60
            )
            elapsed = time.time() - start_time

            if response.status_code == 200:
                result = response.json()
                response_text = result.get("response", "").strip()
                print(f"✓ Response: {response_text[:100]}...")
                print(f"✓ Time: {elapsed:.2f}s")
                print(f"✓ Tokens: {result.get('eval_count', 'N/A')}")
            else:
                print(f"✗ Request failed: {response.status_code}")
        except Exception as e:
            print(f"✗ Error: {e}")

def main():
    """Run all tests."""
    print("=" * 60)
    print("Bonsai 1.7B LLM - Test Suite")
    print("=" * 60)

    if not test_connection():
        print("\n✗ Cannot proceed - API connection failed")
        return 1

    test_inference()

    print("\n" + "=" * 60)
    print("Test suite completed!")
    print("=" * 60)
    return 0

if __name__ == "__main__":
    exit(main())