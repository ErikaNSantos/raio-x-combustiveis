# Raio-X dos Combustíveis

Quanto custa abastecer em cada estado, capital e município pesquisado pela ANP desde 2004, quando o etanol compensa mais que a gasolina e quanto o preço muda dentro da mesma cidade. Com os preços corrigidos pela inflação.

**Página:** https://erikansantos.github.io/raio-x-combustiveis/

**Base de dados:** todas as coletas da ANP desde 2004 em Parquet, um arquivo por ano, na [Release `base-combustiveis`](https://github.com/ErikaNSantos/erikansantos.github.io/releases/tag/base-combustiveis). Dá para consultar direto do DuckDB, sem baixar nada:

```sql
INSTALL httpfs; LOAD httpfs;
SELECT uf, median(preco_venda)
FROM 'https://github.com/ErikaNSantos/erikansantos.github.io/releases/download/base-combustiveis/combustiveis_2024.parquet'
WHERE produto = 'GASOLINA'
GROUP BY uf ORDER BY 2 DESC;
```

*English: monthly dashboard of Brazilian fuel prices (gasoline, ethanol, diesel) by state, capital and city since 2004, built from ANP open data and deflated by IPCA. Every ANP price survey record is consolidated with DuckDB into yearly Parquet files published as a GitHub Release; a weekly GitHub Actions job re-aggregates only the years that changed and publishes a static page.*

## Como funciona

```
página da ANP ──► base/construir.py      acha os links (semestrais e mensais), baixa e grava
                                         um Parquet por ano com DuckDB  ──► Release base-combustiveis
                  pipeline/historico.py  baixa só os anos que mudaram e agrega em SQL:
                                         preço por posto → mediana por município, UF e Brasil
IBGE (SIDRA) ───► pipeline/ipca.py       IPCA para corrigir pela inflação
IBGE (malhas) ──► pipeline/malha.py      contorno das UFs para o mapa
                  pipeline/publicar.py   JSONs colunares em site/data/
GitHub Actions ─► segunda, 6h: atualiza a base (workflow no repositório do portfólio)
                  segunda, 9h: reagrega, versiona os dados novos e publica o site
```

## Decisões que valem explicar

- **Os links não são montados, são lidos da página.** A ANP muda o padrão do nome do arquivo sem aviso (`precos-gasolina-etanol-01.csv`, `01-dados-abertos-precos-...`, `06-dados-abertos-precos-2026-06-...`) e já publicou um com erro de digitação (`02-cados-abertos-preco-...`). Os testes cobrem todos esses casos.
- **Um posto, um voto.** O preço de cada posto no mês é a mediana das coletas dele; as estatísticas de cidade, estado e Brasil saem desses preços. Sem isso, um posto visitado quatro vezes pesaria quatro vezes mais, e a diferença entre o mais barato e o mais caro de uma cidade sairia inflada por coletas de datas diferentes.
- **Uma base só, desde 2004.** A ANP publica a série em dois formatos: arquivos semestrais consolidados (2004 em diante) e arquivos mensais (2023 em diante). A base usa o semestral sempre que ele cobre o mês e o mensal só nos meses ainda não consolidados, então nenhum mês entra duas vezes. Nos meses em que os dois existem, os números batem exatamente; abril de 2026, que não saiu no mensal, veio do semestral. O `manifesto.json` da Release diz de qual arquivo veio cada mês.
- **Parquet por ano, fora do git.** São 25,5 milhões de coletas (maio de 2004 a setembro de 2026) em vários GB de CSV; em Parquet com ZSTD a base inteira tem 197 MB, em 23 arquivos, e fica numa Release sem inchar o histórico do repositório.
- **Incremental.** Cada ano agregado vira um CSV pequeno em `data/agregados/` (versionado), com a assinatura do ano em `data/versoes.json`. Uma atualização semanal reagrega só o ano corrente.
- **Mesmo método, testado.** A agregação em SQL é comparada nos testes com a versão original em pandas, e as duas dão o mesmo resultado.
- **Meses sem dados aparecem como buraco**, não como linha ligando os vizinhos. A ANP não tem coletas em junho de 2014 nem em setembro de 2020 (e os meses vizinhos têm poucas).
- **A fonte tem surpresas.** O 1º semestre de 2022 foi publicado sem ano no nome do arquivo (o ano vem do texto do link), o 2º semestre de 2021 veio em latin-1 em vez de UTF-8, e o gov.br derruba downloads grandes no meio (o download retoma de onde parou).
- **Página sem build e sem dependência externa em tempo real.** HTML, CSS e JS puro, com o d3 e o mapa salvos no próprio repositório.

## Limitações

- A ANP pesquisa uma amostra (hoje cerca de 400 municípios e 6 mil postos por mês), não todos, e o tamanho dela mudou ao longo dos anos. O diesel S10 só entra em 2012.
- O preço de compra pelo posto só vem preenchido até cerca de 2020; a base guarda a coluna, mas a página não calcula margem.
- Preços fora de R$ 0,30 a R$ 15 são descartados como erro de digitação; a contagem fica em `data/qualidade.json`.
- A regra dos 70% para o etanol é uma aproximação; o rendimento real varia com o carro.

## Rodar localmente

```bash
pip install -r requirements.txt
python -m pytest -q          # testes do pipeline
python -m pipeline.run       # baixa da Release os anos que mudaram e agrega
python -m base.construir --anos 2026   # (opcional) monta a base localmente
python -m http.server -d site 8000
```

## Fontes

- ANP, [Série Histórica de Preços de Combustíveis](https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/serie-historica-de-precos-de-combustiveis)
- IBGE, [IPCA (SIDRA, tabela 1737)](https://sidra.ibge.gov.br/tabela/1737) e [API de malhas territoriais](https://servicodados.ibge.gov.br/api/docs/malhas)

Código sob licença MIT. Feito por [Érika Nogueira Santos](https://erikansantos.github.io).
