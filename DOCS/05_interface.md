# 05 · Interface (janela PyQt6)

Mesmo desenho do projeto **Garantia de Atendimento e Reembolso**. A janela só apresenta; toda regra vem
de `servico.py`. Código em `app/janela.py` (orquestração da tela), `app/componentes.py` (lista marcável,
tabelas, carga em thread) e `app/dialogo_*.py` (metas, salvar modelo, Modo I.A); cores em `app/tema.py`.
Módulo novo em `app/` também entra no `build.bat` (`--include-module=<nome>`).

```
┌ Análise de Planilhas ─────────────────────────────── (topo: título, "Relatório: X — análise local", vN) ┐
│ Relatório ▾         │ [KPI][KPI][KPI][KPI]  (cartões; a 1ª em verde)                                  │
│ ☐ Modo I.A  Config. │ 🔎 Buscar na tela (realça nesta aba sem filtrar)…   N resultado(s)  ⚙ Editar metas │
│ Arquivos            │ ┌ Resumo e achados │ Composição │ <dimensões…> │ Qualidade │ Base detalhada │ …  ┐ │
│  Pasta: dados\…\    │ │                                                                              │ │
│  ☑ 2025.xlsx        │ │                                                                              │ │
│  [Adicionar…] Recar.│ └──────────────────────────────────────────────────────────────────────────────┘ │
│ Período pela ▾      │                                                                                  │
│  De [..] até [..]   │                                                                                  │
│ <dimensão> buscar…  │                                                                                  │
│  ☐ valor A ☐ valor B│                                                                                  │
│ ☐ Anonimizar nomes  │                                                                                  │
│ [Aplicar filtros]   │                                                                                  │
│  Limpar filtros     │                                                                                  │
├─────────────────────┴──────────────────────────────────────────────────────────────────────────────────┤
│ status (info/sucesso/alerta/erro)   Salvar como modelo…  Abrir pasta de saída  DOCX  PDF  [Gerar HTML] │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Barra lateral (esquerda, rola)

- **Relatório** — um por modelo do cliente (`config/modelos/*.toml`) + "Sem modelo (inferência
  automática)". Cada relatório lê de **`dados\<pasta>\`** (chave `pasta` do modelo; padrão = o nome do
  modelo; "Sem modelo" = `dados\entrada\`).
- **Modo I.A** (opcional) — gera o modelo a partir das planilhas marcadas e o aplica; **Configurar…**
  define a chave (detecção automática). Ver [11](11_modo_ia.md). Ligado, o seletor de relatório trava.
- **Arquivos** — lista marcável das planilhas da pasta (temporários `~$…` ignorados); **várias marcadas
  são consolidadas** numa base só com «Arquivo de origem» (ex.: um arquivo por ano). **Adicionar…** copia
  planilhas para a pasta; **Recarregar** relê. **Aba** só aparece com UM arquivo de várias abas.
- **Período pela** — qual data recorta o período (todas as datas da base; a principal primeiro) + De/até.
- **Dimensões do relatório** — uma lista marcável com busca por dimensão (`[analise] dimensoes` do
  modelo, ou as deduzidas). **Nada marcado = todos.**
- **Anonimizar nomes** — a entidade (cliente/paciente) vira iniciais na tela e no relatório.
- **Aplicar filtros / Limpar filtros** (cartão fixo) — os filtros só valem ao clicar em Aplicar.

## Conteúdo (direita)

- **KPIs** — cartões (4–6 por linha conforme a largura).
- **Busca na tela** — realça (amarelo) o texto na aba atual, sem filtrar, e conta os resultados.
- **⚙ Editar metas** — estatística dos tempos (mediana/média/P90/P95), alvos com sentido (≥/≤) para os
  indicadores do relatório (taxas, tempos, ticket médio, registros) e observações → `config/metas.json`
  por relatório. Aparecem em "Resumo e achados" com ✔/✗ (e no HTML). Metas do `.toml` continuam valendo;
  as do diálogo prevalecem.

| Aba | Conteúdo |
|---|---|
| **Resumo e achados** | metas ✔/✗, observações do gestor, principais achados, leitura e qualidade, filtros aplicados, fonte |
| **Volume mensal**, **Composição**, uma por **dimensão**, **Tempos**, **Cruzamentos**, **Recorrência**, **Valores**, **Qualidade** | painéis da análise (tabelas ordenáveis, formatadas em pt-BR) |
| **Base detalhada** | o recorte linha a linha, formatado pelo tipo (R$, %, milhar), ordenável |
| **Resumo por coluna** | tipo, % preenchido, únicos e resumo de cada coluna |
| **Tipos** | tipo detectado de cada coluna, **editável**: trocar relê com o novo tipo |

## Rodapé

Status colorido (info/sucesso/alerta/erro) · **Salvar como modelo…** (cria um relatório `.toml` a partir das
colunas) · **Abrir pasta de saída** · **Gerar DOCX / Gerar PDF** (v0.2) · **Gerar HTML** (grava em
`saida/relatorio_<relatório>_AAAAMMDD_HHMMSS.html` e abre — [06](06_relatorio_html.md)).

## Fluxo interno (para quem for mexer)

- `_trocar_relatorio` → `_descobrir_arquivos` → `recarregar` (carga em **thread**: `CarregadorWorker`
  chama `servico.carregar` / `carregar_arquivos`) → `_carga_ok` → `_montar_filtros_da_fonte`,
  `_montar_tipos`, `aplicar`.
- `aplicar` → `servico.analisar(ds, filtros)` → `_render_kpis` + `_render_abas` + `_destacar`.
- Tipo trocado na aba Tipos → override → `recarregar`. Metas salvas → `aplicar`.
- `self._montando` evita disparos de sinal durante a construção.

## Política de front-end (QSS) — obrigatória

Regras vindas de bugs reais: caixas **pretas/cinza-escuras** (Windows em modo escuro) e listas
**espremidas/sobrepostas** na barra lateral.

**Defesa principal — tema claro forçado.** `tema.aplicar(app)` (chamado em `executar()`) fixa o estilo
**Fusion** + uma **paleta clara** derivada dos tokens (`tema.paleta_clara()`) antes do QSS. Isso tira o app
do controle do tema do SO: no Windows em modo escuro, sem isso, o Qt pinta de cinza tudo que o QSS não
cobre (menus, popups, calendário, `QMessageBox`, campos, itens desabilitados). **Nunca troque isso por só
`setStyleSheet`.**

> O bug de cor só aparece no **estilo nativo do Windows**: o backend `offscreen` (teste/CI) renderiza
> claro e não pega a regressão — valide a janela real (`python main.py`).

Ao mexer em `app/tema.py` ou adicionar widgets em `app/` (`janela.py`, `componentes.py`, diálogos):

1. **Cores e tamanhos só pelos tokens** (`PALETA`, `ESPACO`, `FONTE`, `RAIO`) e pela intenção
   (`setProperty("classe", "primario" | "secundario" | "discreto" | "kpi" | "cartao" | …)`); trocou a
   propriedade depois de montar → `tema.repolir(widget)`. O HTML de "Resumo e achados" usa `tema.PALETA`.
2. **Todo widget de área de rolagem tem `background` explícito no QSS** (`QTableView`, `QListWidget`,
   `QTextBrowser`…). Nunca confie na cor-base padrão.
3. **Conteúdo de `QScrollArea` montado dinamicamente:** o layout interno usa
   `setSizeConstraint(SetMinimumSize)` — senão a área encolhe o conteúdo em vez de rolar e os widgets
   se sobrepõem. Listas com altura **mínima** pelo nº de itens (`ListaMarcavel`).
4. **Texto sem espaço que pode ser longo** (caminhos) precisa poder quebrar (ex.: espaço de largura zero
   após `\`), senão alarga a barra lateral e esconde a rolagem.
5. **Valide antes de entregar:**
   ```powershell
   python -c "import sys; sys.path[:0]=['src','app']; from tema import folha_de_estilo; from PyQt6 import QtWidgets; a=QtWidgets.QApplication([]); a.setStyleSheet(folha_de_estilo()); print('QSS OK')"
   python -m pytest testes/test_janela.py      # janela com dados sintéticos (offscreen)
   python main.py                              # e OLHE a janela real
   ```

## Observações

- Os gráficos (SVG) ficam no relatório HTML; a janela mostra tabelas nativas ordenáveis.
- O assistente de modelo **cria/sobrescreve** um `.toml`; ainda não carrega um modelo existente para
  edição (ver [ROADMAP](ROADMAP.md)).
