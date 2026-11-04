"""borda do i2: deteccoes do i1 -> um evento de rastreio por quadro

    cat volei.csv janela.csv | sort -t, -k1,1n | docker run -i --rm inv-i2 --fps 29.97
    ... | docker run -i --rm inv-i2 --fps 29.97 --kafka 34.66.235.91:9093
    docker run --rm --network host inv-i2 --i1 localhost:9092 --kafka localhost:9092

entrada: com --i1, o topico ods.i1.detections (6c), ao vivo, com captured_at, source_id e
session_id de cada quadro repassados; sem --i1, csv no stdin no formato do
old/yolo/detectar.py: quadro,t_s,x1,y1,x2,y2,classe,confianca -- ordenada por quadro,
cabecalho e ignorado.
saida: um evento ods.i2.tracks por quadro, envelope ev-sinal da arquitetura 6c.
com --kafka vai pro topico de mesmo nome, chave source_id (mesma particao, ordem dos
quadros preservada); sem --kafka, uma linha json no stdout.
e streaming: o quadro sai assim que o seguinte comeca.
"""
import argparse
import collections
import csv
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone

from i2_rastreio import Deteccao, ParametrosCamera, Rastreador

TOPICO = "ods.i2.tracks"
ENTRADA = "ods.i1.detections"
VERSAO = "i2-rastreio-1.1"                        # artifact_version: o motor que rastreou
CLASSE = {"bola": "ball", "pessoa": "person"}   # enum do contrato de i1
PERFIL = {v: k for k, v in CLASSE.items()}       # classe do modelo de i1 -> perfil do rastreador


def iso(t):
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def por_classe(texto, padrao):
    """le "bola=1,pessoa=15" num dict, com padrao pra classe nao citada"""
    d = collections.defaultdict(lambda: padrao)
    d.update({c: float(v) for c, v in (par.split("=") for par in texto.split(",") if par)})
    return d


def quadros(linhas):
    """agrupa as linhas do csv por quadro, sem esperar o fim da entrada"""
    atual, t_atual, dets = None, 0.0, []
    # detection_id e a ordem no quadro, contada antes do corte de confianca, como i1 faria
    for r in csv.reader(linhas):
        if not r or r[0] == "quadro":
            continue
        n = int(r[0])
        if atual is not None and n != atual:
            yield atual, t_atual, dets
            dets = []
        atual, t_atual = n, float(r[1])
        dets.append(Deteccao(tuple(map(float, r[2:6])), r[6], float(r[7]), len(dets)))
    if atual is not None:
        yield atual, t_atual, dets


def do_csv(a):
    """stdin csv -> (sessao, fonte, quadro, t_s, captured_at, deteccoes); sessao e tempo dos args"""
    inicio = datetime.fromisoformat(a.inicio.replace("Z", "+00:00")) if a.inicio \
        else datetime.now(timezone.utc)
    for n, t_s, dets in quadros(sys.stdin):
        yield a.sessao, a.source_id, n, t_s, iso(inicio + timedelta(seconds=t_s)), dets


def do_i1(a):
    """ods.i1.detections ao vivo -> mesma tupla de do_csv; t_s e o epoch do captured_at"""
    from confluent_kafka import OFFSET_END, Consumer

    def fim(c, particoes):                          # fluxo: so dagora em diante
        for p in particoes:
            p.offset = OFFSET_END
        c.assign(particoes)
    c = Consumer({"bootstrap.servers": a.i1, "group.id": f"I2-{uuid.uuid4().hex[:8]}",
                  "enable.auto.commit": False, "topic.metadata.refresh.interval.ms": 5000})
    c.subscribe([ENTRADA], on_assign=fim)
    ultimo = {}                                     # (fonte, sessao) -> ultimo frame_index
    try:
        while True:
            msg = c.poll(0.5)
            if msg is None or msg.error():
                continue
            try:
                ev = json.loads(msg.value())
                if ev["schema"] != ENTRADA or not str(ev["schema_version"]).startswith("1."):
                    raise ValueError(f"schema {ev['schema']} {ev['schema_version']}")
                chave, n = (ev["source_id"], ev["session_id"]), ev["payload"]["frame_index"]
                dets = [Deteccao(tuple(map(float, d["bbox"])), PERFIL[d["class"]],
                                 float(d["confidence"]), d["detection_id"])
                        for d in ev["payload"]["detections"] if d["class"] in PERFIL]
                t_s = datetime.fromisoformat(ev["captured_at"].replace("Z", "+00:00")).timestamp()
            except (ValueError, KeyError, TypeError) as erro:
                print(f"i2: mensagem descartada de {ENTRADA}: {erro!r}", file=sys.stderr)
                continue
            # repetida ou fora de ordem: o rastreador precisa do tempo andando para frente
            if n <= ultimo.get(chave, -1):
                continue
            ultimo[chave] = n
            yield ev["session_id"], ev["source_id"], n, t_s, ev["captured_at"], dets
    finally:
        c.close()


def rastrear(rastreadores, cam, t_s, deteccoes):
    """um rastreador por classe, e todos rodam todo quadro -- e no quadro sem
    deteccao que a trilha prediz e segura a identidade"""
    trilhas = []
    for classe in set(rastreadores) | {d.classe for d in deteccoes}:
        r = rastreadores.setdefault(classe, Rastreador(classe, cam))
        trilhas += r.atualizar_quadro(t_s, [d for d in deteccoes if d.classe == classe])
    return trilhas


def saida(a):
    """devolve (publicar, fechar): stdout por padrao, kafka com --kafka"""
    if not a.kafka:
        return lambda ev: print(json.dumps(ev), flush=True), lambda: None
    from confluent_kafka import Producer
    produtor, falhas = Producer({"bootstrap.servers": a.kafka}), []

    def publicar(ev):
        produtor.produce(TOPICO, key=ev["source_id"], value=json.dumps(ev).encode(),
                         on_delivery=lambda erro, _msg: erro and falhas.append(erro))
        produtor.poll(0)                 # entrega os callbacks sem bloquear

    def fechar():
        if produtor.flush(30) or falhas:
            raise SystemExit(f"i2: {len(falhas)} eventos nao entregues em {a.kafka}")
        print(f"i2: publicado em {TOPICO}", file=sys.stderr)
    return publicar, fechar


def rastro(tr):
    """trilha no formato de ods.i2.tracks; point_px e o centro da base, o que s1 projeta"""
    x1, y1, x2, y2 = (round(float(v)) for v in tr.caixa)
    item = {"track_id": f"t-{CLASSE.get(tr.classe, tr.classe)}-{tr.id:04d}",
            "class": CLASSE.get(tr.classe, tr.classe),
            "state": "LOST" if tr.estado == "perdida" else "CONFIRMED",
            "predicted": not tr.visto, "confidence": round(float(tr.confianca), 3),
            "point_px": [round((x1 + x2) / 2, 1), y2], "bbox": [x1, y1, x2, y2]}
    if tr.deteccao is not None:
        item["detection_id"] = tr.deteccao
    return item


def relatorio(a, rastreadores, duracao, quadros_vistos):
    """card I2.3: o numero so vale com o cenario declarado junto"""
    duracao = max(duracao, 1.0 / a.fps)
    esperado = por_classe(a.objetos, 1)
    for classe, r in sorted(rastreadores.items()):
        print(f"i2 {classe:7s}: {r.trocas_por_minuto(duracao, int(esperado[classe])):5.1f} "
              f"trocas/min ({r.confirmadas} confirmadas em {duracao:.1f}s, "
              f"{quadros_vistos} quadros)", file=sys.stderr)


def main(a):
    publicar, fechar = saida(a)
    cam = ParametrosCamera(a.source_id, a.fps, a.largura, a.altura, False)
    conf_min = por_classe(a.conf_min, 0.0)
    rastreadores, sessao, sequencia, t_ini, t_s = {}, None, 0, 0.0, 0.0
    bola = None
    if a.bola_modelo:
        from bola_temporal import BolaTemporal
        bola = BolaTemporal(a.bola_modelo, a.video)
    try:
        for sess, fonte, n, t_s, capturado, dets in (do_i1(a) if a.i1 else do_csv(a)):
            # 6c: a identidade termina com a sessao, e sequence conta por sessao
            if sess != sessao:
                if sessao is not None:
                    relatorio(a, rastreadores, t_s - t_ini, sequencia)
                rastreadores, sessao, sequencia, t_ini = {}, sess, 0, t_s
                if bola is not None:
                    bola.reiniciar()
            dets = [d for d in dets if d.confianca >= conf_min[d.classe]]
            if bola is not None:                  # a bola vem do MODEL temporal, as demais do I1
                dets = [d for d in dets if d.classe != "bola"] + bola.deteccoes(n)
            trilhas = rastrear(rastreadores, cam, t_s, dets)
            publicar({
                "message_type": "event",
                "message_id": str(uuid.uuid4()),
                "schema": TOPICO,
                "schema_version": "1.0",
                "producer": "I2",
                "published_at": iso(datetime.now(timezone.utc)),
                "captured_at": capturado,
                "source_id": fonte,
                "session_id": sessao,
                "sequence": sequencia,
                "artifact_version": VERSAO + ("+" + a.bola_versao if bola is not None else ""),
                "payload": {"frame_index": n, "tracks": [rastro(tr) for tr in trilhas]},
            })
            sequencia += 1
    except KeyboardInterrupt:                     # ao vivo so para no ctrl+c
        pass
    fechar()
    relatorio(a, rastreadores, t_s - t_ini, sequencia)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source-id", default="cam-ref")
    p.add_argument("--sessao", default=str(uuid.uuid4()),
                   help="session_id (uuid) de ods.session.started; padrao e um novo")
    p.add_argument("--fps", type=float, default=30.0)
    p.add_argument("--largura", type=int, default=1920)
    p.add_argument("--altura", type=int, default=1080)
    p.add_argument("--inicio", help="ISO 8601 UTC do quadro 0; padrao e agora")
    p.add_argument("--conf-min", default="",
                   help="corte de confianca por classe, ex. bola=0.5,pessoa=0.3")
    p.add_argument("--kafka", metavar="HOST:PORTA", help="publica no broker em vez do stdout")
    p.add_argument("--i1", metavar="HOST:PORTA",
                   help="le ods.i1.detections do broker em vez do csv no stdin")
    p.add_argument("--bola-modelo", metavar="ONNX",
                   help="MODEL temporal da bola (VballNet); troca a bola do I1 pela do modelo")
    p.add_argument("--bola-versao", default="vballnet-v4c", help="artifact_version do MODEL da bola")
    p.add_argument("--video", help="stream de video (P4, ou a gravacao do P6 em replay) do --bola-modelo")
    p.add_argument("--objetos", default="",
                   help="densidade declarada do cenario, ex. bola=1,pessoa=12")
    main(p.parse_args())
