"""perfis do rastreador por classe

a 6c (convencao 4) diz que a classe vem do vocabulario do MODEL do I1, nao de uma lista fixa:
o I2 aceita qualquer classe. toda classe usa o PADRAO, a menos que tenha perfil proprio.
o embutido so diferencia `ball`, porque objeto pequeno e rapido pede predicao curta.

a aplicacao pode trocar ou acrescentar perfis com --perfis ARQUIVO.json, configuracao da
build dela (6c: cada build tem sua configuracao):

    {"versao": "perfis-a8-1",
     "padrao": {...},                        opcional, as 8 chaves
     "classes": {"vehicle": {...}}}          opcional, as 8 chaves por classe

a versao do arquivo entra no artifact_version dos eventos.
"""
import json
from dataclasses import dataclass, field

CHAVES = frozenset({"dist_max_px", "ambiguo_px", "confirmar_em", "perder_apos", "suavizacao",
                    "cresce", "teto", "horizontes_s"})

# objeto grande e lento (pessoa, veiculo): o problema e oclusao, a trilha aguenta 20 quadros
PADRAO = {"dist_max_px": 90, "ambiguo_px": 45, "confirmar_em": 3, "perder_apos": 20,
          "suavizacao": 0.5, "cresce": 0.0, "teto": 1.0, "horizontes_s": 60.0}

CLASSES = {
    # bola: o problema e predicao. 3 vistas para confirmar, porque 2 pontos quaisquer fazem uma
    # reta e o falso positivo do detector confirmava no segundo quadro; a velocidade constante
    # so vale por 0,2 s e o raio cresce enquanto ela some
    "ball": {"dist_max_px": 60, "ambiguo_px": 30, "confirmar_em": 3, "perder_apos": 20,
             "suavizacao": 0.8, "cresce": 0.25, "teto": 3.0, "horizontes_s": 0.2},
}


def _conferir(perfil, onde):
    if not isinstance(perfil, dict) or set(perfil) != CHAVES:
        faltam, sobram = CHAVES - set(perfil or {}), set(perfil or {}) - CHAVES
        raise ValueError(f"perfil {onde}: faltam {sorted(faltam)}, sobram {sorted(sobram)}")
    return dict(perfil)


@dataclass(frozen=True)
class Perfis:
    versao: str | None = None
    padrao: dict = field(default_factory=lambda: dict(PADRAO))
    classes: dict = field(default_factory=lambda: {c: dict(p) for c, p in CLASSES.items()})

    def de(self, classe):
        """perfil da classe (copia: quem escala nao mexe no original)"""
        return dict(self.classes.get(classe, self.padrao))


def carregar(caminho=None):
    """os perfis embutidos, sobrepostos pelo arquivo quando houver"""
    if caminho is None:
        return Perfis()
    with open(caminho, encoding="utf-8") as f:
        dados = json.load(f)
    if not isinstance(dados.get("versao"), str) or not dados["versao"]:
        raise ValueError(f"{caminho}: falta 'versao' (texto), que entra no artifact_version")
    classes = {c: dict(p) for c, p in CLASSES.items()}
    classes.update({c: _conferir(p, c) for c, p in dados.get("classes", {}).items()})
    padrao = _conferir(dados["padrao"], "padrao") if "padrao" in dados else dict(PADRAO)
    return Perfis(dados["versao"], padrao, classes)
