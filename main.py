"""ponto de entrada na raiz do repo (Docker, B4 e a cadeia chamam `python main.py`); o
componente esta em I2/, ver I2/run_rastreio.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "I2"))

from run_rastreio import main  # noqa: E402

main()
