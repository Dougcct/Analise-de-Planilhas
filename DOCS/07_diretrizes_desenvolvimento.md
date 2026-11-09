# 07 · Diretrizes de desenvolvimento

## Ambiente

- Python 3.11+ (testado em 3.12). Dependências em `requirements.txt` / `requirements-dev.txt`
  (o `-dev` inclui a stack do servidor + pytest/ruff).
- Ambiente virtual por projeto: `python -m venv .venv ; .venv\Scripts\activate`.
- O **produto** sobe com `docker compose up` (serviços `db` + `api`). Para o motor isolado, use as CLIs
  (`python gerar_relatorio.py`, `python analisar.py`).
- Executar sempre a partir da raiz do projeto.

## Organização e estilo

- Código, nomes e comentários em **português**, coerentes com o domínio e com os arquivos vizinhos.
- **Nenhum `import` de interface dentro de `src/analise_planilha`** — o motor é lógica pura. O servidor
  (`servidor/`) e as CLIs consomem o motor; a interface só monta parâmetros/`Filtros` e chama `servico.py`.
- O pacote `Agentes/` (raiz) usa o motor como ferramenta e importa dele por caminho absoluto
  (`from analise_planilha...`); dentro do pacote, imports relativos.
- Regras ajustáveis (limiares, dicas de nome) ficam em `config.py`; estrutura de planilha, em
  `config/modelos/*.toml`; vocabulário de setor, no `config.toml` do agente.
- Todo número exibido passa por `formatacao.py` (pt-BR). Gráficos em SVG puro (`graficos.py`), **sem JS de terceiros**.
- PEP 8; linhas até 120 caracteres. `ruff check .` antes de abrir PR.

## Versionamento

- **SemVer** — `MAIOR.MENOR.CORREÇÃO`:
  - **MAIOR**: quebra o contrato `Analise`/`Esquema`/modelo, a definição de indicadores, ou o esquema do
    banco de forma incompatível.
  - **MENOR**: nova funcionalidade compatível (ex.: um novo Agente de setor).
  - **CORREÇÃO**: ajuste de bug/regra sem mudar contrato.
- Fonte única da versão: `src/analise_planilha/__init__.py` (`__version__`); o `pyproject.toml` lê de lá.
  Aparece no rodapé do relatório.
- Toda mudança entra no [CHANGELOG.md](CHANGELOG.md) (formato *Keep a Changelog*) antes do release.
- Git: `main` estável; branches `feature/<nome>` e `fix/<nome>`; tag `vX.Y.Z` a cada release. Commits em
  Conventional Commits (`feat(agentes): ...`, `fix(leitura): ...`, `docs: ...`). O `.gitignore` exclui
  `dados/`, `saida/`, `Setores/` (LGPD).

## Testes

- Suíte offline em `testes/` (sem rede, sem dados reais): `python -m pytest`. Um arquivo:
  `python -m pytest testes/test_web.py`.
- Fixtures são planilhas/dados **sintéticos** (`testes/conftest.py`) — nunca dados reais. O servidor de teste
  usa SQLite (via `DATABASE_URL`); o banco nasce do modelo atual.
- Ao corrigir um bug, acrescente o teste de regressão que falhava antes.
- Ao mudar uma regra de inferência, atualize [03](03_motor_de_inferencia.md) **antes** e cubra com teste.
- Ao mexer em Agentes, cubra em `testes/test_agentes.py` (Escudo, roteamento, métricas) — ver [19](19_agentes_por_setor.md).

## Banco de dados (migração leve)

Não há Alembic. Colunas novas em tabelas já existentes entram em `servidor/bd.py` (`_migrar_colunas_leves`,
um `ALTER TABLE ADD COLUMN` idempotente guiado por um dicionário `desejadas`). O `create_all` cria as tabelas
novas; a migração leve cobre os bancos de container que já têm dados.

## LGPD e segurança

- Planilhas e relatórios podem conter **dados pessoais e de saúde**. Ficam só atrás da rede interna, com
  acesso escopado por setor.
- Nunca versionar `dados/`, `saida/`, `Setores/`; nunca anexar base real em chamados/e-mails abertos.
- Não publicar o relatório HTML em serviços externos de hospedagem.
- Logs não registram valores de células — apenas nomes de colunas, tipos e contagens. O Modo I.A envia só
  estrutura anonimizada. Detalhes em [18](18_seguranca_lgpd_v2.md).
