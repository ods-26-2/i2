"""contrato de saida: ods.i2.tracks, perfil EV-SINAL da 6c

schemas/ods.i2.tracks.v1.0.schema.json e a unica fonte do contrato: o publicador, o produtor
falso e os testes validam contra ele. a 6c manda validar no publicador: mensagem fora do
contrato nunca chega ao barramento.
"""
import json
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

TOPICO = "ods.i2.tracks"
SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "ods.i2.tracks.v1.0.schema.json"


def agora():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def rastro(tr):
    """Trilha -> item de tracks. point_px e o centro da base da bbox, o ponto que o S1 projeta
    pela homografia do I3; bbox e a da deteccao, inteira, extrapolada quando predicted"""
    x1, y1, x2, y2 = (round(float(v)) for v in tr.caixa)
    item = {"track_id": f"t-{tr.classe}-{tr.id:04d}", "class": tr.classe,
            "state": "LOST" if tr.estado == "perdida" else "CONFIRMED",
            "predicted": not tr.visto, "confidence": round(float(tr.confianca), 3),
            "point_px": [round((x1 + x2) / 2, 1), y2], "bbox": [x1, y1, x2, y2]}
    if tr.deteccao is not None:
        item["detection_id"] = tr.deteccao
    return item


def evento(quadro, sequencia, trilhas, artifact_version):
    """um evento por quadro, inclusive com tracks vazia (6c, convencao 5)"""
    return {
        "message_type": "event",
        "message_id": str(uuid.uuid4()),
        "schema": TOPICO,
        "schema_version": "1.0",
        "producer": "I2",
        "published_at": agora(),
        "captured_at": quadro.capturado,
        "source_id": quadro.fonte,
        "session_id": quadro.sessao,
        "sequence": sequencia,
        "artifact_version": artifact_version,
        "payload": {"frame_index": quadro.n, "tracks": [rastro(tr) for tr in trilhas]},
    }


@lru_cache(maxsize=1)
def _validador():
    from jsonschema import Draft202012Validator, FormatChecker
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def erros(msg):
    """violacoes do contrato, em ordem estavel (caminho do campo: mensagem); vazia se valida"""
    achados = sorted(_validador().iter_errors(msg), key=lambda e: list(map(str, e.absolute_path)))
    return [f"{'/'.join(map(str, e.absolute_path)) or '<raiz>'}: {e.message}" for e in achados]


def validar(msg):
    problemas = erros(msg)
    if problemas:
        raise ValueError(f"{TOPICO} fora do contrato: " + "; ".join(problemas))
