"""entradas do I2: o topico ods.i1.detections (producao) ou um csv no stdin (testes e B4)

as duas viram a mesma sequencia de Quadro, com o tempo de captura, a fonte, a sessao e o
tamanho do quadro de cada um.
"""
import csv
import json
import sys
import uuid
from collections import namedtuple
from datetime import datetime, timedelta, timezone

from rastreio.rastreador import Deteccao

ENTRADA = "ods.i1.detections"
# formato do antigo produtor falso old/yolo/detectar.py do A4, que o B4 ainda usa: as classes
# vinham em portugues. no topico a classe e a do MODEL do I1 e passa sem traducao
LEGADO = {"bola": "ball", "pessoa": "person"}

Quadro = namedtuple("Quadro", "sessao fonte n t_s capturado deteccoes largura altura")


def iso(t):
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _instante(texto):
    return datetime.fromisoformat(texto.replace("Z", "+00:00"))


def quadros_csv(linhas):
    """agrupa o csv quadro,t_s,x1,y1,x2,y2,classe,confianca por quadro, sem esperar o fim da
    entrada. o csv tem que vir ordenado por quadro; linhas de cabecalho sao ignoradas, entao
    da para concatenar varios csv e passar por sort. o detection_id e a ordem da linha no
    quadro, como o I1 faria"""
    atual, t_atual, dets = None, 0.0, []
    for r in csv.reader(linhas):
        if not r or r[0] == "quadro":
            continue
        n = int(r[0])
        if atual is not None and n != atual:
            yield atual, t_atual, dets
            dets = []
        atual, t_atual = n, float(r[1])
        dets.append(Deteccao(tuple(map(float, r[2:6])), LEGADO.get(r[6], r[6]), float(r[7]), len(dets)))
    if atual is not None:
        yield atual, t_atual, dets


def do_csv(linhas, sessao, fonte, inicio, largura, altura):
    """csv -> Quadro; sessao, fonte e tamanho vem dos argumentos, o tempo de captura e
    inicio + t_s (inicio None = agora)"""
    base = _instante(inicio) if inicio else datetime.now(timezone.utc)
    for n, t_s, dets in quadros_csv(linhas):
        yield Quadro(sessao, fonte, n, t_s, iso(base + timedelta(seconds=t_s)), dets, largura, altura)


def quadro_de_i1(ev):
    """uma mensagem de ods.i1.detections -> Quadro; ValueError se estiver fora do contrato.
    t_s e o epoch do captured_at, o tempo de captura que o I1 repassa de P4/P6"""
    try:
        if ev["schema"] != ENTRADA or not str(ev["schema_version"]).startswith("1."):
            raise ValueError(f"schema {ev['schema']} {ev['schema_version']}")
        p = ev["payload"]
        dets = [Deteccao(tuple(map(float, d["bbox"])), str(d["class"]), float(d["confidence"]),
                         int(d["detection_id"])) for d in p["detections"]]
        return Quadro(ev["session_id"], ev["source_id"], int(p["frame_index"]),
                      _instante(ev["captured_at"]).timestamp(), ev["captured_at"], dets,
                      int(p["image_width"]), int(p["image_height"]))
    except (KeyError, TypeError, AttributeError) as erro:
        raise ValueError(f"campo ausente ou com tipo errado: {erro!r}") from erro


def do_kafka(broker):
    """ods.i1.detections ao vivo, do fim do topico em diante, ate o ctrl+c

    grupo proprio a cada partida: o I2 nao guarda estado entre execucoes, entao nao ha offset
    para retomar. quadro repetido ou fora de ordem na mesma (fonte, sessao) e descartado: o
    rastreador precisa do tempo andando para frente. como cada quadro e uma mensagem, isso
    tambem cobre a deduplicacao por message_id que a 6c pede a todo consumidor (convencao 7)
    """
    from confluent_kafka import OFFSET_END, Consumer, KafkaError

    def fim(c, particoes):
        for p in particoes:
            p.offset = OFFSET_END
        c.assign(particoes)

    c = Consumer({"bootstrap.servers": broker, "group.id": f"I2-{uuid.uuid4().hex[:8]}",
                  "enable.auto.commit": False, "topic.metadata.refresh.interval.ms": 5000})
    c.subscribe([ENTRADA], on_assign=fim)
    ultimo = {}                                     # (fonte, sessao) -> ultimo frame_index
    try:
        while True:
            msg = c.poll(0.5)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    print(f"i2: erro do consumidor: {msg.error()}", file=sys.stderr)
                continue
            try:
                q = quadro_de_i1(json.loads(msg.value()))
            except ValueError as erro:
                print(f"i2: mensagem descartada de {ENTRADA}: {erro}", file=sys.stderr)
                continue
            chave = (q.fonte, q.sessao)
            if q.n <= ultimo.get(chave, -1):
                continue
            ultimo[chave] = q.n
            yield q
    finally:
        c.close()
