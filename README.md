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
cat ../a4/yolo/volei.csv ../a4/yolo/janela.csv | sort -t, -k1,1n | docker run -i --rm inv-i2 --fps 29.97 --largura 1280 --altura 720
# no barramento: mesmo comando + --kafka 34.66.235.91:9093
```

Entrada (stdin): csv de detecções `quadro,t_s,x1,y1,x2,y2,classe,confianca`, **ordenado por
quadro**. Linhas de cabeçalho são ignoradas, então dá para concatenar vários csv e passar
por `sort`. É o formato do produtor falso `yolo/detectar.py` do [A4](https://github.com/ods-26-2/a4), até o I1 chegar;
os csv de exemplo também estão lá (`yolo/volei.csv`, `yolo/janela.csv`).

Saída: um evento `ods.visao.identidade_atribuida` por quadro, no formato de
`docs/INV-1_interfaces.md`, como linha JSON no stdout ou, com `--kafka`, no tópico de mesmo nome. É streaming: cada quadro sai assim que o seguinte começa a
chegar. A métrica `trocas_por_minuto` vai para o stderr.

Opções: `--camera-id --sessao --fps --largura --altura --inicio` (ISO do quadro 0, base do
`captured_at`), `--conf-min bola=0.5,pessoa=0.3`, `--kafka HOST:PORTA`, `--objetos bola=1,pessoa=12`.

Entram detecções de I1 (MOD-1). Consumidores: S1, S2, S5, A4.

**Entrada** `Deteccao(caixa, classe, confianca)` + `t_s`, via `atualizar_quadro(t_s, deteccoes)`

| campo | formato | observação |
|---|---|---|
| `caixa` | `(x1, y1, x2, y2)` em px | cantos superior esquerdo e inferior direito |
| `classe` | str | `"bola"`, `"pessoa"` |
| `confianca` | float 0 a 1 | do contrato de I1, ainda não usada |
| `t_s` | float em s | timestamp de **captura**, não de chegada |

**Saída** `Trilha(id, classe, estado, centro, t_s, visto, vistas)`

| campo | formato | observação |
|---|---|---|
| `id` | int | a identidade, o produto do componente |
| `estado` | str | `tentativa`, `confirmada`, `perdida` |
| `centro` | `(u, v)` em px | predito quando `visto` é falso |
| `visto` | bool | houve detecção neste quadro ou é predição |

**O que importa**

- Dois regimes, um motor só. Pessoa é grande e lenta, o problema é oclusão. Bola é
  pequena e rápida, o problema é predição. Dois perfis num dict, mesmo contrato de saída.
- A predição por velocidade constante é o que carrega a trilha pelos quadros em que a
  bola borra. Sem ela, a identidade troca.
- Raio de busca é calibrado pra uma câmera de referência (1920px, 30fps) e escala com
  `ParametrosCamera` — outra resolução ou outro fps, outro raio. Sem isso o perfil
  calibrado numa câmera erra silenciosamente na próxima.
- Métrica: `trocas_por_minuto()`, sobre cenário gravado do B4.
