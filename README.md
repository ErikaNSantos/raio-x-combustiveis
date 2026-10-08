# Raio-X dos Combustíveis

Quanto custa abastecer em cada estado, capital e município pesquisado pela ANP, quando o etanol compensa mais que a gasolina e quanto o preço muda dentro da mesma cidade. Com os preços corrigidos pela inflação.

**Página:** https://erikansantos.github.io/raio-x-combustiveis/

*English: monthly dashboard of Brazilian fuel prices (gasoline, ethanol, diesel) by state, capital and city, built from ANP open data and deflated by IPCA. A Python pipeline runs weekly on GitHub Actions, processes only new months and publishes a static page.*

## Como funciona

```
página da ANP ──► pipeline/fontes.py   acha os links dos CSVs mensais
                  pipeline/run.py      baixa só os meses que ainda não foram processados
                  pipeline/agregar.py  preço por posto → mediana por município, UF e Brasil
IBGE (SIDRA) ───► pipeline/ipca.py     IPCA para corrigir pela inflação
IBGE (malhas) ──► pipeline/malha.py    contorno das UFs para o mapa
                  pipeline/publicar.py JSONs em site/data/
GitHub Actions ─► toda segunda: roda o pipeline, versiona os dados novos e publica o site
```

## Decisões que valem explicar

- **Os links não são montados, são lidos da página.** A ANP muda o padrão do nome do arquivo sem aviso (`precos-gasolina-etanol-01.csv`, `01-dados-abertos-precos-...`, `06-dados-abertos-precos-2026-06-...`) e já publicou um com erro de digitação (`02-cados-abertos-preco-...`). Os testes cobrem todos esses casos.
- **Um posto, um voto.** O preço de cada posto no mês é a mediana das coletas dele; as estatísticas de cidade, estado e Brasil saem desses preços. Sem isso, um posto visitado quatro vezes pesaria quatro vezes mais, e a diferença entre o mais barato e o mais caro de uma cidade sairia inflada por coletas de datas diferentes.
- **Incremental.** Cada mês vira um CSV pequeno em `data/agregados/` (versionado). O CSV bruto da ANP, de ~9 MB, é apagado depois de processado. Uma atualização mensal baixa dois arquivos, não o histórico inteiro.
- **Meses que faltam aparecem como buraco**, não como linha ligando os vizinhos. Abril de 2026 não foi publicado pela ANP.
- **Página sem build e sem dependência externa em tempo real.** HTML, CSS e JS puro, com o d3 e o mapa salvos no próprio repositório.

## Limitações

- A ANP pesquisa uma amostra (cerca de 400 municípios e 6 mil postos por mês), não todos.
- O arquivo não traz o preço de compra pelo posto, então não dá para calcular margem.
- Preços fora de R$ 1 a R$ 15 são descartados como erro de digitação; a contagem fica em `data/qualidade.json`.
- A regra dos 70% para o etanol é uma aproximação; o rendimento real varia com o carro.

## Rodar localmente

```bash
pip install -r requirements.txt
python -m pytest -q          # testes do pipeline
python -m pipeline.run       # baixa e processa os meses novos
python -m http.server -d site 8000
```

## Fontes

- ANP, [Série Histórica de Preços de Combustíveis](https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/serie-historica-de-precos-de-combustiveis)
- IBGE, [IPCA (SIDRA, tabela 1737)](https://sidra.ibge.gov.br/tabela/1737) e [API de malhas territoriais](https://servicodados.ibge.gov.br/api/docs/malhas)

Código sob licença MIT. Feito por [Érika Nogueira Santos](https://erikansantos.github.io).
