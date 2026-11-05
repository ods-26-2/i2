"""perfis por classe: qualquer classe do I1 tem perfil, e a build pode trocar ou acrescentar"""
import json
import tempfile
import unittest
from pathlib import Path

from rastreio import perfis
from rastreio.pipeline import Pipeline


def arquivo(conteudo):
    pasta = tempfile.mkdtemp()
    caminho = Path(pasta) / "perfis.json"
    caminho.write_text(json.dumps(conteudo), encoding="utf-8")
    return caminho


class Perfis(unittest.TestCase):
    def test_classe_desconhecida_usa_o_padrao(self):
        p = perfis.carregar()
        self.assertEqual(p.de("vehicle"), perfis.PADRAO)
        self.assertEqual(p.de("piece"), perfis.PADRAO)

    def test_ball_tem_perfil_proprio(self):
        self.assertEqual(perfis.carregar().de("ball")["horizontes_s"], 0.2)

    def test_de_devolve_copia(self):
        p = perfis.carregar()
        p.de("ball")["dist_max_px"] = 1
        self.assertEqual(p.de("ball")["dist_max_px"], 60)

    def test_arquivo_acrescenta_classe_e_troca_o_padrao(self):
        veiculo = dict(perfis.PADRAO, dist_max_px=150)
        padrao = dict(perfis.PADRAO, confirmar_em=5)
        p = perfis.carregar(arquivo({"versao": "perfis-a8-1", "padrao": padrao, "classes": {"vehicle": veiculo}}))
        self.assertEqual(p.de("vehicle")["dist_max_px"], 150)
        self.assertEqual(p.de("person")["confirmar_em"], 5)
        self.assertEqual(p.de("ball")["horizontes_s"], 0.2, "o embutido continua valendo")
        self.assertEqual(Pipeline(p, 30.0).versao, "i2-rastreio-2.0+perfis-a8-1")

    def test_chave_errada_da_erro_claro(self):
        ruim = dict(perfis.PADRAO)
        del ruim["teto"]
        with self.assertRaisesRegex(ValueError, "teto"):
            perfis.carregar(arquivo({"versao": "x", "classes": {"vehicle": ruim}}))

    def test_arquivo_sem_versao_da_erro(self):
        with self.assertRaisesRegex(ValueError, "versao"):
            perfis.carregar(arquivo({"classes": {}}))


if __name__ == "__main__":
    unittest.main()
