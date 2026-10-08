"""IPCA (IBGE/SIDRA, tabela 1737, número-índice) para pôr os preços em reais de hoje."""

from __future__ import annotations

import json
import urllib.request

URL = "https://apisidra.ibge.gov.br/values/t/1737/n1/all/v/2266/p/{inicio}-{fim}"


def baixar(inicio: str = "200401", fim: str = "209912") -> dict[str, float]:
    """{'AAAA-MM': número-índice, ...}. Os meses ainda não divulgados simplesmente não vêm."""
    req = urllib.request.Request(URL.format(inicio=inicio, fim=fim), headers={"User-Agent": "raio-x-combustiveis"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        linhas = json.load(resp)
    return parse(linhas)


def parse(linhas: list[dict]) -> dict[str, float]:
    indice = {}
    for linha in linhas[1:]:  # a primeira linha é o cabeçalho descritivo
        codigo, valor = linha.get("D3C", ""), linha.get("V", "")
        if len(codigo) == 6 and valor not in ("", "...", "-"):
            indice[f"{codigo[:4]}-{codigo[4:]}"] = float(valor)
    return indice


def fatores(indice: dict[str, float], periodos: list[str]) -> tuple[dict[str, float], str]:
    """Fator que leva o preço de cada mês para reais do último IPCA divulgado.

    Meses mais novos que o último IPCA (o IBGE divulga ~10 dias depois do fim do mês)
    recebem fator 1: ficam em valores nominais até o índice sair.
    """
    base = max(indice)
    return {p: (indice[base] / indice[p] if p in indice else 1.0) for p in periodos}, base
