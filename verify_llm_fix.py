
import sys
import os
from unittest.mock import MagicMock

# Create mock modules to avoid import errors
mock_openai = MagicMock()
sys.modules["openai"] = mock_openai

mock_genai = MagicMock()
sys.modules["google"] = MagicMock()
sys.modules["google.genai"] = mock_genai
sys.modules["google.genai.types"] = MagicMock()

# Mock config manager
mock_config = MagicMock()
sys.modules["config"] = mock_config
sys.modules["config.manager"] = MagicMock()

# Mock logging
mock_logging = MagicMock()
sys.modules["utils.logging_config"] = mock_logging

# Add src to path
sys.path.append(os.path.abspath("src"))

from drivers.llm.openai_driver import OpenAIChatProvider
from drivers.llm.gemini_driver import GeminiProvider
from drivers.llm.openrouter_driver import OpenRouterProvider
from drivers.llm.ollama_driver import OllamaProvider

def verify_provider(provider_class, name):
    print(f"Verifying {name} signature...")
    try:
        # Mock instance
        instance = provider_class({"api_key": "test"})
        # The key test: does it accept max_tokens?
        instance.generate_intent(
            user_input="oi",
            history=[],
            system_prompt="prompt",
            max_tokens=100
        )
        print(f"  {name}: generate_intent accepts max_tokens OK")
        
        instance.generate_text(
            prompt="oi",
            max_tokens=50
        )
        print(f"  {name}: generate_text accepts max_tokens OK")
        return True
    except TypeError as e:
        print(f"  {name}: FAILED - {e}")
        return False
    except Exception as e:
        # Ignore other errors like failed requests since we mocked things
        print(f"  {name}: Accepted signature (failed execution as expected: {type(e).__name__})")
        return True

if __name__ == "__main__":
    providers = [
        (OpenAIChatProvider, "OpenAI"),
        (GeminiProvider, "Gemini"),
        (OpenRouterProvider, "OpenRouter"),
        (OllamaProvider, "Ollama")
    ]
    
    all_passed = True
    for p_class, p_name in providers:
        if not verify_provider(p_class, p_name):
            all_passed = False
            
    if all_passed:
        print("\nAll regression tests for signatures PASSED.")
        sys.exit(0)
    else:
        print("\nSome regression tests FAILED.")
        sys.exit(1)
