"""Monta a base histórica de preços de combustíveis da ANP (2004 em diante) com DuckDB.

    python -m base.construir --saida base/parquet            # anos novos ou cujos arquivos mudaram
    python -m base.construir --saida base/parquet --refazer  # todos os anos, do zero
    python -m base.construir --saida base/parquet --anos 2026  # só os anos pedidos

Um ano já presente em `manifesto.json` e montado a partir dos mesmos arquivos é pulado,
então uma execução interrompida continua de onde parou. Se um ano falha (o gov.br corta
conexões), os outros seguem e o comando sai com erro no fim.

Fontes, escolhidas mês a mês:
- arquivos semestrais (`dsas/ca`), o consolidado oficial, sempre que cobrem o mês;
- arquivos mensais (`dsan`) só para os meses que nenhum semestral cobre ainda.
Assim nenhum mês entra duas vezes, e meses que faltam nos mensais (abril/2026) vêm do semestral.

Saída: um Parquet por ano (`combustiveis_AAAA.parquet`, ZSTD) com uma linha por coleta,
mais `manifesto.json` dizendo de qual arquivo veio cada mês e quantas linhas entraram.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from collections import defaultdict
from pathlib import Path

import duckdb

from pipeline import fontes

# Uma coleta, já tipada. Nomes em português e sem acento, para quem consultar não tropeçar em aspas.
SELECT_PADRAO = """
SELECT
    strptime(trim("Data da Coleta"), '%d/%m/%Y')::DATE                                 AS data,
    upper(trim("Regiao - Sigla"))                                                      AS regiao,
    upper(trim("Estado - Sigla"))                                                      AS uf,
    upper(trim("Municipio"))                                                           AS municipio,
    trim("Revenda")                                                                    AS revenda,
    trim("CNPJ da Revenda")                                                            AS cnpj,
    trim("Bairro")                                                                     AS bairro,
    trim("Cep")                                                                        AS cep,
    upper(trim("Produto"))                                                             AS produto,
    TRY_CAST(replace(trim("Valor de Venda"), ',', '.') AS DOUBLE)                      AS preco_venda,
    TRY_CAST(replace(nullif(trim("Valor de Compra"), ''), ',', '.') AS DOUBLE)         AS preco_compra,
    trim("Unidade de Medida")                                                          AS unidade,
    upper(trim("Bandeira"))                                                            AS bandeira
FROM read_csv({arquivo}, delim=';', header=true, all_varchar=true, quote='"')
"""


def _lit(texto: str) -> str:
    """Literal SQL. Os caminhos são gerados por este script, mas escapar não custa nada."""
    return "'" + texto.replace("'", "''") + "'"


def baixar(url: str, destino: Path, tentativas: int = 12) -> None:
    """curl com retomada (-C -) e espera crescente: o gov.br corta downloads grandes no meio."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    for i in range(tentativas):
        if i:
            time.sleep(min(5 * 2 ** (i - 1), 120))
        r = subprocess.run(
            ["curl", "-sS", "-L", "-C", "-", "--retry", "3", "--max-time", "900", "-o", str(destino), url],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            return
        print(f"    download interrompido ({r.stderr.strip()[:80]}); retomando", flush=True)
    raise RuntimeError(f"Não foi possível baixar {url}")


def csv_de(caminho: Path, pasta: Path) -> Path:
    """Os semestrais mais novos vêm em .zip com um único CSV dentro."""
    if caminho.suffix.lower() != ".zip":
        return caminho
    with zipfile.ZipFile(caminho) as z:
        nomes = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(nomes) != 1:
            raise ValueError(f"{caminho.name}: esperava 1 CSV no zip, achei {nomes}")
        # O nome interno vem em latin-1 ("Pre\x87os semestrais..."); usa o nome do zip.
        destino = pasta / (caminho.stem + ".csv")
        with z.open(nomes[0]) as origem, open(destino, "wb") as saida:
            shutil.copyfileobj(origem, saida)
    caminho.unlink()
    return destino


def meses_do(arq: fontes.Arquivo) -> list[str]:
    inicio = arq.mes
    fim = arq.mes + (5 if arq.grupo == "semestral" else 0)
    return [f"{arq.ano}-{m:02d}" for m in range(inicio, fim + 1)]


def plano(semestrais: list[fontes.Arquivo], mensais: list[fontes.Arquivo]) -> dict[str, list[fontes.Arquivo]]:
    """{mês: [arquivos]}. Semestral quando existe; senão os mensais daquele mês."""
    cobertos = {m for a in semestrais for m in meses_do(a)}
    por_mes: dict[str, list[fontes.Arquivo]] = defaultdict(list)
    for a in semestrais:
        for m in meses_do(a):
            por_mes[m].append(a)
    for a in mensais:
        if a.periodo not in cobertos:
            por_mes[a.periodo].append(a)
    return dict(sorted(por_mes.items()))


def construir(saida: Path, anos: set[int] | None = None, manter: Path | None = None, refazer: bool = False) -> tuple[dict, list[int]]:
    html = fontes.baixar_pagina()
    semestrais = fontes.extrair_semestrais(html)
    mensais = fontes.extrair(html)
    por_mes = plano(semestrais, mensais)
    arquivos_por_ano: dict[int, list[fontes.Arquivo]] = defaultdict(list)
    for mes, arqs in por_mes.items():
        for a in arqs:
            if a not in arquivos_por_ano[int(mes[:4])]:
                arquivos_por_ano[int(mes[:4])].append(a)

    saida.mkdir(parents=True, exist_ok=True)
    manifesto_path = saida / "manifesto.json"
    manifesto = json.loads(manifesto_path.read_text()) if manifesto_path.exists() else {"anos": {}}
    con = duckdb.connect()
    con.execute("SET preserve_insertion_order = false")

    falhas: list[int] = []
    for ano in sorted(arquivos_por_ano):
        if anos and ano not in anos:
            continue
        nomes = sorted(a.url.rsplit("/", 1)[1] for a in arquivos_por_ano[ano])
        anterior = manifesto["anos"].get(str(ano))
        if not refazer and not anos and anterior and anterior.get("arquivos", sorted(set(anterior["origem_por_mes"].values()))) == nomes:
            continue
        try:
            _construir_ano(con, ano, arquivos_por_ano[ano], por_mes, saida, manifesto, manter, nomes)
        except Exception as erro:  # um ano ruim não derruba os outros
            print(f"  {ano} falhou: {erro}", flush=True)
            falhas.append(ano)
            continue
        manifesto_path.write_text(json.dumps(manifesto, indent=1, ensure_ascii=False))

    # Período e buracos pelos meses que têm dados, não pelos que os arquivos prometem.
    todos = sorted(m for info in manifesto["anos"].values() for m in info["origem_por_mes"])
    manifesto["periodo"] = [todos[0], todos[-1]] if todos else []
    manifesto["meses_sem_dados"] = fontes.meses_faltando(
        [fontes.Arquivo(int(m[:4]), int(m[5:]), "x", "") for m in todos]
    )
    manifesto.pop("meses_sem_arquivo", None)
    manifesto["anos"] = dict(sorted(manifesto["anos"].items()))
    manifesto_path.write_text(json.dumps(manifesto, indent=1, ensure_ascii=False))
    return manifesto, falhas


def _construir_ano(con, ano, arquivos, por_mes, saida, manifesto, manter, nomes) -> None:
    """Baixa os arquivos de um ano, grava combustiveis_AAAA.parquet e a entrada do ano no manifesto."""
    meses_do_ano = sorted(m for m in por_mes if m.startswith(f"{ano}-"))
    print(f"{ano}: {len(arquivos)} arquivo(s)", flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        partes = []
        origem_por_mes = {}
        for i, arq in enumerate(arquivos):
            nome = arq.url.rsplit("/", 1)[1]
            bruto = (manter / nome) if manter else tmp / nome
            if not bruto.exists():
                print(f"  baixando {nome}", flush=True)
                baixar(arq.url, bruto)
            csv = csv_de(bruto, bruto.parent)
            # Só os meses deste ano que o plano atribuiu a este arquivo
            meses = [m for m in meses_do_ano if arq in por_mes[m]]
            parte = tmp / f"parte_{i}.parquet"
            lista_meses = ", ".join(_lit(m) for m in meses)
            con.execute(
                f"""COPY (
                    SELECT * FROM ({SELECT_PADRAO.format(arquivo=_lit(str(csv)))})
                    WHERE strftime(data, '%Y-%m') IN ({lista_meses})
                ) TO {_lit(str(parte))} (FORMAT parquet, COMPRESSION zstd)"""
            )
            partes.append(str(parte))
            # Origem só dos meses que de fato vieram no arquivo (a série começa em maio/2004).
            for (m,) in con.execute(
                f"SELECT DISTINCT strftime(data, '%Y-%m') FROM read_parquet({_lit(str(parte))})"
            ).fetchall():
                origem_por_mes[m] = nome
            if not manter:
                csv.unlink(missing_ok=True)
        destino = saida / f"combustiveis_{ano}.parquet"
        lista_partes = "[" + ", ".join(_lit(x) for x in partes) + "]"
        con.execute(
            f"""COPY (SELECT * FROM read_parquet({lista_partes}) ORDER BY data, uf, municipio, cnpj, produto)
                TO {_lit(str(destino))} (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 250000)"""
        )
    linhas, n_meses, sem_preco = con.execute(
        f"SELECT count(*), count(DISTINCT strftime(data, '%Y-%m')), count(*) FILTER (preco_venda IS NULL) FROM read_parquet({_lit(str(destino))})"
    ).fetchone()
    produtos = dict(
        con.execute(
            f"SELECT produto, count(*) FROM read_parquet({_lit(str(destino))}) GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
    )
    manifesto["anos"][str(ano)] = {
        "linhas": linhas,
        "arquivos": nomes,
        "produtos": produtos,
        "meses": n_meses,
        "sem_preco_venda": sem_preco,
        "origem_por_mes": dict(sorted(origem_por_mes.items())),
        "mb": round(destino.stat().st_size / 1e6, 1),
    }
    print(f"  {linhas:,} linhas, {n_meses} meses, {destino.stat().st_size / 1e6:.1f} MB", flush=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--saida", type=Path, default=Path("base/parquet"))
    p.add_argument("--anos", type=int, nargs="*", help="só estes anos (padrão: todos)")
    p.add_argument("--manter-brutos", type=Path, help="pasta para guardar os CSVs baixados e reaproveitar")
    p.add_argument("--refazer", action="store_true", help="refaz também os anos que já estão no manifesto")
    a = p.parse_args(argv)
    _, falhas = construir(a.saida, set(a.anos) if a.anos else None, a.manter_brutos, a.refazer)
    if falhas:
        print(f"Anos que falharam (rode de novo para continuar): {falhas}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
