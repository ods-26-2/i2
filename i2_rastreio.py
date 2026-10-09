"""i2 identidade e rastreio -- sprint 2"""
from collections import namedtuple

import numpy as np

# entrada de i1, caixa em px e confianca de zero a um
Deteccao = namedtuple("Deteccao", "caixa classe confianca")

# saida, estado pode ser tentativa confirmada ou perdida
Trilha = namedtuple("Trilha", "id classe estado centro t_s visto vistas")

ParametrosCamera = namedtuple("ParametrosCamera", "camera_id fps largura_px altura_px retificado")

LARGURA_REF_PX, FPS_REF = 1920.0, 30.0
PERFIS = {
    "pessoa": {"dist_max_px": 90, "ambiguo_px": 45, "confirmar_em": 3,
               "perder_apos": 20, "suavizacao": 0.5,
               "cresce": 0.0, "teto": 1.0, "horizontes_s": 60.0},
    "bola": {"dist_max_px": 60, "ambiguo_px": 30, "confirmar_em": 2,
             "perder_apos": 20, "suavizacao": 0.8,
             "cresce": 0.25, "teto": 3.0, "horizontes_s": 0.2},
}


def centro(caixa):
    """centro da caixa em px

    card I2.1 · associacao entre quadros e track_id -- sprint 2, etapa 2 (Davi)
    """
    x1, y1, x2, y2 = caixa
    return np.array([(x1 + x2) / 2.0, (y1 + y2) / 2.0])


class Rastreador:
    """motor de i2, recebe deteccoes e devolve trilhas"""

    def __init__(self, perfil, camera=None):
        """monta o perfil e escala o raio de busca pra camera

        card I2.1 · associacao entre quadros e track_id -- sprint 2, etapa 2 (Davi)
        """
        self.p = dict(PERFIS[perfil])
        if camera is not None:
            fator = (camera.largura_px / LARGURA_REF_PX) * (FPS_REF / camera.fps)
            self.p["dist_max_px"] *= fator
            self.p["ambiguo_px"] *= fator   # a ambiguidade e distancia, escala igual
            # perder_apos e contado em quadros; se o fps mudar, o mesmo numero de
            # quadros passa a valer um tempo real diferente. escala pra manter a
            # tolerancia de oclusao constante em segundos, nao em quadros
            fator_fps = camera.fps / FPS_REF
            self.p["perder_apos"] = max(1, round(self.p["perder_apos"] * fator_fps))
        self.trilhas, self.proximo_id, self.confirmadas = {}, 1, 0

    def atualizar_quadro(self, t_s, deteccoes):
        """atualiza as trilhas e devolve as confirmadas

        card I2.1 · associacao entre quadros e track_id -- sprint 2, etapas 1 e 3 (Davi)
        card I2.2 · oclusao, cruzamento e reentrada -- sprint 2, etapas 4a e 4b (Lara)
        falta: etapa 7, publicar evento no esquema de B1 -- daqui sai trilha, nao evento
        """
        centros = [centro(d.caixa) for d in deteccoes]           # centro de cada deteccao
        vistos, usadas = self._associar(t_s, centros, deteccoes)  # casa trilha com deteccao
        for tid, tr in self.trilhas.items():                      # quem nao associou ou sumiu mais um quadro
            if tid not in vistos and tr["estado"] != "perdida":
                tr["sumido"] += 1
                if tr["sumido"] > self.p["perder_apos"]:
                    tr["estado"] = "perdida"                      # perdido
        for i, d in enumerate(deteccoes):                          # deteccao que sobrou e objeto novo
            if i not in usadas:
                self._nascer(t_s, d, centros[i])
        # trilha perdida nunca mais e associada: guardar todas faz o laco de
        # associacao percorrer o jogo inteiro a cada quadro
        self.trilhas = {tid: tr for tid, tr in self.trilhas.items() if tr["estado"] != "perdida"}
        return [self._publicar(tr, t_s, tr["id"] in vistos)        # so publica quem ja confirmou
                for tr in self.trilhas.values() if tr["estado"] == "confirmada"]

    def _associar(self, t_s, centros, deteccoes):
        """casa trilha com deteccao pela posicao predita, do mais perto pro mais longe

        card I2.1 · associacao entre quadros -- sprint 2, etapa 2 (Davi, apoio Lara)
        card I2.2 · oclusao e cruzamento -- sprint 2, etapa 4a (Lara)
        """
        custo = {}
        for tid, tr in self.trilhas.items():
            if tr["estado"] == "perdida":
                continue
            pred = self._predizer(tr, t_s)
            raio = self.p["dist_max_px"] * min(1 + self.p["cresce"] * tr["sumido"], self.p["teto"])
            for i, c in enumerate(centros):
                dist = float(np.hypot(*(c - pred)))
                if dist <= raio:
                    custo[(tid, i)] = dist
        # fase 2: casar do mais perto pro mais longe, uma vez cada, pulando a disputa
        vistos, usadas, disputadas = set(), set(), set()
        for (tid, i), d in sorted(custo.items(), key=lambda kv: kv[1]):
            if tid in vistos or i in usadas:
                continue
            if self._disputado(custo, tid, i, d, vistos, usadas):
                disputadas.add(i)
                continue
            vistos.add(tid), usadas.add(i)
            self._atualizar(tid, t_s, deteccoes[i], centros[i])
        # deteccao em disputa nao e objeto novo: ela pertence a uma das trilhas que
        # a disputam, so nao se sabe a qual. deixar nascer inventa identidade a cada
        # quadro de cruzamento -- e num jogo inteiro isso e um vazamento, nao ruido
        return vistos, usadas | disputadas

    def _disputado(self, custo, tid, i, d, vistos, usadas):
        """diz se o segundo colocado esta perto demais pra a escolha valer

        card I2.2 · cruzamento -- sprint 2, etapa 4a (Lara)

        oclusao e cruzamento sao problemas diferentes e o passo a passo pede
        tratamento proprio pra cada um. oclusao e ausencia de deteccao, e a
        predicao resolve. cruzamento e o oposto: ha deteccao demais, e duas
        ficam quase a mesma distancia da trilha -- ou duas trilhas, da mesma
        deteccao. casar no cara-ou-coroa e exatamente como a identidade troca.

        aqui nao se escolhe. quem esta em disputa segue na predicao por este
        quadro, que e o mesmo mecanismo que carrega a oclusao; quando os dois
        se separam, a velocidade ja desempatou.
        """
        rivais = [c for (t2, i2), c in custo.items()
                  if (t2 == tid) != (i2 == i)          # disputa pela trilha ou pela deteccao
                  and t2 not in vistos and i2 not in usadas]
        return bool(rivais) and min(rivais) - d < self.p["ambiguo_px"]

    def trocas_por_minuto(self, duracao_s, objetos=1):
        """identidades confirmadas alem das esperadas, por minuto

        card I2.3 · metrica trocas de identidade / min -- sprint 2, etapa 5 (Lara, apoio Diego)

        conta confirmacao, nao nascimento. trilha que morreu ainda em `tentativa`
        nunca teve identidade publicada -- contar isso media o falso positivo do
        detector, nao a troca de identidade do rastreador.

        `objetos` e a densidade declarada do cenario: 12 pessoas em quadra sao 12
        identidades legitimas, nao 12 trocas. a V6 pede o numero "sob condicoes
        declaradas de oclusao e densidade", e e este o parametro que as declara.
        """
        return max(self.confirmadas - objetos, 0) * 60.0 / max(duracao_s, 1e-6)

    def _predizer(self, tr, t_s):
        """onde a trilha deve estar em t_s, na mesma velocidade ate o horizonte
        
        card I2.2 · oclusao -- sprint 2, etapa 4a (Lara)
        a velocidade constante so vale por um instante. Depois do horizonte
        a predicao para de andar: manter a identidade por mais tempo nao pode
        significar inventar uma posicao ca vez mais longe da bola"""
        
        return tr["pos"] + tr["vel"] * min(t_s - tr["t"], self.p["horizontes_s"])
    
    def _publicar(self, tr, t_s, visto):
        """monta a trilha de saida, com centro predito no quadro sem deteccao

        card I2.1 · trajetoria continua por objeto -- sprint 2, etapa 3 (Davi)
        card I2.2 · oclusao -- sprint 2, etapa 4a (Lara): mantem last-known por N quadros
        """
        pos = tr["pos"] if visto else self._predizer(tr, t_s)
        return Trilha(tr["id"], tr["classe"], tr["estado"], tuple(pos), t_s, visto, tr["vistas"])

    def _nascer(self, t_s, d, c):
        """abre identidade nova pra deteccao que nao casou com nenhuma trilha

        card I2.1 · gerar track_id -- sprint 2, etapa 3 (Davi)
        card I2.2 · reentrada -- sprint 2, etapa 4b (Lara): hoje reentrada vira track_id novo
        falta: a decisao documentada que a etapa 4b pede, nao so o comportamento no codigo
        """
        self.trilhas[self.proximo_id] = {
            "id": self.proximo_id, "classe": d.classe, "estado": "tentativa",
            "pos": c, "vel": np.zeros(2), "t": t_s, "vistas": 1, "sumido": 0}
        self.proximo_id += 1

    def _atualizar(self, tid, t_s, d, c):
        """atualiza posicao e velocidade da trilha e confirma quando junta vistas

        card I2.1 · atualizar track_id, posicao e instante -- sprint 2, etapa 3 (Davi)
        """
        tr, a = self.trilhas[tid], self.p["suavizacao"]
        dt = t_s - tr["t"]
        if dt > 1e-3:   # dt quase zero (duas fontes com o mesmo t_s) explodiria a velocidade
            tr["vel"] = a * (c - tr["pos"]) / dt + (1 - a) * tr["vel"]
        tr["pos"], tr["t"], tr["sumido"] = c, t_s, 0
        tr["vistas"] += 1
        if tr["vistas"] >= self.p["confirmar_em"] and tr["estado"] != "confirmada":
            tr["estado"] = "confirmada"
            self.confirmadas += 1          # so a transicao, nao todo quadro depois dela


if __name__ == "__main__":
    ref = Rastreador("bola")
    assert ref.p["dist_max_px"] == 60, "sem camera, perfil fica cru"

    dobro_res = ParametrosCamera("cam1", FPS_REF, LARGURA_REF_PX * 2, 1080, True)
    r = Rastreador("bola", dobro_res)
    assert r.p["dist_max_px"] == 120, f"resolucao 2x devia dobrar o raio, deu {r.p['dist_max_px']}"

    metade_fps = ParametrosCamera("cam1", FPS_REF / 2, LARGURA_REF_PX, 1080, True)
    r = Rastreador("bola", metade_fps)
    assert r.p["dist_max_px"] == 120, f"fps pela metade devia dobrar o raio, deu {r.p['dist_max_px']}"
    assert r.p["perder_apos"] == 10, (
        f"fps pela metade devia reduzir perder_apos a metade (mesma tolerancia em "
        f"segundos), deu {r.p['perder_apos']}")

    r = Rastreador("bola", dobro_res)
    assert r.p["perder_apos"] == 20, "so a resolucao mudar nao pode afetar perder_apos"

    assert PERFIS["bola"]["dist_max_px"] == 60, "escalar nao pode vazar pro dict global"
    assert PERFIS["bola"]["perder_apos"] == 20, "escalar nao pode vazar pro dict global"

    # oclusao: a trilha tem que atravessar o quadro sem deteccao, predizendo.
    # e o que segura a identidade enquanto a bola borra -- sem isto ela troca
    r = Rastreador("bola")
    for i in range(3):                       # bola andando 10 px por quadro
        x = 100 + 10 * i
        r.atualizar_quadro(i * 0.1, [Deteccao((x, 100, x + 10, 110), "bola", 0.9)])
    (t,) = r.atualizar_quadro(0.3, [])       # quadro sem deteccao
    assert not t.visto, "sem deteccao a trilha tem que sair marcada como predita"
    assert t.estado == "confirmada", "uma falha so nao pode perder a trilha"
    assert 130 <= t.centro[0] <= 140, f"predicao devia seguir pra ~135, deu {t.centro[0]:.1f}"

    # cruzamento: duas trilhas que se cruzam nao podem trocar de id. no encontro
    # a escolha e cara-ou-coroa, entao ninguem escolhe -- as duas predizem e a
    # velocidade desempata do outro lado
    r = Rastreador("pessoa")
    for i in range(11):                      # a vem da esquerda, b da direita, 20 px/quadro
        xa, xb = 100 + 20 * i, 300 - 20 * i
        r.atualizar_quadro(i * 0.1, [Deteccao((xa, 100, xa + 20, 160), "pessoa", 0.9),
                                     Deteccao((xb, 100, xb + 20, 160), "pessoa", 0.9)])
    a, b = sorted(r.atualizar_quadro(1.1, [Deteccao((320, 100, 340, 160), "pessoa", 0.9),
                                           Deteccao((80, 100, 100, 160), "pessoa", 0.9)]),
                  key=lambda tr: tr.id)
    assert (a.id, b.id) == (1, 2), f"os ids originais tinham que sobreviver, deu {a.id},{b.id}"
    assert a.centro[0] > b.centro[0], "quem vinha da esquerda tem que terminar a direita"
    assert r.confirmadas == 2, f"cruzamento nao pode criar identidade, criou {r.confirmadas}"

    r = Rastreador("bola")
    for i in range(3):                       # bola andando 10 px por quadro
        x = 100 + 10 * i
        r.atualizar_quadro(i * 0.033, [Deteccao((x, 100, x + 10, 110), "bola", 0.9)])
        
    ultima = None
    for i in range(3, 13):     
        anterior = ultima
        (ultima,) = r.atualizar_quadro(i * 0.033, [])
        assert not ultima.visto
    assert anterior.centro == ultima.centro, "depois do horizonte a predicao tinha que parar"
    (t,) = r.atualizar_quadro(13 * 0.033, [Deteccao((200, 100, 210, 110), "bola", 0.9)])
    assert (t.id, t.visto) == (1, True), f"a bola voltou com id novo: {t.id}"
    assert r.confirmadas == 1, f"bola longa nao pode criar identidade, criou {r.confirmadas}"
    print("ok")