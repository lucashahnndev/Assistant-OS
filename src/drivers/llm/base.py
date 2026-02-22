from abc import ABC, abstractmethod
from typing import Dict, Any, List
from core.intent import AgentIntent

class ILLMProvider(ABC):
    """
    Interface for LLM Providers (OpenAI, Ollama, etc.).
    Responsible for connecting to the model and parsing the response into an AgentIntent.
    """

    @abstractmethod
    def generate_intent(self, user_input: str, history: List[Dict[str, str]], system_prompt: str, attachments: List[str] = None) -> AgentIntent:
        """
        Generates an structured intent from the user input and context.
        
        Args:
            user_input (str): The latest message from the user.
            history (List[Dict[str, str]]): Conversation history.
            system_prompt (str): The core instructions for the agent.
            attachments (List[str]): Paths to files (images) attached to the message.

        Returns:
            AgentIntent: The structured intent (thought, action, params).
        """
        pass

    @abstractmethod
    def generate_text(self, prompt: str, system_prompt: str = "") -> str:
        """
        Generates a plain text response from a prompt. 
        Used for internal utilities like summarization and log compression.
        """
        pass

    def analyze_image(self, image_path: str, prompt: str) -> str:
        """
        Directly analyzes an image without conversation history.
        Default implementation returns an error if not overridden.
        """
        return "Erro: Este provedor de LLM não suporta análise direta de imagens (Visão)."
