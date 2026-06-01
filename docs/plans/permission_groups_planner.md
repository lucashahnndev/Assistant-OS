# Planner: Migração para Permissões por Grupo (Customizável)

## Objetivo
Migrar o controle de permissão de *skill por usuário* para um modelo **group-based** customizável, mantendo compatibilidade com overrides pontuais e sem quebrar UI/React.

## Escopo
1. Backend/Core:
   - Modelo de `PermissionGroup`.
   - Vínculo `group_id` em `UserEntity` e `ChatEntity`.
   - Políticas de interface com grupos padrão e grupos de auto-approve.
   - Gate de acesso (prompt + dispatch) baseado em grupo + override.
2. API:
   - CRUD de grupos.
   - Atribuição de grupo para usuário/chat.
   - Configuração de grupo padrão por interface.
3. Web UI:
   - Aba de grupos.
   - Seleção de grupo em usuários/chats.
   - Seleção de grupos padrão no tab de configuração.
4. Migração operacional:
   - Web user principal em `master`.
   - Reset de identities quando solicitado.

## Fases
### F1 - Modelagem e Persistência
- [x] `PermissionGroup` no core.
- [x] `group_id` em usuário/chat.
- [x] Bootstrap de grupos padrão (`master`, `medium`, `critical`).

### F2 - Enforcement no AccessController
- [x] Regras efetivas: grupo + overrides.
- [x] Prompt scope filtrado por grupo.
- [x] Dispatch gate filtrado por grupo.
- [x] Auto-vínculo por interface/estado de entrada.

### F3 - API Admin
- [x] `GET/POST/PATCH/DELETE /api/messaging_access/groups`.
- [x] `POST /api/messaging_access/users/{...}/group`.
- [x] `POST /api/messaging_access/chats/{...}/group`.
- [x] Config por interface com grupos padrão/auto-approve.

### F4 - UI Web (sem quebrar design)
- [x] Aba `groups`.
- [x] Gestão de grupos (create/edit/delete).
- [x] Coluna/selector de grupo em usuários e chats.
- [x] Selects de grupos padrão em `config`.

### F5 - Validação
- [x] Testes unitários de grupo (bootstrap/enforcement/auto-assign).
- [x] Testes de identidade web user-based.
- [ ] Rodada manual no painel web com fluxo real.

## Critérios de Pronto
- Usuários/chats não precisam mais de matriz skill-a-skill para operação padrão.
- `master` mantém acesso total por wildcard e novas skills entram automaticamente.
- Fluxo web usa identidade de usuário (não `session_id`) para autorização.
- UI permite administrar grupos sem alterar layout base.

## Relacionados

- [../policies/README.md](../policies/README.md): políticas de governança que cercam o plano.
- [../reports/skills-architecture-audit-2026-03-12.md](../reports/skills-architecture-audit-2026-03-12.md): audit que motiva a padronização de governança.
- [../../agent/specs/skill_contract.spec.md](../../agent/specs/skill_contract.spec.md): contrato normativo das skills afetadas pelo modelo de permissão.
- [../../agent/specs/system_architecture.spec.md](../../agent/specs/system_architecture.spec.md): contrato arquitetural do sistema que aplica o gate.
