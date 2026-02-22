import os
import json
import uuid
import time
from typing import List, Dict, Optional
import chromadb
from utils.logging_config import get_logger

logger = get_logger("EpisodicMemory")

class EpisodicMemoryService:
    def __init__(self):
        # Correctly find project root (up 3 levels from src/services/memory/)
        self.root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        self.memory_dir = os.path.join(self.root_dir, 'data', 'memory')
        self.chroma_dir = os.path.join(self.memory_dir, 'chroma_episodic')
        
        logger.info(f"EpisodicMemoryService directed to: {self.chroma_dir}")
        
        if not os.path.exists(self.memory_dir):
            os.makedirs(self.memory_dir)
            
        try:
            self.chroma_client = chromadb.PersistentClient(path=self.chroma_dir)
            self.collection = self.chroma_client.get_or_create_collection(name="episodic_memory")
            logger.info("ChromaDB Episodic Memory initialized.")
        except Exception as e:
            logger.error(f"Error initializing Episodic ChromaDB: {e}")
            self.collection = None

    def store_episode(self, user_input: str, thought: str, action: str, observation: str, status: str = "success"):
        """Stores a single reasoning/action episode."""
        if not self.collection: return
        
        try:
            doc = f"User: {user_input}\nThought: {thought}\nAction: {action}\nObservation: {observation}"
            metadata = {
                "action": action,
                "status": status,
                "timestamp": time.time(),
                "user_input": user_input[:100] # Truncate for metadata
            }
            
            self.collection.add(
                documents=[doc],
                metadatas=[metadata],
                ids=[str(uuid.uuid4())]
            )
            logger.debug(f"Episode stored for action {action} with status {status}")
        except Exception as e:
            logger.error(f"Error storing episode: {e}")

    def recall_episodes(self, query: str, n_results: int = 3) -> str:
        """Recalls past episodes similar to the current query."""
        if not self.collection: return "Episodic memory unavailable."
        
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results
            )
            
            if not results or not results['documents'] or not results['documents'][0]:
                return "No similar past experiences found."
            
            formatted_episodes = []
            for i, doc in enumerate(results['documents'][0]):
                status = results['metadatas'][0][i].get('status', 'unknown')
                formatted_episodes.append(f"--- Past Episode ({status.upper()}) ---\n{doc}")
                
            return "\n\n".join(formatted_episodes)
        except Exception as e:
            logger.error(f"Error recalling episodes: {e}")
            return "Error retrieving past experiences."

    def delete_episode(self, episode_id: str):
        """Removes an episode from ChromaDB."""
        if not self.collection: return
        try:
            self.collection.delete(ids=[episode_id])
            logger.info(f"Episode {episode_id} deleted.")
        except Exception as e:
            logger.error(f"Error deleting episode: {e}")

    def update_episode(self, episode_id: str, content: str, action: Optional[str] = None):
        """Updates an episode in ChromaDB."""
        if not self.collection: return
        try:
            metadata = {"timestamp": time.time()}
            if action: metadata["action"] = action
            
            self.collection.update(
                ids=[episode_id],
                documents=[content],
                metadatas=[metadata]
            )
            logger.info(f"Episode {episode_id} updated.")
        except Exception as e:
            logger.error(f"Error updating episode: {e}")
