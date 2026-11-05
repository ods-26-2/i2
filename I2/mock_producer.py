"""produtor falso de ods.i2.tracks, para quem consome o I2 (S1, S2) e para a CI do B4

os payloads vem de schemas/examples/valid/, os mesmos exemplos que o validador aceita: mock e
validador nascem do mesmo schema (6c, evidencia minima: produtor falso e validador). o
envelope (message_id, tempos, sessao, sequence, frame_index) e gerado aqui, e toda mensagem
passa pelo publicador real, que valida antes de sair.

    python I2/mock_producer.py --quadros 5
    python I2/mock_producer.py --quadros 100 --kafka localhost:9092
"""
import argparse
import copy
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rastreio import publicacao  # noqa: E402
from rastreio.contrato import agora  # noqa: E402

EXEMPLOS = Path(__file__).resolve().parents[1] / "schemas" / "examples" / "valid"


def eventos(quantos, fonte="cam0", sessao=None):
    """um evento por quadro, percorrendo os exemplos validos em ciclo, sequence a partir de 0"""
    exemplos = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(EXEMPLOS.glob("*.json"))]
    sessao = sessao or str(uuid.uuid4())
    for n in range(quantos):
        ev = copy.deepcopy(exemplos[n % len(exemplos)])
        instante = agora()
        ev.update(message_id=str(uuid.uuid4()), published_at=instante, captured_at=instante,
                  source_id=fonte, session_id=sessao, sequence=n, artifact_version="mock-i2-1.0")
        ev["payload"]["frame_index"] = n
        yield ev


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--quadros", type=int, default=5)
    p.add_argument("--fps", type=float, default=0.0, help="0 = sem espera entre quadros")
    p.add_argument("--source-id", default="cam0")
    p.add_argument("--kafka", metavar="HOST:PORTA", help="publica no broker em vez do stdout")
    a = p.parse_args()
    saida = publicacao.Kafka(a.kafka) if a.kafka else publicacao.Stdout()
    for ev in eventos(a.quadros, a.source_id):
        saida.publicar(ev)
        if a.fps > 0:
            time.sleep(1.0 / a.fps)
    saida.fechar()
    if saida.rejeitadas:
        raise SystemExit(f"i2 mock: {saida.rejeitadas} exemplos rejeitados pelo validador")


if __name__ == "__main__":
    main()
