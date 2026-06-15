# Semantic Decision Boundary Spec

Data: 2026-05-29

## Propósito

Esta spec define a fronteira entre orquestracao tecnica e decisao semantica no Atlas.
Ela deve ser lida junto de [atlas_operating_model.spec.md](atlas_operating_model.spec.md), que define como o Atlas opera dentro do runtime seguro.

O runtime pode preparar o ambiente, validar contratos e aplicar seguranca.
O runtime nao deve decidir o significado final da intencao do usuario por heuristicas fixas.
Atlas decide semanticamente.

## 1. Fronteira obrigatória

### O código pode

- orquestrar ambiente, ferramentas, contexto, memória e policies;
- aplicar validação, schema, ACL, segurança, disponibilidade, concorrência e lifecycle;
- executar fallback técnico quando a saída viola contrato ou faltam dependências;
- adaptar UI, formato e envelope por canal;
- registrar evidência, telemetria e diagnósticos.

### O código nao pode

- decidir intenção semântica final;
- decidir personalidade, modo cognitivo, conclusão agentica ou escolha de ação por keyword matching, regex ou mapas fixos;
- substituir a interpretação do LLM por `if/else` que simula julgamento semântico;
- transformar heurísticas em verdade final semântica;
- reescrever a escolha do Atlas por preferência textual do orquestrador.

## 2. Heurísticas e hints

- Heurísticas semânticas, quando existirem, sao apenas sinais fracos.
- `hint` nao e decisao final.
- `keyword match` e `regex match` podem sugerir contexto, mas nao podem concluir por si mesmos a intenção final.
- Se uma heurística influenciar o comportamento, ela deve ser observável, configurável quando possivel e reversível.

## 3. Reflexes

Reflexes sao permitidos apenas para:

- comandos explícitos, como `/status` e `/cancel`;
- eventos internos determinísticos;
- emergências técnicas;
- fallback de segurança.

Reflexes nao devem ser usados como trilha principal para interpretar linguagem natural comum.
Regex de linguagem natural nao deve bypassar o LLM/Atlas como decisão semantica principal.

## 4. Orchestrator

O orchestrator pode:

- validar;
- enriquecer;
- limitar;
- registrar;
- falhar com segurança;
- corrigir parâmetros claramente técnicos.

O orchestrator nao deve:

- corrigir semanticamente a escolha do modelo por heurística textual;
- trocar a ação escolhida pelo Atlas salvo por segurança, schema, disponibilidade ou fallback técnico;
- assumir que um padrão textual equivale a uma decisão cognitiva.

## 5. Retrieval, memória e policies

- Retrieval, memória e policies devem alimentar contexto e evidência.
- Esses subsistemas nao devem decidir semântica final por `if/else` rígido.
- Eles podem priorizar, supor, sugerir ou reduzir ruido, mas nao substituir a decisão do Atlas.

## 6. Prompt composition

- O prompt composer deve compor contexto, contratos e sinais operacionais.
- O prompt composer nao deve decidir personalidade ou modo por heurística textual forte.
- Personalidade e policies devem vir de contexto declarativo, configuração ou memória, nao de inferência rígida local.

## 7. Regra final

O runtime prepara o ambiente.
Atlas interpreta o contexto.
Atlas decide semanticamente.
## Relacionados

- [semantic_decision_boundary.stat.md](semantic_decision_boundary.stat.md)
- [../README.md](../overview.md)
