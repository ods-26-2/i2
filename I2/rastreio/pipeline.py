"""quadro -> evento, com o estado separado por camera

a 6c define o track_id "valido com source_id + session_id": cada camera tem os seus
rastreadores, a sua sessao e a sua sequence. sessao nova numa camera zera so aquela camera
(a identidade termina com a sessao); as outras seguem.
"""
from dataclasses import dataclass, field

from rastreio.contrato import evento
from rastreio.rastreador import ParametrosCamera, Rastreador

VERSAO = "i2-rastreio-2.0"              # artifact_version: o motor que rastreou


@dataclass
class Estado:
    sessao: str
    t_ini: float
    t_ult: float = 0.0
    sequencia: int = 0
    rastreadores: dict = field(default_factory=dict)   # classe -> Rastreador


class Pipeline:
    def __init__(self, perfis, fps, conf_min=None, objetos=None, relatar=print):
        """conf_min e objetos: classe -> valor; classe ausente = sem corte, 1 objeto esperado.
        relatar recebe as linhas da metrica de cada sessao encerrada"""
        self.perfis, self.fps = perfis, fps
        self.conf_min, self.objetos = conf_min or {}, objetos or {}
        self.relatar = relatar
        self.versao = VERSAO + (f"+{perfis.versao}" if perfis.versao else "")
        self.fontes = {}                               # source_id -> Estado

    def processar(self, q):
        """um Quadro -> o evento ods.i2.tracks dele (ainda nao validado nem publicado)"""
        estado = self.fontes.get(q.fonte)
        if estado is None or estado.sessao != q.sessao:
            if estado is not None:
                self._relatorio(q.fonte, estado)
            estado = self.fontes[q.fonte] = Estado(q.sessao, q.t_s, q.t_s)
        estado.t_ult = q.t_s
        cam = ParametrosCamera(q.fonte, self.fps, q.largura, q.altura)
        dets = [d for d in q.deteccoes if d.confianca >= self.conf_min.get(d.classe, 0.0)]
        trilhas = []
        # todos os rastreadores rodam todo quadro: e no quadro sem deteccao que a trilha prediz
        # e segura a identidade
        for classe in sorted(set(estado.rastreadores) | {d.classe for d in dets}):
            r = estado.rastreadores.get(classe)
            if r is None:
                r = estado.rastreadores[classe] = Rastreador(self.perfis.de(classe), cam)
            trilhas += r.atualizar_quadro(q.t_s, [d for d in dets if d.classe == classe])
        ev = evento(q, estado.sequencia, trilhas, self.versao)
        estado.sequencia += 1
        return ev

    def fechar(self):
        for fonte, estado in self.fontes.items():
            self._relatorio(fonte, estado)
        self.fontes = {}

    def _relatorio(self, fonte, estado):
        """metrica do I2 (trocas de identidade por minuto) da sessao que terminou; o numero so
        vale junto com o cenario declarado (--objetos)"""
        duracao = max(estado.t_ult - estado.t_ini, 1.0 / self.fps)
        for classe, r in sorted(estado.rastreadores.items()):
            esperado = int(self.objetos.get(classe, 1))
            self.relatar(f"i2 {fonte} {classe:7s}: {r.trocas_por_minuto(duracao, esperado):5.1f} trocas/min "
                         f"({r.confirmadas} confirmadas em {duracao:.1f}s, {estado.sequencia} quadros)")
