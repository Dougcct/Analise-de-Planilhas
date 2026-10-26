# POP-01 · Operação da ferramenta (usuário final)

| Campo | Valor |
|---|---|
| Código | POP-01 |
| Versão | 2.0 |
| Executante | Usuário final (analista/gestor) |
| Frequência | Sob demanda |

## Objetivo

Analisar uma planilha e gerar o relatório, interpretando os resultados.

## Pré-requisitos

Programa instalado (ou `python main.py` em desenvolvimento); planilha em `.xlsx/.xlsm/.xls/.ods/.csv`;
acesso autorizado aos dados (LGPD).

## Procedimento

1. Abra o programa (`AnalisePlanilhas.exe` ou `python main.py`).
2. Em **Relatório**, escolha o relatório da planilha (modelo do cliente). Se não houver, use
   "Sem modelo (inferência automática)".
3. Em **Arquivos**, confira a pasta indicada (`dados\<relatório>\`). Coloque as planilhas lá ou clique em
   **Adicionar…**. Marque as que entram na análise — **várias marcadas são consolidadas** (ex.: 2025 + 2026).
4. Confira a aba **Resumo e achados** (metas, achados, leitura e qualidade) e os KPIs no topo.
5. Se algum tipo estiver errado (ex.: CEP lido como número), vá à aba **Tipos** e corrija — reprocessa na hora.
6. Na lateral, escolha o **Período pela** (qual data) e marque valores nas listas de cada dimensão (nada
   marcado = todos). Clique em **Aplicar filtros** (ou **Limpar filtros**).
7. Para achar algo na tela, use **🔎 Buscar na tela** (realça, não filtra).
8. Metas e observações do gestor: **⚙ Editar metas** (ficam salvas para o relatório; aparecem com ✔/✗).
9. Clique em **Gerar HTML**. O arquivo abre no navegador e fica salvo em `saida/` (**Abrir pasta de saída**).

## Verificação

- O nº de registros e de arquivos no rodapé (status) bate com o esperado.
- "Leitura e qualidade" (em **Resumo e achados**) não aponta problemas graves (ou eles são conhecidos).

## Problemas comuns

| Sintoma | Causa provável | Ação |
|---|---|---|
| Colunas com nomes `coluna_3` | Cabeçalho na linha errada | Confira se a aba certa foi escolhida; reporte ao dev |
| Acentos quebrados (CSV) | Encoding atípico | Reporte ao dev (o programa tenta utf-8/cp1252/detecção) |
| Datas trocadas (dia/mês) | Ambiguidade `03/04/2026` | Na aba Tipos, forçar `data`; idealmente usar modelo |
| Número lido como texto | Mistura de `.`/`,` ou "R$" solto | Na aba Tipos, forçar `decimal`/`moeda` |
| "Soma" de um código/contador | Coluna de código vista como métrica | Na aba Tipos, marcar `identificador` |

## Cuidados (LGPD)

- Não envie o HTML a destinatários externos sem autorização.
- Apague a planilha de `dados/` após o uso, se não houver necessidade de guarda.
