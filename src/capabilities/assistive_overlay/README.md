# Assistive Overlay Capability

Overlay assistivo global com janela transparente click-through e TTL automatico.

## Acoes

- `overlay.assist.highlight_target`
- `overlay.assist.draw_circle`
- `overlay.assist.draw_rect`
- `overlay.assist.draw_focus_corners`
- `overlay.assist.draw_arrow`
- `overlay.assist.draw_line`
- `overlay.assist.draw_text`
- `overlay.assist.draw_path`
- `overlay.assist.clear_by_id`
- `overlay.assist.clear_all`

## Fluxo `highlight_target`

1. captura screenshot
2. locator tenta primeiro `vision.locate_screen` (contrato da capability de visao)
3. fallback: chamada direta ao `llm_manager.analyze_image` com prompt estruturado
4. renderer desenha overlay temporario

## Exemplo

```json
{
  "action": "overlay.assist.highlight_target",
  "params": {
    "label": "icone de volume",
    "mark_type": "focus_corners",
    "color": "#00E5FF",
    "ttl_ms": 2200,
    "pulse": true
  }
}
```

## Backend

- `qt` (principal): usa PySide6 em processo residente.
- `noop` (test/dev): sem desenho real, mas valida fluxo/TTL/clear.

Dependencias Linux (X11) para backend `qt`:
- Python: `PySide6` (ja no `requirements.txt`)
- Sistema (Debian/Ubuntu): `libxcb-cursor0`

Observacao sobre Linux/Wayland: por padrao opera em modo conservador (`allow_wayland=false`) e retorna indisponibilidade estruturada para nao prometer click-through completo.

## Debug visual (novo)

Para diagnosticar incoerencia de coordenadas, a capability pode renderizar uma imagem de debug:

- desenha o mesmo comando de overlay sobre o screenshot de referencia
- retorna `debug_image_path` no resultado

Como usar:

1. Em `highlight_target`, envie `debug=true`.
2. Em `draw_*`, envie:
   - `debug=true`
   - `debug_reference_path` com caminho da imagem-base

Tambem pode habilitar globalmente via config:

```json
{
  "overlay": {
    "debug": {
      "enabled": true,
      "save_on_draw": false
    }
  }
}
```
