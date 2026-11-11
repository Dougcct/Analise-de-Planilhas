# Análise de Planilhas

Base única que lê a planilha do cliente como ela é, reconhece os tipos de dado, aplica as regras de
negócio do relatório e entrega indicadores prontos — sem reprogramar para cada planilha nova. O produto
é o **servidor web v3** (FastAPI + Docker): login, controle por setor e relatórios HTML no navegador.
Espelha o desenho do projeto **Garantia de Atendimento**. (O app desktop PyQt6 e o build .exe/Nuitka
foram removidos — ver [[relatorio-sem-exe-desktop]] na memória.)

## Comandos

```powershell
pip install -r requirements-dev.txt   # inclui requirements.txt + pytest/ruff + stack do servidor

docker compose up              # sobe o servidor WEB v2 (serviços: db, api; volumes: cargas, modelos) — é o produto
python scripts/gerar_relatorio.py --listar   # geração de relatório pela CLI (motor direto, sem servidor)

pytest                         # testes (pyproject: pythonpath=src+dominio p/ o pacote Agentes; testpaths=testes)
pytest testes/test_web.py      # um arquivo
ruff check .                   # lint (line-length 120)
```

## Mapa do repositório

- **`scripts/`** — utilitários e CLIs fora do produto: `gerar_relatorio.py` / `analisar.py` (relatório pelo
  motor, sem servidor), `gerar_feedback_nps.py` (dashboard Feedback/NPS → PDF), `painel-controle.py` (painel
  de operação), `aprender_setores.py`, e os `.bat` (`reiniciar-docker`, `reconstruir-docker` = rebuild da
  imagem, `enviar-github`). Rodam a partir da raiz (ex.: `python scripts/gerar_relatorio.py`).
- **`src/analise_planilha/`** — o motor (lógica pura, sem UI). Núcleo:
  - `leitura.py` `normalizacao.py` `tratamento.py` `estrutura.py` — ler e padronizar a planilha
  - `inferencia.py` `perfil.py` `indicadores.py` — deduzir tipos e calcular indicadores
  - `modelo.py` `modelos.py` `especificacao.py` — modelos do cliente (`dominio/modelos/*.toml`)
  - `financeiro.py` `matriz.py` `contas_convenio.py` — relatórios específicos
  - `feedback.py` — Dashboard **Feedback/NPS** (Diretoria): layout FIXO do CSV cru, fora do motor genérico. Ver [dominio/docs/20](dominio/docs/20_feedback_nps.md).
  - `relatorio_html.py` `graficos.py` `formatacao.py` — saída HTML
  - `ia.py` — Modo I.A (envia só estrutura anonimizada; config em `config/ia.toml`)
  - `cerebro/` — "Cérebro": substitui a dedução por tipo. `conhecimento.py` `papeis.py` `lexico.py`
    `serie.py` `setores.py` `modelo_auto.py` `layout.py` `grao.py`
- **`dominio/`** — "lugar único" das definições de negócio (ver `dominio/README.md`):
  - **`dominio/Agentes/`** — Agentes Especialistas por Setor, 100% determinístico. `base_agent.py`
    (Escudo de Entrada de ERP: caça cabeçalho, remove subtotal, blinda códigos, sanitiza nº PT-BR),
    `router.py` (`resolver`/`por_nome`/`candidatos`), e um subpacote por setor (`faturamento/`, `custos/`:
    `rules.py` + `config.toml`). Ligado em `servico.py` quando `modelo is None` (fallback transparente se o
    pacote faltar); limpa a planilha e injeta análise setorial na `Analise`. Nome `Agentes` mantido: importa
    como `from Agentes import …` (`dominio/` está no `pythonpath`/`sys.path`). Ver [dominio/docs/19](dominio/docs/19_agentes_por_setor.md).
  - **`dominio/modelos/`** — modelos de cliente (`*.toml`); no servidor é um volume Docker semeado no 1º start.
  - **`dominio/docs/`** — documentação numerada + POPs + CHANGELOG + ROADMAP.
- **`servidor/`** — backend FastAPI da v2 (Docker) — **o produto**. `web.py` (rotas web, o que o usuário
  usa), `app.py` (API v1 + monta a web), `bd.py`, `autenticacao.py`, `seguranca.py`, `repositorio.py`,
  `modelos_bd.py` / `modelos_fs.py`, `aprendizado.py` (base do Cérebro).
- **`templates/`** — `relatorio.html.j2` (relatório gerado) e `web/` (casca web da v2, Jinja).
- **`testes/`** — pytest (inclui `test_agentes.py`, `test_web.py`). **`config/`** — só `ia.toml` (Modo I.A);
  os modelos foram para `dominio/modelos/`.

## Convenções

- **Código, nomes e comentários em português.** Siga o estilo dos arquivos vizinhos.
- **LGPD:** `dados/` (relatorios, saida, setores, revisar) nunca é versionado e pode conter dado real.
  Ao ler dados reais, trabalhe só com a **estrutura** (nomes de coluna/tipos), nunca com os valores.
  O Modo I.A envia apenas estrutura anonimizada.
- O motor (`src/`) é lógica pura e não importa a UI (`servidor/`). Mantenha essa separação.
- Versão única em `src/analise_planilha/__init__.py` (`__version__`); o pyproject a lê de lá.

## Memória do projeto

Decisões de arquitetura e de produto ficam na memória automática (ver `MEMORY.md`), não aqui. Pontos
vivos: o produto é o **servidor web v3** (navegador), a direção é a **interface de controle por setor**
(login/papéis/isolamento) e o **Cérebro** substitui a dedução por tipo. Tipos de relatório de layout
fixo (ex.: **Feedback/NPS** da Diretoria, [dominio/docs/20](dominio/docs/20_feedback_nps.md)) desviam do
motor genérico. O app desktop PyQt6 e o
build/distribuição `.exe` (Nuitka/GitHub) foram **removidos** — só se usa o HTML/web.
