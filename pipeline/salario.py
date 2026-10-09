"""Salário mínimo mensal (Banco Central, SGS série 1619), para dizer quanto do mínimo vai num botijão."""

from __future__ import annotations

import json
import time
import urllib.request

URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.1619/dados?formato=json&dataInicial=01/01/2004&dataFinal=31/12/2099"


def baixar(tentativas: int = 4) -> dict[str, float]:
    """{'2004-05': 260.0, ...}."""
    req = urllib.request.Request(URL, headers={"User-Agent": "raio-x-combustiveis"})
    for i in range(tentativas):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return parse(json.load(resp))
        except OSError:
            if i == tentativas - 1:
                raise
            time.sleep(2 ** (i + 1))
    raise AssertionError("inalcançável")


def parse(linhas: list[dict]) -> dict[str, float]:
    # data vem como "01/05/2004"
    return {f"{l['data'][6:10]}-{l['data'][3:5]}": float(l["valor"]) for l in linhas}
