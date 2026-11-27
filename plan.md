# Plano revisto (v2): agente de IA para composição MIDI no LYNX SHARE

## Premissa de fundação

Este plano assume a existência e reutilização do [`lynx-mcp`](https://github.com/ITAgnesmeyer/lynx-mcp) (servidor MCP, Python, stdio) como **camada de transporte e ferramentas** para a API `lynx-control/1` do LYNX-SHARE. O agente não reimplementa servidor MCP, handshake, fence de revisão, paginação nem undo: consome as ferramentas `lynx_*` já verificadas em execução (build `0.1.31.1`, 26 ferramentas, M0–M3 concluídas, M4/M5 parcialmente).

O trabalho deste projeto concentra-se exclusivamente na **camada de agente**: análise musical, propostas estruturadas, fluxo de aprovação, feedback e segurança do modelo. Toda a leitura e escrita no LYNX passa pelas ferramentas do `lynx-mcp`.

## Objetivo e âmbito

Criar uma integração em que o produtor e um agente de IA trabalham sobre o mesmo projeto no LYNX SHARE. O agente lê notas e padrões existentes, propõe variações, preenchimentos e grooves, e aplica alterações apenas depois de aprovação explícita. O produtor ouve e decide. Mixagem e masterização ficam fora do âmbito.

O primeiro cenário musical é bateria e baixo em 4/4, num projeto local e numa instância do LYNX. Harmonia, melodias, sessões colaborativas e outros compassos ficam para fases posteriores. O agente deve reconhecer quando um projeto está fora do âmbito e evitar alterações não suportadas.

## Fase 0 — investigação (revisada, desbloqueada pelo lynx-mcp)

**Estado: auditoria documental parcial, não concluída — mas a verificação em execução já foi feita por terceiros.** O `lynx-mcp` fez probing real contra o build `0.1.31.1`: handshake, fence, paginação, hash de documento, leitura de padrões, escrita (no-op em `tempo.set` com mesmo valor) e exportação de áudio. Isto atalha grande parte da auditoria original.

O que resta verificar neste projeto (trabalho de auditoria, não de implementação):

1. Fixar o commit de referência e confirmar que corresponde ao build testado pelo `lynx-mcp` (`0.1.31.1`). Ler `docs/REMOTE_CONTROL.md` e `examples/remote_control.py` no commit escolhido; enumerar operações reais, esquemas, limites, revisão, undo, erros e autenticação.
2. Mapear classes, ficheiros e métodos reais de projeto, canais, padrões, instâncias de Playlist, clips com notas próprias, eventos, tempo, compasso, tonalidade, IDs e serialização. O `lynx-mcp` já documenta convenções (960 PPQ, índices 0-based, Mixer Master = 0, instrumentos nativos bloqueados em `plugin.parameters_set`); confirmar e estender.
3. Rastrear uma edição de nota pela UI até ao modelo, undo e publicação ao motor. Confirmar thread de execução, limites, comportamento em playback e dados preservados.
4. Testar revisão e atomicidade, incluindo edições locais e remotas concorrentes, undo/redo, abrir outro projeto, reiniciar, timeout e repetição de pedido. Confirmar validade dos IDs e regras de undo depois de outras edições.
5. Avaliar permissões do ficheiro de descoberta e autenticação nos três sistemas; confirmar comportamento do modo offline e possíveis credenciais ou dados sensíveis nos snapshots.
6. Construir uma prova de leitura em cópias de projetos de teste e registar resultados. Não abrir o caminho de escrita até demonstrar as garantias exigidas em 2A.

**Entregável da auditoria:** relatório com commit, ficheiros e métodos reais, resultados reproduzíveis, mapeamento das convenções já documentadas pelo `lynx-mcp` e decisão sobre reutilização. Até lá, as estimativas são preliminares.

### Resultados que alteram o plano (confirmados pelo lynx-mcp)

1. **Já existe a API remota experimental e já está consumida.** O `lynx-mcp` usa `lynx-control/1` (loopback, descoberta privada, HMAC, leituras paginadas, edições atómicas via JSON Patch, revisões, undo nativo). **Consequência:** não construir adaptador IPC, sistema de revisões nem undo. Reutilizar o `lynx-mcp`.
2. **A capacidade exata de edição de notas não está totalmente confirmada.** O `lynx-mcp` oferece `lynx_notes_replace`, que **substitui todas as notas de um padrão** (requer leitura completa paginada antes para preservar campos de expressão). Um snapshot paginado não equivale a uma API de notas parcial. **Consequência:** o "adicionar/substituir notas num intervalo" do agente tem de ser implementado como read-modify-write com preservação de tudo o que não se toca. Verificar se existe atualização parcial; caso contrário, rejeitar edições em que não se possa provar a preservação.
3. **O modelo não é simplesmente pista → clip MIDI.** Padrões no Channel Rack/Piano Roll, clips na Playlist, clips com notas próprias, grelha de clips e cenas. **Consequência:** identificar canal, padrão, clip e instância; declarar impacto sobre referências partilhadas antes de aprovar. O `lynx-mcp` expõe estas relações via `lynx_session` e `lynx_read scope=playlist`.
4. **Snapshots imutáveis para áudio.** A UI edita uma cópia e entrega snapshot imutável à thread de áudio. **Consequência:** seguir os mecanismos existentes; mapear caminhos, custo de publicação e efeito durante playback. O `lynx-mcp` não toca no áudio directamente.
5. **Undo com histórico e operações agrupadas** na API remota. **Consequência:** usar o undo nativo via `lynx_history`; verificar guardas reais antes de oferecer undo por lote. O `lynx-mcp` agrupa 1–128 ops JSON Patch num único undo.
6. **Linha temporal com alterações de compasso, tempo e marcadores de tonalidade.** **Consequência:** um único BPM/compasso/tonalidade global pode ser insuficiente. Inicialmente, rejeitar intervalos que atravessem alterações não suportadas.
7. **Projeto em alpha, offline, AGPL-3.0.** **Consequência:** testar em cópias, preservar modo offline, analisar obrigações de licença. O `lynx-mcp` é MIT e consome apenas a API (precedente a seguir).

### Mapa de código e documentação

| Local | Papel documentado | Ação de auditoria pendente |
|---|---|---|
| `docs/REMOTE_CONTROL.md` | Referência do protocolo remoto | Ler operações, esquemas, limites, revisão, undo, erros e autenticação no commit escolhido. |
| `examples/remote_control.py` | Cliente Python autónomo | Verificar descoberta, autenticação, mensagens e tratamento de erros (já espelhado no `lynx-mcp/client.py`). |
| `docs/ARCHITECTURE.md` | Organização da UI e do motor | Mapear threads, cópias e publicação de snapshots. |
| `src/core/` | Modelo, sequenciador e outros componentes em C++ | Localizar definições reais de projeto, padrões, canais, notas, clips, tempo, IDs e serialização. |
| `src/engine/` | Motor JUCE e ficheiros de projeto | Identificar publicação para áudio, ciclo de vida e caminhos de leitura/escrita. |
| `src/ui/` | Channel Rack, Piano Roll, Playlist e outras janelas | Seguir operações concretas de edição, confirmação, undo e atualização de UI. |
| `tests/` | Testes do núcleo | Identificar testes de controlo remoto, notas, undo, snapshots e concorrência; executar os relevantes. |
| `lynx-mcp` (repo externo) | Servidor MCP consumidor da API | Reutilizar; contribuir upstream se faltarem operações. |

## Princípios

- O LYNX é a fonte de verdade; o agente não edita o ficheiro do projeto em paralelo com a aplicação.
- Preferir operações estruturadas e serviços nativos via `lynx-mcp`; não simular cliques.
- Leitura e propostas não alteram o projeto. Uma alteração exige confirmação explícita do utilizador para a proposta exata.
- Apenas alterações pequenas, verificáveis e reversíveis. Em caso de dúvida, rejeitar em vez de aplicar parcialmente.
- Não fazer rede, análise pesada, escrita em disco ou espera prolongada na thread de áudio.
- Apresentar alvos, efeitos, diferenças e limitações; o produtor mantém a decisão musical.
- **Não reimplementar o que o `lynx-mcp` já oferece.** Toda a I/O com o LYNX passa por ferramentas `lynx_*`.

## Arquitetura proposta

```
Cliente de IA (OpenCode/Claude/etc.)
        │  MCP (stdio)
        ▼
lynx-mcp  (transporte + 26 ferramentas lynx_*, fence, paginação, undo)
        │  TCP 127.0.0.1, lynx-control/1, JSON lines
        ▼
LYNX SHARE  (modelo, snapshots, UI, motor de áudio)
```

A **camada de agente** (este projeto) é um skill + orquestração sobre as ferramentas `lynx_*`, não um novo servidor MCP. Componentes:

- **Skill de agente** (`skills/lynx-agent/SKILL.md`): choreografia multi-ferramenta, regras musicais, preservação de atributos.
- **Serviço de propostas**: cache local limitada à sessão com ID + hash criptográfico do conteúdo; expira ao fechar sessão, mudar projeto, mudar revisão ou ultrapassar prazo. Não é fonte de verdade.
- **Portão de aprovação**: componente confiável fora do controlo do modelo — preferencialmente UI nativa do LYNX ou diálogo local seguro. Um texto no chat em que o próprio modelo afirma ter recebido aprovação não constitui autorização verificável. (Decisão de design a fechar antes da Fase 2A; o `lynx-mcp` não fornece este mecanismo.)
- **Analisador musical**: densidade, extensão, repetição, ritmo, avisos limitados ao trecho.

O servidor MCP transforma pedidos de alto nível em consultas e operações limitadas; não executa shell nem código arbitrário. Os dados partilhados com o modelo são o mínimo necessário.

## Representação MIDI e endereçamento

Usar como referência os eventos e atributos nativos que o LYNX efetivamente representa, com posições e durações na precisão original (960 PPQ, confirmado). Não pressupor que todos os eventos MIDI externos sobrevivem à importação. A grid de 16 ou 32 passos é uma **vista derivada**, com resolução, arredondamento e erro indicados; nunca é a fonte exclusiva de uma reescrita.

Preservar notas fora da grid, microtiming, swing, comprimentos, canais, atributos de nota e eventos não visados, incluindo CC, pitch bend e expressão por nota quando suportados. Se não for possível provar a preservação de atributos ou eventos afetados, rejeitar a edição. Para bateria, evitar avisos de escala sem pertinência.

O contexto inclui intervalo, posições e unidades, mapa de tempo e compasso relevantes, instrumento/canal e padrão. Tonalidade deve ser marcada como **definida, inferida com incerteza, ou desconhecida**, podendo variar ao longo do projeto.

O alvo inclui `project_id`, identidade de sessão, canal/pista, padrão, clip e instância quando aplicáveis, intervalo semiaberto com origem explicitada e lista de instâncias afetadas. Distinguir posição no padrão da posição no projeto. Se uma instância partilha o padrão com outras, mostrar todas as referências afetadas; se não for possível demonstrar o alcance, recusar. Não criar cópias independentes implicitamente.

## Mapeamento de ferramentas: plano ↔ lynx-mcp

| Ferramenta do plano | Ferramenta lynx-mcp equivalente | Notas |
|---|---|---|
| `get_project_summary` | `lynx_status` + `lynx_session` + `lynx_read scope=summary` | Combinar; o `lynx-mcp` já devolve identidade, revisão, tempo/compasso, contagens, canais, padrões, arranjos. |
| `list_midi_targets` | `lynx_session` (canais, padrões, clips, mixer) + `lynx_read scope=playlist` | IDs, relações e confiança nas etiquetas de função; nomes como `Kick`/`Bass` são sugestões, não factos. |
| `get_midi_events` | `lynx_read scope=pattern_notes` (paginado por `offset`/`limit`) + `lynx_snapshot` | Vista em grid derivada é cálculo do agente, nunca fonte. |
| `analyze_midi` | (agente, sobre dados de `get_midi_events`) | Densidade, extensão, repetição, ritmo; tonalidade apenas como hipótese ou valor fornecido. |
| `propose_midi_edit` | (agente; persistência no serviço de propostas) | Não escreve no LYNX. Produz proposta estruturada. |
| Escrita mínima | `lynx_notes_replace` (read-first!), `lynx_patch` (1–128 ops = 1 undo), `lynx_tempo_set`, `lynx_pattern_create/clone/set`, `lynx_channel_create/set`, `lynx_mixer_set`, `lynx_playlist_edit`, `lynx_transport`, `lynx_history` | Fence server-side; writes exigem playback parado. |
| Verificação pós-escrita | `lynx_read` + `lynx_status` | Releitura obrigatória; não declarar sucesso se estado desconhecido. |
| Undo | `lynx_history action=undo/redo` | Só solicitar undo directo do lote quando a API demonstrar que é o elemento apropriado no topo da pilha. |
| Export de áudio | `lynx_export` | Headless, não toca na instância em execução. |

**Regra de ouro do `lynx-mcp`:** Schreiboperationen erfordern gestopptes Playback; niemals `uncertain`-Fehler automatisch wiederholen; nach strukturellem Change immer neu lesen.

## Fase 1 — observação e propostas, sem escrita

Construir a camada de agente sobre o `lynx-mcp` (skill + serviço de propostas + analisador). Não construir servidor MCP.

Ferramentas do agente (novas, em cima das `lynx_*`):

- `get_project_summary`: wrapper sobre `lynx_status` + `lynx_session` + `lynx_read scope=summary`. Devolve projeto/sessão, revisão, mapa de tempo/compasso relevante e resumo de canais, padrões e arranjos.
- `list_midi_targets`: wrapper sobre `lynx_session` e `lynx_read scope=playlist`. Canais, padrões e clips elegíveis com IDs, relações e confiança nas etiquetas de função.
- `get_midi_events`: wrapper sobre `lynx_read scope=pattern_notes` (paginado). Eventos e atributos disponíveis para um alvo e intervalo; opcionalmente uma vista em grid derivada.
- `analyze_midi`: densidade, extensão, repetição, ritmo e avisos limitados ao trecho; tonalidade apenas como hipótese ou valor fornecido.
- `propose_midi_edit`: criar proposta estruturada e legível, com eventos antes/depois, razão, alcance e avisos. Não escreve no LYNX.

As propostas são guardadas pelo serviço de aprovação numa cache local limitada à sessão, identificadas por ID e resumo criptográfico do conteúdo; expiram ao fechar a sessão, mudar o projeto, mudar a revisão ou ultrapassar o prazo definido. Não são fonte de verdade. Os dados partilhados com o modelo são o mínimo necessário.

**Conclusão:** projeto de teste aberto; leitura de um alvo e trecho coerentes; análise e proposta de fill ou variação sem alteração do projeto. Testar vazio, nomes duplicados, sessão reiniciada, limite de paginação e falha de ligação.

## Fase 2A — escrita mínima com aprovação

Permitir apenas adicionar ou substituir notas num alvo existente e elegível, mantendo todos os restantes dados. Exigir:

1. Proposta com sessão, revisão, alvo, referências afetadas, intervalo, alterações de notas, valores anteriores e posteriores e razão.
2. Diff legível e confirmação local ligada ao ID e ao hash exato da proposta, revisão e alvo. A autorização é de uso único; qualquer alteração invalida-a. (Portão de aprovação fora do controlo do modelo.)
3. Validação de identidade de sessão, revisão, permissões, limites, alvos e conteúdo, seguida de execução sem janela de concorrência entre validação e aplicação. Reutilizar a transação existente (`lynx_patch` com 1–128 ops) apenas depois de demonstrar que cobre toda a operação.
4. Aplicação integral ou nenhuma alteração. Se não existir transação adequada ou reversão segura comprovada, recusar o lote. Não considerar um undo genérico prova suficiente de rollback transacional.
5. Uma entrada de undo nativo identificável via `lynx_history`, releitura do resultado efetivo (`lynx_read` + `lynx_status`), atualização da UI e resultado estruturado. Se o resultado não corresponder, reportar o erro e não alegar sucesso.

**Undo:** integrar com a pilha nativa via `lynx_history`. O agente só solicita o undo directo do seu lote quando a API demonstrar que é o elemento apropriado no topo da pilha e a revisão/identidade esperadas continuam válidas. Caso contrário, informar o produtor e não desfazer outras ações. Verificar redo e alterações posteriores.

**Timeout e idempotência:** associar um ID de pedido único ao lote. O `lynx-mcp` não tem deduplicação durável; se a API não suportar consulta de estado duráveis para a sessão, implementar mecanismo adequado no lado autoritativo ou tratar o resultado como desconhecido, voltar a consultar e nunca repetir automaticamente uma escrita cuja execução seja incerta. Um cache apenas no cliente não garante idempotência após falha do processo. Respeitar a regra do `lynx-mcp`: nunca repetir automaticamente um erro `uncertain`.

**Conclusão:** edição aprovada visível no projeto e desfeita num passo; conflito rejeitado sem alteração; eventos não visados preservados; timeout tratado sem duplicação; nenhum lote parcial.

## Fases seguintes

- **2B — operações mecânicas:** transposição, velocidade e quantização explícita sobre notas selecionadas, com os mesmos controlos e preservação de atributos. Humanização apenas com limites e semente reproduzível. (Implementável via `lynx_patch` ou `lynx_notes_replace` com read-modify-write.)
- **2C — composição assistida:** fills, deslocamentos rítmicos, variações e templates de groove para bateria e baixo.
- **Posterior:** harmonização, arpejos, contramelodia, mais compassos, clip-launch e colaboração. Definir separadamente a semântica das alterações em sessões ao vivo antes de as permitir.

## Estado, sincronização e contexto

Cada leitura inclui identidade da sessão/projeto e revisão (via `lynx_status`/`lynx_session`). Antes de propor, reler os detalhes relevantes; antes de aplicar, confirmar que a mesma revisão permanece válida. Uma alteração do produtor ao mesmo clip entre proposta e confirmação invalida a proposta. Se a revisão for global, alterações irrelevantes também podem exigir nova proposta: é uma limitação conservadora aceitável no MVP.

Começar com consultas sob pedido e revisão; usar notificações existentes apenas depois de verificar o seu contrato. O `lynx-mcp` não tem push — usar polling via `lynx_changes` (máx. 128; `gap:true` ⇒ Vollread) ou `lynx_status` (revisão como ticker barato). Após reconexão ou perda de eventos, invalidar cache e reler. Para múltiplas janelas, associar explicitamente cada pedido à sessão alvo e recusar ambiguidade.

A consulta é progressiva: resumo pequeno → alvo e relações → eventos do intervalo. Limitar respostas e indicar truncagem, paginação e campos omitidos (o `lynx-mcp` já pagina `lynx_read` e trunca respostas a ~200 KiB com flag `truncated`). Manter memória curta da tarefa, mas nunca usar a memória como substituto da releitura. Nomes como `Kick` ou `Bass` são sugestões, não factos; permitir correção.

## Budget de tokens (teoria adaptada do Kumi)

O agente não reimplementa gestão de contexto (o OpenCode já comprime), mas segue a **teoria** do Kumi (`crates/kumi-agent/src/kernel/budget.rs`) para a disciplina de leitura e para um eventual cliente próprio:

- **Medição:** bytes de JSON da conversa (~3 bytes por token), não tokenização. `BYTES_PER_TOKEN = 3.0`.
- **Dois limiares:** `clear_at` (soft, 40% do limite) e `limit` (hard). Default Kumi: 160 KiB / 400 KiB (~53k / ~133k tokens), deixando ~25–30k tokens para instruções + ferramentas `lynx_*` e espaço para a resposta.
- **Para modelos com janela menor:** `limit = min(default, max(16 KiB, (window - answer) * 3 - fixed))`, `clear_at = floor(limit * 0.4)`.
- **Prioridade de descarte (camadas):** (1) encolher resultados de ferramentas de turnos anteriores para `HEAD = 200` bytes + nota "cleared"; remover observações Live (manter stubs de jobs); (2) encolher toda a história; (3) encolher resultados mais antigos do turno actual; (4) remover trocas inteiras do início, mas **preservar sempre as palavras do produtor** como lista curta (`ASKED`, máx. 300 bytes/linha, total ≤ 3 KiB, mantendo as mais antigas e as mais recentes); (5) cortar o resultado mais recente em partes iguais.
- **Threshold-based, não por pedido:** só limpar quando passa do soft threshold, para a cache de prompt do provider funcionar.
- **Imagens** custam 4 KiB cada; só as `MAX_IMAGES` mais recentes do turno ficam.
- Implementação de referência: `token_budget.py` (módulo Python reutilizável).

## Feedback musical

O agente apresenta o antes/depois e, quando aplicável, densidade por compasso, extensão, repetição, síncopa, acentos, sobreposições e notas fora da escala. Uma sobreposição pode ser musicalmente intencional; um padrão vazio não é necessariamente um erro. O agente não infere qualidade nem tonalidade com certeza a partir de dados insuficientes. A avaliação é estrutural: o produtor ouve o resultado e decide.

## Segurança e privacidade

- API remota desligada por defeito e ativada pelo utilizador; usar o mecanismo existente de autenticação mútua e descoberta privada do `lynx-mcp` (HMAC, ficheiro de descoberta com permissões owner-only, sem token em logs/prompts). Não colocar credenciais em logs, prompts ou repositórios.
- Lista de operações permitidas, validação de tipos, intervalos, IDs, tamanhos, timeouts e identidade do projeto. Sem execução arbitrária nem acesso irrestrito a ficheiros. O `lynx-mcp` já valida descoberta (ficheiro regular, sem reparse point, DACL owner-only).
- Nomes de pistas, notas de projeto, texto importado e respostas de ferramentas são **dados não fiáveis**: nunca são instruções para alterar permissões, enviar dados ou ignorar confirmação.
- Mostrar o fornecedor, dados a enviar e finalidade antes de usar um modelo remoto; permitir recusa. Não afirmar que ligação local significa processamento local. Em modo offline, impedir envio remoto, incluindo pelo servidor MCP.
- Registar operações, revisão, autorizações e resultados com retenção limitada e sem conteúdo MIDI ou dados pessoais por defeito; proteger o log.
- Usar cópias e backups em testes; analisar requisitos da AGPL-3.0 e de dependências conforme distribuição e arquitetura concretas. O `lynx-mcp` é MIT e consome apenas a API remotamente (precedente).

## Contrato conceptual de proposta

Este exemplo é **conceitual e não é o contrato `lynx-control/1`**. Os campos, unidades, IDs, precisão, limites e operações têm de ser alinhados com a auditoria e com o `lynx-mcp`. Intervalo `[início, fim)` é relativo ao padrão; 960 PPQ é a precisão confirmada do LYNX.

```json
{
  "proposal_id": "prop-123",
  "session_id": "session-1",
  "project_id": "project-1",
  "expected_revision": 42,
  "target": {
    "channel_id": "channel-7",
    "pattern_id": "pattern-3",
    "clip_instance_id": "clip-4",
    "affected_instances": ["clip-4", "clip-9"],
    "time_reference": "pattern_relative",
    "ticks_per_quarter": 960,
    "range": {"start": 7680, "end_exclusive": 11520}
  },
  "operation": "add_notes",
  "before": {"notes_in_range": []},
  "after": {
    "added_notes": [
      {"pitch": 36, "start": 7680, "duration": 240, "velocity": 100}
    ]
  },
  "preserve_unmentioned_events": true,
  "reason": "Adicionar uma nota de baixo no início do terceiro compasso."
}
```

O diff deve mostrar a escala dos valores, qualquer aproximação e todas as instâncias afetadas. A confirmação e a aplicação usam ID e hash calculados sobre a proposta integral; não aceitam alterações de conteúdo depois da aprovação. A resposta informa estado por operação, revisão efetiva, ID do lote e disponibilidade de undo, sem declarar sucesso quando o estado for desconhecido.

## Testes e definição de pronto

- [ ] Leitura em cópias de projetos sem alterações; paginação, nomes duplicados e padrões vazios.
- [ ] Padrões partilhados, clips independentes, loops, recortes e posições relativas apresentados corretamente ou rejeitados quando não suportados.
- [ ] Tempo e compasso variáveis tratados corretamente ou trecho rejeitado; tonalidade desconhecida é válida.
- [ ] Aprovação ligada à proposta exata, expirada ou recusada quando projeto/sessão/revisão mudam.
- [ ] Concorrência entre validação e escrita testada; operações integrais, sem efeitos parciais nem perda de atributos não visados.
- [ ] Undo/redo nativo, edição humana posterior, timeout, desconexão, reinício e repetição sem duplicação verificados.
- [ ] Permissões locais, credenciais, privacidade, prompt injection e modo offline testados.
- [ ] Playback testado com projeto e hardware documentados, versão, driver, taxa, tamanho de buffer, duração e carga. Comparar controlo sem agente com leituras e edições repetidas; registar xruns, interrupções, atrasos de callback e observação auditiva quando disponíveis. Definir limiares por plataforma antes da execução e reportar resultados, sem extrapolar para todos os dispositivos.
- [ ] UI e dados relidos após aplicação; testes de regressão e exportação/serialização dos dados preservados quando aplicável.
- [ ] Integração com `lynx-mcp` verificada: todas as leituras/escritas passam por ferramentas `lynx_*`; nenhum acesso directo ao LYNX fora do MCP.

## Sequência e estimativas

Estimativas para uma pessoa experiente a tempo inteiro; não foram validadas por execução nem por auditoria completa. A reutilização do `lynx-mcp` reduz drasticamente o trabalho de infraestrutura; lacunas de notas, confirmação e compatibilidade podem aumentá-lo.

| Marco | Resultado | Estimativa preliminar |
|---|---|---|
| 0 | Completar auditoria técnica e prova de leitura (alavancando verificação live do `lynx-mcp`) | 1–3 dias |
| 1 | Camada de agente: skill + `get_project_summary`/`list_midi_targets`/`get_midi_events`/`analyze_midi`/`propose_midi_edit` sobre `lynx-mcp` | 3–5 dias após auditoria |
| 2A | Escrita mínima, aprovação, conflito e undo (read-modify-write via `lynx_notes_replace`/`lynx_patch`) | 1–2 semanas, dependente das garantias existentes e do portão de aprovação |
| 2B/2C | Operações mecânicas e variações | A estimar após 2A; não incluídas no prazo anterior |

## Primeiro passo prático

Fixar o commit, ler `docs/REMOTE_CONTROL.md` e o cliente de exemplo, e executar uma prova de leitura em projeto de teste usando o `lynx-mcp` (instalar, configurar, correr `probe`). Em paralelo, seguir no código uma nota do Piano Roll até ao modelo, undo e snapshot de áudio. Comparar os resultados reais com os requisitos de 2A e decidir se é necessária extensão em C++ (contribuição upstream ao LYNX) ou se o `lynx-mcp` já cobre. Fechar a decisão do portão de aprovação antes de iniciar a escrita.