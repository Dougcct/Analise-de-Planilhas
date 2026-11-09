# POP-01 · Operação (usuário final / gestor)

| Campo | Valor |
|---|---|
| Código | POP-01 |
| Versão | 3.0 |
| Executante | Usuário final (analista/gestor) |
| Frequência | Sob demanda |

## Objetivo

Enviar uma planilha, conferir a prévia e **publicar o relatório** no sistema web; depois, ler e filtrar os
indicadores.

## Pré-requisitos

- Servidor no ar (`docker compose up`) e acesso a **http://localhost:8000/web** (ou o endereço interno).
- Usuário e senha; acesso autorizado aos dados do setor (LGPD).
- Planilha em `.xlsx/.xlsm/.xls/.ods/.csv`.

## Procedimento

1. **Entrar** — faça login. Se esqueceu a senha, use **Esqueci a senha** (vira um pedido para o ADM).
2. **Enviar planilha** (menu *Dashboard → Enviar planilha*):
   - Escolha **novo relatório** (dê um nome) ou **atualizar** um relatório do seu setor.
   - Selecione uma ou **várias** planilhas (várias entram numa fila de lote).
3. **Conferir a prévia** (abre automaticamente):
   - **Modelo**: se combinou, já vem vinculado; pode trocar ou deixar "sem modelo".
   - **Agente de setor** (quando não há modelo): deixe em *Automático* ou escolha/desligue — ex.: Custos,
     Faturamento ([19](../19_agentes_por_setor.md)).
   - **O que o sistema entendeu**: confira o papel de cada coluna (selos ✓/⚠/❓/LGPD). Se algo estiver
     errado, **corrija os papéis** e reanalise.
   - Veja o nº de registros e os painéis da prévia.
4. **Publicar** — se estiver certo, clique em **Publicar** (ou **Descartar** para jogar fora o rascunho).
   Reenviar a mesma planilha (mesmo nome) substitui a anterior (vira backup); planilhas diferentes somam.
5. **Ler o relatório** (menu *Relatórios* → abra o seu):
   - **Painel Executivo** no topo (KPIs, destaque, gráficos) — editável pelo gestor.
   - **Filtros**: *Período pela* (qual data), dimensões (multi-seleção), faixas; **Anonimizar nomes** antes de
     mostrar a terceiros. Nada marcado = tudo.
   - **Seções/abas**: achados, composição, tempos, qualidade… e, com agente, **"Análise de {setor}"**.

## Verificação

- O nº de registros/arquivos bate com o esperado.
- "Leitura e qualidade" não aponta problemas graves (ou são conhecidos).
- Os KPIs e gráficos fazem sentido para o período/recorte.

## Problemas comuns

| Sintoma | Causa provável | Ação |
|---|---|---|
| Colunas com nomes genéricos (`coluna_3`) | Cabeçalho na linha errada | Confira a aba/linha na prévia; se for ERP bagunçado, tente um **Agente de setor** |
| Acentos quebrados (CSV) | Encoding atípico | Reporte pelo botão **Sugestões** (o sistema tenta utf-8/cp1252/detecção) |
| Datas trocadas (dia/mês) | Ambiguidade `03/04/2026` | Corrija o papel/tipo na prévia; idealmente use modelo |
| Número lido como texto | Mistura de `.`/`,` ou "R$" | Corrija na prévia; um Agente de setor sanitiza valores PT-BR |
| "Soma" de um código/contador | Código visto como métrica | Marque como identificador na prévia (ou use modelo/agente) |

## Cuidados (LGPD)

- Não compartilhe o relatório com pessoas de fora do setor sem autorização; use **Anonimizar nomes**.
- Precisa de ajuda ou achou um bug? Use o botão **Sugestões** — pode anexar a planilha (fica restrita ao ADM e a você).
