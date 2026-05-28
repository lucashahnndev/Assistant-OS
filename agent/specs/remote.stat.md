# Remote Access Stat

Data da ultima atualizacao: 2026-05-28

## Estado atual

- especificacao de acesso remoto descentralizado mantida como contrato ativo;
- capacidades cloudflare_tunnel e ngrok_tunnel implementadas;
- endpoint de status de tuneis ativo no core;
- ui do frontend atualizada com indicador reativo e redirecionamento.

## Pendencias

- adicionar o plugin tailscale numa iteracao futura se necessario.

## Evidencias / validacoes

- integracao efetiva de cada provedor de tunnel com o runtime atual validada;
- indicador unificado e popover multi-tunnel criados e revisados;
- arquivos de capabilities criados e operacionais;
- codigo e specs commitados com sucesso (commit `0d14b326` e `c649ca0d`).

## Proximo passo recomendado

- atualizar esta stat quando o plugin tailscale for criado.
