import os
import requests
from typing import Dict, Tuple, Optional
from utils.logging_config import get_logger
from config.manager import ConfigManager

logger = get_logger("LocationService")

class LocationService:
    def __init__(self):
        self.config_manager = ConfigManager()

    def _read_config_default_location(self) -> Dict:
        location_cfg = self.config_manager.get_location_config()
        if not isinstance(location_cfg, dict):
            location_cfg = {}
        mode = str(location_cfg.get("mode") or "auto").strip().lower()

        config_root = self.config_manager.get('location', {})
        if not isinstance(config_root, dict):
            config_root = {}
        config_loc = config_root.get('default', {})

        # Compatibility with legacy 'environment.location' if needed
        if not config_loc:
            env_root = self.config_manager.get('environment', {})
            if not isinstance(env_root, dict):
                env_root = {}
            config_loc = env_root.get('location', {})
        if not isinstance(config_loc, dict):
            config_loc = {}

        cached_loc = {
            "city": config_loc.get("city") or config_loc.get("name") or "Unknown",
            "state": config_loc.get("state"),
            "country": config_loc.get("country"),
            "latitude": config_loc.get("latitude") or config_loc.get("lat"),
            "longitude": config_loc.get("longitude") or config_loc.get("lon")
        }
        return {"mode": mode, "cached": cached_loc}
        
    def get_current_location(self, context_data: Optional[Dict] = None) -> Dict:
        """
        Hierarchy of location sources:
        1. Context Data (from Web/API)
        2. Config Default (Manual cache)
        3. IP Geolocation (Optional complement)
        """
        # 1. From Context (e.g. Browser GPS)
        if isinstance(context_data, dict) and 'location' in context_data:
            loc = context_data.get('location')
            if isinstance(loc, dict):
                lat = loc.get('latitude') or loc.get('lat')
                lon = loc.get('longitude') or loc.get('lon')
                if lat is not None and lon is not None:
                    cfg = self._read_config_default_location()
                    cached_loc = cfg["cached"]
                    logger.debug(f"Location from context: {loc.get('city', 'Unknown')}")
                    return {
                        "city": loc.get("city") or cached_loc.get("city"),
                        "state": loc.get("state") or cached_loc.get("state"),
                        "country": loc.get("country") or cached_loc.get("country"),
                        "latitude": lat,
                        "longitude": lon,
                    }

        # 2. From Config (manual cache fallback; preferred over IP)
        cfg = self._read_config_default_location()
        mode = cfg["mode"]
        cached_loc = cfg["cached"]
        if self._has_usable_location(cached_loc):
            logger.debug("Location from config cache")
            return cached_loc

        # 3. Optional IP geolocation complement (only when config is not usable in auto mode)
        if mode == "auto":
            ip_loc = self._get_location_from_ip()
            if ip_loc:
                logger.debug(f"Location from IP complement: {ip_loc.get('city', 'Unknown')}")
                return ip_loc

        logger.debug("Location fallback: default unknown")
        return cached_loc

    @staticmethod
    def _has_usable_location(loc: Dict) -> bool:
        if not isinstance(loc, dict):
            return False
        city = str(loc.get("city") or "").strip().lower()
        lat = loc.get("latitude")
        lon = loc.get("longitude")
        has_city = city not in {"", "unknown"}
        has_coords = lat is not None and lon is not None
        return has_city or has_coords

    def _get_location_from_ip(self) -> Optional[Dict]:
        """Fetches approximate location using multiple IP-based APIs for resilience."""
        # Provider 1: ipapi.co
        try:
            response = requests.get('https://ipapi.co/json/', timeout=3)
            if response.status_code == 200:
                data = response.json()
                return {
                    "city": data.get("city"),
                    "state": data.get("region_code"),
                    "country": data.get("country_name"),
                    "latitude": data.get("latitude"),
                    "longitude": data.get("longitude")
                }
        except Exception as e:
            logger.debug(f"Source ipapi.co failed: {e}")

        # Provider 2: ip-api.com (Fallback)
        try:
            response = requests.get('http://ip-api.com/json/', timeout=3)
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    return {
                        "city": data.get("city"),
                        "state": data.get("region"),
                        "country": data.get("country"),
                        "latitude": data.get("lat"),
                        "longitude": data.get("lon")
                    }
        except Exception as e:
            logger.debug(f"Source ip-api.com failed: {e}")

        logger.warning("All IP geolocation sources failed. Using configuration defaults.")
        return None
