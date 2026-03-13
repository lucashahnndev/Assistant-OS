from typing import Any, Dict, List, Tuple

from ..base import CapabilityBase


class DataAnalysisCapability(CapabilityBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "data.analysis"

    @property
    def name(self) -> str:
        return "data_analysis"

    @property
    def actions(self) -> List[str]:
        return ["summarize"]

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(str(value).replace(",", "."))
        except Exception:
            return None

    @staticmethod
    def _safe_str(value: Any) -> str:
        return str(value if value is not None else "").strip()

    def _max_points(self, params: Dict[str, Any]) -> int:
        defaults = self.config.get("defaults", {}) if isinstance(self.config, dict) else {}
        default = int(defaults.get("max_points", 24))
        try:
            value = int(params.get("max_points", default))
        except Exception:
            value = default
        return max(4, min(value, 200))

    def _from_rows(self, params: Dict[str, Any], max_points: int) -> Tuple[str, str, List[Dict[str, Any]]]:
        rows = params.get("rows")
        if not isinstance(rows, list):
            return "", "", []
        if len(rows) == 0:
            return "", "", []

        x_key = self._safe_str(params.get("x_key"))
        y_key = self._safe_str(params.get("y_key"))
        first = rows[0] if isinstance(rows[0], dict) else None
        if first is None:
            return "", "", []

        keys = list(first.keys())
        if not x_key and keys:
            x_key = str(keys[0])
        if not y_key:
            for k in keys[1:]:
                if self._to_float(first.get(k)) is not None:
                    y_key = str(k)
                    break
        if not y_key and len(keys) >= 2:
            y_key = str(keys[1])

        points: List[Dict[str, Any]] = []
        for row in rows[:max_points]:
            if not isinstance(row, dict):
                continue
            label = self._safe_str(row.get(x_key))
            value = self._to_float(row.get(y_key))
            if label and value is not None:
                points.append({"label": label, "value": value})

        return x_key, y_key, points

    def _from_arrays(self, params: Dict[str, Any], max_points: int) -> Tuple[str, str, List[Dict[str, Any]]]:
        labels = params.get("labels")
        values = params.get("values")
        if not isinstance(labels, list) or not isinstance(values, list):
            return "", "", []

        x_key = self._safe_str(params.get("x_key") or "Category")
        y_key = self._safe_str(params.get("y_key") or "Value")

        points: List[Dict[str, Any]] = []
        for label, value in list(zip(labels, values))[:max_points]:
            lbl = self._safe_str(label)
            val = self._to_float(value)
            if lbl and val is not None:
                points.append({"label": lbl, "value": val})

        return x_key, y_key, points

    @staticmethod
    def _markdown_table(x_key: str, y_key: str, points: List[Dict[str, Any]]) -> str:
        head = f"| {x_key} | {y_key} |\n|---|---:|"
        body = "\n".join(f"| {p['label']} | {p['value']:.4g} |" for p in points)
        return f"{head}\n{body}"

    @staticmethod
    def _stats(points: List[Dict[str, Any]]) -> Dict[str, Any]:
        values = [float(p["value"]) for p in points]
        count = len(values)
        total = sum(values)
        avg = total / count if count else 0.0
        return {
            "count": count,
            "min": min(values) if values else None,
            "max": max(values) if values else None,
            "avg": avg if values else None,
            "sum": total if values else None,
        }

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        action = str(action_id).split(".")[-1]
        if action != "summarize":
            return {
                "ok": False,
                "status": "error",
                "error": "UNKNOWN_ACTION",
                "error_details": f"Unknown action: {action_id}",
            }

        max_points = self._max_points(params)
        x_key, y_key, points = self._from_rows(params, max_points)
        if len(points) < 2:
            x_key, y_key, points = self._from_arrays(params, max_points)

        if len(points) < 2:
            return {
                "ok": False,
                "status": "error",
                "error": "INSUFFICIENT_DATA",
                "error_details": "Could not build a numeric series with at least 2 points.",
            }

        x_key = x_key or "Category"
        y_key = y_key or "Value"
        stats = self._stats(points)
        title = self._safe_str(params.get("title") or y_key or "Data Series")
        markdown_table = self._markdown_table(x_key, y_key, points)
        summary = (
            f"{title}: {stats['count']} points analyzed. "
            f"Min={stats['min']:.4g}, Avg={stats['avg']:.4g}, Max={stats['max']:.4g}."
        )

        return {
            "ok": True,
            "status": "success",
            "error_details": summary,
            "title": title,
            "x_label": x_key,
            "y_label": y_key,
            "stats": stats,
            "points": points,
            "markdown_table": markdown_table,
            "card_hint": {
                "type": "data_chart",
                "xLabel": x_key,
                "yLabel": y_key,
                "points": points,
            },
        }
