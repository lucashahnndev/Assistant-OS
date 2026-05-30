# Secret Management Standardization (2026-03-12)

> Historical report. This standardization note reflects an earlier secret-management stage and may not match the current discovery-first contract.

## Objetivo
Padronizar a gestão de secrets para uso reutilizável no sistema web, com política de acesso forte:
- sessão web admin autenticada, **ou**
- posse de chave de gerenciamento/decriptação via header.

## Backend Implementado

### Novo núcleo reutilizável
- `src/server/core/secret_manager.py`
- Funções:
  - leitura/escrita atômica de `.env`
  - normalização de refs `ENV_*`
  - listar refs sensíveis
  - criar/atualizar/remover secret

### Nova API canônica
- `src/server/routes/secrets.py`
- Endpoints:
  - `GET /api/secrets/refs`
  - `POST /api/secrets`
  - `DELETE /api/secrets/{key}`

### Gate de acesso
Acesso permitido por:
1. usuário admin autenticado via web (`access_token` cookie), ou
2. header com chave válida:
   - `X-Secret-Management-Key`
   - ou `X-Secret-Decryption-Key`

Chave esperada no backend:
- `SECRET_MANAGEMENT_KEY` (preferencial)
- fallback: `SECRET_DECRYPTION_KEY`

### Integração no app
- Router adicionado em `src/server/main.py`

## Frontend Padronizado

### Utilitário único
- `frontend/src/utils/secretsApi.js`
- Funções:
  - `listSecretRefs()`
  - `createSecret(...)`
  - `deleteSecret(...)`

### Telas migradas para API canônica
- `frontend/src/pages/Capabilities.jsx`
- `frontend/src/pages/Settings.jsx`
- `frontend/src/components/ModelPoolManager.jsx`

Fluxo UX preservado:
- selecionar ref existente
- criar nova secret
- vincular ref sem exibir valor

## Observações de Segurança
- Transporte continua protegido por HTTPS/TLS.
- Este passo padroniza governança/acesso e reduz exposição de valor no frontend.
- Criptografia de payload no cliente (além de TLS) pode ser adicionada em fase seguinte (JWE/HPKE/libsodium sealed box).
