"""motor do I2: deteccoes de um quadro -> trilhas com identidade estavel dentro de uma camera

o rastreador nao conhece aplicacao nem classe: recebe um perfil (perfis.py) e as deteccoes de
uma classe so. quem decide qual perfil vale para qual classe e quem guarda um rastreador por
camera e por sessao e o pipeline.
"""
import math
from collections import namedtuple

import numpy as np

# entrada, caixa em px e confianca de zero a um
# id e o detection_id de I1 no quadro; sem id, a trilha sai sem detection_id
Deteccao = namedtuple("Deteccao", "caixa classe confianca id", defaults=[None])

# saida, estado pode ser tentativa, confirmada ou perdida. caixa e a da deteccao, sem
# suavizacao (extrapolada quando predita); deteccao e o id dela, ou None quando predita
Trilha = namedtuple("Trilha", "id classe estado centro t_s visto vistas caixa deteccao confianca")

ParametrosCamera = namedtuple("ParametrosCamera", "source_id fps largura_px altura_px")

# os perfis sao medidos numa camera de referencia; outra resolucao ou outro fps escalam o raio
LARGURA_REF_PX, FPS_REF = 1920.0, 30.0


def centro(caixa):
    """centro da caixa em px"""
    x1, y1, x2, y2 = caixa
    return np.array([(x1 + x2) / 2.0, (y1 + y2) / 2.0])


class Rastreador:
    """associa deteccoes de uma classe entre quadros e devolve as trilhas confirmadas"""

    def __init__(self, perfil, camera=None):
        """copia o perfil e escala o raio de busca e a vida sem deteccao para a camera"""
        self.p = dict(perfil)
        if camera is not None:
            fator = (camera.largura_px / LARGURA_REF_PX) * (FPS_REF / camera.fps)
            self.p["dist_max_px"] *= fator
            self.p["ambiguo_px"] *= fator   # a ambiguidade e distancia, escala igual
            # perder_apos e contado em quadros; se o fps mudar, o mesmo numero de
            # quadros passa a valer um tempo real diferente. escala pra manter a
            # tolerancia de oclusao constante em segundos, nao em quadros
            fator_fps = camera.fps / FPS_REF
            self.p["perder_apos"] = max(1, round(self.p["perder_apos"] * fator_fps))
        # a trilha so sobrevive sem deteccao enquanto a predicao vale: depois do horizonte
        # ela parava no lugar e saia como posicao inventada, parada, quadro apos quadro
        fps = camera.fps if camera is not None else FPS_REF
        self.p["perder_apos"] = min(self.p["perder_apos"], max(1, math.ceil(self.p["horizontes_s"] * fps)))
        self.trilhas, self.proximo_id, self.confirmadas = {}, 1, 0

    def atualizar_quadro(self, t_s, deteccoes):
        """atualiza as trilhas com as deteccoes do quadro e devolve as confirmadas, mais as que
        encerram neste quadro (essas saem uma vez, como perdidas)"""
        centros = [centro(d.caixa) for d in deteccoes]
        vistos, usadas = self._associar(t_s, centros, deteccoes)
        encerradas = []                                            # confirmadas que morrem neste quadro
        for tid, tr in self.trilhas.items():                      # quem nao associou sumiu mais um quadro
            if tid not in vistos and tr["estado"] != "perdida":
                tr["sumido"] += 1
                if tr["sumido"] > self.p["perder_apos"]:
                    if tr["estado"] == "confirmada":
                        encerradas.append(self._publicar(tr, t_s, False)._replace(estado="perdida"))
                    tr["estado"] = "perdida"
        for i, d in enumerate(deteccoes):                          # deteccao que sobrou e objeto novo
            if i not in usadas:
                self._nascer(t_s, d, centros[i])
        # trilha perdida nunca mais e associada: guardar todas faz o laco de
        # associacao percorrer o jogo inteiro a cada quadro
        self.trilhas = {tid: tr for tid, tr in self.trilhas.items() if tr["estado"] != "perdida"}
        # so publica quem ja confirmou; a perdida sai uma vez, no quadro em que encerra (6c)
        return [self._publicar(tr, t_s, tr["id"] in vistos)
                for tr in self.trilhas.values() if tr["estado"] == "confirmada"] + encerradas

    def _associar(self, t_s, centros, deteccoes):
        """casa trilha com deteccao pela posicao predita, do mais perto pro mais longe"""
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
        # casar do mais perto pro mais longe, uma vez cada, pulando a disputa
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

        oclusao e cruzamento sao problemas diferentes. oclusao e ausencia de deteccao, e a
        predicao resolve. cruzamento e o oposto: ha deteccao demais, e duas ficam quase a
        mesma distancia da trilha -- ou duas trilhas, da mesma deteccao. casar no
        cara-ou-coroa e exatamente como a identidade troca.

        aqui nao se escolhe. quem esta em disputa segue na predicao por este quadro, que e o
        mesmo mecanismo que carrega a oclusao; quando os dois se separam, a velocidade ja
        desempatou.
        """
        rivais = [c for (t2, i2), c in custo.items()
                  if (t2 == tid) != (i2 == i)          # disputa pela trilha ou pela deteccao
                  and t2 not in vistos and i2 not in usadas]
        return bool(rivais) and min(rivais) - d < self.p["ambiguo_px"]

    def trocas_por_minuto(self, duracao_s, objetos=1):
        """identidades confirmadas alem das esperadas, por minuto (a metrica do I2 na 6c)

        conta confirmacao, nao nascimento. trilha que morreu ainda em `tentativa` nunca teve
        identidade publicada -- contar isso media o falso positivo do detector, nao a troca
        de identidade do rastreador.

        `objetos` e a densidade declarada do cenario: 12 pessoas em quadra sao 12 identidades
        legitimas, nao 12 trocas. a 6c pede o numero "sob condicoes declaradas de oclusao e
        densidade", e e este o parametro que as declara.
        """
        return max(self.confirmadas - objetos, 0) * 60.0 / max(duracao_s, 1e-6)

    def _predizer(self, tr, t_s):
        """onde a trilha deve estar em t_s, na mesma velocidade ate o horizonte

        a velocidade constante so vale por um instante. depois do horizonte a predicao para de
        andar: manter a identidade por mais tempo nao pode significar inventar uma posicao cada
        vez mais longe do objeto"""
        return tr["pos"] + tr["vel"] * min(t_s - tr["t"], self.p["horizontes_s"])

    def _publicar(self, tr, t_s, visto):
        """monta a trilha de saida, com centro predito no quadro sem deteccao"""
        pos = tr["pos"] if visto else self._predizer(tr, t_s)
        caixa = tr["caixa"] + np.tile(pos - tr["pos"], 2)   # predita: a caixa anda com o centro
        return Trilha(tr["id"], tr["classe"], tr["estado"], tuple(pos), t_s, visto, tr["vistas"],
                      tuple(caixa), tr["det_id"] if visto else None, tr["confianca"])

    def _nascer(self, t_s, d, c):
        """abre identidade nova pra deteccao que nao casou com nenhuma trilha; objeto que sai e
        volta tambem cai aqui e ganha identidade nova (decisao da 6c para a 1.0)"""
        self.trilhas[self.proximo_id] = {
            "id": self.proximo_id, "classe": d.classe, "estado": "tentativa",
            "pos": c, "vel": np.zeros(2), "t": t_s, "vistas": 1, "sumido": 0,
            "caixa": np.array(d.caixa, float), "det_id": d.id, "confianca": d.confianca}
        self.proximo_id += 1

    def _atualizar(self, tid, t_s, d, c):
        """atualiza posicao e velocidade da trilha e confirma quando junta vistas"""
        tr, a = self.trilhas[tid], self.p["suavizacao"]
        dt = t_s - tr["t"]
        if dt > 1e-3:   # dt quase zero (duas fontes com o mesmo t_s) explodiria a velocidade
            tr["vel"] = a * (c - tr["pos"]) / dt + (1 - a) * tr["vel"]
        tr["pos"], tr["t"], tr["sumido"] = c, t_s, 0
        tr["caixa"], tr["det_id"], tr["confianca"] = np.array(d.caixa, float), d.id, d.confianca
        tr["vistas"] += 1
        if tr["vistas"] >= self.p["confirmar_em"] and tr["estado"] != "confirmada":
            tr["estado"] = "confirmada"
            self.confirmadas += 1          # so a transicao, nao todo quadro depois dela
