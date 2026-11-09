# 02 · Arquitetura

Três camadas, com uma regra de ouro: **o motor (`src/analise_planilha/`) é lógica pura e não importa a
interface.** O servidor web e as CLIs consomem o mesmo motor → os números são idênticos em qualquer saída.

```
┌ Interface ───────────────────────────────────────────────────────────────────┐
│ servidor/  (FastAPI + Docker) — o PRODUTO: login, setores, envio/prévia, HTML  │
│ gerar_relatorio.py · analisar.py — CLIs (motor direto, sem servidor)           │
└───────────────────────────────┬───────────────────────────────────────────────┘
                                 │  chama
┌ Motor ─────────────────────────▼───────────────────────────────────────────────┐
│ src/analise_planilha/  — leitura → inferência/Cérebro → especificação →          │
│                          tratamento → indicadores → Analise → relatório HTML     │
│ Agentes/  — Agentes de setor (Escudo de ERP + análise setorial) plugados no motor │
└──────────────────────────────────────────────────────────────────────────────────┘
```

## Fluxo de dados

```
planilha enviada (ou dados/<relatório>/*.xlsx|ods|csv)
        │  leitura.py        formato, encoding, separador, abas, células mescladas → grade bruta
        │  estrutura.py      acha a tabela: cabeçalho, seções, totais, notas, escolhe a aba → diagnóstico
        ▼
  base bruta
        │  Agentes/ (se modelo is None e a planilha é de um setor conhecido — ver 19):
        │    Escudo de Entrada limpa o export de ERP (cabeçalho real, subtotais, códigos, números PT-BR)
        │  modelo.py          (se houver modelo) mapeia cabeçalhos → canônicos e fixa tipos; abas="todas" consolida
        ▼
        │  inferencia.py      tipo semântico de cada coluna (modelo manda; resto inferido)
        │  cerebro/           (sem modelo) papel de cada coluna, grão e layout; aprende com as correções
        ▼
  DataFrame tipado + Esquema
        │  especificacao.py   PAPÉIS e REGRAS DE NEGÓCIO: do .toml, do Cérebro ou automáticas
        │  tratamento.py      grafias, classificações, taxas, tempos (dias úteis/meta), qualidade por linha
        ▼
  Dataset { df tratado, esquema, spec, problemas, meta, agente }
        │  indicadores.py     (por recorte) KPIs, quebras, tempos, cruzamentos, recorrência, achados, metas
        │  perfil.py          alertas genéricos de qualidade, resumo por coluna
        │  Agentes/           (se há agente) achados + painéis + alertas do SETOR são dobrados na Analise
        ▼
  Analise { kpis, achados, metas, paineis (tabelas + gráficos), alertas, filtros_desc }
        │
        └─ relatorio_html.py  relatório HTML autocontido (Jinja2 + gráficos SVG, sem JS de terceiros)
```

`servico.py` orquestra todas as etapas e é o **único** ponto chamado pela interface e pelas CLIs. As metas
do gestor (`metas.py`, `config/metas.json`) entram em `servico.analisar` (estatística de tempo + alvos ✔/✗).

## Camadas

```
servidor/               servidor web (FastAPI + Docker) — o produto
  web.py                rotas do site (o que o usuário usa: login, relatórios, envio/prévia, admin, chamados)
  app.py                monta o FastAPI (API + site), caches de dataset/modelo, acesso/escopo
  bd.py                 engine do banco (Postgres no container; SQLite nos testes) + migração leve de colunas
  modelos_bd.py         tabelas ORM (usuários, setores, relatórios, cargas, sugestões…)
  modelos_fs.py         modelos de cliente no sistema de arquivos (listar/ler .toml)
  autenticacao.py       sessão, papéis (ADM/gestor), escopo por setor
  seguranca.py          hashing de senha, validações
  repositorio.py        consultas escopadas por setor (isolamento de dados)
  aprendizado.py        ponte servidor ↔ Cérebro (base aprendida, contexto, correções da prévia)
templates/web/          casca web (Jinja2): base, login, relatório, prévia, admin, chamados
templates/relatorio.html.j2   o relatório HTML gerado

src/analise_planilha/   motor (lógica pura; nenhum import de servidor/)
Agentes/                Agentes Especialistas por Setor (ver 19)
gerar_relatorio.py      CLI: relatório HTML com filtros          analisar.py  CLI: resumo da inferência
```

**Nenhum `import` do servidor existe dentro de `src/analise_planilha`.** A lógica roda igual com ou sem o
servidor — é o que as CLIs e os testes exercitam. Trocar/estender a interface afeta só `servidor/` e `templates/`.

## Módulos de `src/analise_planilha/`

| Módulo | Responsabilidade |
|---|---|
| `__init__.py` | `__version__` — fonte única da versão |
| `config.py` | Caminhos, limiares de inferência, dicas de nome |
| `modelos.py` | Contratos (dataclasses): `ColunaInferida`, `Esquema`, `Dataset`, `Analise`, `Filtros`, `KPI`, `Painel`, `Alerta`, constantes de tipo |
| `normalizacao.py` | Conversões pt-BR/ISO (número, data, booleano), chaves de comparação, nomes de coluna |
| `leitura.py` | Lê o arquivo (CSV robusto, Excel com mesclas, ODS/XLS), limpa células, escolhe a aba |
| `estrutura.py` | Leitura estrutural: localiza a tabela na grade e explica o que descartou ([09](09_leitura_estrutural.md)) |
| `modelo.py` | Carrega/salva modelos de cliente (`.toml`); mapeia cabeçalhos → canônicos |
| `inferencia.py` | Cascata de detecção de tipo semântico; aplica overrides e tipos do modelo |
| `cerebro/` | "Cérebro": sem modelo, decide papel/grão/layout e aprende com as correções da prévia |
| `especificacao.py` | Papéis e regras (taxas, tempos, classificações, cruzamentos, qualidade, metas) — do modelo, do Cérebro ou automáticas |
| `tratamento.py` | Aplica a especificação: grafias, classificações, taxas, tempos, dias úteis, qualidade por linha |
| `indicadores.py` | Motor genérico de indicadores de negócio e achados ([10](10_indicadores.md)) |
| `financeiro.py` / `matriz.py` | Relatórios de série mensal (conta × mês): Faturamento/Custos/DRE ([13](13_financeiro_hunf.md)) |
| `contas_convenio.py` | Leitor do relatório «Contas Convênio» (formulário em blocos → tabela) ([12](12_contas_convenio.md)) |
| `perfil.py` | Alertas genéricos de qualidade, resumo por coluna |
| `metas.py` | Metas do gestor por relatório (`config/metas.json`) |
| `ia.py` | Modo I.A (opcional): gera o modelo por API de LLM ([11](11_modo_ia.md)) |
| `graficos.py` / `formatacao.py` | Gráficos SVG puro; formatação pt-BR (`formatar(valor, formato)`) |
| `relatorio_html.py` | Relatório HTML (`templates/relatorio.html.j2`) |
| `servico.py` | Orquestração (carregar/consolidar → analisar; filtros, "período pela", anonimização, metas, Agente) |

## Agentes de setor (`Agentes/`, na raiz)

Pacote **top-level** (fora de `src`), 100% determinístico. Quando `modelo is None`, `servico.py` pergunta ao
`router` qual agente assume a planilha; se nenhum casa (ou o pacote falta), roda como hoje — **fallback
transparente**. Um agente (a) limpa o export de ERP (Escudo de Entrada) e (b) acrescenta a análise do setor
à `Analise`. Detalhes, roteamento e como plugar um novo: [19](19_agentes_por_setor.md).

## Decisões de projeto

- **`Analise` como contrato.** `servico.analisar` devolve um objeto único; web e relatório HTML consomem o
  mesmo objeto → números idênticos em qualquer lugar.
- **Modelo editável fora do código.** A estrutura de cada cliente mora em `config/modelos/*.toml`, não em `if`.
- **Gráficos sem JavaScript de terceiros.** SVG puro: abre offline, imprime/vira PDF. Ver [06](06_relatorio_html.md).
- **Isolamento por setor.** Consultas escopadas (`repositorio.py`) e papéis garantem que cada equipe só vê o
  que é seu ([18](18_seguranca_lgpd_v2.md)).
- **Agente ≠ reescrever o motor.** O agente usa o motor como ferramenta; o valor dele é ERP bagunçado + análise setorial.

## Como estender (resumo — detalhes no [POP-03](pops/POP-03_manutencao_modulos.md))

- **Nova coluna/cliente:** criar/editar `config/modelos/<cliente>.toml` ([04](04_modelo_de_cliente.md)).
- **Nova regra de negócio (taxa, tempo, classificação…):** no `.toml` — sem código.
- **Novo tipo de regra/indicador:** campo em `especificacao.py`, cálculo em `tratamento.py` (por linha) ou
  `indicadores.py` (agregado); documentar em [10](10_indicadores.md) e testar.
- **Novo tipo semântico:** detector em `inferencia.py`.
- **Novo Agente de setor:** subpacote em `Agentes/<setor>/` (`rules.py` + `config.toml`) + 1 linha no router ([19](19_agentes_por_setor.md)).
- **Novo formato de saída:** novo módulo que consome `Analise` (nunca recalcula números).
