# 09 · Leitura estrutural (achar a tabela dentro de qualquer planilha)

Planilhas reais quase nunca começam em A1 com um cabeçalho limpo. Antes de inferir tipos
([03](03_motor_de_inferencia.md)) a base precisa **encontrar a tabela de dados** e separar o que é dado
do que é enfeite. Esse trabalho é do módulo `estrutura.py`; `leitura.py` cuida só do arquivo (formato,
encoding, separador, abas, células mescladas).

## O que é reconhecido automaticamente

| Situação na planilha | O que a leitura faz | Aparece no diagnóstico como |
|---|---|---|
| Título, "Gerado em…", metadados acima da tabela | Ignora; acha o cabeçalho real pela pontuação | "Cabeçalho localizado na linha N" |
| Cabeçalho em **dois níveis** (grupo mesclado em cima: "Financeiro" sobre "Valor", "Glosa") | Junta como `Financeiro - Valor` | "Cabeçalho em dois níveis" |
| Células **mescladas** (cabeçalho ou dados) | Replica o valor para toda a área mesclada | — |
| **Linhas de seção** ("REGIÃO SERRANA" sozinha numa linha) | Vira a coluna **«Seção»** e a linha some | "linha(s) de seção … viraram a coluna «Seção»" |
| **Subtotal / Total geral** (com rótulo) | Descarta (não soma em dobro) | "N total/subtotal" |
| **Total sem rótulo** na última linha (é a soma das anteriores) | Descarta | "N total/subtotal" |
| **Cabeçalho reimpresso** a cada página (relatório exportado) | Descarta as repetições | "N cabeçalho repetido" |
| **Notas de rodapé** ("Fonte:", "Obs.:", "* valores…", "Página 1 de 3") | Descarta | "N nota/rodapé" |
| **Outra tabela abaixo** (após linha em branco, com cabeçalho próprio ou em outras colunas) | Para a leitura ali | "há outro bloco/tabela … ignorado" |
| Linha em branco **no meio** dos dados | Continua lendo (não corta a tabela) | — |
| 1ª coluna **agrupada** (valor só na 1ª linha de cada grupo) | Repete o valor para baixo | "valor aparecia só na 1ª linha de cada grupo" |
| Linha-gabarito (molde com só o "Nº") | Descarta | "N linha-gabarito (molde vazio)" |
| Erros de fórmula (`#DIV/0!`, `#REF!`, `#N/D`…) | Viram vazio | "N célula(s) com erro de fórmula" |
| Várias abas (capa, instruções, base, listas ocultas) | Escolhe a aba da base (maior tabela; com modelo, a que mais casa) | "Aba «X» escolhida automaticamente" |
| CSV com preâmbulo / separador `;` `,` `TAB` `\|` | Separador pela consistência do nº de campos; **nenhuma linha é perdida** | — |
| Datas mistas (nativas + texto, ou 2 formatos) | Converte todas (formato dominante primeiro) | — |
| Data como número serial do Excel (45292) em coluna "Data…" | Converte para data | evidência na aba Tipos |
| Formato "largo" (colunas Jan/26, Fev/26, Mar/26…) | Mantém, mas sinaliza | "Formato «largo»" |

**Nada é descartado em silêncio:** tudo vai para `MetaLeitura.diagnostico` e aparece como alerta
(nível *info*) na janela e no relatório. Planilha limpa não gera diagnóstico.

## Como o cabeçalho é escolhido

Cada uma das primeiras `LINHAS_CABECALHO_BUSCA` (30) linhas não vazias recebe uma pontuação 0–1:

| Sinal | Peso | Ideia |
|---|---|---|
| rótulos textuais (ou anos) | 0,30 | cabeçalho é texto |
| cobertura abaixo | 0,30 | as colunas rotuladas têm dados embaixo |
| valores únicos | 0,15 | rótulos não se repetem na linha |
| contraste de tipo | 0,15 | texto em cima de números/datas |
| rótulos curtos (≤ 40) | 0,10 | título é longo, rótulo é curto |
| × largura | — | o cabeçalho cobre a largura da tabela (título de 1 célula fica fora) |
| − repetição na coluna | −0,35 | valor que se repete embaixo é dado categórico, não rótulo |
| + casamento com o modelo | +0,8 | com modelo, a linha que contém os sinônimos vence |

Se a linha vencedora reaparece inteira mais abaixo (cabeçalho reimpresso), isso conta **a favor**.
A pontuação vira `MetaLeitura.confianca`; abaixo de `CONFIANCA_MINIMA_ESTRUTURA` (0,5) a análise
mostra o aviso "Estrutura da planilha incerta" — sinal de que vale criar um modelo para aquele layout.

## Com modelo de cliente

O modelo deixa a leitura **guiada** ([04](04_modelo_de_cliente.md)):

- os sinônimos das colunas ajudam a achar a **linha do cabeçalho** e a **aba** certas;
- cabeçalho com grafia nova parecida (≥ `LIMIAR_SEMELHANCA_CABECALHO` = 0,85, ex.: "Vlr. Total Pago" ≈
  "valor total pago") é associado sozinho — e o diagnóstico avisa, para você incluir o sinônimo no `.toml`.

## Limites conhecidos (ver [ROADMAP](ROADMAP.md))

- Tabelas **lado a lado** na mesma aba (separadas por coluna vazia) são lidas como uma só.
- Formato largo é só sinalizado; ainda não é "despivotado" para uma coluna de período.
- Cabeçalho com 3+ níveis: só os dois últimos níveis são combinados.
- A linha do cabeçalho pode ser forçada por código (`linha_cabecalho=`), ainda não pela janela.

## Onde ajustar

- Limiares e listas: `config.py` (seção *leitura estrutural*): `LINHAS_CABECALHO_BUSCA`,
  `CONFIANCA_MINIMA_ESTRUTURA`, `LIMIAR_SEMELHANCA_CABECALHO`, `NOME_COLUNA_SECAO`, `ERROS_EXCEL`,
  `ABAS_AUXILIARES`.
- Padrões de total e de nota: `_RE_TOTAL`, `_RE_NOTA` em `estrutura.py`.
- Testes de referência (uma planilha bagunçada sintética por situação): `testes/test_estrutura.py`.
  **Todo caso novo que der problema vira um teste aqui antes da correção.**

## Desempenho

A tipagem de célula é feita sob demanda (topo + amostras + linhas suspeitas) e a inferência decide o
tipo por amostra de `AMOSTRA_INFERENCIA` (2000) valores. Referência: CSV de 100 mil × 12 ≈ 4 s;
xlsx de 30 mil × 12 ≈ 4 s (≈ 1 s acima de um `pd.read_excel` puro).
