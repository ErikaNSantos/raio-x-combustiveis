"""Contorno das UFs (malha oficial do IBGE) salvo junto do site, sem depender da API em tempo real."""

from __future__ import annotations

import gzip
import json
import unicodedata
import urllib.request
from pathlib import Path

MALHA = (
    "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR"
    "?formato=application/vnd.geo%2Bjson&intrarregiao=UF&qualidade=minima"
)
ESTADOS = "https://servicodados.ibge.gov.br/api/v1/localidades/estados"
MUNICIPIOS = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios?view=nivelado"


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "raio-x-combustiveis"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        corpo = resp.read()
    # A API de malhas responde em gzip mesmo sem Accept-Encoding: detecta pelos bytes mágicos.
    if corpo[:2] == b"\x1f\x8b":
        corpo = gzip.decompress(corpo)
    return json.loads(corpo)


def _arredondar(coords, casas: int = 3):
    if isinstance(coords[0], (int, float)):
        return [round(c, casas) for c in coords]
    return [_arredondar(c, casas) for c in coords]


def _area(anel) -> float:
    """Área com sinal (fórmula do laço): positiva = anti-horário em lon/lat."""
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(anel, anel[1:])) / 2


def _orientar(poligono):
    """d3 espera o anel externo no sentido horário e os buracos no anti-horário (o oposto
    da RFC 7946, que a API do IBGE segue). Sem isso o mapa pinta "o mundo menos o estado"."""
    externo, *buracos = poligono
    externo = externo[::-1] if _area(externo) > 0 else externo
    buracos = [b[::-1] if _area(b) < 0 else b for b in buracos]
    return [externo, *buracos]


def gerar(destino: Path) -> dict[str, str]:
    """Grava o GeoJSON com `sigla` e `nome` em cada UF e devolve {sigla: nome}."""
    estados = {str(e["id"]): (e["sigla"], e["nome"]) for e in _get(ESTADOS)}
    malha = _get(MALHA)
    for feat in malha["features"]:
        sigla, nome = estados[str(feat["properties"]["codarea"])]
        feat["properties"] = {"sigla": sigla, "nome": nome}
        geom = feat["geometry"]
        coords = _arredondar(geom["coordinates"])
        geom["coordinates"] = [_orientar(p) for p in coords] if geom["type"] == "MultiPolygon" else _orientar(coords)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(malha, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    return {sigla: nome for sigla, nome in estados.values()}


def normalizar(nome: str) -> str:
    """Como a ANP escreve: maiúsculas, sem acento, apóstrofo e hífen viram espaço."""
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.upper().replace("'", " ").replace("-", " ").split())


def nomes_municipios() -> dict[str, str]:
    """{'SP|SAO PAULO': 'São Paulo', ...} para mostrar o nome oficial do IBGE, com acento."""
    return {
        f"{m['UF-sigla']}|{normalizar(m['municipio-nome'])}": m["municipio-nome"]
        for m in _get(MUNICIPIOS)
    }
