"""Transforma um CSV mensal da ANP em estatísticas por Brasil, UF e município.

Método, em duas etapas:
1. Preço do posto no mês = mediana das coletas daquele posto e produto. Assim um
   posto visitado 5 vezes não pesa 5 vezes mais que um visitado uma vez.
2. Estatísticas do recorte (Brasil, UF ou município) sobre os preços dos postos.

Cada arquivo é um mês completo e independente, então o resultado de cada um é
gravado à parte em data/agregados/ e o pipeline só processa meses novos.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

PRODUTOS = {
    "GASOLINA": "gasolina",
    "GASOLINA ADITIVADA": "gasolina_aditivada",
    "ETANOL": "etanol",
    "DIESEL": "diesel",
    "DIESEL S10": "diesel_s10",
    "GNV": "gnv",
    "GLP": "glp",  # botijão de 13 kg, em R$ por botijão
}

# Faixa plausível de preço (R$/litro ou R$/m³), de 2004 (etanol a R$ 0,90) até hoje. Fora dela é erro de digitação,
# como 0,00 ou 59,90 no lugar de 5,99. Linhas descartadas são contadas, não escondidas.
FAIXA_VALIDA = (0.3, 15.0)
# O botijão é vendido por unidade: R$ 30 em 2004, perto de R$ 130 hoje.
FAIXAS = {"glp": (10.0, 400.0)}


def faixa(produto: str) -> tuple[float, float]:
    """Faixa válida de preço para um produto (nome nosso, ex.: 'glp')."""
    return FAIXAS.get(produto, FAIXA_VALIDA)

CAPITAIS = {
    "AC": "RIO BRANCO", "AL": "MACEIO", "AP": "MACAPA", "AM": "MANAUS", "BA": "SALVADOR",
    "CE": "FORTALEZA", "DF": "BRASILIA", "ES": "VITORIA", "GO": "GOIANIA", "MA": "SAO LUIS",
    "MT": "CUIABA", "MS": "CAMPO GRANDE", "MG": "BELO HORIZONTE", "PA": "BELEM",
    "PB": "JOAO PESSOA", "PR": "CURITIBA", "PE": "RECIFE", "PI": "TERESINA",
    "RJ": "RIO DE JANEIRO", "RN": "NATAL", "RS": "PORTO ALEGRE", "RO": "PORTO VELHO",
    "RR": "BOA VISTA", "SC": "FLORIANOPOLIS", "SP": "SAO PAULO", "SE": "ARACAJU", "TO": "PALMAS",
}

COLUNAS = {
    "Estado - Sigla": "uf",
    "Municipio": "municipio",
    "CNPJ da Revenda": "cnpj",
    "Produto": "produto",
    "Valor de Venda": "preco",
}


def ler_csv(caminho: Path) -> pd.DataFrame:
    """Lê o CSV da ANP (UTF-8 com BOM; latin-1 como reserva) só com as colunas usadas."""
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            df = pd.read_csv(caminho, sep=";", encoding=encoding, dtype=str)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - nenhum encoding funcionou
        raise ValueError(f"Encoding desconhecido: {caminho}")
    df.columns = [c.strip() for c in df.columns]
    faltando = set(COLUNAS) - set(df.columns)
    if faltando:
        raise ValueError(f"{caminho.name}: colunas ausentes {sorted(faltando)}")
    df = df[list(COLUNAS)].rename(columns=COLUNAS)
    for col in ("uf", "municipio", "cnpj", "produto"):
        df[col] = df[col].str.strip().str.upper()
    df["preco"] = pd.to_numeric(df["preco"].str.replace(",", ".", regex=False), errors="coerce")
    return df


def precos_por_posto(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Uma linha por posto e produto, com o preço mediano do posto no mês."""
    total = len(df)
    df = df[df["produto"].isin(PRODUTOS)]
    fora_escopo = total - len(df)
    df = df.assign(produto=df["produto"].map(PRODUTOS))
    limites = df["produto"].map(faixa)
    validos = (df["preco"] >= limites.str[0]) & (df["preco"] <= limites.str[1])
    descartadas = int((~validos).sum())
    df = df[validos]
    postos = df.groupby(["uf", "municipio", "cnpj", "produto"], as_index=False).agg(
        preco=("preco", "median"), coletas=("preco", "size")
    )
    qualidade = {"linhas": total, "fora_escopo": fora_escopo, "descartadas_faixa": descartadas}
    return postos, qualidade


def _estatisticas(grupo: pd.Series) -> pd.Series:
    return pd.Series(
        {
            "postos": int(grupo.size),
            "mediana": grupo.median(),
            "p10": grupo.quantile(0.10),
            "p90": grupo.quantile(0.90),
            "minimo": grupo.min(),
            "maximo": grupo.max(),
        }
    )


def resumir(postos: pd.DataFrame, periodo: str) -> pd.DataFrame:
    """Estatísticas em três níveis: BR, UF e MUN (código do município = 'UF|NOME')."""
    niveis = []
    for nivel, chaves in (("BR", []), ("UF", ["uf"]), ("MUN", ["uf", "municipio"])):
        g = postos.groupby(chaves + ["produto"])["preco"].apply(_estatisticas).unstack().reset_index()
        if nivel == "BR":
            g["codigo"] = "BR"
        elif nivel == "UF":
            g["codigo"] = g["uf"]
        else:
            g["codigo"] = g["uf"] + "|" + g["municipio"]
        g["nivel"] = nivel
        niveis.append(g[["nivel", "codigo", "produto", "postos", "mediana", "p10", "p90", "minimo", "maximo"]])
    out = pd.concat(niveis, ignore_index=True)
    out.insert(0, "periodo", periodo)
    out["postos"] = out["postos"].astype(int)
    for col in ("mediana", "p10", "p90", "minimo", "maximo"):
        out[col] = out[col].astype(float).round(3)
    return out


def agregar_arquivo(caminho: Path, periodo: str) -> tuple[pd.DataFrame, dict]:
    postos, qualidade = precos_por_posto(ler_csv(caminho))
    return resumir(postos, periodo), qualidade
