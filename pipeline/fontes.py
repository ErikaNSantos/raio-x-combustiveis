"""Descobre os arquivos mensais da ANP a partir da página de dados abertos.

A ANP não segue um padrão fixo de nome: já houve `precos-gasolina-etanol-01.csv`,
`01-dados-abertos-precos-gasolina-etanol.csv`, `06-dados-abertos-precos-2026-06-...`
e até `02-cados-abertos-preco-...` (com erro de digitação). Por isso a URL nunca é
montada: os links são lidos da página e classificados pelo caminho.
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass

PAGINA = (
    "https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/"
    "serie-historica-de-precos-de-combustiveis"
)

# Grupos de arquivo que entram no projeto. GLP fica de fora na v1.
GRUPOS = {
    "gasolina-etanol": ("gasolina", "etanol"),
    "diesel-gnv": ("diesel", "gnv"),
}


@dataclass(frozen=True, order=True)
class Arquivo:
    ano: int
    mes: int
    grupo: str
    url: str

    @property
    def periodo(self) -> str:
        return f"{self.ano}-{self.mes:02d}"

    @property
    def chave(self) -> str:
        return f"{self.periodo}_{self.grupo}"


_LINK = re.compile(r'href="([^"]+/shpc/dsan/(\d{4})/([^"/]+\.csv))"', re.IGNORECASE)


def _mes(nome: str) -> int | None:
    """Mês pelo prefixo (`06-dados...`) ou pelo sufixo (`...-etanol-06.csv`)."""
    m = re.match(r"(\d{2})-", nome) or re.search(r"-(\d{2})\.csv$", nome, re.IGNORECASE)
    if not m:
        return None
    mes = int(m.group(1))
    return mes if 1 <= mes <= 12 else None


def _grupo(nome: str) -> str | None:
    nome = nome.lower()
    for grupo, termos in GRUPOS.items():
        if all(t in nome for t in termos):
            return grupo
    return None


def extrair(html: str) -> list[Arquivo]:
    """Lista os arquivos mensais (pasta `dsan`) presentes no HTML, sem duplicatas."""
    vistos: dict[str, Arquivo] = {}
    for url, ano, nome in _LINK.findall(html):
        mes, grupo = _mes(nome), _grupo(nome)
        if mes is None or grupo is None:
            continue
        arq = Arquivo(int(ano), mes, grupo, url)
        vistos.setdefault(arq.chave, arq)
    return sorted(vistos.values())


def meses_faltando(arquivos: list[Arquivo]) -> list[str]:
    """Meses sem arquivo entre o primeiro e o último publicados (ex.: abril/2026)."""
    if not arquivos:
        return []
    periodos = {a.periodo for a in arquivos}
    ano, mes = arquivos[0].ano, arquivos[0].mes
    fim = (arquivos[-1].ano, arquivos[-1].mes)
    faltando = []
    while (ano, mes) <= fim:
        if f"{ano}-{mes:02d}" not in periodos:
            faltando.append(f"{ano}-{mes:02d}")
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return faltando


def baixar_pagina(url: str = PAGINA) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "raio-x-combustiveis"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


_ANCORA_SEMESTRAL = re.compile(r'<a[^>]+href="([^"]+/shpc/dsas/ca/[^"]+\.(?:csv|zip))"[^>]*>(.*?)</a>', re.IGNORECASE | re.S)
_TEXTO_SEMESTRE = re.compile(r"([12])\s*º\s*semestre\s+de\s+(\d{4})", re.IGNORECASE)
_NOME_SEMESTRE = re.compile(r"ca-(\d{4})-0([12])\.", re.IGNORECASE)


def extrair_semestrais(html: str) -> list[Arquivo]:
    """Arquivos semestrais de combustíveis automotivos (pasta `dsas/ca`), de 2004 em diante.

    O ano e o semestre vêm do texto do link ("1º semestre de 2022"): o nome do arquivo nem
    sempre diz (o 1º semestre de 2022 foi publicado como `precos-semestrais-ca.zip`).
    O nome `ca-AAAA-0S` só é usado quando o texto não ajuda. O semestre vira `mes` 1 ou 7.
    """
    vistos: dict[str, Arquivo] = {}
    for url, ancora in _ANCORA_SEMESTRAL.findall(html):
        texto = re.sub(r"<[^>]+>", " ", ancora)
        m = _TEXTO_SEMESTRE.search(texto)
        if m:
            semestre, ano = m.group(1), m.group(2)
        else:
            n = _NOME_SEMESTRE.search(url.rsplit("/", 1)[-1])
            if not n:
                continue
            ano, semestre = n.group(1), n.group(2)
        arq = Arquivo(int(ano), 1 if semestre == "1" else 7, "semestral", url)
        vistos.setdefault(arq.chave, arq)
    return sorted(vistos.values())
