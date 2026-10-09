"""borda do i2: csv de deteccoes no stdin -> um evento de rastreio por quadro no stdout

    cat volei.csv janela.csv | sort -t, -k1,1n | docker run -i --rm inv-i2 --fps 29.97
    ... | docker run -i --rm inv-i2 --fps 29.97 --kafka 34.66.235.91:9093

entrada no formato do yolo/detectar.py (o produtor falso do i1):
quadro,t_s,x1,y1,x2,y2,classe,confianca -- ordenada por quadro, cabecalho e ignorado.
saida: um evento por quadro, envelope do guia kafka b2 (docs/Guia_Kafka_B2_v2.pdf).
com --kafka vai pro topico ods.visao.identidade_atribuida, chave camera_id (mesma
particao, ordem dos quadros preservada); sem --kafka, uma linha json no stdout.
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

TOPICO = "ods.visao.identidade_atribuida"
CLASSE = {"bola": "ball", "pessoa": "person"}   # enum do contrato de i1


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
    for r in csv.reader(linhas):
        if not r or r[0] == "quadro":
            continue
        n = int(r[0])
        if atual is not None and n != atual:
            yield atual, t_atual, dets
            dets = []
        atual, t_atual = n, float(r[1])
        dets.append(Deteccao(tuple(map(float, r[2:6])), r[6], float(r[7])))
    if atual is not None:
        yield atual, t_atual, dets


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
        produtor.produce(TOPICO, key=a.camera_id, value=json.dumps(ev).encode(),
                         on_delivery=lambda erro, _msg: erro and falhas.append(erro))
        produtor.poll(0)                 # entrega os callbacks sem bloquear

    def fechar():
        if produtor.flush(30) or falhas:
            raise SystemExit(f"i2: {len(falhas)} eventos nao entregues em {a.kafka}")
        print(f"i2: publicado em {TOPICO}", file=sys.stderr)
    return publicar, fechar


def main(a):
    publicar, fechar = saida(a)
    cam = ParametrosCamera(a.camera_id, a.fps, a.largura, a.altura, False)
    inicio = datetime.fromisoformat(a.inicio.replace("Z", "+00:00")) if a.inicio \
        else datetime.now(timezone.utc)
    conf_min = por_classe(a.conf_min, 0.0)
    rastreadores = {}
    n, t_s = -1, 0.0
    for n, t_s, dets in quadros(sys.stdin):
        dets = [d for d in dets if d.confianca >= conf_min[d.classe]]
        trilhas = rastrear(rastreadores, cam, t_s, dets)
        capturado = iso(inicio + timedelta(seconds=t_s))
        publicar({
            "message_id": str(uuid.uuid4()),
            "message_type": "event",
            "schema": TOPICO,
            "schema_version": "1.0",
            "producer": "I2",
            "occurred_at": capturado,
            "published_at": iso(datetime.now(timezone.utc)),
            "payload": {
                "camera_id": a.camera_id,
                "session_id": a.sessao,
                "captured_at": capturado,
                "frame": n,
                "tracks": [{"track_id": tr.id, "class": CLASSE.get(tr.classe, tr.classe),
                            "state": "confirmed", "u_px": round(float(tr.centro[0]), 1),
                            "v_px": round(float(tr.centro[1]), 1), "predicted": not tr.visto}
                           for tr in trilhas],
            },
        })
    fechar()

    # card I2.3: o numero so vale com o cenario declarado junto
    duracao = max(t_s, 1.0 / a.fps)
    esperado = por_classe(a.objetos, 1)
    for classe, r in sorted(rastreadores.items()):
        print(f"i2 {classe:7s}: {r.trocas_por_minuto(duracao, int(esperado[classe])):5.1f} "
              f"trocas/min ({r.confirmadas} confirmadas em {duracao:.1f}s, "
              f"{n + 1} quadros)", file=sys.stderr)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--camera-id", default="cam-ref")
    p.add_argument("--sessao", default="sessao-1")
    p.add_argument("--fps", type=float, default=30.0)
    p.add_argument("--largura", type=int, default=1920)
    p.add_argument("--altura", type=int, default=1080)
    p.add_argument("--inicio", help="ISO 8601 UTC do quadro 0; padrao e agora")
    p.add_argument("--conf-min", default="",
                   help="corte de confianca por classe, ex. bola=0.5,pessoa=0.3")
    p.add_argument("--kafka", metavar="HOST:PORTA", help="publica no broker em vez do stdout")
    p.add_argument("--objetos", default="",
                   help="densidade declarada do cenario, ex. bola=1,pessoa=12")
    main(p.parse_args())
