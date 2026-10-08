Base histórica de preços de combustíveis da ANP: **uma linha por coleta**, de maio de 2004 até o mês mais recente publicado, em Parquet (um arquivo por ano). Montada e atualizada toda semana pelo projeto [Raio-X dos Combustíveis](https://erikansantos.github.io/raio-x-combustiveis/).

**Consultar sem baixar tudo** (DuckDB):

```sql
INSTALL httpfs; LOAD httpfs;
SELECT produto, year(data) AS ano, median(preco_venda) AS mediana
FROM 'https://github.com/ErikaNSantos/erikansantos.github.io/releases/download/base-combustiveis/combustiveis_2024.parquet'
WHERE uf = 'BA'
GROUP BY ALL ORDER BY ALL;
```

**Colunas:** `data`, `regiao`, `uf`, `municipio`, `revenda`, `cnpj`, `bairro`, `cep`, `produto`, `preco_venda`, `preco_compra` (preenchido até ~2020), `unidade`, `bandeira`.

**Fontes, mês a mês:** o arquivo semestral da ANP (consolidado oficial) quando existe; o mensal só nos meses que nenhum semestral cobre ainda. `manifesto.json` diz de qual arquivo veio cada mês e quantas linhas entraram.

Fonte: ANP, Série Histórica de Levantamento de Preços de Combustíveis (dados abertos). Montagem: Érika Nogueira Santos.
