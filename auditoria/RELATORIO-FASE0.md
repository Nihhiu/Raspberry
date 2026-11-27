# Relatório de Auditoria — Fase 0 (LYNX-SHARE + lynx-mcp)

Data: 2026-11-27 · Commit de referência fixado: **`3e978976551c4ea3e143c46c1dfa089935bfcb66`** (tag `v0.1.31.1-alpha`, verificado com `git rev-parse` no clone local `D:\trabalho\LYNX Agent\lynx-share`).

Fontes: `docs/REMOTE_CONTROL.md` e `examples/remote_control.py` (commit fixado), dois relatórios de exploração do código C++ (modelo nativo + caminho de edição), e prova de leitura ao vivo contra a instância instalada do LYNX SHARE.

## 1. Resultado principal — decisão de reutilização

**DECISÃO: reutilizar o lynx-mcp como única camada de transporte. Não é necessária extensão C++ para a Fase 1 nem para a 2A.**

Todas as garantias exigidas pela 2A existem no código nativo e são consumíveis via `lynx_*`:

| Garantia exigida pelo plano (2A) | Onde vive no LYNX | Via lynx-mcp |
|---|---|---|
| Fence de sessão (project/epoch/revision) | `RemoteControl.cpp:292-300`; epoch = token por boot; revision = `AudioEngine::songStamp` | Preenchido server-side pelo lynx-mcp a partir do último read |
| Atomicidade (tudo-ou-nada) | Staging em cópia + validação round-trip nativo antes do commit (`RemoteProjectDocument.cpp:502-528`, `AudioEngine.cpp:7781-7821`) | `lynx_patch` (1–128 ops RFC 6902 = 1 undo) e `lynx_notes_replace` |
| 1 undo nativo identificável por lote | `HistoryEntry{song, remote, deviceHash}` (`AudioEngine.h:1894`) | `lynx_history action=undo/redo` com fence opcional `expectedDeviceStateHash` |
| Recusa em playback/gravação | `RemoteControl.cpp:301-304,368-369,388-389`; `AudioEngine.cpp:7783` | Writes do lynx-mcp exigem transport parado (comportamento herdado) |
| Preservação de campos não visados | Round-trip `fromJson`→`toJsonExact` deep-equal rejeita tudo o que o formato nativo descartaria | `lynx_notes_replace` exige todos os campos (read-modify-write); `lynx_patch` para o resto |
| Nunca repetir `uncertain` | Falha pós-commit devolve `uncertain` (`RemoteProjectControl.cpp:126`) | Regra de ouro do lynx-mcp (client.py) |

## 2. Modelo nativo (ficheiros reais)

Tudo em `src/core/Song.h` — o projeto é um único value type `struct Song` (linha 2964), copiado por inteiro em cada edição; publicação de snapshot imutável para a thread de áudio via `SnapshotExchange<RackState>` (`core/SnapshotExchange.h`, publish em `AudioEngine.cpp:5658`), sem locks nem alocação na thread de áudio.

- `Note` (`Song.h:1812`): start/length (int64 ticks, ≤1e9), channel, key (0-127, 60=C4), velocity (0-1, default 0.78), pan (−1..1), finePitch (cents −120..120), muted, slide, porta, held, release (0-1, default 0.5), modX/modY (0-1), colour (0-15), group, chance, velocityRange (−1..1), chanceGroup, chanceOne, repeat (0-14), curves (MPE). MPE = `NoteCurves` copy-on-write com 3 lanes pitch/timbre/pressure, ticks relativos ao início da nota, ±4800 cents, ≤4096 pontos/lane (`core/NoteCurves.h`).
- `Pattern` (`Song.h:1972`): `lengthTicks = 0` é automático (arredonda fim da última nota a compassos inteiros, `Song.cpp:60-74`); `uid` 64-bit → `patternId` hex na rede; uids re-normalizados a cada publish. Novas entidades remotas omittem uid; existentes preservam-no.
- Referências a padrões: clips (`Clip::pattern`), `currentPattern`, blocks legacy, loop starters (`ChannelDef::loopStarterPattern`). Índices são **posicionais** — insert/remove renumera tudo (`RackOps.cpp:121-141`, `Song::removePattern` em `Song.cpp:252-281`); projeto mantém sempre ≥1 pattern. Cliente nunca deve fazer cache de índices.
- Clips partilham o padrão por referência (edits visíveis em todos); independência só via track clips (`ownClips`/`Pattern::trackClip`).
- Serialização .lynx: notas são **arrays compactos** truncados no último não-default (`ProjectFile.cpp:3199-3260`); documento remoto = `toJsonExact` com 17 dígitos significativos (ficheiros gravados: 15 + arredondamento), base64 paginado, SHA-256, ≤64 MiB.

## 3. Caminho de edição remota

- Servidor: TCP loopback, uma ligação por pedido, handshake HMAC-SHA256 mutuo (`engine/RemoteAuthentication.h`), ops ≤1 MiB, depth ≤64. Discovery: `connection.json` (port+token+pid), override `LYNX_CONTROL_DISCOVERY`.
- **Ops executam na JUCE message thread** (`RemoteControl.cpp:452-515` via `MessageManager::callAsync`); a thread de áudio nunca bloqueia em edições (só o callback lock do plugin hospedado durante restore de estado).
- `pattern.replace_notes` (`RemoteControl.cpp:366-385`): recusa em playback → parse ≤10.000 notas (todos os campos obrigatórios) → `editSongRemoteTransaction`.
- `editSongRemoteTransaction` (`AudioEngine.cpp:7781`): busy-guard → snapshot → staging → no-op por igualdade de serialização exata → undo step com flag `remote` + device-hash → `publishSong` (revision++) → sync de plugin states. Falha pós-commit ⇒ `uncertain`.
- `project.edit`: exige `snapshotId` + `expectedDocumentHash` de um `project.read` prévio (deque de 4 snapshots, invalidados a cada revisão); allowlist por shape (`RemoteProjectDocument.cpp:37-188`); campos de identidade congelados; `plugin.state` read-only; sem novos paths de assets/plugins.
- **Undo sem ownership por cliente**: labels derivadas por diff de snapshots (`core/History.cpp:100`); sem marcador "remote" na UI. O "ownership" é o fence de device-hash: undo via API recusa com `changed` se algum device state mudou desde a edição — um undo atrasado nunca atinge edições de produtor intercaladas.

## 4. Limites confirmados no código

≤10.000 notas/replace_notes · ≤100.000 channels/patterns/automations · mixer ≤501 (Master+500) · ≤500 playlist rows · ≤10 effect slots/insert · notes ≤1e9 ticks · pattern length 0 ou 1..999 compassos inteiros · depth ≤64 · handshake ≤1 KiB · PPQ 960 (240/step).

## 5. Testes automatizados relevantes (targets CTest)

`lynx_tests`, `lynx_remote_project_tests` (patchSemantics, exactDocuments, remoteNotesRoundtrip, noteCurvesDocuments, transactionValidation, allowlists…), `lynx_remote_pattern_tests`, `lynx_remote_playlist_tests`, `lynx_remote_instrument_tests`; fences de remote-history em `tests/tests.cpp:4955-5038`; SnapshotExchange em `tests.cpp:2535-2568`.

**Gap identificado:** o servidor TCP (listener/HMAC/fence ao vivo) não está em nenhum target de teste — a cobertura end-to-end é o `examples/remote_control.py` e a prova live do lynx-mcp. Cobertura de codecs/patch/document/history é sólida.

## 6. Prova de leitura ao vivo (instância instalada)

- Instância atualizada (2026-11-27) para **0.1.31.1** via instalador oficial (`LYNX-0.1.31.1-alpha-setup-x64.exe`, SHA-256 verificado contra `SHA256SUMS.txt`); ligação revalidada: 29 ops, revision 4, todas as capabilities ativas (projectId muda a cada arranque do projeto default: `c5b84af9133d8243e708c6c64ffc60d6`, epoch `c39b4017...`). Arranque: `uv run --project lynx-mcp python -m lynx_mcp.testhost start` com `LYNX_CONTROL_ENABLED=1` (a instância 0.1.30 anterior tinha-se entretanto fechado).
- Projeto default: BPM 130, 4/4, PPQ 960, revision 4, 5 canais (Kick/Clap/Hat/Snare/Synth), `Pattern 1` vazio (patternId 0000010000000006), playlist vazia, mixer Master+Insert1-16, playback parado. Handshake + `lynx_status`/`lynx_session` OK via opencode.json (servidor MCP `lynx`).

## 7. Riscos e pendências para o portão antes da 2A

1. **Não há atualização parcial de notas**: `lynx_notes_replace` substitui o padrão inteiro (todos os campos obrigatórios). Read-modify-write é obrigatório; a proposta 2A tem de provar preservação campo-a-campo (o round-trip nativo ajuda — rejeita perdas).
2. **Portão de aprovação fora do controlo do modelo continua em aberto** (decisão de design exigida pelo plano antes da 2A). O undo fence de device-hash dá reversibilidade, mas não autorização verificável.
3. **Índices posicionais** — propostas 2A devem ancorar-se em uids/IDs estáveis e reler antes de aplicar.
4. **Concorrência**: stale fence ⇒ `changed` (sem mutação); timeout de socket (>5 s; 60 s ops longas) ⇒ `uncertain` — nunca repetir.
5. Falta executar a suite CTest (requer build CMake/MSVC; a fazer se necessário — a superfície relevante já está verificada ao vivo).
6. Falta teste live de revisão/undo/atomicidade com escritas em **cópia de projeto** (pertence ao portão 2A, com aprovação do utilizador).
