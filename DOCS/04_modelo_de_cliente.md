# 04 · Modelo de cliente (o `.toml`)

Este é o documento central para **adaptar a base a uma planilha nova**. Um modelo descreve a planilha de
um cliente em duas camadas:

1. **Colunas** — quais existem, seus tipos e as grafias de cabeçalho aceitas (leitura determinística);
2. **Regras de negócio** — quem é a entidade, que taxas, tempos, classificações, cruzamentos, checagens
   de qualidade e metas importam. É o que transforma estatística genérica em **indicadores de gestão**
   (mesmo padrão do projeto *Garantia de Atendimento* — ver [10](10_indicadores.md)).

Os modelos ficam em `config/modelos/<cliente>.toml` e aparecem no seletor da janela. **Exemplo completo
com todas as seções:** `config/modelos/garantia_atendimento.toml.sample` (reproduz a Garantia só com
configuração). Sem modelo, as regras são **deduzidas** dos tipos (ver "Sem modelo" abaixo).

## Cabeçalho do arquivo

```toml
nome  = "Faturamento HUNF"   # nome único (chave de metas, títulos, CLI)
aba   = "FATURAMENTO"        # a aba REAL que este modelo lê — é o rótulo do nível «Página»
pasta = "HUNF"               # subpasta de dados\ — nível «Pasta» (padrão: o nome do modelo)
ordem = 1                    # (opcional) ordem da página (aba) no seletor (menor primeiro)
abas  = "todas"              # (opcional) consolida TODAS as abas com este layout (ou ["A", "B"])
apenas_mapeadas = true       # (opcional) descarta colunas NÃO declaradas na leitura (LGPD — padrão: false)
```

Com `abas = "todas"` (consolida meses/tipos numa base só) o relatório vira, na tela, uma página única
**«Todas as abas (consolidado)»** em vez de uma página por aba. Com `apenas_mapeadas = true` a leitura
**mantém só as colunas declaradas** no modelo e descarta o resto (ex.: CPF/banco/PIX no Pagamento
Reembolso) — nada fora do modelo chega à base, ao relatório ou ao Modo IA; ver
[14_garantia_reembolso.md](14_garantia_reembolso.md).

Com `abas`, cada aba que tiver ao menos metade das colunas do modelo entra na base, com a coluna
**«Aba de origem»**; abas com outro layout (resumo, dashboard) são ignoradas e listadas no diagnóstico.

### Navegação Pasta › Relatório › Página

O seletor da barra lateral tem **três níveis**, todos com **nomes reais**:

- **Pasta** — as subpastas de `dados\` (nível vindo do campo `pasta` dos modelos).
- **Relatório** — os **arquivos** (planilhas) que estão na pasta escolhida, pelo nome real do arquivo
  (ex.: `DADOS HUNF`, `2025`, `2026`).
- **Página** — as **abas reais** daquele arquivo que algum modelo da pasta reconhece (`aba`), em ordem
  de `ordem` (ex.: `FATURAMENTO`, `Page 1`). Abre sempre na primeira; com uma só aba, o seletor fica
  oculto. Um arquivo sem nenhum modelo que case cai como **Sem modelo** (inferência automática).

Abaixo do menu, **Arquivos (juntar)** lista os arquivos da pasta: por padrão só o do relatório atual
fica marcado (cada arquivo é analisado **à parte**); marque mais de um e clique **Recarregar** para
**juntar (consolidar)** os dados (ex.: 2025 + 2026). Um arquivo sem a aba da página é ignorado ao juntar.
Planilhas em **matriz conta × mês** usam ainda a seção `[leitura]` (blocos, totais da planilha, base a
partir de um mês) e `[analise] tipo = "serie"` para os dashboards financeiros (custos, faturamento, DRE)
— ver [13_financeiro_hunf.md](13_financeiro_hunf.md). (Os campos `categoria`/`pagina` são legados e ignorados.)

## `[[coluna]]`

```toml
[[coluna]]
canonico  = "prestador"              # id interno, único (usado nas regras abaixo)
rotulo    = "Prestador"              # nome exibido
tipo      = "categorico"             # ver tipos
sinonimos = ["prestador identificado"]
papel     = "dimensao"               # (opcional) dimensao | medida | entidade | texto
obrigatoria = true                   # (opcional) vazio vira ocorrência de qualidade
aliases   = { "CARDIOLOGISTA" = "CARDIOLOGIA" }   # (opcional) grafia variante → padrão
ignorar_palavras = ["DR", "DRA"]     # (opcional) ignoradas ao unificar grafias
validar   = "numerico"               # (opcional) conteúdo só com dígitos (ex.: transação)
opcional  = true                     # (opcional) pode faltar em algumas planilhas sem gerar alerta
```

Com modelo, coluna **não obrigatória** vazia não gera aviso de "% de vazios" (vazio é regra de
negócio — ex.: OPME só existe em contas com prótese); as obrigatórias são checadas linha a linha.

**Tipos:** `identificador`, `booleano`, `data`, `data_hora`, `percentual`, `moeda`, `inteiro`, `decimal`,
`categorico`, `texto_livre`.

**Papel** (padrão deduzido do tipo): `dimensao` = quebra e filtro (padrão de `categorico`); `medida` =
valor somado (padrão de `moeda/inteiro/decimal`); `entidade` = quem é atendido (distintos, recorrência,
anonimização); `texto` = só exibição (não vira quebra).

**Grafias:** toda dimensão é unificada automaticamente — valores iguais sem acento/caixa/pontuação viram
um só (`NITEROI` + `Niterói` → `Niterói`, a mais frequente, preferindo a acentuada). `aliases` resolve
o que a regra não pega (abreviações, erros).

Mapeamento de cabeçalho: compara `canonico`, `rotulo` e `sinonimos` ignorando acento/caixa/pontuação;
grafia nova **parecida** (≥ 0,85) é associada sozinha e o diagnóstico avisa para incluir o sinônimo.
Cabeçalhos repetidos na mesma aba (dois "Prestador identificado") viram uma coluna (1º valor preenchido).

## `[analise]`

```toml
[analise]
entidade          = "cliente"           # canônico da coluna-entidade
entidade_plural   = "clientes"          # (opcional) para as frases
data_base         = "data_solicitacao"  # filtro de período e evolução mensal
medida_principal  = "valor"             # (opcional) valor somado nas quebras
estatistica_tempo = "mediana"           # mediana | media | p90 | p95
dimensoes = ["tipo_atendimento", "canal", "especialidade"]   # (opcional) quais e em que ordem
top = 15                                # linhas por quebra
# --- análise financeira (opcionais; sem elas o comportamento é o de sempre) ---
medidas        = ["valor", "custo"]     # restringe as medidas do painel Valores
medidas_quebra = ["valor", "custo", "resultado"]   # somadas em cada quebra e nos KPIs
                                        # (a principal ganha também a média = ticket médio;
                                        #  KPI avisa cobertura parcial: "em 12 de 91")
composicao     = ["diarias", "opme"]    # partes da medida principal → painel «Composição»
                                        # (soma, % do total, nº de registros com valor)
```

Margem e participações se declaram como **taxa ponderada** (`numerador`/`denominador`) — ver o
exemplo completo em `config/modelos/contas_convenio.toml` ([12](12_contas_convenio.md)).

## `[[classificacao]]` — coluna nova por regra de texto

```toml
[[classificacao]]
canonico = "canal"
rotulo   = "Canal"
origem   = "canal_abertura"     # coluna lida; "_aba" = nome da aba
regras   = [["NIP", "Regulatório / Jurídico"], ["CRM", "CRM"],
            ["observacoes", "CANCEL", "Cancelado"]]   # [trecho, categoria] ou [coluna, trecho, categoria]
vazio    = "Não informado"      # origem vazia
outros   = "Outros"             # nenhuma regra casou ("manter" = mantém o valor da origem)
```

O trecho é procurado no texto **sem acento e em maiúsculas**; a 1ª regra que casar vence (ordem importa:
`CRM / E-MAIL` cai em CRM se CRM vier antes). A classificação vira dimensão e filtro.

## `[[taxa]]` — % que importa

```toml
[[taxa]]
canonico = "resolvido_rede"
rotulo   = "Resolvidas na rede"
coluna   = "status"
valores  = ["AGENDADO", "PRESTADOR IDENTIFICADO"]
sentido  = "maior"              # maior | menor (o que é bom) — guia os achados
# taxa ponderada por valor (em vez de coluna/valores):
# numerador = "valor_autorizado"
# denominador = "valor_solicitado"
```

## `[[tempo]]` — prazo entre duas datas

```toml
[[tempo]]
canonico   = "total"
rotulo     = "Tempo total"
inicio     = "data_solicitacao"
fim        = "data_finalizacao"
dias_uteis = true                # seg–sex, sem feriados nacionais/móveis (+ [feriados] extras)
meta       = 14                  # dias (úteis, se dias_uteis)
meta_por   = "tipo_atendimento"  # meta diferente por categoria…
metas      = { "CONSULTA" = 14, "EXAME" = 10 }
em_aberto  = true                # início sem fim = pendência (KPI + qualidade)
```

Cria as colunas `Tempo total (dias)`, `(dias úteis)` e `: dentro da meta`. Data final antes da inicial
vira ocorrência de qualidade (e o tempo fica vazio).

## `[[cruzamento]]`

```toml
[[cruzamento]]
rotulo   = "Possíveis vazios assistenciais"
linhas   = "especialidade"
colunas  = "cidade_demanda"
somente  = "reembolso"           # (opcional) id de taxa: conta só onde ela é verdadeira
diferentes = false               # (opcional) só pares linha ≠ coluna (fluxo entre cidades)
```

Poucas categorias → matriz com totais; muitas → ranking de pares.

## `[qualidade]`, `[feriados]`, `[[meta]]`

```toml
[qualidade]
duplicidade       = ["transacao", "especialidade"]   # juntas não devem repetir
grafias_parecidas = ["prestador"]                    # aponta pares ≥ 86% parecidos

[feriados]
extras = ["2026-06-29"]          # municipais / pontos facultativos

[[meta]]
indicador = "resolvido_rede"     # id de taxa ou de tempo, ou "registros"
alvo      = 60                   # % (taxa) | dias (tempo) | número
sentido   = ">="
```

Qualidade automática (sempre): data/valor inválido, data improvável (ano fora de 2000–2100), obrigatória
vazia, conteúdo não numérico, duplicidade, data final < inicial, em aberto — **cada ocorrência com aba e
linha** para corrigir na planilha de origem.

## Sem modelo (especificação automática)

| O que | Como é deduzido |
|---|---|
| entidade | 1ª coluna de texto cujo nome contém nome/cliente/beneficiário/paciente/usuário… |
| dimensões | categóricas com 2 a 60 valores |
| medidas | moeda → decimal → inteiro (a 1ª é a principal) |
| data base | a data mais preenchida |
| tempos | cada par de datas consecutivas (e 1ª → última, se houver 3+) |
| taxas | colunas sim/não |
| cruzamento | as duas dimensões com menos categorias |

Serve para a 1ª análise; para indicadores de gestão de verdade (o que é "resolvido", metas), escreva as
regras no modelo.

## Dois jeitos de criar um modelo

**A) Pelo assistente da janela:** abra sem modelo → corrija tipos na aba **Tipos** → **Salvar como
modelo…** → gera as `[[coluna]]`. Depois acrescente as regras (passo B).

**B) Editando o `.toml`:** copie `exemplo.toml.sample` (mínimo) ou `garantia_atendimento.toml.sample`
(completo) para `config/modelos/<cliente>.toml` e edite. Erros de formato (tipo/papel inválido) são
avisados ao carregar; regra que cita coluna inexistente é **ignorada com aviso** no diagnóstico.
