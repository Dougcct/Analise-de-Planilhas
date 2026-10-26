# 02 · Arquitetura

## Fluxo

```
dados/<relatório>/*.xlsx|ods|csv   — uma subpasta por relatório (modelo); várias planilhas = consolidadas
        │  leitura.py        formato, encoding, separador, abas, células mescladas → grade bruta
        │  estrutura.py      acha a tabela: cabeçalho (1 ou 2 níveis), seções, totais, notas,
        │                    cabeçalho repetido, outra tabela; escolhe a aba; gera diagnóstico
        │                    → DataFrame bruto + MetaLeitura (confiança, descartes, diagnóstico)
        ▼
  base bruta
        │  modelo.py         (se houver modelo) mapeia cabeçalhos → rótulos canônicos e fixa tipos;
        │                    com abas="todas", consolida as abas com o mesmo layout
        ▼
        │  inferencia.py     decide o tipo semântico de cada coluna (modelo manda; resto é inferido)
        ▼
  DataFrame tipado + Esquema (coluna → tipo, confiança, evidências)
        │  especificacao.py  PAPÉIS e REGRAS DE NEGÓCIO: do .toml ou deduzidas dos tipos
        │  tratamento.py     grafias, classificações, taxas, tempos (dias úteis/meta), qualidade por linha
        ▼
  Dataset { df tratado, esquema, spec, problemas, meta }
        │  indicadores.py    (por recorte) KPIs, quebras, tempos, cruzamentos, recorrência, achados, metas
        │  perfil.py         alertas genéricos de qualidade, resumo por coluna
        ▼
  Analise  { kpis, achados, metas, paineis (tabelas + gráficos), alertas, filtros_desc }
        │
        ├─ app/janela.py          interface desktop (desenho do projeto Garantia de Atendimento)
        └─ relatorio_html.py      relatório HTML autocontido (Jinja2 + gráficos SVG, sem JS de terceiros)
```

`servico.py` orquestra todas as etapas e é o **único** ponto chamado pela interface, pelas CLIs
(`gerar_relatorio.py`, `analisar.py`) e pelo autoteste (`main.py --autoteste`). As metas do gestor
(`metas.py`, `config/metas.json`) entram em `servico.analisar` (estatística de tempo + alvos ✔/✗).

## Camadas

```
main.py                 ponto de entrada; --autoteste faz o diagnóstico sem janela
app/janela.py           janela principal PyQt6: orquestra a tela (só apresentação; nenhuma regra de negócio)
app/componentes.py      peças reutilizáveis: lista marcável, tabela de DataFrame, carga em thread, layout
app/dialogo_metas.py    diálogo "⚙ Editar metas" (grava config/metas.json)
app/dialogo_modelo.py   diálogo "Salvar como modelo…" (gera o .toml do cliente)
app/dialogo_ia.py       diálogo "Configurar Modo I.A" + thread que chama a API
app/atualizador.py      atualização automática do .exe na tela (lógica em analise_planilha/atualizacao.py)
app/tema.py             tokens de cor/espaço/fonte e folha de estilo (a marca fica num lugar só)
templates/              relatório HTML (Jinja2)
src/analise_planilha/   lógica de análise (independente de interface)
```

**Nenhum `import` de PyQt6 existe dentro de `src/analise_planilha`.** A lógica roda igual com ou sem
janela — é o que o autoteste e os testes exercitam. Trocar a interface (ex.: outra UI) afeta só `app/`.

## Módulos de `src/analise_planilha/`

| Módulo | Responsabilidade |
|---|---|
| `__init__.py` | `__version__` — fonte única da versão |
| `config.py` | Caminhos (inclusive quando compilado), limiares de inferência, dicas de nome |
| `modelos.py` | Contratos (dataclasses): `ColunaInferida`, `Esquema`, `Dataset`, `Analise`, `Filtros`, KPI, Painel, Alerta, e as constantes de tipo |
| `normalizacao.py` | Conversões pt-BR/ISO (número, data, booleano), chaves de comparação, nomes de coluna |
| `leitura.py` | Lê o arquivo (CSV robusto, Excel com mesclas, ODS/XLS), limpa células, escolhe a aba |
| `estrutura.py` | Leitura estrutural: localiza a tabela de dados na grade e explica o que descartou ([09](09_leitura_estrutural.md)) |
| `modelo.py` | Carrega/salva modelos de cliente (`.toml`); mapeia cabeçalhos → canônicos |
| `inferencia.py` | Cascata de detecção de tipo semântico; aplica overrides e tipos do modelo |
| `especificacao.py` | Papéis (entidade, dimensões, medidas, datas) e regras (taxas, tempos, classificações, cruzamentos, qualidade, metas) — do modelo ou automáticas ([04](04_modelo_de_cliente.md)) |
| `tratamento.py` | Aplica a especificação: unifica grafias, classifica, marca taxas, calcula tempos e dias úteis (feriados), levanta ocorrências por linha |
| `indicadores.py` | Motor genérico de indicadores de negócio e achados ([10](10_indicadores.md)) |
| `perfil.py` | Alertas genéricos de qualidade, resumo por coluna, tabela de tipos |
| `contas_convenio.py` | Leitor do relatório «Contas Convênio» (formulário em blocos → tabela) ([12](12_contas_convenio.md)) |
| `metas.py` | Metas do gestor por relatório (`config/metas.json`): catálogo, persistência, aplicação na especificação |
| `ia.py` | Modo I.A (opcional): gera o modelo por API de LLM ([11](11_modo_ia.md)) |
| `graficos.py` | Gráficos SVG/HTML puro para o relatório (colunas, barras; sem JavaScript de terceiros) |
| `formatacao.py` | Formatação pt-BR; `formatar(valor, formato)` usado pela janela e pelo HTML |
| `relatorio_html.py` | Relatório HTML (template `templates/relatorio.html.j2`): filtros, resumo e achados, painéis, qualidade, base, metodologia |
| `servico.py` | Orquestração (carregar/consolidar arquivos → analisar; filtros, "período pela", anonimização, metas) |

## Decisões de projeto

- **`Analise` como contrato.** `servico.analisar` devolve um objeto único; a janela e o relatório HTML
  consomem o mesmo objeto → números idênticos na tela e no relatório.
- **Modelo editável fora do código.** A estrutura de cada cliente mora em `config/modelos/*.toml`, não
  em `if` no código.
- **Gráficos sem JavaScript de terceiros.** SVG puro no relatório: abre offline, imprime/vira PDF e o
  `.exe` não embute motor web nem Plotly (fica leve). A janela mostra tabelas nativas. Ver [06](06_relatorio_html.md).
- **Mesmo desenho do projeto Garantia de Atendimento** (interface, tema, metas do gestor, relatório,
  CLI, autoteste) — a equipe usa as duas ferramentas do mesmo jeito.
- **Caminhos resolvidos para o `.exe`.** `config.py` detecta execução compilada e usa a pasta do binário
  para `dados/`, `saida/` e `config/` (graváveis). Ver [08](08_build_e_distribuicao.md).

## Como estender (resumo — detalhes no POP-03)

- **Nova coluna/cliente:** criar/editar `config/modelos/<cliente>.toml` ([04](04_modelo_de_cliente.md)).
- **Nova regra de negócio (taxa, tempo, classificação…):** no `.toml` do cliente — sem código.
- **Novo tipo de regra/indicador:** campo em `especificacao.py`, cálculo em `tratamento.py` (por linha) ou
  `indicadores.py` (agregado), documentar em [10](10_indicadores.md) e testar em `testes/test_indicadores.py`.
- **Novo tipo semântico:** adicionar detector em `inferencia.py`.
- **Novo formato de saída:** novo módulo que consome `Analise` (nunca recalcula números).
