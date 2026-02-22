from fastapi import APIRouter, Depends, HTTPException, Request
from ..auth import get_current_user
from ..core.models import User
import logging

router = APIRouter(prefix="/api/memory", tags=["memory"])
logger = logging.getLogger("MemoryRoutes")

def get_orchestrator(request: Request):
    kernel = request.app.state.kernel
    if not kernel or not kernel.orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not active")
    return kernel.orchestrator

@router.get("/semantic")
def get_semantic_memory(limit: int = 50, request: Request = None, user: User = Depends(get_current_user)):
    """
    List recent semantic facts from ChromaDB.
    """
    orch = get_orchestrator(request)
    if not orch.memory_service.collection:
        return {"error": "ChromaDB not initialized", "documents": []}
    
    try:
        # ChromaDB .get() returns dict with 'ids', 'documents', 'metadatas'
        results = orch.memory_service.collection.get(limit=limit)
        
        # Format for UI
        formatted = []
        for i, doc_id in enumerate(results['ids']):
             formatted.append({
                 "id": doc_id,
                 "content": results['documents'][i],
                 "metadata": results['metadatas'][i] if results['metadatas'] else {}
             })
        return formatted
    except Exception as e:
        logger.error(f"Error fetching semantic memory: {e}")
        return {"error": str(e)}

@router.get("/episodic")
def get_episodic_memory(limit: int = 50, request: Request = None, user: User = Depends(get_current_user)):
    """
    List recent episodes from Episodic Memory.
    """
    orch = get_orchestrator(request)
    if not orch.episodic_memory.collection:
        return {"error": "Episodic ChromaDB not initialized", "documents": []}
    
    try:
        results = orch.episodic_memory.collection.get(limit=limit)
        formatted = []
        for i, doc_id in enumerate(results['ids']):
             formatted.append({
                 "id": doc_id,
                 "content": results['documents'][i],
                 "metadata": results['metadatas'][i] if results['metadatas'] else {}
             })
        return formatted
    except Exception as e:
        logger.error(f"Error fetching episodic memory: {e}")
        return {"error": str(e)}

@router.post("/facts")
def add_fact(fact: dict, request: Request, user: User = Depends(get_current_user)):
    """
    Add a new semantic fact.
    Payload: {"category": "...", "content": "..."}
    """
    if user.role not in ["admin", "operator"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
        
    orch = get_orchestrator(request)
    category = fact.get("category", "General")
    content = fact.get("content")
    
    if not content:
        raise HTTPException(status_code=400, detail="Content required")
        
    orch.memory_service.add_fact(category, content)
    return {"status": "added", "category": category}

@router.post("/query")
def query_memory(query: dict, request: Request, user: User = Depends(get_current_user)):
    """
    Test vector search.
    Payload: {"q": "search term"}
    """
    orch = get_orchestrator(request)
    q = query.get("q")
    if not q: return {"error": "Query 'q' required"}
    
    result = orch.memory_service.search_memory(q)
    return {"result": result}

@router.delete("/{mem_type}/{mem_id}")
def delete_memory(mem_type: str, mem_id: str, request: Request, user: User = Depends(get_current_user)):
    """Delete a memory entry."""
    if user.role not in ["admin", "operator"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    
    orch = get_orchestrator(request)
    if mem_type == "semantic":
        orch.memory_service.delete_fact(mem_id)
    elif mem_type == "episodic":
        orch.episodic_memory.delete_episode(mem_id)
    else:
        raise HTTPException(status_code=400, detail="Invalid memory type")
    
    return {"status": "deleted"}

@router.put("/{mem_type}/{mem_id}")
def update_memory(mem_type: str, mem_id: str, payload: dict, request: Request, user: User = Depends(get_current_user)):
    """Update a memory entry."""
    if user.role not in ["admin", "operator"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    
    content = payload.get("content")
    if not content:
        raise HTTPException(status_code=400, detail="Content required")
        
    orch = get_orchestrator(request)
    if mem_type == "semantic":
        category = payload.get("category")
        orch.memory_service.update_fact(mem_id, content, category)
    elif mem_type == "episodic":
        action = payload.get("action")
        orch.episodic_memory.update_episode(mem_id, content, action)
    else:
        raise HTTPException(status_code=400, detail="Invalid memory type")
    
    return {"status": "updated"}
