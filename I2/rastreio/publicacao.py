"""saida do I2: uma linha json no stdout, ou o topico ods.i2.tracks com --kafka

os dois validam antes de publicar; mensagem fora do contrato e contada, registrada no stderr e
nao sai (6c: o validador do publicador rejeita, e ela nunca chega ao barramento).
"""
import json
import sys

from rastreio import contrato


class Publicador:
    def __init__(self):
        self.publicadas, self.rejeitadas = 0, 0

    def publicar(self, ev):
        problemas = contrato.erros(ev)
        if problemas:
            self.rejeitadas += 1
            print(f"i2: evento rejeitado pelo validador: {'; '.join(problemas)}", file=sys.stderr)
            return False
        self._enviar(ev)
        self.publicadas += 1
        return True

    def _enviar(self, ev):
        raise NotImplementedError

    def fechar(self):
        pass


class Stdout(Publicador):
    def _enviar(self, ev):
        print(json.dumps(ev), flush=True)


class Kafka(Publicador):
    """chave source_id: a mesma particao para a mesma camera, ordem dos quadros preservada"""

    def __init__(self, broker):
        super().__init__()
        from confluent_kafka import Producer
        self.broker, self.falhas = broker, []
        self.produtor = Producer({"bootstrap.servers": broker})

    def _enviar(self, ev):
        self.produtor.produce(contrato.TOPICO, key=ev["source_id"], value=json.dumps(ev).encode(),
                              on_delivery=lambda erro, _msg: erro and self.falhas.append(erro))
        self.produtor.poll(0)                 # entrega os callbacks sem bloquear

    def fechar(self):
        if self.produtor.flush(30) or self.falhas:
            raise SystemExit(f"i2: {len(self.falhas)} eventos nao entregues em {self.broker}")
        print(f"i2: {self.publicadas} eventos publicados em {contrato.TOPICO}", file=sys.stderr)
