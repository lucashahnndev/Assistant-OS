import json
import logging
from typing import List, Dict, Any, Optional, Union
from .schemas import AnalyzerResponse, AnalyzerCandidate, BBox

logger = logging.getLogger("aosd.capabilities.browser_control.dom_analyzer")

class DomAnalyzer:
    """Stateless DOM Analyzer Module for Technical Extraction."""
    
    def analyze(self, compressed_dom: Union[str, List[Dict[str, Any]]], intent: str) -> AnalyzerResponse:
        """
        Analyzes the compressed DOM for elements matching the intent.
        Returns a list of candidates with semantic roles and confidence scores.
        """
        logger.info(f"[DOM] Analyzing for intent: {intent}")
        
        if isinstance(compressed_dom, str):
            try:
                nodes = json.loads(compressed_dom)
            except Exception as e:
                logger.error(f"[DOM] Failed to parse DOM: {e}")
                return AnalyzerResponse(candidates=[], intent_confirmation="Invalid DOM format")
        else:
            nodes = compressed_dom

        candidates = []
        intent_lower = intent.lower()
        intent_words = [w for w in intent_lower.split() if len(w) > 2] # Basic stop-word filter
        
        for node in nodes:
            tag = node.get("tag", "").lower()
            text = str(node.get("text", "")).lower()
            name = node.get("name", "").lower()
            placeholder = node.get("placeholder", "").lower()
            role = node.get("role", "").lower()
            
            # 1. Matching Logic (Scoring)
            match_score = 0.0
            found_words = []
            for word in intent_words:
                if word in text: 
                    match_score += 0.4
                    found_words.append(word)
                if word in name: 
                    match_score += 0.5
                    found_words.append(word)
                if word in placeholder: 
                    match_score += 0.5
                    found_words.append(word)
                if word in role: 
                    match_score += 0.4
                    found_words.append(word)
            
            # 2. Heuristic Bonus
            if tag in ["input", "textarea"] and ("search" in intent_lower or "find" in intent_lower):
                match_score += 0.3
            
            if match_score > 0.3:
                bbox_raw = node.get("bbox") or {"x": 0, "y": 0, "w": 0, "h": 0}
                bbox_norm = BBox(
                    x=float(bbox_raw.get("x", 0)),
                    y=float(bbox_raw.get("y", 0)),
                    width=float(bbox_raw.get("w", 0)),
                    height=float(bbox_raw.get("h", 0))
                )
                candidates.append(AnalyzerCandidate(
                    element_id=str(node.get("id")),
                    semantic_role=role or tag or "element",
                    bounding_box=bbox_norm,
                    confidence_score=min(1.0, match_score),
                    reasoning=f"Matched keywords: {', '.join(set(found_words))}"
                ))
            
        # Sort by confidence
        candidates.sort(key=lambda c: c.confidence_score, reverse=True)
        
        return AnalyzerResponse(
            candidates=candidates[:10], # Cap to top 10
            intent_confirmation=f"DOM Analysis found {len(candidates)} candidates."
        )

    @staticmethod
    def compress_dom(raw_nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filters raw node list into interactive nodes with essential metadata.
        """
        # This is typically pre-filtered by JS in runtime.py but we ensure here too.
        compressed = []
        for n in raw_nodes:
            if not isinstance(n, dict): continue
            compressed.append({
                "id": n.get("id"),
                "tag": n.get("tag"),
                "text": n.get("text", ""),
                "role": n.get("role", ""),
                "name": n.get("name", ""),
                "placeholder": n.get("placeholder", ""),
                "bbox": n.get("bbox")
            })
        return compressed
