# Budget de tokens — teoria adaptada do Kumi

Fonte: `user1303836/kumi`, `crates/kumi-agent/src/kernel/budget.rs` e `crates/kumi-ai/src/binding.rs`.
Implementação de referência: `token_budget.py`.

## Medição
- Conversa medida em **bytes de JSON** (~3 bytes por token), não tokenização.
- `BYTES_PER_TOKEN = 3.0`.

## Budget
```python
ContextBudget(clear_at, limit)  # em bytes
```
- Default Kumi: `clear_at = 160 KiB`, `limit = 400 KiB` (~53k / ~133k tokens).
- Deixa ~25–30k tokens para instruções + ferramentas `lynx_*` e espaço para a resposta.
- Modelos com janela menor:
  - `limit = min(default, max(16 KiB, (window - answer) * 3 - fixed))`
  - `clear_at = floor(limit * 0.4)`

## Constantes
| Nome | Valor | Significado |
|---|---|---|
| `HEAD` | 200 | bytes mantidos de um resultado limpo |
| `SMALL` | 1024 | resultados deste tamanho ficam inteiros |
| `ASK` | 300 | bytes máx. de uma linha do produtor |
| `ASKS` | 3 KiB | total da lista de pedidos do produtor |
| `IMAGE_BYTES` | 4 KiB | custo de uma imagem |
| `MAX_IMAGES` | (kumi-types) | imagens por pedido |

## Algoritmo de ajuste (`fit`)
Só actua quando passa dos limiares (preserva cache de prompt):

1. Se `history + turn ≤ clear_at` → sem alteração.
2. **Camada 1:** limpar resultados de ferramentas de turnos anteriores (cortar para `HEAD` + nota); remover observações Live (manter stubs de jobs). Manter observação do último turno.
   - Se `≤ limit` → fim.
3. **Camada 2:** limpar toda a história.
   - Se `≤ limit` → fim.
4. **Camada 3:** limpar resultados mais antigos do turno actual (até ao último índice de ferramenta).
   - Se `≤ limit` → fim.
5. **Camada 4:** remover trocas inteiras do início até caber em 75% do limite, com espaço para `SHORTENED` + lista de pedidos do produtor. **Preservar sempre as palavras do produtor** (mais antigas e mais recentes; remover as do meio).
6. **Camada 5:** cortar o resultado de ferramenta mais recente em partes iguais (mínimo `HEAD + CUT`).

## Preservação de intenção
- Palavras do produtor nunca descartadas silenciosamente.
- Resultados grandes cortados para "opening + nota de re-leitura".
- Observações Live (dados) são as primeiras a ir.

## Persistência
- `without_observations`: remove observações ao guardar conversas (mantém stubs de jobs).
- `transcript_of`: reconstrói vista de UI.

## Aplicação no LYNX Agent
- O agente não controla o buffer do OpenCode; esta teoria governa a **disciplina de leitura** do skill: resumo pequeno → alvo → eventos paginados; não guardar dumps completos; re-ler em vez de confiar na memória.
- Se um dia se construir cliente próprio, portar `token_budget.py` / `budget.rs`.