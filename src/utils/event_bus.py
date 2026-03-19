import asyncio
import json
from typing import Dict, List, Any, Optional
from utils.logging_config import get_logger

logger = get_logger("EventBus")

class EventBus:
    """
    A simple async event bus for broadcasting events to multiple subscribers.
    Useful for Server-Sent Events (SSE).
    """
    def __init__(self):
        self.subscribers: List[asyncio.Queue] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: Optional[asyncio.AbstractEventLoop]):
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        queue = asyncio.Queue()
        self.subscribers.append(queue)
        logger.debug(f"New subscriber. Total: {len(self.subscribers)}")
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        if queue in self.subscribers:
            self.subscribers.remove(queue)
            logger.debug(f"Subscriber removed. Total: {len(self.subscribers)}")

    async def emit(self, event: Dict[str, Any]):
        """
        Emits an event to all subscribers. Must be called from the async loop.
        """
        if not self.subscribers:
            return
            
        # Add timestamp if missing
        if "ts" not in event:
            import datetime
            # Try to get centralized config for timezone if possible, 
            # but event_bus is low-level. Fallback to UTC-aware.
            event["ts"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            
        for queue in self.subscribers:
            await queue.put(event)

    def emit_threadsafe(self, event: Dict[str, Any]):
        """
        Thread-safe way to emit events from outside the main event loop.
        """
        loop = self._loop
        if not loop:
            # In CLI/diagnostic runs there is no loop; drop silently to avoid noisy logs.
            return
        if loop.is_closed():
            logger.warning("EventBus loop is closed. Clearing loop reference.")
            self._loop = None
            return
        try:
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self.emit(event))
            )
        except RuntimeError as e:
            if "closed" in str(e).lower():
                logger.warning("EventBus emit failed because loop is closed. Clearing loop reference.")
                self._loop = None
                return
            raise

# Global instance
global_event_bus = EventBus()
