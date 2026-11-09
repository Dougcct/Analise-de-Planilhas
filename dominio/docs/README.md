# Documentação — Análise de Planilhas

Programa-base para análise de planilhas, **adaptável por cliente** através de um arquivo de modelo.
Esta pasta documenta a base para que adaptar a uma planilha nova seja rápido e sem mexer no código.

## Índice

| Doc | Assunto |
|---|---|
| [01_visao_geral.md](01_visao_geral.md) | O que é, para quem, o conceito de modelo por cliente |
| [02_arquitetura.md](02_arquitetura.md) | Camadas, fluxo de dados, responsabilidade de cada módulo |
| [03_motor_de_inferencia.md](03_motor_de_inferencia.md) | Como os tipos são detectados (cascata e limiares) |
| [04_modelo_de_cliente.md](04_modelo_de_cliente.md) | **Como criar/adaptar o modelo de uma planilha** (formato `.toml`) |
| [05_interface.md](05_interface.md) | **Interface web** (v2): login, controle por setor, envio/prévia, relatório no navegador |
| [06_relatorio_html.md](06_relatorio_html.md) | O dashboard HTML gerado |
| [07_diretrizes_desenvolvimento.md](07_diretrizes_desenvolvimento.md) | Estilo, versionamento, testes, LGPD |
| [09_leitura_estrutural.md](09_leitura_estrutural.md) | **Como qualquer planilha é lida**: cabeçalho, seções, totais, notas, abas |
| [10_indicadores.md](10_indicadores.md) | **O que a análise entrega**: KPIs, quebras, tempos, achados, metas, qualidade |
| [11_modo_ia.md](11_modo_ia.md) | **Modo I.A** (opcional): gerar o modelo por IA a partir da planilha; privacidade/LGPD |
| [12_contas_convenio.md](12_contas_convenio.md) | **Relatório Contas Convênio** (contas hospitalares em blocos): leitura, regras, indicadores financeiros |
| [13_financeiro_hunf.md](13_financeiro_hunf.md) | **Relatórios financeiros HUNF** (planilhas em matriz conta × mês): leitor `matriz.py`, Faturamento/Custos/DRE |
| [14_garantia_reembolso.md](14_garantia_reembolso.md) | **Garantia / Reembolso / Pagamento** (do projeto de referência): modelos, consolidação de abas, `apenas_mapeadas` (LGPD) |
| [16_arquitetura_v2.md](16_arquitetura_v2.md) | **v2 (vigente)** — cliente-servidor por centro de custo: decisões, papéis, dados, API |
| [18_seguranca_lgpd_v2.md](18_seguranca_lgpd_v2.md) | **v2 (vigente)** — anonimização no servidor, upload seguro, isolamento, auditoria, checklist |
| [19_agentes_por_setor.md](19_agentes_por_setor.md) | **Agentes Especialistas por Setor**: Escudo de Entrada de ERP + análise setorial (Faturamento, Custos); roteamento e como plugar um novo |
| [CHANGELOG.md](CHANGELOG.md) | Histórico de versões (Keep a Changelog) |
| [ROADMAP.md](ROADMAP.md) | Próximos passos |

### POPs (procedimentos operacionais)

| POP | Para quem | Assunto |
|---|---|---|
| [pops/POP-01_operacao.md](pops/POP-01_operacao.md) | Usuário final | Enviar uma planilha e publicar o relatório (web) |
| [pops/POP-02_adaptar_novo_cliente.md](pops/POP-02_adaptar_novo_cliente.md) | Analista/dev | **Adaptar a base a uma planilha nova** (modelo `.toml`) |
| [pops/POP-03_manutencao_modulos.md](pops/POP-03_manutencao_modulos.md) | Dev | Adicionar tipo, gráfico, formato **ou Agente de setor** |

## Resumo em uma frase

`leitura → estrutura → (Agente de setor | modelo) → inferência/Cérebro → especificação → tratamento → indicadores → Analise → relatório HTML (web)`.
A lógica (`src/analise_planilha/`) não depende da interface; adaptar a um cliente é editar um `.toml` —
colunas **e regras de negócio** (exemplo completo: `dominio/modelos/garantia_atendimento.toml.sample`) — ou,
para um setor inteiro bagunçado de ERP, um **Agente** ([19](19_agentes_por_setor.md)).
