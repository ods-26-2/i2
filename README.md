# I2 · identidade e rastreio

Parte do INV-1 · ODS 2026/2. O squad tem três componentes, cada um no seu repositório
e no seu container: [I2](https://github.com/ods-26-2/i2) (identidade e rastreio), [I3](https://github.com/ods-26-2/i3) (geometria e
calibração) e [A4](https://github.com/ods-26-2/a4) (arbitragem). Nenhum importa o outro: eles conversam pelo
Kafka do projeto, no envelope de `docs/INV-1_interfaces.md`, seguindo o guia
`docs/Guia_Kafka_B2_v2.pdf`. A cadeia completa está no README do [A4](https://github.com/ods-26-2/a4).

Só numpy + cliente Kafka.

## Rodar

```
docker build -t inv-i2 .
# csv de exemplo vem do repo a4, clonado ao lado
cat ../a4/old/yolo/volei.csv ../a4/old/yolo/janela.csv | sort -t, -k1,1n | docker run -i --rm inv-i2 --fps 29.97 --largura 1280 --altura 720
# no barramento: mesmo comando + --kafka 34.66.235.91:9093

# ao vivo, lendo o I1 do barramento (Ctrl+C para parar)
docker run --rm --network host inv-i2 --i1 localhost:9092 --kafka localhost:9092 --fps 29.97 --largura 1280 --altura 720
```

Entrada, com `--i1`: o tópico `ods.i1.detections` do [I1](https://github.com/ods-26-2/i1) (MOD-1), do fim
em diante. `captured_at`, `source_id` e `session_id` de cada quadro passam direto para o
rastro; sessão nova zera os rastros e o `sequence`. Quadro repetido ou fora de ordem na
mesma sessão é descartado.

Entrada, sem `--i1` (stdin): csv de detecções `quadro,t_s,x1,y1,x2,y2,classe,confianca`, **ordenado por
quadro**. Linhas de cabeçalho são ignoradas, então dá para concatenar vários csv e passar
por `sort`. É o formato do antigo produtor falso `old/yolo/detectar.py` do [A4](https://github.com/ods-26-2/a4);
os csv de exemplo também estão lá (`old/yolo/volei.csv`, `old/yolo/janela.csv`). O `detection_id` é a
ordem da linha dentro do quadro, contada antes do corte de confiança.

Saída: um evento `ods.i2.tracks` por quadro, no envelope EV-SINAL da arquitetura 6c, como
linha JSON no stdout ou, com `--kafka`, no tópico de mesmo nome (chave `source_id`). É
streaming: cada quadro sai assim que o seguinte começa a chegar. A métrica
`trocas_por_minuto` vai para o stderr.

```json
{"frame_index": 48, "tracks": [{"track_id": "t-ball-0001", "detection_id": 0, "class": "ball",
  "state": "CONFIRMED", "predicted": false, "confidence": 0.78,
  "point_px": [744.0, 271], "bbox": [739, 260, 749, 271]}]}
```

- `point_px` é o centro da base da `bbox`, o ponto que o S1 projeta pela homografia do I3.
- `bbox` é a da detecção, sem suavização; com `predicted` ela é extrapolada e sai sem
  `detection_id`.
- `state` `LOST` sai uma vez, no quadro em que o rastro encerra. Objeto que volta recebe
  `track_id` novo (decisão da 6c para a 1.0).

Opções: `--source-id --sessao` (uuid; padrão é um novo) `--fps --largura --altura --inicio` (ISO do quadro 0, base do
`captured_at`), `--conf-min bola=0.5,pessoa=0.3`, `--kafka HOST:PORTA`, `--i1 HOST:PORTA`, `--objetos bola=1,pessoa=12`.

Entram detecções de I1 (MOD-1). Consumidores: S1 e S2.

**Entrada** `Deteccao(caixa, classe, confianca, id)` + `t_s`, via `atualizar_quadro(t_s, deteccoes)`

| campo | formato | observação |
|---|---|---|
| `caixa` | `(x1, y1, x2, y2)` em px | cantos superior esquerdo e inferior direito |
| `classe` | str | `"bola"`, `"pessoa"` |
| `confianca` | float 0 a 1 | do contrato de I1, ainda não usada |
| `id` | int ou None | `detection_id` de I1 no quadro |
| `t_s` | float em s | timestamp de **captura**, não de chegada |

**Saída** `Trilha(id, classe, estado, centro, t_s, visto, vistas, caixa, deteccao, confianca)`

| campo | formato | observação |
|---|---|---|
| `id` | int | a identidade, o produto do componente |
| `estado` | str | `tentativa`, `confirmada`, `perdida` |
| `centro` | `(u, v)` em px | predito quando `visto` é falso |
| `visto` | bool | houve detecção neste quadro ou é predição |
| `caixa` | `(x1, y1, x2, y2)` em px | da detecção; deslocada com o centro quando predita |
| `deteccao` | int ou None | id da detecção associada; None quando predita |
| `confianca` | float 0 a 1 | da última detecção associada |

**O que importa**

- Dois regimes, um motor só. Pessoa é grande e lenta, o problema é oclusão. Bola é
  pequena e rápida, o problema é predição. Dois perfis num dict, mesmo contrato de saída.
- A predição por velocidade constante é o que carrega a trilha pelos quadros em que a
  bola borra. Sem ela, a identidade troca.
- Raio de busca é calibrado pra uma câmera de referência (1920px, 30fps) e escala com
  `ParametrosCamera` — outra resolução ou outro fps, outro raio. Sem isso o perfil
  calibrado numa câmera erra silenciosamente na próxima.
- Métrica: `trocas_por_minuto()`, sobre cenário gravado do B4.
