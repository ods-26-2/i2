"""o pipeline: estado por camera e por sessao, classes do I1 e tamanho do quadro"""
import unittest

from rastreio import contrato, perfis
from rastreio.entrada import Quadro
from rastreio.pipeline import Pipeline
from rastreio.rastreador import Deteccao

S1, S2 = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"


def quadro(fonte, sessao, n, x, classe="person", largura=1920, altura=1080):
    t = n / 30.0
    return Quadro(sessao, fonte, n, t, f"2026-09-23T14:00:{t:06.3f}Z", [Deteccao((x, 100, x + 40, 200), classe, 0.9, 0)],
                  largura, altura)


def pipeline(**kw):
    linhas = []
    return Pipeline(perfis.carregar(), 30.0, relatar=linhas.append, **kw), linhas


class PorCamera(unittest.TestCase):
    def test_duas_cameras_intercaladas_sao_independentes(self):
        p, _ = pipeline()
        eventos = {"cam0": [], "cam1": []}
        for n in range(10):
            for fonte, x in (("cam0", 100 + 5 * n), ("cam1", 900 - 5 * n)):
                eventos[fonte].append(p.processar(quadro(fonte, S1, n, x)))
        for fonte, evs in eventos.items():
            self.assertEqual([e["sequence"] for e in evs], list(range(10)), fonte)
            ids = {t["track_id"] for e in evs for t in e["payload"]["tracks"]}
            self.assertEqual(ids, {"t-person-0001"}, f"{fonte}: uma pessoa, uma identidade")
            self.assertTrue(all(e["source_id"] == fonte for e in evs))
            for e in evs:
                contrato.validar(e)

    def test_sessao_nova_zera_so_aquela_camera(self):
        p, linhas = pipeline()
        for n in range(5):
            p.processar(quadro("cam0", S1, n, 100 + 5 * n))
            p.processar(quadro("cam1", S1, n, 500 + 5 * n))
        e0 = p.processar(quadro("cam0", S2, 0, 300))
        e1 = p.processar(quadro("cam1", S1, 5, 525))
        self.assertEqual((e0["sequence"], e0["payload"]["tracks"]), (0, []), "sessao nova comeca do zero")
        self.assertEqual(e1["sequence"], 5)
        self.assertEqual([t["track_id"] for t in e1["payload"]["tracks"]], ["t-person-0001"])
        self.assertEqual(len(linhas), 1, "so a sessao encerrada da cam0 vira relatorio")
        self.assertIn("cam0", linhas[0])

    def test_metrica_usa_a_duracao_da_propria_sessao(self):
        p, linhas = pipeline()
        for n in range(31):                                   # 1 s de sessao
            p.processar(quadro("cam0", S1, n, 100 + 5 * n))
        p.processar(Quadro(S2, "cam0", 0, 99.0, "2026-09-23T14:01:39.000Z", [], 1920, 1080))
        self.assertIn("em 1.0s", linhas[0])


class Generalizacao(unittest.TestCase):
    def test_classe_vehicle_atravessa_com_o_perfil_padrao(self):
        p, _ = pipeline()
        evs = [p.processar(quadro("cam-patio", S1, n, 100 + 8 * n, classe="vehicle")) for n in range(5)]
        (t,) = evs[-1]["payload"]["tracks"]
        self.assertEqual((t["class"], t["track_id"]), ("vehicle", "t-vehicle-0001"))

    def test_corte_de_confianca_por_classe(self):
        p, _ = pipeline(conf_min={"person": 0.95})
        evs = [p.processar(quadro("cam0", S1, n, 100 + 5 * n)) for n in range(5)]
        self.assertTrue(all(e["payload"]["tracks"] == [] for e in evs))

    def test_tamanho_do_quadro_escala_o_raio_por_camera(self):
        p, _ = pipeline()
        p.processar(quadro("hd", S1, 0, 100, largura=1920, altura=1080))
        p.processar(quadro("4k", S1, 0, 100, largura=3840, altura=2160))
        raio = {f: e.rastreadores["person"].p["dist_max_px"] for f, e in p.fontes.items()}
        self.assertEqual(raio["4k"], 2 * raio["hd"])


if __name__ == "__main__":
    unittest.main()
