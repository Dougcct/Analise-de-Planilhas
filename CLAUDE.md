# Análise de Planilhas

Base única que lê a planilha do cliente como ela é, reconhece os tipos de dado, aplica as regras de
negócio do relatório e entrega indicadores prontos — sem reprogramar para cada planilha nova. O produto
é o **servidor web v2** (FastAPI + Docker): login, controle por setor e relatórios HTML no navegador.
Espelha o desenho do projeto **Garantia de Atendimento**. (O app desktop PyQt6 e o build .exe/Nuitka
foram removidos — ver [[relatorio-sem-exe-desktop]] na memória.)

## Comandos

```powershell
pip install -r requirements-dev.txt   # inclui requirements.txt + pytest/ruff + stack do servidor

docker compose up              # sobe o servidor WEB v2 (serviços: db, api; volumes: cargas, modelos) — é o produto
python gerar_relatorio.py --listar    # geração de relatório pela CLI (motor direto, sem servidor)

pytest                         # testes (config no pyproject: pythonpath=src, testpaths=testes)
pytest testes/test_web.py      # um arquivo
ruff check .                   # lint (line-length 120)
```

## Mapa do repositório

- **`analisar.py` / `gerar_relatorio.py`** — entradas de CLI (geram o relatório sem servidor).
- **`src/analise_planilha/`** — o motor (lógica pura, sem UI). Núcleo:
  - `leitura.py` `normalizacao.py` `tratamento.py` `estrutura.py` — ler e padronizar a planilha
  - `inferencia.py` `perfil.py` `indicadores.py` — deduzir tipos e calcular indicadores
  - `modelo.py` `modelos.py` `especificacao.py` — modelos do cliente (`config/modelos/*.toml`)
  - `financeiro.py` `matriz.py` `contas_convenio.py` — relatórios específicos
  - `relatorio_html.py` `graficos.py` `formatacao.py` — saída HTML
  - `ia.py` — Modo I.A (envia só estrutura anonimizada; config em `config/ia.toml`)
  - `cerebro/` — "Cérebro": substitui a dedução por tipo. `conhecimento.py` `papeis.py` `lexico.py`
    `serie.py` `setores.py` `modelo_auto.py` `layout.py` `grao.py`
- **`servidor/`** — backend FastAPI da v2 (Docker) — **o produto**. `web.py` (rotas web, o que o usuário
  usa), `app.py` (API v1 + monta a web), `bd.py`, `autenticacao.py`, `seguranca.py`, `repositorio.py`,
  `modelos_bd.py` / `modelos_fs.py`, `aprendizado.py` (base do Cérebro).
- **`templates/`** — `relatorio.html.j2` (relatório gerado) e `web/` (casca web da v2, Jinja).
- **`testes/`** — pytest. **`DOCS/`** — documentação numerada (01…16) + POPs + CHANGELOG.

## Convenções

- **Código, nomes e comentários em português.** Siga o estilo dos arquivos vizinhos.
- **LGPD:** `dados/`, `saida/`, `Setores/`, `_revisar/` nunca são versionados e podem conter dado real.
  Ao ler dados reais, trabalhe só com a **estrutura** (nomes de coluna/tipos), nunca com os valores.
  O Modo I.A envia apenas estrutura anonimizada.
- O motor (`src/`) é lógica pura e não importa a UI (`app/`). Mantenha essa separação.
- Versão única em `src/analise_planilha/__init__.py` (`__version__`); o pyproject a lê de lá.

## Memória do projeto

Decisões de arquitetura e de produto ficam na memória automática (ver `MEMORY.md`), não aqui. Pontos
vivos: o produto é o **servidor web v2** (navegador), a direção é a **interface de controle por setor**
(login/papéis/isolamento) e o **Cérebro** substitui a dedução por tipo. O app desktop PyQt6 e o
build/distribuição `.exe` (Nuitka/GitHub) foram **removidos** — só se usa o HTML/web.
