"""bola por modelo temporal no I2 (6c: o I2 consome P4 e, condicional, P2 com um MODEL)

a bola e pequena e rapida: o detector por quadro do I1 confunde logo redondo, tenis e bandeira
com bola e perde a bola borrada. um modelo que ve 9 quadros seguidos (VballNet, ONNX, MIT) acha
a bola pelo movimento; medido no video do A4: 74% de acerto contra 13% do detector por quadro.
o I2 le o stream (P4 ao vivo, ou a gravacao do P6 em replay) pelo frame_index de cada
ods.i1.detections e troca as deteccoes de bola do I1 pelas do modelo; as outras classes seguem
do I1. a bola que vem do modelo nao tem detection_id de I1.
"""
import cv2
import numpy as np

from i2_rastreio import Deteccao

LIMIAR = 0.5          # o do modelo (DEFAULT_HEATMAP_THRESHOLD do repo dele)
RAIO_PADRAO = 6.0     # px, quando o modelo nao traz o mapa de raio


class BolaTemporal:
    def __init__(self, modelo, video):
        import onnxruntime as ort
        self.sessao = ort.InferenceSession(modelo, providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
        entrada = self.sessao.get_inputs()[0]
        self.nome, (_, self.seq, self.h, self.w) = entrada.name, entrada.shape
        self.video = video
        self.reiniciar()

    def reiniciar(self):
        """sessao nova (o replay voltou ao comeco): o stream recomeca do quadro 0"""
        self.cap = cv2.VideoCapture(self.video)
        self.proximo, self.cache = 0, {}

    def deteccoes(self, n):
        """bola do quadro n do stream, como Deteccao do I2 (vazia se o modelo nao viu)"""
        if n not in self.cache:
            self._janela(n // self.seq * self.seq)
        return self.cache.get(n, [])

    def _janela(self, inicio):
        if inicio != self.proximo:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, inicio)
        quadros = []
        for _ in range(self.seq):
            ok, q = self.cap.read()
            if not ok:
                break
            quadros.append(q)
        self.proximo = inicio + len(quadros)
        if not quadros:
            return
        largura, altura = quadros[0].shape[1], quadros[0].shape[0]
        reais = len(quadros)
        quadros += [quadros[-1]] * (self.seq - reais)           # fim do video: repete o ultimo
        cinza = np.stack([cv2.cvtColor(cv2.resize(q, (self.w, self.h)), cv2.COLOR_BGR2GRAY) for q in quadros])
        saida = self.sessao.run(None, {self.nome: (cinza.astype(np.float32) / 255.0)[None]})[0]
        com_raio = saida.shape[1] == 2 * self.seq
        self.cache = {k: v for k, v in self.cache.items() if k >= inicio - self.seq}
        for k in range(reais):
            self.cache[inicio + k] = self._decodificar(saida, k, com_raio, largura, altura)

    def _decodificar(self, saida, k, com_raio, largura, altura):
        """maior blob acima do limiar, centroide; mesmo pos-processamento do repo do modelo"""
        hm = saida[0, k].astype(np.float32)
        _, binaria = cv2.threshold(hm, LIMIAR, 1.0, cv2.THRESH_BINARY)
        contornos, _ = cv2.findContours((binaria * 255).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contornos:
            return []
        m = cv2.moments(max(contornos, key=cv2.contourArea))
        if m["m00"] == 0:
            return []
        cx, cy = m["m10"] / m["m00"], m["m01"] / m["m00"]
        raio = float(saida[0, self.seq + k, int(cy), int(cx)]) * largura if com_raio else 0.0
        raio = raio if raio > 0 else RAIO_PADRAO
        u, v = cx * largura / self.w, cy * altura / self.h
        return [Deteccao((u - raio, v - raio, u + raio, v + raio), "bola", float(hm.max()), None)]
