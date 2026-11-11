# Roadmap

Ordem sugerida, não compromissada. Itens entram no [CHANGELOG](CHANGELOG.md) quando concluídos.

## Estado atual

O produto é o **servidor web (v3)** (FastAPI + Docker): login, controle por setor, envio com prévia,
relatórios HTML, Painel Executivo editável, chamados, os **Agentes Especialistas por Setor**
([19](19_agentes_por_setor.md)) e o **Dashboard Feedback / NPS** da Diretoria ([20](20_feedback_nps.md)).
O app desktop/.exe foi descontinuado.

## Curto prazo

1. **Novos Agentes de setor** — seguindo o molde de Faturamento/Custos ([19](19_agentes_por_setor.md)):
   Intercâmbio, OPME, Financeiro, Contabilidade, Repasse Médico, Estoque/Farmácia. Cada um = um subpacote
   (`rules.py` + `config.toml`) + uma linha no router.
2. **Anonimização de dados sensíveis** — ✅ nomes da entidade (iniciais). Falta: CPF, telefone e outras
   colunas marcadas como `sensivel` no modelo. **Prioridade por LGPD** ([18](18_seguranca_lgpd_v2.md)).
3. **Leitura estrutural — próximos passos** ([09](09_leitura_estrutural.md)):
   - escolher a linha do cabeçalho na prévia quando a confiança for baixa (o motor já aceita `linha_cabecalho`);
   - "despivotar" formato largo (colunas Jan/Fev/Mar → Período + Valor), opcional no modelo;
   - tabelas lado a lado na mesma aba;
   - guardar no `.toml` a "assinatura" estrutural do layout para leitura 100% determinística.

## Médio prazo

4. **Exportação PDF/DOCX** — mesmo objeto `Analise`, novos renderizadores (nunca recalcular números).
5. **Comparação entre períodos/arquivos** — variação mês a mês e histórico.
6. **Editar modelo existente pela web** — hoje o assistente cria/sobrescreve; carregar um `.toml` para edição.

## Longo prazo

7. **Insights automáticos** — resumo em linguagem natural e detecção de anomalias (local/privado por LGPD).
8. **Biblioteca de modelos** — vários clientes/relatórios com seleção e versionamento dos `.toml`.
9. **Cérebro — fases avançadas** — consolidar a dedução por papel/grão e o corte automático (ver memória do projeto).
