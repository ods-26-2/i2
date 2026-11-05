# Como rodar o I2

## 1. Testes

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s I2/tests -t I2 -v
```

A suíte cobre o rastreador, os perfis, as duas entradas, o estado por câmera, o contrato
(todos os exemplos de `schemas/examples/`) e a linha de comando, inclusive a chamada exata da
suíte do B4. A mesma suíte roda no GitHub Actions a cada envio (`.github/workflows/i2-tests.yml`).

## 2. Offline, com csv

```bash
.venv/bin/python main.py --fps 30 --largura 1280 --altura 720 --source-id cam0 < dados/deteccoes_exemplo.csv
```

O csv é `quadro,t_s,x1,y1,x2,y2,classe,confianca`, ordenado por quadro; linhas de cabeçalho são
ignoradas, então dá para concatenar arquivos e passar por `sort -t, -k1,1n`. As classes `bola` e
`pessoa` do formato antigo do A4 viram `ball` e `person`. Sai uma linha json por quadro no stdout
e a métrica no stderr.

## 3. Ao vivo, com Kafka

```bash
docker build -t inv-i2 .
docker run --rm --network host inv-i2 --i1 localhost:9092 --kafka localhost:9092 --fps 30
```

- **Kafka local:** `docker compose up -d` no repo do [A4](https://github.com/ods-26-2/a4) sobe um
  broker em `localhost:9092` com os tópicos da cadeia.
- **Kafka da Jetson:** `172.18.4.56:9092`, acessível só dentro da rede do DCOMP.
- O I2 lê `ods.i1.detections` do fim em diante, então deve subir antes de o I1 começar a publicar.
- `Ctrl+C` ou `docker stop` encerram com a entrega pendente confirmada no broker.
- **Um I2 por câmera no broker:** duas builds publicando `ods.i2.tracks` da mesma câmera
  duplicam os rastros no S1.

## 4. Produtor falso

Para quem consome o I2 (S1, S2, a CI do B4) trabalhar sem o I1 nem uma câmera:

```bash
.venv/bin/python I2/mock_producer.py --quadros 10                          # stdout
.venv/bin/python I2/mock_producer.py --quadros 300 --fps 30 --kafka localhost:9092
```

Os payloads vêm de `schemas/examples/valid/`, e toda mensagem passa pelo validador do publicador.

## 5. Suíte de integração do B4

O B4 roda `python i2/main.py --camera-id cam0 --sessao <uuid> --inicio <iso>` com um csv no stdin,
a partir da raiz deste repo. O `main.py` da raiz e o `--camera-id` (nome antigo de `--source-id`)
existem para manter essa chamada; `I2/tests/test_cli.py` a reproduz.
