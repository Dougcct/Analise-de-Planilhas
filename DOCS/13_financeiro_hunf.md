# 13 · Relatórios financeiros HUNF (planilhas em matriz conta × mês)

O workbook do HUNF (`DADOS HUNF.xlsx`, pasta `dados\HUNF\`) tem 21 abas; três são **matrizes**: cada
linha é uma conta (ou convênio) e cada coluna é um mês. Elas ganharam um **leitor próprio**
(`matriz.py`), que converte para uma linha por conta × mês, e um **motor de análise financeira**
(`financeiro.py`), que monta os dashboards. Navegação na janela: **Pasta** HUNF › **Relatório**
DADOS HUNF › **Página** FATURAMENTO · DRE HUNF · CUSTOS. Cada página é analisada à parte.

**Base a partir de jan/2024** (`a_partir_de = "2024-01"` nos três modelos). Meses sem nenhum lançamento
por conta (futuros) ficam fora; mês que só tem o total da planilha (ex.: ago/26 nos Custos) fica fora
do detalhe e aparece na conferência.

| Página | Modelo | Linha | Valor | Filtros | Perfil |
|---|---|---|---|---|---|
| **CUSTOS** (principal) | `custos_hunf.toml` | conta de custo | custo (+) | Grupo, Conta, mês | `custos` (subir é ruim) |
| **DRE HUNF** | `dre_hunf.toml` | conta | receita (+) / despesa (−) | Grupo, Conta, mês | `dre` |
| **FATURAMENTO** | `faturamento_hunf.toml` | convênio | receita (+) | Convênio, mês | `faturamento` |

## CUSTOS — os blocos da planilha

O modelo declara os blocos **exatamente como na planilha** (`agrupamento = "secoes"`):

| Bloco (grupo) | Abre na linha | Observação |
|---|---|---|
| Custos hospitalares | CUSTOS HOSPITALARES | |
| Despesas administrativas | DESPESAS ADMINISTRATIVAS HUNF | |
| Despesas com empregados | DESPESAS COM EMPREGADOS HUNF | inclui contas sem código (ENCARGOS SOCIAIS, REMUNERAÇÃO, REPOUSO REMUNERADO) |
| Encargos sociais | DESPESAS COM ENCARGOS SOCIAIS | |
| Seguros de bens e imóveis | TOTAL DESPESAS SEGUROS DE BENS E IMOVEIS | só tem a linha de total — ela é o dado; a linha aparece **duas vezes** e vale a última (a 1ª tem **datas digitadas** no lugar de valores em 2026) |
| Impostos e taxas | DESPESAS COM IMPOSTOS TAXAS HUNF | |
| Serviços de terceiros | REMUNERAÇÃO SERVIÇOS TERCEIROS | |

Subtotais e linhas «TOTAL» **não entram como dado**: são guardados para a conferência. Resultado com os
dados de out/2026: **os 7 blocos batem centavo a centavo** com os subtotais da planilha, em todos os meses.

As três últimas linhas são **referências** (guardadas à parte, não somam no detalhe):
**Procedimentos cooperado no hospital**, **Custo complexo hospitalar (contábil)** e **Total complexo
hospitalar**. Achados:
- *Total complexo = cooperado + contábil* em todos os meses, **menos fev–jun/2025** (valores digitados à mão).
- O **custo detalhado** (soma das contas) e o **contábil** são visões diferentes: o detalhado fica
  acima no período. **Não somar** um com o outro.

## Dashboards no HTML (e abas na janela)

Comuns às três páginas: **Resumo e achados** (KPIs do período, último mês × mês anterior e × mesmo mês do
ano anterior, últimos 12 meses × 12 anteriores, acumulado do ano; frases automáticas), **Contas /
Convênios** (20 maiores, curva ABC, maiores aumentos e reduções, tabela completa com média mensal,
último mês e variações), **Atípicos e ajustes** (meses fora do padrão, picos por conta, valores
negativos/estornos) e **Conferência com a planilha**.

- **CUSTOS:** *Visão geral* (custo mês a mês empilhado por bloco; média mensal por ano; mesmo mês em
  anos diferentes), *Composição por grupo* (participação, custo médio/mês, indicadores e custo por ano)
  e **uma seção por bloco** (mini-KPIs, evolução mensal, maiores contas, matriz conta × mês como na
  planilha e indicadores das contas).
- **DRE HUNF:** *Demonstrativo* (a DRE por ano e mês a mês, com % da receita; receita × custos ×
  resultado; margem líquida mensal; para onde vai a receita), KPIs de receita, resultado, margem, meses
  com prejuízo, e **contas de despesa com valor positivo** (sinal a conferir — elas aumentam o resultado
  da planilha: Energia Elétrica, Peças, Material de informática…). As variações por conta aparecem como
  "melhoram/pioram o resultado".
- **FATURAMENTO:** concentração (3 maiores, maior convênio, índice HHI), matriz convênio × mês e a
  conferência com a linha «TOTAL MÊS».

## Configuração no modelo

```toml
[leitura]
formato       = "matriz_mensal"
coluna_rotulo = 3              # coluna (base 0) com o nome da conta
agrupamento   = "secoes"       # nenhum | codigo | maiusculas | secoes
a_partir_de   = "2024-01"
limpar_codigo = true           # «AGUA E ESGOTO 70188» → «AGUA E ESGOTO»
pular         = ["TOTAL"]
linha_inicio  = 2
linha_fim     = 133

[[leitura.secao]]              # um por bloco (agrupamento = "secoes")
inicio = "CUSTOS HOSPITALARES" # rótulo da linha que abre o bloco (sem acento/caixa)
grupo  = "Custos hospitalares"
# linha_unica = true + conta = "…": bloco que só tem a linha de total

[[leitura.referencia]]         # linha de total da planilha, só para conferência
rotulo = "TOTAL COMPLEXO HOSPITALAR"
nome   = "Total complexo hospitalar"

[analise]
tipo = "serie"                 # usa financeiro.py
perfil = "custos"              # custos | faturamento | dre
sentido = "menor"              # menor (custo) | maior (receita/resultado)

[[analise.conferencia]]        # total = soma das partes, mês a mês («__soma__» = soma das contas)
total  = "Total complexo hospitalar"
partes = ["Procedimentos cooperado no hospital", "Custo complexo hospitalar (contábil)"]

[[analise.comparacao]]         # informativo: detalhado × uma referência
referencia = "Custo complexo hospitalar (contábil)"
```

Na DRE (`agrupamento = "maiusculas"`): `contas = ["EPI", "IMPOSTOS"]` (em caixa alta, mas são contas) e
`pular_prefixos = ["*", "(Soma"]` (a linha «(-) Descontos…» é conta). Com isso, a soma das contas bate com
o **Resultado líquido** da planilha em todos os meses.

## Fórmulas entre as abas

As abas se **referenciam por fórmula**: a DRE é calculada a partir de FATURAMENTO e CUSTOS. Não há link
entre os arquivos `DADOS HUNF.xlsx` e `DADOS.xlsx`. O leitor usa os **valores que o Excel calculou e
salvou** (100% de cobertura hoje). Se a planilha for salva sem esses valores (alguns fluxos do LibreOffice),
**abra no Excel e salve** antes de analisar — o leitor avisa quando não encontra valor.

## Versões duplicadas na pasta

`DADOS.xlsx` é uma versão anterior do mesmo workbook e **volta a aparecer** em `dados\HUNF\` (provável
sincronização na máquina). Se os dois forem juntados, para cada conta × mês repetido **vale o arquivo mais
recente** — não há soma em dobro — e um **aviso** aparece no topo do relatório. O ideal é manter só uma
versão na pasta.

## Importante

- Leitura **gerencial**: os blocos conferem com os subtotais da planilha, mas a planilha tem lançamentos
  digitados à mão (ver conferência). Para decisão fina, confira com a contabilidade.
- **LGPD:** abas financeiras, sem dado de paciente. `dados\` e `saida\` não são versionados.

Testes: `testes/test_matriz.py` e `testes/test_financeiro.py` (matrizes **sintéticas**).
