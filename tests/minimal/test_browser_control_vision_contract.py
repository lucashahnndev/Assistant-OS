from src.skills.browser_control.vision_contract import normalize_vision_observation


def test_vision_contract_extracts_xy_pairs():
    raw = "Botao pular anuncio visivel em X: 812 Y: 134"
    obs = normalize_vision_observation(raw, goal="pular anuncio", url="https://youtube.com/watch?v=1")
    assert obs.get("schema") == "browser_control.vision.v1"
    coords = obs.get("coordinates") or []
    assert coords
    assert coords[0]["x"] == 812
    assert coords[0]["y"] == 134
    assert "Coords" in str(obs.get("prompt_view") or "")


def test_vision_contract_accepts_dict_payload():
    raw = {"summary": "Tela de player carregada", "coordinates": [{"x": 120, "y": 480, "label": "play"}]}
    obs = normalize_vision_observation(raw, goal="tocar", url="https://youtube.com")
    assert obs.get("summary") == "Tela de player carregada"
    assert (obs.get("coordinates") or [])[0]["x"] == 120
