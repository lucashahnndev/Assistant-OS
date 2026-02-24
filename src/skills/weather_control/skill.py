from ..base import SkillBase
from typing import Dict, Any, List
import logging
import requests
from services.location.location_service import LocationService

logger = logging.getLogger("WeatherSkill")

class WeatherSkill(SkillBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "weather"
        self.location_service = LocationService()

    @property
    def name(self) -> str:
        return "weather_control"

    @property
    def actions(self) -> List[str]:
        return ["get", "forecast"]

    @staticmethod
    def _clamp_days(value: Any, default: int = 3) -> int:
        try:
            n = int(value)
        except Exception:
            n = default
        return max(1, min(n, 5))

    def _resolve_location(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        session_ctx = {}
        session = context.get("session") if isinstance(context, dict) else None
        if session and getattr(session, "context", None):
            session_ctx = session.context

        current_loc = self.location_service.get_current_location(session_ctx)
        city = params.get("city") or params.get("location")
        lat = params.get("lat") or current_loc.get("latitude")
        lon = params.get("lon") or current_loc.get("longitude")
        return {"city": city, "lat": lat, "lon": lon}

    @staticmethod
    def _render_current_text(city: str, temp: Any, desc: str, feels_like: Any = None) -> str:
        base = f"Agora em {city} faz {temp}°C com {desc}."
        if feels_like is not None:
            base += f" Feels like: {feels_like}°C."
        return base

    @staticmethod
    def _render_forecast_text(city: str, days: List[Dict[str, Any]]) -> str:
        if not days:
            return f"I could not obter previsão para {city}."
        lines = [f"Forecast for {city} ({len(days)} dias):"]
        for day in days:
            lines.append(
                f"- {day.get('date')}: {day.get('description')} | min {day.get('temp_min')}°C | max {day.get('temp_max')}°C"
            )
        return "\n".join(lines)

    @staticmethod
    def _group_openweather_daily(items: List[Dict[str, Any]], days: int) -> List[Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for item in items:
            dt_txt = item.get("dt_txt", "")
            if not dt_txt:
                continue
            date_key = dt_txt.split(" ")[0]
            if date_key not in grouped:
                grouped[date_key] = {
                    "date": date_key,
                    "temp_min": None,
                    "temp_max": None,
                    "description": "",
                    "humidity": None,
                    "wind_speed": None,
                    "pop": None,
                }
            main = item.get("main", {})
            weather = (item.get("weather") or [{}])[0]
            wind = item.get("wind", {})
            entry = grouped[date_key]

            tmin = main.get("temp_min")
            tmax = main.get("temp_max")
            if tmin is not None:
                entry["temp_min"] = tmin if entry["temp_min"] is None else min(entry["temp_min"], tmin)
            if tmax is not None:
                entry["temp_max"] = tmax if entry["temp_max"] is None else max(entry["temp_max"], tmax)
            if not entry["description"]:
                entry["description"] = weather.get("description") or ""
            if entry["humidity"] is None:
                entry["humidity"] = main.get("humidity")
            if entry["wind_speed"] is None:
                entry["wind_speed"] = wind.get("speed")
            if entry["pop"] is None:
                entry["pop"] = item.get("pop")

        out = [grouped[k] for k in sorted(grouped.keys())]
        return out[:days]

    def _get_openweather_current(self, api_key: str, city: str, lat: Any, lon: Any) -> Dict[str, Any]:
        if city:
            url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric&lang=pt_br"
        elif lat and lon:
            url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units=metric&lang=pt_br"
        else:
            return {
                "ok": False,
                "status": "error",
                "error": "LOCATION_UNAVAILABLE",
                "message": "Location not detected and city not provided.",
            }

        response = requests.get(url, timeout=10)
        data = response.json()
        if response.status_code != 200:
            return {
                "ok": False,
                "status": "error",
                "error": "API_ERROR",
                "message": data.get("message", f"HTTP {response.status_code}"),
            }

        name = data.get("name", city or "your location")
        temp = (data.get("main") or {}).get("temp")
        feels = (data.get("main") or {}).get("feels_like")
        desc = ((data.get("weather") or [{}])[0]).get("description", "")
        humidity = (data.get("main") or {}).get("humidity")
        wind = (data.get("wind") or {}).get("speed")
        return {
            "ok": True,
            "status": "success",
            "provider": "openweather",
            "location": name,
            "current": {
                "temp": temp,
                "feels_like": feels,
                "description": desc,
                "humidity": humidity,
                "wind_speed": wind,
            },
            "text": self._render_current_text(name, temp, desc, feels_like=feels),
        }

    def _get_openweather_forecast(self, api_key: str, city: str, lat: Any, lon: Any, days: int) -> Dict[str, Any]:
        if city:
            url = f"https://api.openweathermap.org/data/2.5/forecast?q={city}&appid={api_key}&units=metric&lang=pt_br"
        elif lat and lon:
            url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={api_key}&units=metric&lang=pt_br"
        else:
            return {
                "ok": False,
                "status": "error",
                "error": "LOCATION_UNAVAILABLE",
                "message": "Location not detected and city not provided.",
            }

        response = requests.get(url, timeout=10)
        data = response.json()
        if response.status_code != 200:
            return {
                "ok": False,
                "status": "error",
                "error": "API_ERROR",
                "message": data.get("message", f"HTTP {response.status_code}"),
            }

        name = (data.get("city") or {}).get("name", city or "your location")
        daily = self._group_openweather_daily(data.get("list") or [], days=days)
        return {
            "ok": True,
            "status": "success" if daily else "empty",
            "provider": "openweather",
            "location": name,
            "days": len(daily),
            "forecast": daily,
            "text": self._render_forecast_text(name, daily),
        }

    def _get_wttr_payload(self, city=None, lat=None, lon=None, days: int = 3) -> Dict[str, Any]:
        """Fallback to wttr.in (no API key required), with current + forecast support."""
        try:
            if city:
                loc_query = city
            elif lat and lon:
                loc_query = f"{lat},{lon}"
            else:
                loc_query = ""

            url = f"https://wttr.in/{loc_query}?format=j1"
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                return {
                    "ok": False,
                    "status": "error",
                    "error": "WTTR_HTTP_ERROR",
                    "message": f"wttr.in HTTP {response.status_code}",
                }

            data = response.json()
            current = (data.get("current_condition") or [{}])[0]
            area = (data.get("nearest_area") or [{}])[0]
            area_name = (
                ((area.get("areaName") or [{}])[0]).get("value")
                or city
                or "your region"
            )

            forecast_days = []
            for item in (data.get("weather") or [])[:days]:
                hourly = (item.get("hourly") or [])
                midday = hourly[len(hourly) // 2] if hourly else {}
                forecast_days.append({
                    "date": item.get("date"),
                    "temp_min": item.get("mintempC"),
                    "temp_max": item.get("maxtempC"),
                    "description": ((midday.get("weatherDesc") or [{}])[0]).get("value", ""),
                    "humidity": midday.get("humidity"),
                    "wind_speed": midday.get("windspeedKmph"),
                    "pop": midday.get("chanceofrain"),
                })

            payload = {
                "ok": True,
                "status": "success",
                "provider": "wttr.in",
                "location": area_name,
                "current": {
                    "temp": current.get("temp_C"),
                    "feels_like": current.get("FeelsLikeC"),
                    "description": ((current.get("weatherDesc") or [{}])[0]).get("value", ""),
                    "humidity": current.get("humidity"),
                    "wind_speed": current.get("windspeedKmph"),
                },
                "days": len(forecast_days),
                "forecast": forecast_days,
            }
            payload["text"] = self._render_current_text(
                area_name,
                payload["current"]["temp"],
                payload["current"]["description"],
                feels_like=payload["current"]["feels_like"],
            )
            return payload
        except Exception as e:
            logger.error(f"wttr.in error: {e}")
            return {
                "ok": False,
                "status": "error",
                "error": "WTTR_EXCEPTION",
                "message": str(e),
            }

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        action = action_id.split(".")[-1]
        api_key = self.config.get("api_key")
        if not api_key or "ENV_" in str(api_key):
            api_key = None

        loc = self._resolve_location(params, context)
        city, lat, lon = loc["city"], loc["lat"], loc["lon"]
        days = self._clamp_days(params.get("days"), default=3)

        if action == "get":
            if api_key:
                result = self._get_openweather_current(api_key, city, lat, lon)
                if result.get("ok"):
                    return result
                logger.warning(f"OpenWeather current failed, using wttr fallback: {result.get('message')}")

            fallback = self._get_wttr_payload(city, lat, lon, days=days)
            if fallback.get("ok"):
                return {
                    "ok": True,
                    "status": fallback.get("status", "success"),
                    "provider": "wttr.in",
                    "location": fallback.get("location"),
                    "current": fallback.get("current"),
                    "fallback": True,
                    "text": fallback.get("text"),
                }
            return {
                "ok": False,
                "status": "error",
                "error": "WEATHER_UNAVAILABLE",
                "message": fallback.get("message", "Weather service unavailable."),
                "text": "I could not obter clima atual no momento.",
            }

        if action == "forecast":
            if api_key:
                result = self._get_openweather_forecast(api_key, city, lat, lon, days=days)
                if result.get("ok"):
                    return result
                logger.warning(f"OpenWeather forecast failed, using wttr fallback: {result.get('message')}")

            fallback = self._get_wttr_payload(city, lat, lon, days=days)
            if fallback.get("ok"):
                text = self._render_forecast_text(fallback.get("location", "your region"), fallback.get("forecast") or [])
                return {
                    "ok": True,
                    "status": fallback.get("status", "success"),
                    "provider": "wttr.in",
                    "location": fallback.get("location"),
                    "days": len(fallback.get("forecast") or []),
                    "forecast": fallback.get("forecast") or [],
                    "fallback": True,
                    "text": text,
                }
            return {
                "ok": False,
                "status": "error",
                "error": "FORECAST_UNAVAILABLE",
                "message": fallback.get("message", "Forecast service unavailable."),
                "text": "I could not obter previsão no momento.",
            }

        return {
            "ok": False,
            "status": "error",
            "error": "UNKNOWN_ACTION",
            "message": f"Unknown action: {action_id}",
            "text": f"Unknown action: {action_id}",
        }
