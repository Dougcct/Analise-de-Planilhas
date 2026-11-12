# 22 — Custos por Centro de Custo (SoulMV)

Tipo de relatório de **layout FIXO** para o PDF da SoulMV **«Apresentação dos custos dos centros de
custos»** (Gestão de Custos & Resultados). O PDF é **hierárquico** (uma seção por centro de custo, ~291
páginas por mês), não uma planilha; por isso tem leitor e tela próprios, fora do motor genérico — o motor
tentava tabelar o PDF e a leitura saía «fora de contexto».

Código: `src/analise_planilha/custos_centros.py` (lógica pura) · registro em `dashboards.py` ·
leitura das cargas em `servidor/app.py` (`_dashboard_pdf`).

## Como ligar (no envio)

Campo **Modelo de análise** → **«Custos por Centro de Custo (SoulMV)»** (`SLUG = "custos_centros_custo"`).
Sem escolher, o sistema ainda reconhece o PDF pela assinatura do cabeçalho. **Um PDF por mês**: envie
vários (ex.: `01-26.pdf` … `07-26.pdf`) e o relatório soma os meses. A competência vem do cabeçalho do
PDF (`Competência -MM/AAAA-`); o nome do arquivo é só reserva.

## O que a tela mostra (por centro de custo)

| Bloco | Conteúdo |
|---|---|
| Identidade | **código + nome** do centro (prioridade de leitura), consolidador e mês do detalhe |
| Custo primário | grupos de conta (`32 - CUSTOS HOSPITALARES`…), itens (descrição · código · valor), total do grupo e soma geral — grupos recolhíveis |
| Rateio absorvido | tabela compacta (origem · regra · descrição · valor) em blocos recolhíveis com subtotal e total absorvido |
| Resumo operacional | métricas × **meses incluídos** (adapta-se à quantidade de arquivos) + evolução do Total de Custo |

**Filtros (no navegador, instantâneos):** setores em multisseleção (busca + chips) e período de/até.
**1 setor** = documento detalhado; **2+ setores** = **comparativo** (tabela métricas × centros e gráfico de
linhas do Total de Custo por centro).

## Leitura do PDF e conferência

- Extrator **rápido** (pypdfium2, já instalado como dependência do pdfplumber, ~58× mais rápido). Ele
  devolve o texto na **ordem interna** do PDF (títulos depois do conteúdo); por isso o parser classifica
  cada linha pelo **próprio conteúdo**, sem depender da ordem das seções.
- **Conferência** (`conferir`) em todo centro × mês: soma dos itens = total do grupo; soma dos grupos =
  total do primário; soma das linhas = subtotal do bloco de rateio; soma dos subtotais = total absorvido.
  Se o extrator rápido não fechar, o arquivo é relido com o **pdfplumber** (lento, ordem visual). Se nem
  assim fechar, a tela mostra **⚠ «a leitura deste mês não fechou a conta»**.
- Regras de rateio reconhecidas: Incidência Percentual, Unidade de Mensuração, Produção, **Convenção**.
  Regra nova → o bloco não fecha → aparece o aviso (nada some em silêncio). Linhas do **Rateio
  distribuído** (`Origem 1,00 % 1.000,00`) nunca entram como item do custo primário.
- Mudou o parser? Suba `VERSAO_PARSER`: os parses guardados são refeitos.

## Desempenho (cache)

1. **Disco, por arquivo:** o parse de cada PDF fica em `<arquivo_uuid>.custos_centros_custo.v<N>.json`
   no volume de cargas, com o hash SHA-256 da carga; só é reaproveitado se hash e versão baterem
   (gravação atômica). Acontece já na **prévia** do envio, sobrevive a reinícios e é incremental.
2. **Memória:** o resultado mesclado, por `(SLUG, hashes das cargas)` — até 24 entradas.

Ordem de grandeza (7 PDFs): leitura 3,2 s (antes 185 s); abertura depois de reiniciar ~0,01 s.

## Segurança e LGPD

- A permissão é checada nas rotas **antes** do cache; o cache só evita recomputar.
- Chave por conteúdo: conjuntos de arquivos diferentes nunca compartilham resultado.
- O parse guardado fica **no mesmo volume do PDF bruto** (fora do git, mesmo controle de acesso).
- **Excluir carga = `apagar_arquivo_carga(c)`** (`servidor/app.py`): apaga PDF + parse em disco + cache em
  memória. Toda rota que descarta/exclui carga deve usar essa função.
- Os testes usam **texto sintético** (nunca o PDF real nem valores reais).

## Pontos em aberto

- «Baixar modelo (PDF)» e «Gerar versão editável» da barra não se aplicam a este dashboard (a tela é
  montada no navegador): esconder/adaptar.
- Ainda não lidos: indicadores de produtividade, médias anteriores (trimestre/semestre/anual), filtro por
  consolidador, rótulo Genérico/Específico dos blocos de rateio.
