# Contrato do I2 · `ods.i2.tracks`

A Arquitetura 6c (seção 6, "Contratos e propriedade") pede, para cada contrato, evidência de
contrato, semântica, operação, teste e build. Este documento reúne as cinco para o I2.

## Contrato

- **Schema:** [`schemas/ods.i2.tracks.v1.0.schema.json`](../schemas/ods.i2.tracks.v1.0.schema.json),
  perfil de envelope EV-SINAL (os 13 campos da 6c). O payload segue o schema oficial do B1
  (`ods-26-2/b1`, `I2/tracksEvent.schema.json`), com duas restrições a mais: nenhum campo além dos
  previstos, e `detection_id` ausente quando `predicted = true`.
- **Exemplos:** `schemas/examples/valid/` e `schemas/examples/invalid/`; cada inválido falha por um
  motivo só, dito no nome do arquivo.
- **Validação no publicador:** todo evento passa pelo schema antes de sair (`I2/rastreio/publicacao.py`).
  O que não passa é contado, registrado no stderr e não chega ao barramento.
- **Compatibilidade:** `schema_version` MAJOR.MINOR. Campo novo é opcional e sobe MINOR; renomear,
  remover ou mudar tipo sobe MAJOR. Esta é a 1.0.

## Semântica

| campo | significado |
|---|---|
| `track_id` | identidade dentro de `source_id` + `session_id`; formato `t-<classe>-<n>`. Objeto que sai do quadro e volta recebe id novo (6c, 1.0) |
| `class` | a do MODEL do I1, sem tradução nem lista fixa |
| `state` | `CONFIRMED` enquanto o rastro vive; `LOST` uma vez, no quadro em que encerra |
| `predicted` | `true` quando não houve detecção no quadro e a posição foi extrapolada pela velocidade; a predição só vale até o horizonte do perfil, depois o rastro encerra |
| `detection_id` | a detecção do I1 associada no quadro; ausente quando `predicted` |
| `confidence` | a da última detecção associada |
| `point_px` | centro da base da `bbox`, em pixels do quadro bruto: onde o objeto toca o chão |
| `bbox` | a da detecção, inteira e sem suavização; em `predicted`, deslocada com o centro |
| `captured_at`, `source_id`, `session_id`, `frame_index` | repassados de `ods.i1.detections` |
| `sequence` | contador por câmera e sessão, a partir de 0; lacuna é perda |
| `artifact_version` | versão do motor (`i2-rastreio-2.0`) e, quando a build passa `--perfis`, a do arquivo de perfis |

Um rastro só é publicado depois de confirmado (3 vistas): rastro que morre antes disso nunca sai,
nem como `LOST`.

## Operação

- Uma mensagem por quadro, inclusive com `tracks` vazia (6c, convenção 5), chave `source_id`:
  mesma partição para a mesma câmera, ordem dos quadros preservada.
- **Entrada:** `ods.i1.detections`, num grupo novo a cada partida, do fim do tópico em diante. O
  I2 não guarda estado entre execuções. Quadro repetido ou fora de ordem na mesma câmera e sessão
  é descartado, o que cobre a deduplicação por `message_id` (6c, convenção 7).
- **Sessão:** quando o `session_id` de uma câmera muda, os rastros dela terminam e tudo recomeça
  do zero (6c: "a identidade termina quando a sessão muda"). As outras câmeras seguem.
- **Encerramento:** `Ctrl+C` e `docker stop` (SIGTERM) confirmam a entrega pendente antes de sair.
  Falha de entrega encerra com erro.
- **Um I2 por câmera no broker:** duas instâncias publicando `ods.i2.tracks` da mesma câmera
  duplicam os rastros no S1.
- **Latência:** o rastreio é O(rastros × detecções) por quadro, sem GPU.

## Teste

- Suíte em `I2/tests/`, no GitHub Actions a cada envio.
- Produtor falso em `I2/mock_producer.py`, com payloads dos exemplos válidos.
- Cenário gravado: o vídeo do A4 servido pelo P6 em replay (ou o csv de detecções dele), com a
  métrica de trocas por minuto no stderr.

## Build

- `Dockerfile` (`python:3.14-slim`), dependências fixas em `requirements.txt`: numpy, confluent-kafka
  e jsonschema.
- Configuração por aplicação: `--fps`, `--perfis` e, se a aplicação quiser, `--conf-min` e
  `--objetos`. O broker vem de `--i1` e `--kafka`, sem endereço embutido.
