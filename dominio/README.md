# dominio/ — definições de negócio num lugar só

Este é o ponto central para **achar e editar** o que define *como cada setor/relatório é analisado*.
Reúne os três artefatos de negócio que ficam em disco:

| Subpasta | O que é | Quando mexer |
|---|---|---|
| **`Agentes/`** | **Código** dos Agentes Especialistas por Setor (determinístico): Escudo de Entrada de ERP + análise setorial. Um subpacote por setor (`faturamento/`, `custos/` = `rules.py` + `config.toml`). | Criar/ajustar um agente de setor. Guia: [docs/19](docs/19_agentes_por_setor.md). |
| **`modelos/`** | **Config** dos modelos de cliente (`*.toml`): colunas, tipos, sinônimos e regras de negócio de cada relatório. No servidor, é um **volume Docker** semeado no 1º start. | Adaptar a base a uma planilha nova. Guia: [docs/04](docs/04_modelo_de_cliente.md) e [docs/pops/POP-02](docs/pops/POP-02_adaptar_novo_cliente.md). |
| **`docs/`** | **Documentação** do projeto: visão geral, arquitetura, motor, POPs, CHANGELOG, ROADMAP. | Documentar. Índice: [docs/README.md](docs/README.md). |

## Detalhes

- **`Agentes/`** mantém o nome `Agentes` (maiúsculo) de propósito: o import continua
  `from Agentes import …` porque `dominio/` está no `pythonpath` (pytest) e no `sys.path` do servidor/CLIs.
  No container Docker os arquivos vão para `/app/dominio/Agentes`.
- **`modelos/`** é lido pelo motor via `config.PASTA_MODELOS` (`src/analise_planilha/config.py`). No Docker,
  `dominio/modelos` é um volume editável em runtime, semeado a partir da cópia baked (`_seed_modelos`) na
  primeira subida (ver `servidor/app.py._semear_modelos`).

## E "relatórios" e "setores"?

Essas duas coisas, no dia a dia, **não são arquivos** — são geridas pela **web**, em *Administração*:

- **Relatórios** e **Setores** (centros de custo, usuários, acessos) vivem no **banco de dados** (Postgres).
  Gerencie em `/web/admin/...` (Gerenciar Relatórios, Gerenciar Setores).
- Os **dados reais** (planilhas enviadas, treino do Cérebro, relatórios gerados) ficam **fora do Git** por
  LGPD: tudo sob `dados/` na raiz do projeto — nunca versionados.
