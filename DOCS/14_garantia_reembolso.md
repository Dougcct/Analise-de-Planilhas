# 14 · Relatórios Garantia / Reembolso / Pagamento (projeto de referência)

Três relatórios trazidos do projeto **`garantia_atendimento`** (a referência que o nosso analisador
espelha). Foram reproduzidos **só com modelos `.toml`**, reusando o motor atual — sem mexer nos
relatórios existentes. O projeto de referência (código + dados de exemplo) ficou em
`dados\garantia_atendimento_reembolso\` (não aparece no seletor: é só material de consulta).

| Relatório | Pasta | Modelo | Como a referência lê |
|---|---|---|---|
| **Garantia de Atendimento** | `dados\Garantia de Atendimento\` | `garantia_atendimento.toml` | leitor especializado: tipo pelo nome da aba, canal/desfecho por regra de texto, tempos com meta |
| **Reembolso** | `dados\Reembolso\` | `reembolso.toml` | motor tabular: valores solicitado/autorizado/negado, status, justificativa |
| **Pagamento Reembolso** | `dados\Pagamento Reembolso\` | `pagamento_reembolso.toml` | motor tabular: valor do documento/reembolso, forma de pagamento, centro de custo |

Nos três, a planilha tem **uma aba por mês** (JUNHO, JULHO…) ou por tipo (Consultas, Exames…) com o
mesmo cabeçalho. O nosso motor **consolida todas as abas** (`abas = "todas"`) numa análise só — como a
referência faz — e ignora abas sem o layout (ex.: DASHBOARD).

## Indicadores (iguais à referência)

- **Garantia:** resolvidas na rede, encaminhadas a reembolso, canal regulatório; tempos espera /
  tratativa / total (com meta em dias úteis por tipo); classificações tipo de atendimento (pela aba),
  canal, desfecho e encaminhamento; cruzamentos (vazios assistenciais, deslocamento de cidade).
- **Reembolso:** **taxa de autorização** (autorizado ÷ solicitado, ponderada), tempo **abertura →
  finalização**, **em aberto** (sem data de finalização), somas dos valores; quebras por cidade, tipo
  de serviço, status, justificativa e setor.
- **Pagamento:** somas de valor do documento e do reembolso; quebras por centro de custo, fluxo, forma
  de pagamento e prestador; série mensal pela data do depósito.

## Navegação na janela

Pasta (ex.: `Reembolso`) › Relatório (o **arquivo**) › Página **«Todas as abas (consolidado)»**. A
página de consolidação aparece quando o modelo tem `abas = "todas"`; o relatório lê e junta todas as
abas do arquivo numa análise só. Para juntar **vários arquivos** da pasta (ex.: `… REEMBOLSOS …xlsx`
+ `ENTRADA.xlsx`), marque os dois em **Arquivos (juntar)** e clique **Recarregar**.

## LGPD — dados sensíveis

Estas planilhas trazem **nome de beneficiário**; a de Pagamento traz ainda **CPF, banco, agência,
conta e chave PIX**. Proteções:

- O modelo de Pagamento usa **`apenas_mapeadas = true`**: só as colunas declaradas entram na análise.
  **CPF, banco, agência, conta, chave PIX e código do beneficiário ficam de fora** — não vão para a
  base detalhada, nem para o relatório HTML, nem para o Modo IA.
- Antes de **compartilhar** um HTML, marque **Anonimizar nomes** (os nomes viram iniciais).
- `dados\` e `saida\` não são versionados.

## Campos de modelo usados aqui

- `abas = "todas"` — consolida as abas (meses/tipos) numa base só; na tela vira a página «Todas as abas».
- `apenas_mapeadas = true` — descarta colunas não declaradas (privacidade). Padrão: `false` (os demais
  relatórios mantêm as colunas extras).
- Taxa **ponderada por valor** (`numerador`/`denominador`), `[[tempo]]` com `em_aberto`, dimensões,
  medidas — tudo já existente no formato de modelo (ver [04_modelo_de_cliente.md](04_modelo_de_cliente.md)).

Testes sintéticos: `testes/test_garantia_reembolso.py`.
