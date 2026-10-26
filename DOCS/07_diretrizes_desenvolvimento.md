# 07 · Diretrizes de desenvolvimento

## Ambiente

- Python 3.11+ (testado em 3.12). Dependências em `requirements.txt` / `requirements-dev.txt`.
- Ambiente virtual por projeto: `python -m venv .venv ; .venv\Scripts\activate`.
- Ao adicionar uma dependência, rode `pip install -r requirements.txt` com o `.venv` ativo.
- Executar sempre a partir da raiz do projeto.

## Organização e estilo

- Código, nomes e comentários em **português**, coerentes com o domínio.
- **Nenhum `import` de PyQt6 dentro de `src/analise_planilha`** — a lógica não conhece a interface.
- Interface (`app/janela.py`) só monta `Filtros` e chama `servico.py`. Estilo via `app/tema.py`
  (sem CSS espalhado; usar `setProperty("classe", ...)`). Siga a **Política de front-end (QSS)**
  de [05](05_interface.md#política-de-front-end-qss--obrigatória) — em especial: todo widget de
  área de rolagem (`QTextBrowser`, `QListWidget`, `QTableView`…) precisa de `background` explícito
  no QSS, senão o seletor universal `*` deixa o *viewport* preto.
- Regras ajustáveis (limiares, dicas de nome) ficam em `config.py`; estrutura de planilha, em `config/modelos/`.
- Todo número exibido passa por `formatacao.py` (pt-BR).
- PEP 8; linhas até 120 caracteres.

## Versionamento

- **SemVer** — `MAIOR.MENOR.CORREÇÃO`:
  - MAIOR: quebra o contrato `Analise`/modelos ou a definição de indicadores.
  - MENOR: nova funcionalidade compatível.
  - CORREÇÃO: ajuste de bug/regra sem mudar contrato.
- A versão vive em `src/analise_planilha/__init__.py` e aparece no rodapé do relatório.
- Toda mudança entra no [CHANGELOG.md](CHANGELOG.md) (formato *Keep a Changelog*) antes do release.
- Git sugerido: `main` estável; branches `feature/<nome>` e `fix/<nome>`; tag `vX.Y.Z` a cada release.
  Padrão de commit: Conventional Commits (`feat(inferencia): ...`, `fix(leitura): ...`, `docs: ...`).
  O `.gitignore` exclui `dados/` e `saida/` (LGPD).

## Testes

- Suíte offline em `testes/` (sem rede, sem dados reais): `python -m pytest`.
- Fixtures são planilhas **sintéticas** (`testes/conftest.py`) — nunca dados reais.
- Ao corrigir um bug, acrescentar o teste de regressão que falhava antes.
- Ao mudar uma regra de inferência, atualizar [03](03_motor_de_inferencia.md) **antes** e cobrir com teste.
- `python main.py --autoteste` exercita a pilha de análise sem janela (usado também no build do `.exe`).

## LGPD e segurança

- Planilhas e relatórios podem conter **dados pessoais e de saúde**. Ficam apenas em pastas com acesso
  restrito à equipe.
- Nunca versionar `dados/` nem `saida/`; nunca anexar base real em chamados/e-mails abertos.
- Não publicar o relatório HTML em serviços externos de hospedagem.
- Logs não devem registrar valores de células — apenas nomes de colunas, tipos e contagens.
