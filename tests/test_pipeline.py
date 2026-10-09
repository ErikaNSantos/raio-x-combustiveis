from pathlib import Path

import pandas as pd
import pytest

from pipeline import fontes, ipca
from pipeline.agregar import agregar_arquivo, precos_por_posto

BASE = "https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/shpc/dsan"


def _html(*caminhos: str) -> str:
    return "".join(f'<a href="{BASE}/{c}">x</a>' for c in caminhos)


def test_extrai_todos_os_padroes_de_nome_da_anp():
    html = _html(
        "2023/precos-gasolina-etanol-01.csv",  # mês no fim
        "2026/01-dados-abertos-precos-diesel-gnv.csv",  # mês no começo
        "2026/06-dados-abertos-precos-2026-06-gasolina-etanol.csv",  # ano repetido no meio
        "2026/02-cados-abertos-preco-gasolina-etanol.csv",  # erro de digitação da ANP
        "2026/01-dados-abertos-precos-glp.csv",  # GLP (botijão), família própria
        "2026/01-dados-abertos-precos-oleo.csv",  # grupo desconhecido fica fora
    )
    chaves = [a.chave for a in fontes.extrair(html)]
    assert chaves == [
        "2023-01_gasolina-etanol",
        "2026-01_diesel-gnv",
        "2026-01_glp",
        "2026-02_gasolina-etanol",
        "2026-06_gasolina-etanol",
    ]


def test_ignora_links_duplicados_e_meses_invalidos():
    html = _html("2025/precos-gasolina-etanol-03.csv", "2025/precos-gasolina-etanol-03.csv", "2025/precos-gasolina-etanol-13.csv")
    assert [a.chave for a in fontes.extrair(html)] == ["2025-03_gasolina-etanol"]


def test_aponta_mes_sem_arquivo():
    html = _html("2026/03-dados-abertos-precos-gasolina-etanol.csv", "2026/05-dados-abertos-precos-gasolina-etanol.csv")
    assert fontes.meses_faltando(fontes.extrair(html)) == ["2026-04"]


CSV = """Regiao - Sigla;Estado - Sigla;Municipio;Revenda;CNPJ da Revenda;Nome da Rua;Numero Rua;Complemento;Bairro;Cep;Produto;Data da Coleta;Valor de Venda;Valor de Compra;Unidade de Medida;Bandeira
NE;BA;SALVADOR;POSTO A; 11.111.111/0001-11;RUA;1;;B;40000-000;GASOLINA;01/09/2026;6,00;;R$ / litro;X
NE;BA;SALVADOR;POSTO A; 11.111.111/0001-11;RUA;1;;B;40000-000;GASOLINA;08/09/2026;6,20;;R$ / litro;X
NE;BA;SALVADOR;POSTO A; 11.111.111/0001-11;RUA;1;;B;40000-000;GASOLINA;15/09/2026;6,40;;R$ / litro;X
NE;BA;SALVADOR;POSTO B; 22.222.222/0001-22;RUA;2;;B;40000-000;GASOLINA;01/09/2026;7,00;;R$ / litro;X
NE;BA;SALVADOR;POSTO B; 22.222.222/0001-22;RUA;2;;B;40000-000;GASOLINA;01/09/2026;59,90;;R$ / litro;X
NE;BA;SALVADOR;POSTO B; 22.222.222/0001-22;RUA;2;;B;40000-000;ETANOL;01/09/2026;4,50;;R$ / litro;X
SE;SP;SAO PAULO;POSTO C; 33.333.333/0001-33;RUA;3;;B;01000-000;GASOLINA;01/09/2026;5,80;;R$ / litro;X
"""


@pytest.fixture
def csv_anp(tmp_path: Path) -> Path:
    caminho = tmp_path / "anp.csv"
    caminho.write_bytes(CSV.encode("utf-8-sig"))
    return caminho


def test_posto_visitado_varias_vezes_conta_uma_vez(csv_anp):
    resumo, qualidade = agregar_arquivo(csv_anp, "2026-09")
    ssa = resumo[(resumo.codigo == "BA|SALVADOR") & (resumo.produto == "gasolina")].iloc[0]
    # Posto A: mediana de 6,00/6,20/6,40 = 6,20. Posto B: 7,00. Dois postos, não quatro coletas.
    assert ssa.postos == 2
    assert ssa.minimo == pytest.approx(6.20)
    assert ssa.maximo == pytest.approx(7.00)
    assert ssa.mediana == pytest.approx(6.60)


def test_descarta_preco_fora_da_faixa_e_conta(csv_anp):
    resumo, qualidade = agregar_arquivo(csv_anp, "2026-09")
    assert qualidade["descartadas_faixa"] == 1  # o 59,90 digitado errado
    assert resumo["maximo"].max() < 15


def test_niveis_brasil_uf_municipio(csv_anp):
    resumo, _ = agregar_arquivo(csv_anp, "2026-09")
    gasolina = resumo[resumo.produto == "gasolina"].set_index("codigo")
    assert gasolina.loc["BR", "postos"] == 3
    assert gasolina.loc["BA", "postos"] == 2
    assert gasolina.loc["SP|SAO PAULO", "mediana"] == pytest.approx(5.80)


def test_produto_desconhecido_fica_fora():
    df = pd.DataFrame({"uf": ["BA"], "municipio": ["X"], "cnpj": ["1"], "produto": ["QUEROSENE"], "preco": [5.0]})
    postos, qualidade = precos_por_posto(df)
    assert postos.empty and qualidade["fora_escopo"] == 1


def test_ipca_converte_para_o_ultimo_indice_e_deixa_meses_sem_indice_nominais():
    linhas = [{"D3C": "cabecalho"}, {"D3C": "202301", "V": "100"}, {"D3C": "202302", "V": "110"}, {"D3C": "202303", "V": "..."}]
    indice = ipca.parse(linhas)
    fatores, base = ipca.fatores(indice, ["2023-01", "2023-02", "2023-03"])
    assert base == "2023-02"
    assert fatores == {"2023-01": pytest.approx(1.1), "2023-02": 1.0, "2023-03": 1.0}


def test_mapa_orienta_aneis_como_o_d3_espera():
    from pipeline.malha import _area, _orientar

    anti_horario = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
    externo, = _orientar([anti_horario])
    assert _area(externo) < 0  # externo no sentido horário
    externo, buraco = _orientar([anti_horario[::-1], anti_horario[::-1]])
    assert _area(externo) < 0 and _area(buraco) > 0


def test_nome_da_anp_casa_com_o_do_ibge():
    from pipeline.malha import normalizar

    assert normalizar("São Luís") == "SAO LUIS"
    assert normalizar("Alta Floresta D'Oeste") == "ALTA FLORESTA D OESTE"
    assert normalizar("Embu-Guaçu") == "EMBU GUACU"


def _ancora(caminho: str, texto: str) -> str:
    return f'<a href="https://www.gov.br/anp/x/shpc/dsas/ca/{caminho}">{texto}</a>'


def test_semestral_le_ano_do_texto_quando_o_nome_nao_diz():
    html = (
        _ancora("ca-2021-02.csv", "2º semestre de 2021")
        + _ancora("precos-semestrais-ca.zip", "1º semestre de 2022")  # nome sem ano: caso real da ANP
        + _ancora("ca-2022-02.zip", "<span>2º semestre de 2022</span>")
    )
    arquivos = fontes.extrair_semestrais(html)
    assert [a.chave for a in arquivos] == ["2021-07_semestral", "2022-01_semestral", "2022-07_semestral"]
    assert fontes.meses_faltando([fontes.Arquivo(a.ano, m, "x", "") for a in arquivos for m in range(a.mes, a.mes + 6)]) == []


def test_plano_prefere_semestral_e_usa_mensal_so_no_que_falta():
    from base.construir import plano

    semestral = fontes.Arquivo(2026, 1, "semestral", "s")
    mensais = [fontes.Arquivo(2026, m, "gasolina-etanol", f"m{m}") for m in (3, 5, 7)]
    por_mes = plano([semestral], mensais)
    assert [a.url for a in por_mes["2026-03"]] == ["s"]  # coberto pelo semestral: mensal ignorado
    assert [a.url for a in por_mes["2026-04"]] == ["s"]  # mês que falta nos mensais vem do semestral
    assert [a.url for a in por_mes["2026-07"]] == ["m7"]  # depois do último semestral: mensal


def test_agregacao_em_sql_bate_com_a_do_pandas(csv_anp, tmp_path):
    import duckdb

    from base.construir import SELECT_PADRAO, _lit
    from pipeline.historico import agregar_parquet

    parquet = tmp_path / "ano.parquet"
    duckdb.execute(f"COPY ({SELECT_PADRAO.format(arquivo=_lit(str(csv_anp)), codificacao="'utf-8'")}) TO {_lit(str(parquet))} (FORMAT parquet)")
    sql, qual_sql = agregar_parquet(parquet)
    pd_, qual_pd = agregar_arquivo(csv_anp, "2026-09")
    chaves = ["periodo", "nivel", "codigo", "produto"]
    pd.testing.assert_frame_equal(
        sql.sort_values(chaves).reset_index(drop=True),
        pd_.sort_values(chaves).reset_index(drop=True),
        check_dtype=False,
    )
    assert qual_sql == {"2026-09": qual_pd}


def test_serie_colunar_deixa_buraco_no_mes_sem_dado():
    from pipeline.publicar import _serie

    g = pd.DataFrame({"periodo": ["2026-03", "2026-05"], "mediana": [6.5, 6.7], "postos": [10, 12]})
    assert _serie(g, ["mediana", "postos"]) == {"p": "2026-03", "mediana": [6.5, None, 6.7], "postos": [10, None, 12]}


def test_le_csv_em_latin1(tmp_path):
    import duckdb

    from base.construir import SELECT_PADRAO, _lit, codificacao

    csv = tmp_path / "latin1.csv"
    csv.write_bytes(CSV.replace("SAO PAULO", "SÃO PAULO").replace("\n", "\r\n").encode("latin-1"))
    assert codificacao(csv) == "latin-1"
    linhas = duckdb.execute(SELECT_PADRAO.format(arquivo=_lit(str(csv)), codificacao=_lit(codificacao(csv)))).fetchall()
    assert len(linhas) == 7 and linhas[-1][3] == "SÃO PAULO"
