"""Roda o pipeline completo: `python -m pipeline.run`.

Lê a base histórica da ANP (Parquet por ano, desde 2004), montada por `base/construir.py`
e publicada na Release `base-combustiveis` do portfólio. Só os anos que mudaram são
baixados e reagregados; o agregado de cada ano fica versionado em data/agregados/.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from . import historico, ipca, malha, salario
from .publicar import carregar, publicar

RAIZ = Path(__file__).resolve().parent.parent
AGREGADOS = RAIZ / "data" / "agregados"
VERSOES = RAIZ / "data" / "versoes.json"
SITE_DATA = RAIZ / "site" / "data"


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)

    print("Lendo o manifesto da base histórica...", flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        manifestos, qualidade = historico.atualizar(Path(tmp), AGREGADOS, VERSOES)
    for familia, man in manifestos.items():
        print(f"{familia}: {man['periodo'][0]} a {man['periodo'][1]}; sem dados: {man.get('meses_sem_dados') or 'nenhum'}")
    faltando = {familia: man.get("meses_sem_dados", []) for familia, man in manifestos.items()}

    print("IPCA e malha do IBGE...", flush=True)
    agregados = carregar(AGREGADOS)
    indice = ipca.baixar()
    fatores, base = ipca.fatores(indice, sorted(agregados["periodo"].unique()))
    ufs = malha.gerar(SITE_DATA / "ufs.geojson")

    nomes = malha.nomes_municipios()
    minimo = salario.baixar()
    periodos = sorted(agregados["periodo"].unique())
    extras = {
        "meses_faltando_por_familia": faltando,
        "salario_minimo": {p: minimo[p] for p in periodos if p in minimo},
    }
    info = publicar(agregados, SITE_DATA, fatores, base, faltando["combustiveis"], ufs, qualidade, nomes, extras)
    print(f"Publicado: {info['periodos']} meses, {sum(info['municipios_por_uf'].values())} municípios; IPCA até {base}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
