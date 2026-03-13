import json
import logging
from typing import List, Dict, Any, Optional
from .schemas import AnalyzerResponse, AnalyzerCandidate, BBox

logger = logging.getLogger("aosd.capabilities.browser_control.image_analyzer")

class ImageAnalyzer:
    """Stateless Image Analyzer Module for VLM-based Technical Extraction."""
    
    def __init__(self, llm_manager: Any):
        self.llm_manager = llm_manager

    def analyze(self, image_path: str, intent: str) -> AnalyzerResponse:
        """
        Analyzes the vision snapshot for elements matching the intent using a VLM.
        """
        logger.info(f"[Vision] Analyzing for intent: {intent}")
        
        prompt = f"""You are a Technical Vision Agent for a browser automation tool.
Intent: "{intent}"

Identify all interactive UI elements relevant to this intent.
For each element, providing:
1. label: Concise name
2. visual_role: (button, input, link, icon)
3. coordinates: [x, y, w, h] in 0-1000 scale (relative to viewport)
4. confidence: 0.0 to 1.0

Return ONLY a valid JSON object:
{{
  "candidates": [
    {{"label": "...", "visual_role": "...", "coordinates": [x,y,w,h], "confidence": 0.9, "reasoning": "..."}}
  ]
}}
"""
        try:
            # Note: image_path is expected to be a local path or data URL
            result = self.llm_manager.analyze_image(image_path=image_path, prompt=prompt)
            data = self._extract_json(result)
            
            candidates = []
            for c in data.get("candidates", []):
                coords = c.get("coordinates", [0, 0, 0, 0])
                candidates.append(AnalyzerCandidate(
                    visual_role=c.get("visual_role"),
                    bounding_box=BBox(x=coords[0], y=coords[1], width=coords[2], height=coords[3]),
                    confidence_score=float(c.get("confidence", 0.0)),
                    reasoning=c.get("reasoning", "VLM Detection")
                ))
            
            return AnalyzerResponse(
                candidates=candidates,
                intent_confirmation=f"Vision analysis found {len(candidates)} targets."
            )
        except Exception as e:
            logger.error(f"[Vision] VLM Error: {e}")
            return AnalyzerResponse(candidates=[], intent_confirmation=f"Vision failed: {e}")

    def _extract_json(self, text: str) -> Dict[str, Any]:
        try:
            # Basic extraction
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1:
                return json.loads(text[start:end+1])
            return {}
        except:
            return {}
