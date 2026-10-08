"""Roda o pipeline completo: `python -m pipeline.run`.

Incremental: só baixa e processa os meses que ainda não têm agregado em data/agregados/.
O CSV bruto é apagado logo depois de agregado (cada um tem ~9 MB), a não ser com --manter-brutos.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

from . import fontes, ipca, malha
from .agregar import agregar_arquivo
from .publicar import carregar, publicar

RAIZ = Path(__file__).resolve().parent.parent
BRUTOS = RAIZ / "data" / "brutos"
AGREGADOS = RAIZ / "data" / "agregados"
QUALIDADE = RAIZ / "data" / "qualidade.json"
SITE_DATA = RAIZ / "site" / "data"
INICIO = (2023, 1)  # primeiro mês com arquivos mensais na ANP


def baixar(url: str, destino: Path, tentativas: int = 4) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "raio-x-combustiveis"})
            with urllib.request.urlopen(req, timeout=180) as resp, open(destino, "wb") as f:
                while bloco := resp.read(1 << 20):
                    f.write(bloco)
            return
        except OSError as erro:  # rede do gov.br oscila: tenta de novo com espera crescente
            if i == tentativas - 1:
                raise
            espera = 2 ** (i + 1)
            print(f"  falhou ({erro}); nova tentativa em {espera}s", flush=True)
            time.sleep(espera)


def main(argv: list[str] | None = None) -> int:
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--manter-brutos", action="store_true", help="não apaga os CSVs baixados")
    args.add_argument("--limite", type=int, default=0, help="processa no máximo N arquivos novos (teste)")
    opts = args.parse_args(argv)

    print("Lendo a página da ANP...", flush=True)
    arquivos = [a for a in fontes.extrair(fontes.baixar_pagina()) if (a.ano, a.mes) >= INICIO]
    faltando = fontes.meses_faltando(arquivos)
    print(f"{len(arquivos)} arquivos de {arquivos[0].periodo} a {arquivos[-1].periodo}; sem arquivo: {faltando or 'nenhum'}")

    qualidade = json.loads(QUALIDADE.read_text()) if QUALIDADE.exists() else {}
    novos = [a for a in arquivos if not (AGREGADOS / f"{a.chave}.csv").exists()]
    if opts.limite:
        novos = novos[: opts.limite]
    print(f"{len(novos)} arquivo(s) novo(s) para processar")

    for arq in novos:
        bruto = BRUTOS / f"{arq.chave}.csv"
        print(f"- {arq.chave}", flush=True)
        if not bruto.exists():
            baixar(arq.url, bruto)
        resumo, qual = agregar_arquivo(bruto, arq.periodo)
        AGREGADOS.mkdir(parents=True, exist_ok=True)
        resumo.to_csv(AGREGADOS / f"{arq.chave}.csv", index=False)
        qualidade[arq.chave] = qual
        QUALIDADE.write_text(json.dumps(dict(sorted(qualidade.items())), indent=1))
        if not opts.manter_brutos:
            bruto.unlink()

    print("IPCA e malha do IBGE...", flush=True)
    agregados = carregar(AGREGADOS)
    indice = ipca.baixar()
    fatores, base = ipca.fatores(indice, sorted(agregados["periodo"].unique()))
    ufs = malha.gerar(SITE_DATA / "ufs.geojson")

    nomes = malha.nomes_municipios()
    info = publicar(agregados, SITE_DATA, fatores, base, faltando, ufs, qualidade, nomes)
    print(f"Publicado: {info['periodos']} meses, {sum(info['municipios_por_uf'].values())} municípios; IPCA até {base}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
