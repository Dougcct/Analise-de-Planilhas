# 06 · Relatório HTML

O botão **Gerar HTML** (e a CLI `gerar_relatorio.py`) produzem um relatório autocontido em `saida/`, no
mesmo padrão do projeto Garantia de Atendimento. Código em `relatorio_html.py` + `templates/relatorio.html.j2`
(Jinja2) + `graficos.py` (SVG).

## Características

- **Autocontido e offline:** CSS, gráficos e scripts embutidos; **nenhum JavaScript de terceiros**. Abre
  em qualquer navegador sem internet e pode ser impresso / salvo como PDF. Leve (~100 KB para 200 contas,
  contra ~4,7 MB da versão anterior com Plotly).
- **Gráficos em SVG/HTML puro** (`graficos.colunas` para o volume mensal, `graficos.barras` para dimensões e
  composição) com tooltip (`data-tip`); as cores vêm de variáveis CSS e trocam no tema escuro.
- **Tema claro/escuro** (botão ◐ tema, lembrado no navegador; segue o sistema por padrão).
- **Filtro de período embutido** (quando o relatório tem datas): seletor **Período** no índice, ao lado do
  ◐ tema — ver abaixo.
- **Mesmos números da tela:** consome o mesmo objeto `Analise` da janela (contrato único).

## Filtro de período («períodos prontos»)

Relatórios com uma coluna de data (ex.: os financeiros HUNF, pela coluna «Mês») saem com um **seletor
Período** no topo. Ele troca a visão **no navegador**, como o ◐ tema — sem recalcular nada: cada visão é
**calculada no Python** e embutida, então os números batem sempre com a janela e não há JavaScript de
matemática (nem risco de divergir). Opções: **Todo o período**, **cada ano** e **Últimos 12 meses** (e o
**recorte atual**, como 1ª opção, se o usuário tiver estreitado o De/até antes de gerar).

- A **base detalhada** é renderizada **uma vez** (período todo), para não multiplicar o tamanho do arquivo.
  Ainda assim o HTML cresce com as visões (ex.: Custos HUNF ~1,8 MB com 5 períodos).
- Relatórios **sem datas** (ex.: Contas Convênio, cujo «Ano» vem do nome do arquivo) saem sem o seletor.
- Na CLI, `--inicio/--fim` viram a **1ª opção** (recorte atual) e os demais períodos são adicionados.

## Estrutura

Topo (título, data, versão, nº de arquivos) · índice fixo (com ◐ tema e, quando houver datas, o seletor
**Período**) · **Filtros aplicados** (+ fonte e avisos) · **Resumo e achados** (KPIs, metas do gestor ✔/✗,
observações, principais achados) · uma seção por painel (gráfico + "Ver tabela", ou tabela) · **Leitura e
qualidade** · **Base detalhada** (recorte linha a linha, recolhida; até 5.000 linhas) · **Metodologia** ·
rodapé LGPD. Com o seletor de período, tudo de **Filtros** até as seções de painéis é repetido por período
(a parte que muda); Leitura, Base e Metodologia são comuns.

## Nome e local

`saida/relatorio_<relatório>_AAAAMMDD_HHMMSS.html`. A pasta `saida/` **não** é versionada (LGPD).

## Gerar pela linha de comando (RPA/agendamento)

```powershell
python gerar_relatorio.py --listar                                   # relatórios e suas pastas
python gerar_relatorio.py --relatorio "Contas Convênio"
python gerar_relatorio.py --relatorio "Contas Convênio" --anonimizar --dim "Ano=2026"
python gerar_relatorio.py --inicio 2026-07-01 --fim 2026-07-31 --data-base "Data da solicitação"
```

Por código:

```python
from analise_planilha import config, relatorio_html, servico
ds = servico.carregar_arquivos(config.listar_arquivos(config.PASTA_ENTRADA))
destino = relatorio_html.gerar(servico.analisar(ds), "Título")
```

## Personalização

- Cores e layout: CSS no topo de `templates/relatorio.html.j2` (`--marca` = verde da marca; `--s1…--s4`
  = séries dos gráficos, com versão escura).
- Novo formato de saída (PDF/DOCX, previsto na v0.2): módulo que receba o mesmo `Analise` — **não
  recalcule números** — ligado aos botões *Gerar PDF/DOCX* (hoje desativados).

## LGPD

O relatório contém os dados da planilha (possivelmente pessoais/sensíveis) — o rodapé avisa. **Não
publicar** em serviços externos; use **Anonimizar nomes** antes de compartilhar.
