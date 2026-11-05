"""o main.py da raiz, do jeito que o B4 e a cadeia chamam"""
import json
import signal
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path

from rastreio import contrato

RAIZ = Path(__file__).resolve().parents[2]

# a chamada exata da suite do B4 (ods-26-2/b4, tests/integration/i2/test_i2.py)
CSV_B4 = (
    "quadro,t_s,x1,y1,x2,y2,classe,confianca\n"
    "0,0.0,10,10,50,100,pessoa,0.9\n"
    "1,0.1,11,10,51,100,pessoa,0.9\n"
    "2,0.2,12,10,52,100,pessoa,0.9\n"
    "3,0.3,13,10,53,100,pessoa,0.9\n"
)


def rodar(*args, entrada=""):
    return subprocess.run([sys.executable, str(RAIZ / "main.py"), *args], cwd=RAIZ, input=entrada,
                          text=True, capture_output=True, timeout=60)


class ChamadaDoB4(unittest.TestCase):
    def test_csv_com_camera_id_da_eventos_validos(self):
        r = rodar("--camera-id", "cam0", "--sessao", str(uuid.uuid4()), "--inicio", "2026-09-23T14:29:59.000Z",
                  entrada=CSV_B4)
        self.assertEqual(r.returncode, 0, r.stderr)
        evs = [json.loads(l) for l in r.stdout.splitlines()]
        self.assertEqual(len(evs), 4)
        for e in evs:
            self.assertEqual(contrato.erros(e), [])
        self.assertEqual(evs[-1]["source_id"], "cam0")
        self.assertEqual({t["class"] for t in evs[-1]["payload"]["tracks"]}, {"person"})

    def test_conf_min_mal_escrito_e_recusado(self):
        r = rodar("--conf-min", "ball:0.5")
        self.assertEqual(r.returncode, 2)
        self.assertIn("classe=valor", r.stderr)


class Sinais(unittest.TestCase):
    def test_sigterm_encerra_limpo(self):
        p = subprocess.Popen([sys.executable, str(RAIZ / "main.py")], cwd=RAIZ, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        p.stdin.write("0,0.0,10,10,50,100,person,0.9\n")
        p.stdin.flush()
        time.sleep(1.0)
        p.send_signal(signal.SIGTERM)
        _, erro = p.communicate(timeout=10)
        self.assertEqual(p.returncode, 0, erro)


if __name__ == "__main__":
    unittest.main()
