from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class OverlayBackend(ABC):
    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def stop(self) -> None:
        pass

    @abstractmethod
    def is_available(self) -> bool:
        pass

    @abstractmethod
    def draw(self, command: Dict[str, Any]) -> Dict[str, Any]:
        pass

    @abstractmethod
    def clear_by_id(self, command_id: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def clear_all(self) -> Dict[str, Any]:
        pass
