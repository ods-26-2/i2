"""o motor de rastreio: escala do perfil, oclusao, cruzamento, horizonte e encerramento"""
import unittest

from rastreio.perfis import CLASSES, PADRAO
from rastreio.rastreador import FPS_REF, LARGURA_REF_PX, Deteccao, ParametrosCamera, Rastreador

BOLA, PESSOA = CLASSES["ball"], PADRAO


def bola_andando(r, quadros=3, dt=0.1, det_id=None, conf=0.9):
    """bola andando 10 px por quadro; devolve a saida do ultimo quadro"""
    saida = None
    for i in range(quadros):
        x = 100 + 10 * i
        saida = r.atualizar_quadro(i * dt, [Deteccao((x, 100, x + 10, 110), "ball", conf, det_id)])
    return saida


class Escala(unittest.TestCase):
    def test_sem_camera_o_perfil_fica_cru(self):
        self.assertEqual(Rastreador(BOLA).p["dist_max_px"], 60)

    def test_resolucao_dobrada_dobra_o_raio(self):
        r = Rastreador(BOLA, ParametrosCamera("cam1", FPS_REF, LARGURA_REF_PX * 2, 1080))
        self.assertEqual(r.p["dist_max_px"], 120)
        self.assertEqual(r.p["perder_apos"], 6, "so a resolucao mudar nao pode afetar perder_apos")

    def test_fps_pela_metade_dobra_o_raio_e_encurta_a_vida(self):
        r = Rastreador(BOLA, ParametrosCamera("cam1", FPS_REF / 2, LARGURA_REF_PX, 1080))
        self.assertEqual(r.p["dist_max_px"], 120)
        self.assertEqual(r.p["perder_apos"], 3, "a 15 fps o horizonte de 0,2 s da bola sao 3 quadros")

    def test_horizonte_longo_mantem_a_vida_do_perfil(self):
        r = Rastreador(PESSOA, ParametrosCamera("cam1", FPS_REF, LARGURA_REF_PX * 2, 1080))
        self.assertEqual(r.p["perder_apos"], 20)

    def test_escalar_nao_vaza_para_o_perfil_original(self):
        Rastreador(BOLA, ParametrosCamera("cam1", FPS_REF / 2, LARGURA_REF_PX * 2, 1080))
        self.assertEqual((BOLA["dist_max_px"], BOLA["perder_apos"]), (60, 20))


class Comportamento(unittest.TestCase):
    def test_oclusao_a_trilha_atravessa_o_quadro_sem_deteccao_predizendo(self):
        r = Rastreador(BOLA)
        bola_andando(r)
        (t,) = r.atualizar_quadro(0.3, [])
        self.assertFalse(t.visto)
        self.assertEqual(t.estado, "confirmada", "uma falha so nao pode perder a trilha")
        self.assertTrue(130 <= t.centro[0] <= 140, f"predicao devia seguir pra ~135, deu {t.centro[0]:.1f}")

    def test_cruzamento_nao_troca_identidade(self):
        r = Rastreador(PESSOA)
        for i in range(11):                      # a vem da esquerda, b da direita, 20 px/quadro
            xa, xb = 100 + 20 * i, 300 - 20 * i
            r.atualizar_quadro(i * 0.1, [Deteccao((xa, 100, xa + 20, 160), "person", 0.9),
                                         Deteccao((xb, 100, xb + 20, 160), "person", 0.9)])
        a, b = sorted(r.atualizar_quadro(1.1, [Deteccao((320, 100, 340, 160), "person", 0.9),
                                               Deteccao((80, 100, 100, 160), "person", 0.9)]),
                      key=lambda tr: tr.id)
        self.assertEqual((a.id, b.id), (1, 2))
        self.assertGreater(a.centro[0], b.centro[0], "quem vinha da esquerda termina a direita")
        self.assertEqual(r.confirmadas, 2, "cruzamento nao pode criar identidade")

    def test_depois_do_horizonte_a_trilha_encerra_e_quem_volta_e_novo(self):
        r = Rastreador(BOLA)
        bola_andando(r, dt=0.033)
        publicadas = [r.atualizar_quadro(i * 0.033, []) for i in range(3, 13)]
        preditas = [t for q in publicadas for t in q if t.estado == "confirmada"]
        self.assertTrue(all(not t.visto for t in preditas))
        self.assertEqual(len({t.centro for t in preditas}), len(preditas), "predita parada e posicao inventada")
        self.assertTrue(any(t.estado == "perdida" for q in publicadas for t in q))
        self.assertEqual(r.atualizar_quadro(13 * 0.033, [Deteccao((200, 100, 210, 110), "ball", 0.9)]), [],
                         "a bola que volta nasce como tentativa, sem herdar a identidade (6c 1.0)")

    def test_caixa_e_deteccao_da_trilha_e_perdida_uma_vez(self):
        r = Rastreador(BOLA)
        (t,) = bola_andando(r, det_id=7, conf=0.8)
        self.assertEqual((t.caixa, t.deteccao, t.confianca), ((120, 100, 130, 110), 7, 0.8))
        (t,) = r.atualizar_quadro(0.3, [])
        self.assertIsNone(t.deteccao, "predita nao tem deteccao associada")
        self.assertLess(abs(t.caixa[0] + 5 - t.centro[0]), 1e-6, "a caixa anda com o centro")
        self.assertGreater(t.caixa[0], 120)
        saidas = [r.atualizar_quadro(0.3 + 0.1 * i, []) for i in range(1, 25)]
        self.assertEqual(len([tr for s in saidas for tr in s if tr.estado == "perdida"]), 1)
        self.assertEqual(saidas[-1], [], "depois de perdida a trilha nao volta a sair")

    def test_trocas_por_minuto_desconta_os_objetos_declarados(self):
        r = Rastreador(PESSOA)
        r.confirmadas = 14
        self.assertEqual(r.trocas_por_minuto(60.0, objetos=12), 2.0)
        self.assertEqual(r.trocas_por_minuto(60.0, objetos=20), 0.0)


if __name__ == "__main__":
    unittest.main()
