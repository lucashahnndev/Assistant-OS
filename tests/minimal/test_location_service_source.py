from services.location.location_service import LocationService


class _ConfigStub:
    def get_location_config(self):
        return {"mode": "auto"}


def test_location_service_reports_config_default_source():
    service = LocationService.__new__(LocationService)
    service.config_manager = _ConfigStub()
    service._read_config_default_location = lambda: {
        "mode": "auto",
        "cached": {
            "city": "Canoas",
            "state": "RS",
            "country": "Brazil",
            "timezone": "America/Sao_Paulo",
            "language": "pt-BR",
            "latitude": -29.9,
            "longitude": -51.1,
        },
    }
    service._get_location_from_ip = lambda: None

    result = service.get_current_location({})

    assert result["source"] == "config_default"
    assert result["mode"] == "auto"
    assert result["city"] == "Canoas"


def test_location_service_reports_context_source():
    service = LocationService.__new__(LocationService)
    service.config_manager = _ConfigStub()
    service._read_config_default_location = lambda: {
        "mode": "auto",
        "cached": {
            "city": "Canoas",
            "state": "RS",
            "country": "Brazil",
            "timezone": "America/Sao_Paulo",
            "language": "pt-BR",
            "latitude": -29.9,
            "longitude": -51.1,
        },
    }
    service._get_location_from_ip = lambda: None

    result = service.get_current_location(
        {
            "location": {
                "city": "Porto Alegre",
                "state": "RS",
                "country": "Brazil",
                "latitude": -30.0,
                "longitude": -51.2,
            },
            "timezone": "America/Sao_Paulo",
            "user_language": "pt-BR",
        }
    )

    assert result["source"] == "context"
    assert result["mode"] == "auto"
    assert result["city"] == "Porto Alegre"
