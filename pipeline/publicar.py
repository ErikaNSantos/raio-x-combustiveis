"""Junta os agregados mensais e gera os JSONs que a página lê.

- site/data/resumo.json: Brasil e UFs, todos os meses (carregado sempre, pequeno).
- site/data/municipios/<UF>.json: municípios de uma UF (carregado só quando a UF é escolhida).

As séries são listas de [periodo, mediana, p10, p90, minimo, maximo, postos], em valores
nominais; o fator do IPCA de cada mês vai junto para a página converter em reais de hoje.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .agregar import CAPITAIS
from .malha import normalizar

CAMPOS = ["periodo", "mediana", "p10", "p90", "minimo", "maximo", "postos"]


def carregar(pasta: Path) -> pd.DataFrame:
    arquivos = sorted(pasta.glob("*.csv"))
    if not arquivos:
        raise FileNotFoundError(f"Nenhum agregado em {pasta}")
    return pd.concat((pd.read_csv(a, dtype={"periodo": str}) for a in arquivos), ignore_index=True)


def _series(df: pd.DataFrame) -> dict:
    """{codigo: {produto: [[periodo, ...], ...]}} ordenado por período."""
    saida: dict = {}
    for (codigo, produto), g in df.sort_values("periodo").groupby(["codigo", "produto"]):
        linhas = g[CAMPOS].astype(object).values.tolist()
        saida.setdefault(codigo, {})[produto] = linhas
    return saida


def _gravar(caminho: Path, dados: dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")


def publicar(
    agregados: pd.DataFrame,
    destino: Path,
    fatores_ipca: dict[str, float],
    ipca_base: str,
    meses_faltando: list[str],
    ufs: dict[str, str],
    qualidade: dict,
    nomes_ibge: dict[str, str] | None = None,
) -> dict:
    periodos = sorted(agregados["periodo"].unique())
    topo = agregados[agregados["nivel"].isin(["BR", "UF"])]
    capitais = agregados[
        (agregados["nivel"] == "MUN")
        & agregados["codigo"].isin([f"{uf}|{nome}" for uf, nome in CAPITAIS.items()])
    ]
    nomes_ibge = nomes_ibge or {}

    def nome_bonito(codigo: str) -> str:
        """Nome oficial do IBGE quando casa; senão, o da ANP mesmo (nunca some da lista)."""
        uf, nome_anp = codigo.split("|", 1)
        return nomes_ibge.get(f"{uf}|{normalizar(nome_anp)}", nome_anp.title())

    resumo = {
        "atualizado_em": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "periodos": periodos,
        "meses_faltando": meses_faltando,
        "ipca": {"base": ipca_base, "fatores": {p: round(fatores_ipca[p], 5) for p in periodos}},
        "ufs": dict(sorted(ufs.items())),
        "capitais": CAPITAIS,
        "nomes_capitais": {f"{uf}|{n}": nome_bonito(f"{uf}|{n}") for uf, n in CAPITAIS.items()},
        "campos": CAMPOS,
        "series": _series(pd.concat([topo, capitais])),
        "qualidade": qualidade,
    }
    _gravar(destino / "resumo.json", resumo)

    municipios = agregados[agregados["nivel"] == "MUN"].copy()
    municipios["uf"] = municipios["codigo"].str.split("|").str[0]
    contagem = {}
    for uf, g in municipios.groupby("uf"):
        series = _series(g.assign(codigo=g["codigo"].str.split("|").str[1]))
        nomes = {anp: nome_bonito(f"{uf}|{anp}") for anp in series}
        _gravar(destino / "municipios" / f"{uf}.json", {"nomes": nomes, "series": series})
        contagem[uf] = len(series)
    return {"periodos": len(periodos), "municipios_por_uf": contagem}
