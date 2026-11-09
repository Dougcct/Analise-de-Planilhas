# 05 · Interface web (v2)

A interface é um **site** servido pelo FastAPI em `/web`, renderizado com Jinja2 (`templates/web/`). Toda
regra de negócio vem do motor (`servico.py`); as rotas ficam em `servidor/web.py`. Mesmo desenho do projeto
**Garantia de Atendimento e Reembolso**. Sobe com `docker compose up` → **http://localhost:8000/web**.

> Não há app desktop. A antiga janela PyQt6 foi descontinuada; o produto é este site.

## Login e papéis

- **Login** com ícone do produto; autoatendimento de senha: **Alterar senha** (`/web/trocar-senha`) e
  **Esqueci a senha** (`/web/esqueci`, que vira um pedido para o ADM).
- Papéis: **ADM** (tudo, todos os setores) e **gestor** (os seus setores). O **escopo por setor** isola os
  dados: cada equipe só vê o que é seu.

## Menu lateral (por papel)

- **Dashboard** — *Relatórios* (lista do setor), *Enviar planilha*, *Rascunhos*.
- **Solicitações** — *Abrir novo chamado*, *Minhas sugestões* (e, para o ADM, *Chamados*).
- **Administração** — *Usuários*, *Gerenciar Setores*, *Gerenciar Modelos*, *Gerenciar Relatórios*,
  *Base de conhecimento* (aparece conforme o papel).

## Ver um relatório (`/web/r/<slug>`)

- **Painel Executivo** no topo (KPIs, destaque e gráficos) — **editável** pelo gestor: escolher KPIs,
  título, layout e promover gráficos ao topo (`POST /web/r/<slug>/painel-executivo`, salvo em `config_exec`).
- **Filtros** na própria tela: período ("Período pela" = qual data recorta), dimensões (multi-seleção),
  faixas; **Anonimizar nomes** (entidade vira iniciais). Nada marcado = tudo.
- **Seções** = os painéis da `Analise` (tabelas ordenáveis em pt-BR + gráficos SVG). Com Agente de setor
  ativo, aparece a aba **"Análise de {setor}"** ([19](19_agentes_por_setor.md)).
- **Versão editável/curada** (`versao_editada`): reordenar/ocultar seções, títulos, blocos de nota, achados
  curados — para impressão/apresentação; pode ser **compartilhada** com outro setor.
- **Conteúdo completo / download** dos dados do recorte por rota própria (acesso escopado).

## Enviar e publicar (gestor) — a prévia

Fluxo guiado: **subir planilha → prévia → publicar** (ou descartar). Uma ou **várias** planilhas por envio
(fila de lote). Na prévia (`/web/enviar/previa/<id>`):

- **Modelo**: vínculo automático quando combina; dá para trocar (`/modelo`) ou ficar "sem modelo".
- **Agente de setor** (sem modelo): *Automático* / escolher / *Nenhum* (`/agente`) — [19](19_agentes_por_setor.md).
- **O que o Cérebro entendeu**: papel/grão de cada coluna com selos de situação (✓ reconhecida /
  ⚠ adivinhada / ❓ ignorada / LGPD) e **correção de papéis** (`/reanalisar`), que vira aprendizado ao publicar.
- **Prévia do relatório** renderizada (nº de registros, painéis) antes de gravar.
- **Publicar** (`/publicar`) torna o relatório visível; **descartar** (`/descartar`) joga fora o rascunho.
  Reenviar a mesma planilha (mesmo nome) substitui a versão anterior (vira backup); planilhas diferentes somam.

## Chamados (sugestões e bugs)

Botão **«Sugestões»** em todas as telas: qualquer usuário abre um chamado (💡 sugestão / 🐛 bug) com texto,
**print** (anexar imagem ou colar `Ctrl`+`V`) e **anexo de arquivo** opcional (ex.: a planilha). Cada chamado
é uma conversa (ADM ↔ colaborador) com selo de mensagem nova. Anexos ficam no volume (nome UUID), nunca no
banco, servidos só ao ADM e ao autor (LGPD).

## Administração

- **Usuários** (criar, papel, setores, redefinir senha), **Setores** (e importar), **Relatórios**,
  **Modelos** (listar/gerenciar os `.toml`), **Base de conhecimento** (o que o Cérebro aprendeu, por contexto).

## Para quem for mexer (dev)

- Rotas e telas: `servidor/web.py` + `templates/web/` (`base.html` é a casca; uma página por função).
- O dataset de cada carga/relatório é montado em `servidor/app.py` (`_dataset_da_carga` /
  `_dataset_consolidado`, com cache) chamando `servico.carregar` / `carregar_varios`.
- Aprendizado do Cérebro e contexto por setor: `servidor/aprendizado.py`.
- Nunca coloque regra de negócio na rota: a interface só monta `Filtros`/parâmetros e chama `servico.py`.
