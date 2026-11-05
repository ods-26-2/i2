"""I2 · identidade e rastreio: deteccoes do I1 -> um evento ods.i2.tracks por quadro

    docker run --rm --network host inv-i2 --i1 localhost:9092 --kafka localhost:9092
    cat deteccoes.csv | docker run -i --rm inv-i2 --fps 29.97 --largura 1280 --altura 720

entrada: com --i1, o topico ods.i1.detections (6c), ao vivo, do fim em diante; captured_at,
source_id, session_id e o tamanho do quadro vem de cada mensagem. sem --i1, csv no stdin
(quadro,t_s,x1,y1,x2,y2,classe,confianca, ordenado por quadro), com fonte, sessao e tamanho
dos argumentos.
saida: um evento ods.i2.tracks por quadro (envelope EV-SINAL), validado contra o schema antes
de sair; com --kafka vai para o topico, chave source_id, e sem --kafka e uma linha json no
stdout. a metrica (trocas de identidade por minuto) vai para o stderr ao fim de cada sessao.
"""
import argparse
import signal
import sys
import uuid

from rastreio import entrada, perfis, publicacao
from rastreio.pipeline import Pipeline


def por_classe(texto):
    """"ball=0.5,person=0.3" -> {"ball": 0.5, "person": 0.3}"""
    try:
        return {c.strip(): float(v) for c, v in (par.split("=") for par in texto.split(",") if par.strip())}
    except ValueError as erro:
        raise argparse.ArgumentTypeError(f"esperado classe=valor[,classe=valor], veio {texto!r}") from erro


def argumentos(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # --camera-id: nome de antes da 6c, ainda usado pela suite do B4
    p.add_argument("--source-id", "--camera-id", dest="source_id", default="cam-ref",
                   help="fonte do modo csv (com --i1 vem de cada mensagem)")
    p.add_argument("--sessao", default=str(uuid.uuid4()),
                   help="session_id (uuid) do modo csv; padrao e um novo")
    p.add_argument("--inicio", help="ISO 8601 UTC do quadro 0 no modo csv; padrao e agora")
    p.add_argument("--largura", type=int, default=1920, help="largura do quadro no modo csv")
    p.add_argument("--altura", type=int, default=1080, help="altura do quadro no modo csv")
    p.add_argument("--fps", type=float, default=30.0, help="taxa da camera; escala os perfis")
    p.add_argument("--conf-min", type=por_classe, default={},
                   help="corte extra de confianca por classe do I1, ex. ball=0.5,person=0.3 (padrao: nenhum)")
    p.add_argument("--perfis", metavar="JSON", help="perfis do rastreador por classe (ver rastreio/perfis.py)")
    p.add_argument("--objetos", type=por_classe, default={},
                   help="densidade declarada do cenario para a metrica, ex. ball=1,person=12")
    p.add_argument("--i1", metavar="HOST:PORTA", help="le ods.i1.detections do broker em vez do csv no stdin")
    p.add_argument("--kafka", metavar="HOST:PORTA", help="publica no broker em vez do stdout")
    return p.parse_args(argv)


def _parar(_sinal, _quadro):
    raise KeyboardInterrupt                   # docker stop: sai pelo mesmo caminho do ctrl+c


def main(argv=None):
    a = argumentos(argv)
    signal.signal(signal.SIGTERM, _parar)
    try:
        pipeline = Pipeline(perfis.carregar(a.perfis), a.fps, a.conf_min, a.objetos,
                            relatar=lambda linha: print(linha, file=sys.stderr))
    except (OSError, ValueError) as erro:
        raise SystemExit(f"i2: perfis: {erro}") from erro
    saida = publicacao.Kafka(a.kafka) if a.kafka else publicacao.Stdout()
    quadros = entrada.do_kafka(a.i1) if a.i1 else \
        entrada.do_csv(sys.stdin, a.sessao, a.source_id, a.inicio, a.largura, a.altura)
    try:
        for q in quadros:
            saida.publicar(pipeline.processar(q))
    except KeyboardInterrupt:                 # ao vivo so para no ctrl+c ou no docker stop
        pass
    finally:
        pipeline.fechar()
        saida.fechar()
    if saida.rejeitadas:
        print(f"i2: {saida.rejeitadas} eventos rejeitados pelo validador", file=sys.stderr)


if __name__ == "__main__":
    main()
