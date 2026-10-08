"""Junta os agregados e gera os JSONs que a página lê.

- site/data/resumo.json: Brasil e UFs desde 2004 com todas as estatísticas, capitais nos
  últimos 13 meses (carregado sempre).
- site/data/municipios/<UF>.json: mediana dos municípios de uma UF desde 2004 (carregado só
  quando a UF é escolhida).

Formato colunar para caber 20+ anos sem pesar: cada série é {"p": primeiro mês, campo: [valores]},
um valor por mês corrido a partir de "p" (null quando não há dado). Valores nominais; o fator
do IPCA de cada mês vai junto para a página converter em reais de hoje.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .agregar import CAPITAIS
from .malha import normalizar

CAMPOS = ["mediana", "p10", "p90", "minimo", "maximo", "postos"]
MESES_CAPITAIS = 13  # o gráfico de capitais usa o último mês; 13 dá a comparação com um ano antes


def carregar(pasta: Path) -> pd.DataFrame:
    arquivos = sorted(pasta.glob("*.csv"))
    if not arquivos:
        raise FileNotFoundError(f"Nenhum agregado em {pasta}")
    return pd.concat((pd.read_csv(a, dtype={"periodo": str}) for a in arquivos), ignore_index=True)


def _mes_seguinte(periodo: str) -> str:
    ano, mes = int(periodo[:4]), int(periodo[5:])
    return f"{ano + 1}-01" if mes == 12 else f"{ano}-{mes + 1:02d}"


def _serie(g: pd.DataFrame, campos: list[str]) -> dict:
    """{"p": primeiro mês, campo: [...]} com um valor por mês corrido (null nos buracos)."""
    g = g.set_index("periodo").sort_index()
    meses = [g.index[0]]
    while meses[-1] < g.index[-1]:
        meses.append(_mes_seguinte(meses[-1]))
    g = g.reindex(meses)
    saida: dict = {"p": meses[0]}
    for c in campos:
        col = g[c]
        saida[c] = [None if pd.isna(v) else (int(v) if c == "postos" else float(v)) for v in col]
    return saida


def _series(df: pd.DataFrame, campos: list[str] = CAMPOS) -> dict:
    """{codigo: {produto: série colunar}}."""
    saida: dict = {}
    for (codigo, produto), g in df.groupby(["codigo", "produto"]):
        saida.setdefault(codigo, {})[produto] = _serie(g, campos)
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
        & (agregados["periodo"] >= periodos[-MESES_CAPITAIS])
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
        "series": _series(pd.concat([topo, capitais])),
        "qualidade": qualidade,
    }
    _gravar(destino / "resumo.json", resumo)

    municipios = agregados[agregados["nivel"] == "MUN"].copy()
    municipios["uf"] = municipios["codigo"].str.split("|").str[0]
    contagem = {}
    for uf, g in municipios.groupby("uf"):
        series = _series(g.assign(codigo=g["codigo"].str.split("|").str[1]), ["mediana"])
        nomes = {anp: nome_bonito(f"{uf}|{anp}") for anp in series}
        _gravar(destino / "municipios" / f"{uf}.json", {"nomes": nomes, "series": series})
        contagem[uf] = len(series)
    return {"periodos": len(periodos), "municipios_por_uf": contagem}
