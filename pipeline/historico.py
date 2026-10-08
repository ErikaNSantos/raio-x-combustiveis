"""Agrega a base histórica (Parquet por ano, publicada na Release do portfólio) com DuckDB.

Mesmo método de `agregar.py`, agora em SQL e para a série inteira desde 2004:
1. preço do posto no mês = mediana das coletas daquele posto e produto;
2. estatísticas de Brasil, UF e município sobre os preços dos postos.

Incremental por ano: um ano só é baixado e reagregado quando a assinatura dele no
manifesto (linhas e arquivo de origem de cada mês) muda. Na prática, só o ano corrente
e, quando sai o semestral, o anterior.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

import duckdb
import pandas as pd

from .agregar import FAIXA_VALIDA, PRODUTOS

RELEASE = "https://github.com/ErikaNSantos/erikansantos.github.io/releases/download/base-combustiveis"


def _baixar(url: str, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "raio-x-combustiveis"})
    with urllib.request.urlopen(req, timeout=300) as resp, open(destino.with_suffix(".tmp"), "wb") as f:
        while bloco := resp.read(1 << 20):
            f.write(bloco)
    destino.with_suffix(".tmp").replace(destino)


def manifesto(base: Path) -> dict:
    caminho = base / "manifesto.json"
    _baixar(f"{RELEASE}/manifesto.json", caminho)
    return json.loads(caminho.read_text())


def assinatura(info_ano: dict) -> str:
    texto = json.dumps([info_ano["linhas"], info_ano["origem_por_mes"]], sort_keys=True)
    return hashlib.sha1(texto.encode()).hexdigest()[:12]


def _sql_produtos() -> str:
    casos = " ".join(f"WHEN '{anp}' THEN '{nosso}'" for anp, nosso in PRODUTOS.items())
    return f"CASE produto {casos} END"


def agregar_parquet(arquivo: Path) -> tuple[pd.DataFrame, dict]:
    """Agregados (mesmo formato de agregar.resumir) e qualidade por mês de um Parquet anual."""
    con = duckdb.connect()
    lo, hi = FAIXA_VALIDA
    lista = ", ".join(f"'{p}'" for p in PRODUTOS)
    con.execute(
        f"""
        CREATE TEMP TABLE coletas AS
        SELECT strftime(data, '%Y-%m') AS periodo, uf, municipio, cnpj, produto, preco_venda AS preco
        FROM read_parquet('{arquivo}')
        """
    )
    qualidade = {
        p: {"linhas": linhas, "fora_escopo": fora, "descartadas_faixa": desc}
        for p, linhas, fora, desc in con.execute(
            f"""
            SELECT periodo, count(*),
                   count(*) FILTER (produto NOT IN ({lista})),
                   count(*) FILTER (produto IN ({lista}) AND (preco IS NULL OR preco NOT BETWEEN {lo} AND {hi}))
            FROM coletas GROUP BY 1 ORDER BY 1
            """
        ).fetchall()
    }
    con.execute(
        f"""
        CREATE TEMP TABLE postos AS
        SELECT periodo, uf, municipio, cnpj, {_sql_produtos()} AS produto, median(preco) AS preco
        FROM coletas
        WHERE produto IN ({lista}) AND preco BETWEEN {lo} AND {hi}
        GROUP BY periodo, uf, municipio, cnpj, produto
        """
    )
    # quantile_cont = interpolação linear, a mesma do pandas.Series.quantile
    estat = """count(*) AS postos, quantile_cont(preco, 0.5) AS mediana,
               quantile_cont(preco, 0.1) AS p10, quantile_cont(preco, 0.9) AS p90,
               min(preco) AS minimo, max(preco) AS maximo"""
    df = con.execute(
        f"""
        SELECT periodo, 'BR' AS nivel, 'BR' AS codigo, produto, {estat} FROM postos GROUP BY periodo, produto
        UNION ALL
        SELECT periodo, 'UF', uf, produto, {estat} FROM postos GROUP BY periodo, uf, produto
        UNION ALL
        SELECT periodo, 'MUN', uf || '|' || municipio, produto, {estat} FROM postos GROUP BY periodo, uf, municipio, produto
        ORDER BY periodo, nivel, codigo, produto
        """
    ).df()
    df["postos"] = df["postos"].astype(int)
    for col in ("mediana", "p10", "p90", "minimo", "maximo"):
        df[col] = df[col].astype(float).round(3)
    return df, qualidade


def atualizar(base: Path, agregados: Path, versoes_path: Path) -> tuple[dict, dict]:
    """Reagrega os anos que mudaram. Devolve (manifesto, qualidade por mês)."""
    man = manifesto(base)
    versoes = json.loads(versoes_path.read_text()) if versoes_path.exists() else {}
    qualidade = versoes.get("qualidade", {})
    anos = versoes.get("anos", {})
    agregados.mkdir(parents=True, exist_ok=True)
    for ano, info in sorted(man["anos"].items()):
        sig = assinatura(info)
        destino = agregados / f"{ano}.csv"
        if anos.get(ano) == sig and destino.exists():
            continue
        print(f"- {ano}: baixando e agregando ({info['mb']} MB)", flush=True)
        parquet = base / f"combustiveis_{ano}.parquet"
        _baixar(f"{RELEASE}/combustiveis_{ano}.parquet", parquet)
        df, qual = agregar_parquet(parquet)
        df.to_csv(destino, index=False)
        qualidade = {p: q for p, q in qualidade.items() if not p.startswith(f"{ano}-")} | qual
        anos[ano] = sig
        parquet.unlink()
        versoes_path.write_text(
            json.dumps({"anos": dict(sorted(anos.items())), "qualidade": dict(sorted(qualidade.items()))}, indent=1)
        )
    return man, dict(sorted(qualidade.items()))
