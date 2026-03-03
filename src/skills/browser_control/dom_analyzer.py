import json
import logging
from typing import List, Dict, Any, Optional, Union
from .schemas import AnalyzerResponse, AnalyzerCandidate, BBox

logger = logging.getLogger("aosd.skills.browser_control.dom_analyzer")

class DomAnalyzer:
    """Stateless DOM Analyzer Module."""
    
    def analyze(self, compressed_dom: Union[str, List[Dict[str, Any]]], intent: str) -> AnalyzerResponse:
        """
        Analyzes the compressed DOM (flattened list) for elements matching the intent.
        """
        logger.info(f"Analyzing DOM for intent: {intent}")
        
        if isinstance(compressed_dom, str):
            try:
                nodes = json.loads(compressed_dom)
            except Exception as e:
                logger.error(f"Failed to parse compressed DOM string: {e}")
                return AnalyzerResponse(candidates=[], intent_confirmation="Invalid DOM format")
        else:
            nodes = compressed_dom

        candidates = []
        intent_lower = intent.lower()
        intent_words = intent_lower.split()
        
        for node in nodes:
            tag = node.get("tag", "").lower()
            text = str(node.get("text", "")).lower()
            name = node.get("name", "").lower()
            placeholder = node.get("placeholder", "").lower()
            role = node.get("role", "").lower()
            
            match_score = 0
            for word in intent_words:
                if word in text: match_score += 0.4
                if word in name: match_score += 0.5
                if word in placeholder: match_score += 0.5
                if word in role: match_score += 0.4
                if word in tag and (text or name or placeholder): match_score += 0.2
            
            # Special case for Google Search 'q'
            if "search" in intent_lower and name == "q":
                match_score = 1.0
                candidates.append(AnalyzerCandidate(
                    element_id=str(node.get("id")),
                    semantic_role=node.get("role") or node.get("tag") or "element",
                    bounding_box=BBox(x=100, y=100, width=50, height=20), # Fallback
                    confidence_score=min(1.0, match_score),
                    reasoning=f"Matched '{intent}' in {tag} (attr match)"
                ))
            
        return AnalyzerResponse(
            candidates=candidates,
            intent_confirmation=f"Identified {len(candidates)} potential matches"
        )

    @staticmethod
    def compress_dom(raw_dom_res: Dict[str, Any]) -> str:
        """
        Processes flattened CDP DOM nodes into a minimal list of interactive elements.
        """
        nodes = raw_dom_res.get("nodes", [])
        compressed = []
        
        for node in nodes:
            node_type = node.get("nodeType")
            if node_type != 1: continue # Only elements
            
            tag = node.get("localName", "").lower()
            # Only keep potentially interactive or structural nodes
            if tag not in ["input", "button", "textarea", "a", "select", "form", "span", "div"]:
                continue
                
            attrs = node.get("attributes", [])
            attr_dict = {}
            for i in range(0, len(attrs), 2):
                attr_dict[attrs[i]] = attrs[i+1]
                
            entry = {
                "tag": tag,
                "id": node.get("nodeId"),
                "role": attr_dict.get("role", ""),
                "name": attr_dict.get("name", ""),
                "placeholder": attr_dict.get("placeholder", ""),
                "text": attr_dict.get("aria-label", "") or attr_dict.get("value", "") or ""
            }
            
            # Heuristic for text: if it's a small element, try to get its text content from following text nodes
            # (In flattened list, text nodes follow their parent element)
            
            compressed.append(entry)
            
        logger.info(f"Compressed DOM into {len(compressed)} semantic nodes.")
        return json.dumps(compressed)
