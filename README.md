# Raspberry 🍇🔴

Agente de IA para composição MIDI no [LYNX SHARE](https://github.com/Ka1-S/LYNX-SHARE) — um DAW tipo FL-Studio. O nome: algo no tema do FL Studio, algo vermelho como o LYNX.

O agente **observa** o projeto aberto no LYNX, **analisa** o conteúdo musical (densidade, ritmo, repetição, tonalidade) e **propõe** edições MIDI. Nada é escrito no projeto sem um **portão de aprovação humano**: um diálogo local com diff, onde um token de uso único nasce só do clique em "Aprovar".

## Arquitetura

```
OpenCode (agente) ──► lynx-mcp (transporte MCP, 26 ferramentas lynx_*)
                          │  TCP loopback, protocolo lynx-control/1
                          ▼
                     LYNX SHARE (modelo nativo, fence triplo, undo nativo)
```

- **`agent/lynx_agent/`** — camada de agente em Python puro (sem transporte):
  - `analysis.py` — analisador musical (densidade, extensão, off-grid/síncopa, acentos, repetição, hipótese de tonalidade por Krumhansl).
  - `proposals.py` — contrato de proposta (ID + SHA-256 canónico) e cache de sessão que expira por sessão/projeto/revisão/prazo.
  - `approval.py` — portão de aprovação (diálogo tkinter, token de uso único com prazo).
  - `apply.py` — validação de notas (formato nativo), cálculo do novo estado, verificação pós-escrita por releitura.
  - `transforms.py` — transposição, velocity, quantização, humanização (semente reprodutível), deslocamentos.
  - `generation.py` — templates de groove (bateria/baixo) e fills com rampa de velocity.
- **`skills/lynx-agent/SKILL.md`** — coreografia multi-ferramenta e regras invioláveis (nunca escrever sem token; read-first; a grelha é derivada, nunca fonte; nomes de canais são sugestões).
- **`auditoria/`** — relatório da auditoria ao código do LYNX SHARE (modelo nativo, caminho de edição remota, garantias de escrita).
- **`plan.md`** — plano mestre do projeto (fases 0–2C, todas validadas).

## Garantias de escrita

- **Fence triplo** (`projectId` + `epoch` + `revision`) em toda escrita — se o projeto mudar, a escrita é recusada (`changed`).
- **Tudo-ou-nada**: cada lote é validado por round-trip no formato nativo antes de commit; 1 lote aceite = 1 passo de undo nativo.
- **Nunca repetir** um write com resultado `uncertain`.
- Verificação obrigatória por releitura — o agente nunca alega sucesso sem confirmar.

## Testes

```sh
# a partir da raiz, com o .venv do lynx-mcp
$env:PYTHONPATH = "agent"
python -m unittest discover agent/tests
```

## Estado

- Fase 0 (auditoria) ✓ — decisão: reutilizar o lynx-mcp sem extensão C++.
- Fase 1 (observação/análise/propostas) ✓
- Fase 2A (escrita mínima com aprovação + undo/redo) ✓
- Fase 2B (transformações) ✓ · Fase 2C (geração de grooves/fills) ✓
- Usado em projeto real: break de piano de 16 compassos (38 notas) composto a partir do motif e progressão existentes, aplicado e verificado.
