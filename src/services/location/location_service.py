import os
import requests
from typing import Dict, Tuple, Optional
from utils.logging_config import get_logger
from config.manager import ConfigManager

logger = get_logger("LocationService")

class LocationService:
    def __init__(self):
        self.config_manager = ConfigManager()
        
    def get_current_location(self, context_data: Optional[Dict] = None) -> Dict:
        """
        Hierarchy of location sources:
        1. Context Data (from Web/API)
        2. IP Geolocation (Dynamic)
        3. Config Default (Manual)
        """
        # 1. From Context (e.g. Browser GPS)
        if context_data and 'location' in context_data:
            loc = context_data['location']
            if loc.get('latitude') and loc.get('longitude'):
                logger.debug(f"Location from context: {loc.get('city', 'Unknown')}")
                return loc

        # 2. From IP (Dynamic fallback)
        ip_loc = self._get_location_from_ip()
        if ip_loc:
            logger.debug(f"Location from IP: {ip_loc.get('city', 'Unknown')}")
            return ip_loc

        # 3. From Config (Manual fallback)
        config_loc = self.config_manager.get('location', {}).get('default', {})
        # Compatibility with legacy 'environment.location' if needed
        if not config_loc:
            config_loc = self.config_manager.get('environment', {}).get('location', {})
            
        logger.debug(f"Location from config fallback")
        return {
            "city": config_loc.get("city") or config_loc.get("name") or "Unknown",
            "latitude": config_loc.get("latitude") or config_loc.get("lat"),
            "longitude": config_loc.get("longitude") or config_loc.get("lon")
        }

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
