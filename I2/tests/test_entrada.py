"""entradas: csv legado e mensagens de ods.i1.detections"""
import copy
import json
import unittest
from pathlib import Path

from rastreio.entrada import do_csv, quadro_de_i1, quadros_csv

I1 = json.loads((Path(__file__).parent / "fixtures" / "i1_detections.json").read_text(encoding="utf-8"))

CSV = """quadro,t_s,x1,y1,x2,y2,classe,confianca
0,0.0,10,10,50,100,pessoa,0.9
0,0.0,200,10,210,20,bola,0.4
1,0.1,11,10,51,100,pessoa,0.9
""".splitlines()


class Csv(unittest.TestCase):
    def test_agrupa_por_quadro_e_numera_as_deteccoes(self):
        quadros = list(quadros_csv(CSV))
        self.assertEqual([(n, len(d)) for n, _, d in quadros], [(0, 2), (1, 1)])
        self.assertEqual([d.id for d in quadros[0][2]], [0, 1])

    def test_classes_do_formato_legado_viram_as_do_i1(self):
        (n, _, dets), _ = quadros_csv(CSV)
        self.assertEqual([d.classe for d in dets], ["person", "ball"])

    def test_classe_nova_passa_sem_traducao(self):
        ((_, _, (d,)),) = quadros_csv(["0,0.0,1,1,9,9,vehicle,0.8"])
        self.assertEqual(d.classe, "vehicle")

    def test_tempo_de_captura_e_inicio_mais_t_s(self):
        q0, q1 = do_csv(CSV, "s", "cam0", "2026-09-23T14:00:00.000Z", 1280, 720)
        self.assertEqual((q1.capturado, q1.largura, q1.altura), ("2026-09-23T14:00:00.100Z", 1280, 720))


class MensagemDoI1(unittest.TestCase):
    def test_mensagem_valida_vira_quadro(self):
        q = quadro_de_i1(I1)
        self.assertEqual((q.fonte, q.sessao, q.n, q.largura, q.altura),
                         ("cam0", I1["session_id"], 48213, 1920, 1080))
        self.assertEqual([(d.classe, d.id) for d in q.deteccoes], [("person", 0), ("helmet", 1)],
                         "toda classe do MODEL passa, inclusive as que o A4 nao usa")
        self.assertEqual(q.capturado, I1["captured_at"])

    def test_mensagem_fora_do_contrato_da_value_error(self):
        sem_tamanho = copy.deepcopy(I1)
        del sem_tamanho["payload"]["image_width"]
        outra_versao = dict(I1, schema_version="2.0")
        for ruim in (sem_tamanho, outra_versao, dict(I1, schema="ods.i9.ppe_compliance"), {"payload": None}):
            with self.assertRaises(ValueError):
                quadro_de_i1(ruim)


if __name__ == "__main__":
    unittest.main()
