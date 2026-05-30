# Secret Transport Encryption Phase 2 (2026-03-12)

> Historical report. This transport-encryption note reflects an earlier security stage and may not match the current discovery-first contract.

## Implementação

### Backend
- `src/server/core/secret_transport_crypto.py`
  - criptografia híbrida: `RSA-OAEP-256 + AES-256-GCM`
  - endpoint usa chave pública para frontend cifrar
  - backend decripta com chave privada

- `src/server/routes/secrets.py`
  - novo `GET /api/secrets/transport-key`
  - `POST /api/secrets` aceita payload cifrado em `encrypted`
  - política opcional de enforcement via `SECRET_TRANSPORT_REQUIRE_ENCRYPTION`

### Frontend
- `frontend/src/utils/secretCrypto.js`
  - usa WebCrypto para cifrar segredo antes do envio
- `frontend/src/utils/secretsApi.js`
  - handshake automático com `/api/secrets/transport-key`
  - envia payload cifrado quando chave pública estiver disponível
  - fallback plaintext somente quando backend não exigir criptografia

## Variáveis de Ambiente (produção)

1. Chave privada de transporte (persistente)
- `SECRET_TRANSPORT_PRIVATE_KEY_PEM`
- ou `SECRET_TRANSPORT_PRIVATE_KEY_FILE`

2. Exigir criptografia de transporte
- `SECRET_TRANSPORT_REQUIRE_ENCRYPTION=true`

3. Gestão de secrets por chave administrativa (opcional)
- `SECRET_MANAGEMENT_KEY=<chave forte>`
- fallback aceito: `SECRET_DECRYPTION_KEY=<chave forte>`

## Recomendação operacional
1. Definir chave privada persistente (não usar fallback efêmero)
2. Ativar `SECRET_TRANSPORT_REQUIRE_ENCRYPTION=true`
3. Exigir acesso por sessão admin web ou chave de gestão
4. Rotacionar `SECRET_MANAGEMENT_KEY` periodicamente

## Observação
Sem chave privada persistente configurada, o backend gera uma chave efêmera ao subir o processo; isso funciona para sessão corrente, mas não é ideal para produção.
