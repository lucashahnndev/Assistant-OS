import os
import json
import time
import uuid
from typing import List, Dict, Optional
import chromadb
from utils.logging_config import get_logger

logger = get_logger("MemoryService")

class MemoryService:
    def __init__(self):
        # Correctly find project root
        self.root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        self.memory_dir = os.path.join(self.root_dir, 'data', 'memory')
        self.chroma_dir = os.path.join(self.memory_dir, 'chroma')
        
        logger.info(f"MemoryService directed to: {self.memory_dir}")
        
        if not os.path.exists(self.memory_dir):
            os.makedirs(self.memory_dir)
            
        # Initialize Vector Memory (ChromaDB)
        try:
            self.chroma_client = chromadb.PersistentClient(path=self.chroma_dir)
            self.collection = self.chroma_client.get_or_create_collection(name="long_term_memory")
            logger.info("ChromaDB Memory initialized.")
        except Exception as e:
            logger.error(f"Error initializing ChromaDB: {e}")
            self.collection = None

    def add_fact(self, category: str, content: str, relevance: int = 1):
        """Adds a fact to vector store."""
        fact_id = str(uuid.uuid4())
        
        if self.collection:
            try:
                doc = f"[{category}]: {content}"
                self.collection.add(
                    documents=[doc],
                    metadatas=[{"category": category, "relevance": relevance}],
                    ids=[fact_id]
                )
                logger.info(f"New fact added to memory: {category} - {content[:30]}...")
            except Exception as e:
                logger.error(f"Error adding fact to ChromaDB: {e}")

    def delete_fact(self, fact_id: str):
        """Removes a fact from both stores."""
        if self.collection:
            try:
                self.collection.delete(ids=[fact_id])
                logger.info(f"Fact {fact_id} deleted from memory.")
            except Exception as e:
                logger.error(f"Error deleting from ChromaDB: {e}")

    def update_fact(self, fact_id: str, content: str, category: Optional[str] = None):
        """Updates an existing fact."""
        if self.collection:
            try:
                cat = category or "General"
                doc = f"[{cat}]: {content}"
                self.collection.update(
                    ids=[fact_id],
                    documents=[doc],
                    metadatas=[{"category": cat}]
                )
                logger.info(f"Fact {fact_id} updated.")
                return True
            except Exception as e:
                logger.error(f"Error updating ChromaDB: {e}")
        return False

    def search_memory(self, query: str) -> str:
        """Vector-based semantic search."""
        if self.collection:
            try:
                results = self.collection.query(
                    query_texts=[query],
                    n_results=5
                )
                if results and results['documents'] and results['documents'][0]:
                    return "\n".join(results['documents'][0])
            except Exception as e:
                logger.error(f"ChromaDB search failed: {e}")

        return "Nenhuma memória relevante encontrada."

    def get_all_summaries(self, sessions_dir: str) -> str:
        """Gathers all session summaries for context."""
        summaries = []
        if not os.path.exists(sessions_dir):
            return ""
            
        for filename in sorted(os.listdir(sessions_dir), reverse=True): # Newest first
            if filename.endswith(".json"):
                try:
                    with open(os.path.join(sessions_dir, filename), 'r') as f:
                        data = json.load(f)
                        if data.get('summary'):
                            summaries.append(f"- Session {data['session_id']}: {data['summary']}")
                        if len(summaries) >= 3: break # Limit to last 3 for context efficiency
                except:
                    continue
        
        return "\n".join(summaries)
