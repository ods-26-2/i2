"""o contrato ods.i2.tracks: exemplos do schema, validacao no publicador e produtor falso"""
import contextlib
import io
import json
import unittest
from pathlib import Path

import mock_producer
from rastreio import contrato, publicacao

EXEMPLOS = Path(__file__).resolve().parents[2] / "schemas" / "examples"


def exemplos(pasta):
    return [(p.name, json.loads(p.read_text(encoding="utf-8"))) for p in sorted((EXEMPLOS / pasta).glob("*.json"))]


class Exemplos(unittest.TestCase):
    def test_validos_passam(self):
        for nome, ev in exemplos("valid"):
            with self.subTest(nome):
                self.assertEqual(contrato.erros(ev), [])

    def test_invalidos_falham(self):
        for nome, ev in exemplos("invalid"):
            with self.subTest(nome):
                self.assertNotEqual(contrato.erros(ev), [])


class Publicador(unittest.TestCase):
    def test_recusa_evento_fora_do_contrato_e_publica_o_valido(self):
        saida, erro = io.StringIO(), io.StringIO()
        pub = publicacao.Stdout()
        _, valido = exemplos("valid")[0]
        _, invalido = exemplos("invalid")[0]
        with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erro):
            self.assertFalse(pub.publicar(invalido))
            self.assertTrue(pub.publicar(valido))
        self.assertEqual((pub.publicadas, pub.rejeitadas), (1, 1))
        self.assertEqual([json.loads(l)["message_id"] for l in saida.getvalue().splitlines()], [valido["message_id"]])
        self.assertIn("rejeitado", erro.getvalue())


class ProdutorFalso(unittest.TestCase):
    def test_emite_eventos_validos_com_sequence_crescente(self):
        evs = list(mock_producer.eventos(8, "cam9"))
        self.assertEqual([e["sequence"] for e in evs], list(range(8)))
        self.assertEqual(len({e["session_id"] for e in evs}), 1)
        for e in evs:
            self.assertEqual(contrato.erros(e), [])


if __name__ == "__main__":
    unittest.main()
