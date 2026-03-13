import logging
import asyncio
import time
from typing import List, Dict, Any
from .schemas import AnalyzerResponse, AnalyzerCandidate, BBox

logger = logging.getLogger("aosd.capabilities.browser_control.perception_merger")

class PerceptionMerger:
    """
    Orchestrates parallel perception from DOM and Vision analyzers
    and merges them into a unified, high-confidence candidate list.
    """

    def __init__(
        self,
        dom_analyzer: Any,
        image_analyzer: Any,
        *,
        dom_weight: float = 0.35,
        vision_weight: float = 0.65,
        dom_timeout_s: float = 4.0,
        vision_timeout_s: float = 7.5,
        vision_backoff_s: float = 8.0,
    ):
        self.dom_analyzer = dom_analyzer
        self.image_analyzer = image_analyzer
        self.dom_weight = max(0.0, float(dom_weight))
        self.vision_weight = max(0.0, float(vision_weight))
        self.dom_timeout_s = max(0.5, float(dom_timeout_s))
        self.vision_timeout_s = max(0.5, float(vision_timeout_s))
        self.vision_backoff_s = max(1.0, float(vision_backoff_s))
        self._vision_backoff_until = 0.0

    async def get_unified_state(self, dom_data: Any, image_data: Any, intent: str) -> Dict[str, Any]:
        """
        Executes analyzers in parallel and performs geometric fusion of candidates.
        """
        logger.info(f"[Merger] Starting parallel analysis for intent: {intent}")

        async def _run_dom() -> AnalyzerResponse:
            return await asyncio.wait_for(
                asyncio.to_thread(self.dom_analyzer.analyze, dom_data, intent),
                timeout=self.dom_timeout_s,
            )

        async def _run_vision() -> AnalyzerResponse:
            # When screenshot is unavailable we still return a valid empty response.
            if not image_data:
                return AnalyzerResponse(candidates=[], intent_confirmation="Vision skipped (no image).")
            if time.time() < self._vision_backoff_until:
                return AnalyzerResponse(candidates=[], intent_confirmation="Vision skipped (backoff).")
            return await asyncio.wait_for(
                asyncio.to_thread(self.image_analyzer.analyze, image_data, intent),
                timeout=self.vision_timeout_s,
            )

        # 1. Parallel Execution with timeout + partial fallback
        dom_resp, vis_resp = await asyncio.gather(_run_dom(), _run_vision(), return_exceptions=True)

        if isinstance(dom_resp, Exception):
            logger.warning(f"[Merger] DOM Analyzer unavailable: {dom_resp}")
            dom_resp = AnalyzerResponse(candidates=[], intent_confirmation=f"DOM unavailable: {dom_resp}")

        if isinstance(vis_resp, Exception):
            logger.warning(f"[Merger] Vision Analyzer unavailable: {vis_resp}")
            self._vision_backoff_until = time.time() + self.vision_backoff_s
            vis_resp = AnalyzerResponse(candidates=[], intent_confirmation=f"Vision unavailable: {vis_resp}")
        else:
            # Clear backoff on successful vision call.
            self._vision_backoff_until = 0.0

        # 2. Geometric Fusion Logic (vision-dominant weighting)
        fused_candidates = self._fuse(dom_resp.candidates, vis_resp.candidates)
        fused_candidates.sort(key=lambda c: float(c.get("confidence_score") or 0.0), reverse=True)

        return {
            "candidates": fused_candidates,
            "dom_confirmation": dom_resp.intent_confirmation if hasattr(dom_resp, "intent_confirmation") else "",
            "vision_confirmation": vis_resp.intent_confirmation if hasattr(vis_resp, "intent_confirmation") else "",
            "global_confidence": self._calculate_global_confidence(fused_candidates)
        }

    def _fuse(self, dom: List[AnalyzerCandidate], vis: List[AnalyzerCandidate]) -> List[Dict[str, Any]]:
        """
        Merges candidates based on bounding box proximity.
        """
        unified = []
        matched_vis_indices = set()

        for d in dom:
            entry = d.dict()
            entry["source"] = "DOM"
            
            # Look for visual overlap
            best_vis_match = None
            best_iou = 0.0
            best_idx = -1

            for i, v in enumerate(vis):
                iou = self._calculate_iou(d.bounding_box, v.bounding_box)
                if iou > 0.5 and iou > best_iou:
                    best_iou = iou
                    best_vis_match = v
                    best_idx = i

            if best_vis_match is not None:
                entry["source"] = "FUSED"
                entry["visual_role"] = best_vis_match.visual_role
                dw = self.dom_weight
                vw = self.vision_weight
                den = (dw + vw) if (dw + vw) > 0 else 1.0
                entry["confidence_score"] = (
                    (float(entry.get("confidence_score") or 0.0) * dw)
                    + (float(best_vis_match.confidence_score or 0.0) * vw)
                ) / den
                entry["reasoning"] += f" | Visual confirm (IoU={float(round(best_iou, 2))})"
                matched_vis_indices.add(best_idx)

            unified.append(entry)

        # Add remaining Vision-only candidates
        for i, v in enumerate(vis):
            if i not in matched_vis_indices:
                entry = v.dict()
                entry["source"] = "VISION"
                unified.append(entry)

        return unified

    def _calculate_iou(self, box_a: BBox, box_b: BBox) -> float:
        """Standard Intersection over Union calculation."""
        x_left = max(box_a.x, box_b.x)
        y_top = max(box_a.y, box_b.y)
        x_right = min(box_a.x + box_a.width, box_b.x + box_b.width)
        y_bottom = min(box_a.y + box_a.height, box_b.y + box_b.height)

        if x_right < x_left or y_bottom < y_top:
            return 0.0

        intersection_area = (x_right - x_left) * (y_bottom - y_top)
        area_a = box_a.width * box_a.height
        area_b = box_b.width * box_b.height
        
        return intersection_area / float(area_a + area_b - intersection_area)

    def _calculate_global_confidence(self, candidates: List[Dict[str, Any]]) -> float:
        if not candidates: return 0.0
        return sum(c["confidence_score"] for c in candidates) / len(candidates)
