# Changelog

Formato [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) · [SemVer](https://semver.org/lang/pt-BR/)

## [3.2.1] — 2026-11-11

### Corrigido
- **Consulta SQL ao MV — datas (ORA-01843 «not a valid month»).** No modo thick a sessão herdava um
  `NLS_DATE_FORMAT` genérico (mês por extenso), então `01/11/2026` quebrava. Toda conexão passa a fixar
  NLS pt-BR (`DD/MM/YYYY`, idioma Português) — ajustável por `MV_NLS_SESSAO`. Doc [21](21_banco_mv_e_migracao.md).

## [3.2.0] — 2026-11-11

Ponte do banco do MV para os relatórios: o que sai da Consulta SQL vira relatório do sistema.

### Adicionado
- **Enviar resultado do MV para um relatório** (tela «Consulta SQL (MV)»): o SELECT é re-executado no
  banco, o resultado vira CSV e cria uma **carga** — relatório novo (setor + modelo) ou atualizando um
  existente — caindo na mesma prévia/publicação das planilhas. Substitui o export manual. Rota
  `POST …/enviar`, helper `_gravar_uma_carga`.
- **Consultas salvas** (tabela `consultas_mv`): guardar um SELECT + ambiente com nome para re-rodar com
  um clique («Carregar»); rotas `…/salvar` (upsert pelo nome, com a guarda `validar_select`) e `…/excluir`.
- **Relatório vivo / atualização agendada** — desenhado para o futuro (doc [21](21_banco_mv_e_migracao.md) §2.C): o relatório
  lembra a consulta e se atualiza sozinho (sob demanda ou por horário). Ainda **não** implementado.

## [3.1.1] — 2026-11-11

### Corrigido
- **Consulta SQL ao MV — autenticação (DPY-3015).** Contas do Oracle com verificador de senha antigo/não
  suportado (ex.: `0x939`) falhavam no modo *thin* do `oracledb`. A imagem passa a trazer o **Oracle
  Instant Client** (Basic Light) e `mv._init_thick()` liga o **modo thick** antes de conectar, aceitando
  qualquer verificador; sem o client (dev/CI) o driver cai em thin automaticamente. Doc [21](21_banco_mv_e_migracao.md).

## [3.1.0] — 2026-11-11

Novo tipo de dashboard (Manifestações/Ouvidoria), redesenho do Feedback, Consulta SQL ao banco do MV e
um ajuste no DRE pedido por chamado.

### Adicionado
- **Consulta SQL ao MV (Oracle)** — tela ADM «Consulta SQL (MV)» (`/web/admin/consulta-sql`): conexões
  Teste/Produção, testar conexão, editor SQL com realce **offline** e Executar/**F8**, resultados em tabela.
  Motor `automacao/mv.py` (driver `oracledb` thin; guarda só-leitura: bloqueia DML/DDL, 2º comando, `INTO`,
  `FOR UPDATE`, limita linhas, nunca faz commit), tabela `conexoes_mv`, atalho no painel. Doc [21](21_banco_mv_e_migracao.md).
- **Dashboard Manifestações / Ouvidoria** — 2º tipo de layout fixo (setor Diretoria): KPIs por tipo
  (Elogio/Reclamação/Conduta Ética), rosca e feed detalhado. Selecionável no «Modelo de análise».
- **Registro de dashboards** (`src/analise_planilha/dashboards.py`) — tipos de layout fixo (feedback,
  manifestacoes) viram módulos plugáveis com interface uniforme; o servidor não conhece cada um.
- **Migração da Docker** — mapeada para o futuro (doc 21 + botão «Migrar Docker (planejado)» no painel).

### Alterado
- **Feedback/NPS** — redesenho (tema escuro, Tailwind + Chart.js): NPS em barras, tempo/expectativas em
  rosca + cartões, gráficos com hover; Total de Atendimentos editável no cabeçalho.
- **DRE** (chamado «separar a receita da despesa») — no perfil DRE o painel «20 maiores contas no período»
  (que misturava receita + e despesa −) virou dois: «Maiores receitas» e «Maiores despesas».

## [3.0.0] — 2026-11-11

Novo **tipo de relatório Feedback / NPS** para o setor **Diretoria**: reproduz um dashboard de layout
FIXO (modelo em PDF da pesquisa de pacientes) alimentado pelo CSV cru, sem passar pelo motor genérico.

### Adicionado (Dashboard Feedback / NPS — [20](20_feedback_nps.md))
- **Motor:** `src/analise_planilha/feedback.py` (lógica pura) — lê o CSV cru da pesquisa, calcula NPS
  (Detrator/Neutro/Promotor), tempo de espera, expectativas e a tabela por serviço (catálogo fixo de 30),
  e renderiza um HTML de 4 páginas com gráficos de rosca (cores do modelo). Reconhecido pelas colunas.
- **Tipo selecionável:** «Feedback / NPS» aparece no seletor **Modelo de análise** do envio
  (`feedback.SLUG = "feedback_nps"`); escolhendo-o, o relatório rende o dashboard garantidamente e **não**
  usa modelo `.toml` nem auto-modelo.
- **Setor Diretoria** (`DIR`) semeado em `servidor/seed.py` (instalações novas).
- **Total de Atendimentos** (único dado fora do CSV) é um **campo editável na tela** para gestor/ADM,
  salvo em `config_exec` (`POST /web/r/{slug}/feedback/atendimentos`).
- **Visual:** rosca limpa + **chips de %** à direita, **tooltip** e destaque ao passar o mouse (web);
  filtro de data escondido para esse relatório.
- **CLI:** `scripts/gerar_feedback_nps.py` (CSV → PDF via Chrome/Edge headless ou WeasyPrint).
- **Operação:** botão **Reconstruir (rebuild)** no `scripts/painel-controle.py` e `scripts/reconstruir-docker.bat`
  (`docker compose up -d --build`) — o código é copiado para a imagem, então reiniciar não recompila.

### Corrigido
- O motor classificava o CSV de feedback como série financeira e quebrava (`KeyError: None`); todas as
  rotas de exibição (prévia, página, conteúdo e PDF) agora desviam para o dashboard **antes** do motor.
- Detecção de feedback robusta: só arquivos `.csv`/`.txt` são testados; erro de parse é tratado (não
  derruba relatórios normais com `.xlsx` ou CSV multilinha); `ler_csv` usa `newline=""`.

## [2.0.1] — 2026-11-09

Organização do repositório (sem mudança de comportamento do produto), painel de operação e lint.

### Alterado (estrutura — "um lugar para achar cada coisa")
- **`dominio/`** passa a reunir as definições de negócio versionadas: `dominio/Agentes/` (ex-`Agentes/`),
  `dominio/modelos/` (ex-`config/modelos/`) e `dominio/docs/` (ex-`DOCS/`), com um `dominio/README.md` que
  mapeia tudo. O import segue `from Agentes import …` (`dominio/` entra no `pythonpath`/`sys.path`); o
  servidor copia para `/app/dominio/…` e o volume de modelos monta em `/app/dominio/modelos`.
- **`dados/`** vira a única casa do dado local (LGPD): `dados/relatorios/` (entradas por relatório, ex-`dados/`),
  `dados/saida/` (ex-`saida/`), `dados/setores/` (ex-`Setores/`) e `dados/revisar/` (ex-`Revisar planilha/`).
  `config.PASTA_DADOS`/`PASTA_SAIDA` e os scripts apontam para lá.
- **`scripts/`** reúne CLIs e utilitários fora do produto: `gerar_relatorio.py`, `analisar.py`,
  `painel-controle.py`, `aprender_setores.py` e os `.bat` (`reiniciar-docker`, `enviar-github`).
- Documentação, `CLAUDE.md`, `README.md` e comentários atualizados para a nova estrutura.

### Adicionado (painel de controle — ferramenta de operação, `scripts/painel-controle.py`)
- Atalhos: **abrir o site**, **abrir a pasta do projeto** e a **pasta de saída**; e tarefas com log ao
  vivo: **rodar testes** (pytest), **lint** (ruff), **ver logs do Docker** e **parar o Docker**.

### Corrigido
- **LGPD:** a pasta de revisão (`Revisar planilha/`) não era ignorada pelo git (o `.gitignore` tinha o nome
  antigo `_revisar/`). Agora **todo** dado real vive sob `dados/` e o `.gitignore`/`.dockerignore` usam uma
  única regra `dados/`, blindada.
- **Lint:** política de `ruff` revisada (ignora idiomas intencionais — `B008` do FastAPI, `BLE001`, `S110`,
  `ISC`, etc. — com justificativa) e correções pontuais; `ruff check .` passa limpo.

### Removido
- `iniciar.bat` (apontava para o `main.py` do desktop já removido) e a pasta `DOCS/Planejamento` (histórico).

## [2.0.0] — 2026-11-09

Marco do **produto web v2**: consolida o servidor (FastAPI + Docker, login e controle por setor) como o
único produto e **remove em definitivo** o app desktop PyQt6 e o build `.exe`/Nuitka/atualizador. Estreia os
**Agentes Especialistas por Setor**.

### Adicionado (Agentes Especialistas por Setor)
- **Pacote `Agentes/`** (raiz, 100% determinístico, sem IA em execução): **Escudo de Entrada de ERP**
  (caça o cabeçalho real, descarta subtotais, blinda códigos, sanitiza números PT-BR) + roteamento com
  **fallback transparente**. Vocabulário de cada setor em `config.toml` (adaptável sem tocar no código).
  Ver [DOCS/19](19_agentes_por_setor.md).
- **Agente de Faturamento Hospitalar**: taxa de glosa, valor líquido, taxa de recuperação, dedup de contas
  parciais (guia × internação), aging alta→envio e backlog, Pareto 80% da glosa, alertas de risco.
- **Agente de Custos**: Orçado × Realizado por centro/grupo (desvio R$ e %), Curva ABC (80/20), evolução por
  competência, composição por grupo/natureza, lançamentos atípicos (z-score), alertas (estouro, gasto sem
  orçamento, estorno, concentração).
- **Análise setorial no relatório**: os achados/painéis/alertas do agente são dobrados na `Analise`
  (aba "Análise de {setor}") — antes o agente só limpava a planilha.
- **Roteamento robusto**: pontuação determinística (contexto do setor domina a densidade de colunas;
  empate pela ordem de registro); `por_nome` (escolha forçada) e `candidatos` (lista para a prévia).
- **Seletor de Agente na prévia** (`POST /web/enviar/previa/{id}/agente`): *Automático* / escolher / *Nenhum*,
  salvo na carga (coluna `cargas.agente`); só sem modelo aplicado.

### Adicionado (chamados)
- **Anexo de arquivo** opcional nos chamados (além do print de imagem): a pessoa anexa a planilha que tenta
  incluir. Tipos aceitos (xlsx/xls/xlsm/ods/csv/tsv/txt/pdf/json/zip) até 25 MB, com download pelo nome
  original. Arquivo no volume (nome UUID), nunca no banco; servido só ao ADM e ao autor do chamado (LGPD).
  Novas colunas `sugestao_mensagens.anexo_uuid` / `anexo_nome`.

### Alterado
- **Documentação reescrita para o produto web** (01 visão geral, 02 arquitetura, 05 interface web,
  07 diretrizes), índice e READMEs atualizados; 16/18 passam a descrever a v2 como **vigente** (não mais
  "planejamento"). POPs revisados para o fluxo web.

### Removido
- Documentos e referências do **app desktop PyQt6** e do **build `.exe`/Nuitka**/atualizador (08 e 17 já não
  existiam; `05` deixou de ser a "janela PyQt6"); pasta `DOCS/Planejamento` (histórico já incorporado).

### Migração
- **Banco**: `cargas.agente` e `sugestao_mensagens.anexo_uuid`/`anexo_nome` entram pela migração leve
  (`servidor/bd.py`, `ALTER TABLE ADD COLUMN` idempotente) — nada a fazer manualmente.
- **Compatibilidade**: sem modelo e sem agente aplicável, o comportamento é idêntico ao anterior
  (fallback transparente). Modelos `.toml` existentes continuam valendo.

## [1.6.0] — 2026-11-04

### Alterado (menu lateral reorganizado + Administração em telas separadas)
- **Menu lateral agrupado** em três seções com cabeçalho, que aparecem conforme o papel:
  **Dashboard** (Relatórios · Enviar planilha · Rascunhos), **Solicitações** (Abrir novo chamado ·
  Chamados [ADM] · Minhas sugestões) e **Administração** (Usuários · Gerenciar Setores · Gerenciar Modelos ·
  Gerenciar Relatórios · Base de conhecimento). **«Abrir novo chamado»** abre o mesmo modal do botão do canto.
- **Administração deixou de ser uma tela única.** `/web/admin` agora redireciona e cada função tem a sua
  página: **Setores** (`/web/admin/setores`, com o «Importar setores» dentro), **Relatórios**
  (`/web/admin/relatorios`), **Modelos** (`/web/admin/modelos`) e **Base de conhecimento**
  (`/web/admin/conhecimento`). **Usuários** fica em Administração e continua visível ao gestor.

### Adicionado (chamados: sugestões e bugs — apoio à homologação)
- **Botão «Sugestões»** no canto superior direito, em todas as telas, para **qualquer usuário logado** abrir
  um **chamado** — uma **sugestão de melhoria** ou um **relato de bug**. Modal com tipo (💡 Sugestão /
  🐛 Bug), texto e **print opcional** (anexar imagem **ou** colar com `Ctrl`+`V`). A página de origem e o
  navegador são registrados automaticamente (ajudam a reproduzir o problema).
- **Conversa de ida e volta (ticket).** Cada chamado é uma **thread**: o colaborador abre, o ADM responde,
  e os dois trocam mensagens até resolver. **Toda mensagem** aceita print opcional (anexo ou `Ctrl`+`V`).
  Fluxo de permissões: o **ADM** age em qualquer chamado (responder, resolver, reabrir); o **colaborador**
  age no **próprio** chamado e tem o direito de **responder** ou **marcar como resolvido**.
- **ADM — «Chamados»** (`/web/admin/sugestoes`): lista com a conversa completa, quem abriu, setor, página e
  filtros **Em aberto / Resolvidos / Todos**; selo com a contagem de chamados aguardando o ADM.
- **Colaborador — «Minhas sugestões»** (novo item no menu, para todos): os chamados que abriu, a conversa e
  os botões de responder/resolver. Quando há **mensagem nova** do outro lado, acende um **selo** no
  botão/menu, que zera ao abrir a respectiva lista (controle de «lido» por lado).
- **Modelo de dados:** `sugestoes` (cabeçalho do chamado) + nova tabela **`sugestao_mensagens`** (a conversa,
  com `de_adm` e print por mensagem). Prints ficam no volume (nome UUID), **nunca no banco**, e são servidos
  só ao ADM e ao autor do chamado. **LGPD:** o anexo é escolhido pela pessoa e o modal avisa para não incluir
  dados pessoais; só imagens (PNG/JPG/WEBP/GIF) até 8 MB.

## [1.4.0] — 2026-11-03

### Adicionado (tela de login + autoatendimento de senha)
- **Login renovado**: o antigo bloco «AP» deu lugar ao **ícone do produto** (`assets/icon.ico`) e o subtítulo
  passou a ser **«Da planilha ao relatório, automaticamente.»**.
- **Alterar senha** (`/web/trocar-senha`): a própria pessoa troca a senha a partir do login, informando
  **usuário, senha atual, nova senha e repetir** (valida senha atual, mínimo de 6 caracteres e confirmação).
- **Esqueci a senha** (`/web/esqueci`): registra um pedido de redefinição que vira **notificação para o ADM**
  no painel inicial («Pedidos de redefinição de senha», com **Redefinir** e **Resolver**). Redefinir a senha
  pelo ADM encerra o pedido automaticamente; a mensagem ao usuário é genérica (não revela se o login existe).
  Nova tabela `pedidos_senha`.

### Adicionado (Painel Executivo editável + versão editável compartilhada)
- **Painel Executivo personalizável** pelo Gestor/ADM: escolher KPIs e destaque, título, tamanho/altura,
  largura da página e **gráficos personalizados** (inclusive promover gráficos das seções ao topo), salvos
  por relatório (`config_exec`). Rota `POST /web/r/{slug}/painel-executivo`.
- **Versão editável/curada** do relatório (`versao_editada`): reordenar/ocultar seções e painéis, títulos e
  descrições, blocos extras (nota), gráficos personalizados por seção, achados curados — para impressão e
  apresentação. Rota `POST /web/r/{slug}/versao-editada`.
- **Compartilhar a versão editada** com outro setor: ao recompartilhar com a mesma pessoa, o acesso anterior
  é **substituído** (não empilha), e quando há mais de um acesso vigente vale o **mais recente**.

### Corrigido
- Gráficos personalizados do Painel Executivo e da versão editável enviados com a chave `figura_html`
  (além de `figura`) agora são renderizados corretamente.

## [1.3.0] — 2026-10-30

### Adicionado (dashboard navegável + tela de rascunhos)
- **Cards do painel inicial agora são clicáveis** e levam à sua tela: **Setores** → Administração
  (`/web/admin`), **Usuários** → Usuários (`/web/usuarios`) e **Rascunhos p/ publicar** → a nova tela de
  rascunhos (`/web/rascunhos`). O card de **Relatórios** não navega (já é o conteúdo da própria home).
- **Nova tela «Rascunhos p/ publicar»** (`/web/rascunhos`, também no menu lateral): lista as planilhas já
  enviadas que **ainda não foram publicadas**, com relatório, arquivo, quem enviou, data e tamanho, e um
  botão **Revisar** que abre a prévia (publicar ou descartar). Resolve o «não encontro meus rascunhos».
- **Escopo por setor:** cada pessoa vê só os rascunhos do **próprio setor**; o **ADM vê todos** (com a
  coluna «Setor»). A tela é restrita a gestores/ADM, como o restante do fluxo de publicação. O
  isolamento reusa o `RepoCargas` (já filtrado pelo escopo) — novo método `RepoCargas.rascunhos()`.
- **Ações por linha na tela de rascunhos:** além de **Revisar** (abre a prévia), cada linha tem
  **Editar** (abre a gestão do relatório — nome/modelo/setor), **Inativar/Ativar** (liga/desliga a
  visibilidade do relatório) e **Excluir** (descarta o rascunho; se for um relatório novo ainda sem nada
  publicado, remove o relatório junto). As rotas `/gestao/relatorio/{slug}/ativo` e
  `/enviar/previa/{id}/descartar` ganharam um parâmetro `voltar` (validado p/ `/web/…`) para retornarem à
  lista de rascunhos. A exclusão definitiva de um relatório já publicado continua só no ADM, pela página
  de gestão (botão Editar).

## [1.2.3] — 2026-10-30

### Melhorado (DRE: evolução Receitas × Despesas e comparativo por conta filtrável)
- **Evolução mensal mostrando Receitas e Despesas mês a mês** (ponto 3 do feedback). No «Demonstrativo
  (DRE)», o gráfico mensal virou **«Evolução mensal — Receitas × Despesas»** e ganhou **tabela** com
  Receitas, Despesas (valor absoluto), Resultado líquido e a variação de cada uma em relação ao mês
  anterior — fica fácil ver como receitas e despesas evoluem lado a lado.
- **Comparativo mês a mês por conta, separado em Receita ou Despesa** (ponto 4 do feedback). Nova seção
  **«Comparativo mês a mês por conta»** com **duas tabelas conta × mês**: uma só com as contas dos blocos
  de **receita** e outra só com as de **despesa** (a conta herda o sinal do seu bloco) — permite olhar
  receitas e despesas em separado, como pediram.

## [1.2.2] — 2026-10-30

### Melhorado (DRE HUNF: grupo × conta pelo NEGRITO da planilha)
- O que é **grupo** e o que é **conta** na DRE passou a sair do **negrito da coluna A** (o setor marca os
  blocos em negrito), em vez da CAIXA ALTA. Novo `agrupamento = "negrito"` no leitor de matriz
  (`matriz.py`): rótulo em negrito = bloco/subtotal; texto normal = conta. Assim **EPI, IMPOSTOS, IOF,
  Glosas Acatadas** — que estão em CAIXA ALTA mas **não** em negrito — voltam a ser **contas** dos blocos
  acima delas (como na planilha), e não grupos. Seções numeradas («8. …», «9. …», «10. …»), que somam as
  linhas abaixo e nem sempre vêm em negrito, também são tratadas como subtotal.
- Resultado: a **soma das contas bate 100% com o subtotal de cada bloco da planilha** (conferência: 279/279
  bloco×mês). O total de custos/despesas ficou mais completo porque EPI e IMPOSTOS (contas reais, antes
  excluídas quando viravam grupo) voltaram a ser somadas. Modelo `gestaodecustos_dadoshunf_drehunf.toml`
  atualizado para `agrupamento = "negrito"`.

## [1.2.1] — 2026-10-30

### Corrigido (DRE HUNF: grupo × conta não se misturam mais)
- **Relatório «Dados Hunf — DRE HUNF»** passou a usar o **motor DRE dedicado** (`financeiro.py`, perfil
  `dre`) em vez da dedução genérica do Cérebro. Antes, grupos e contas se misturavam: blocos viravam conta
  (ex.: «RESULTADO OPERACIONAL ANTES FINANCEIRO» aparecia como conta), linhas de fórmula entravam como
  conta («*(Item 8 + Item 9)*») e EPI/IMPOSTOS engoliam contas de outros blocos. Agora cada bloco (RECEITA,
  DESPESAS COM PESSOAL, EPI, IMPOSTOS, RESULTADO…) fica com as suas contas, e o relatório ganha o
  **Demonstrativo (DRE)** (DRE por ano, mês a mês, receita × custos × resultado, margem). O modelo
  `gestaodecustos_dadoshunf_drehunf.toml` foi reescrito como modelo v1 de matriz com `[analise] perfil="dre"`.
- **Leitor de matriz do Cérebro** (`cerebro/layout.py`), que atende os demais relatórios em matriz:
  passou a **ignorar linhas de fórmula/observação** («*(…)*», «(Soma dos itens…)») e a reconhecer
  **subtotais «RESULTADO…/LUCRO…/MARGEM…»** em CAIXA ALTA como subtotal (não como conta), mesmo quando
  seguidos de outro bloco. Reduz a mistura grupo/conta em qualquer planilha-matriz.
- Obs. de deploy: `config/modelos` é um volume semeado só na 1ª vez; em ambiente já existente, o modelo
  atualizado precisa ser reenviado (admin → importar modelo) ou copiado para o volume. Deploys novos já
  nascem com o modelo correto (semente embutida na imagem).

## [1.2.0] — 2026-10-30

### Adicionado (envio de várias planilhas de uma vez)
- **Envio em lote**: a tela «Enviar» aceita **vários arquivos de uma vez**. Depois do envio, as planilhas
  entram numa **fila de prévias** — revise e publique (ou descarte) uma a uma; ao publicar, já pula para a
  próxima. A prévia mostra um selo «Envio em lote — planilha X de N».
- Em **Novo relatório**, ao escolher 2+ arquivos aparece a opção: **tudo em um relatório só** (o relatório
  soma todas as planilhas, ex.: um arquivo por ano/mês) ou **cada planilha é um relatório separado** (cada
  arquivo vira um relatório com o nome do próprio arquivo, com sufixo (2), (3)… se o nome repetir).
- Em **Atualizar existente**, dá para mandar várias planilhas novas de uma vez para o mesmo relatório.
- Arquivos inválidos no lote são **ignorados com aviso** (nome + motivo), sem travar os demais.
- `Carga` ganhou a coluna `lote` (agrupa o envio); migração automática em `bd._migrar_colunas_leves`.

## [1.1.0] — 2026-10-29

### Adicionado (relatório estilo painel/Power BI + comparativo)
- **Painel executivo** no topo de cada relatório (pensado para diretoria): banda de KPIs grandes com
  **variação ▲▼ vs. período anterior** (cor por bom/ruim/neutro), medidores de meta e os 2 gráficos-chave
  promovidos. O «Resumo e achados» passou a focar nos achados/observações.
- **Visual de dashboard** (antes as barras eram monótonas): gráfico de **rosca (donut)** com legenda
  (valor + %) para composições de poucas categorias (`graficos.rosca`); **barras coloridas em trilho**
  com paleta por categoria (`graficos.barras(..., paleta=True)`); **linhas com área preenchida** em
  gradiente e colunas com gradiente suave; cards de KPI com accent colorido, sombra e hover.
- **Comparativo entre períodos**: seção «Comparar» com dois seletores — escolhe dois períodos (ex.: 2025 ×
  2026) e vê os indicadores lado a lado com Δ (absoluto e %). Dados embutidos; nada recalcula no navegador.
- **Comparação sem coluna de data**: quando o relatório não tem data (ex.: Convênio), as vistas e o
  comparativo passam a usar a dimensão **Ano** ou **Arquivo de origem** (cada planilha somada vira uma vista).
- `KPI` ganhou `valor_num`/`fmt`/`sentido` (número + unidade + «maior/menor é melhor») para o delta ser
  preciso; preenchido no motor genérico, na série do Cérebro e nos relatórios financeiros.

### Removido (produto passa a ser só web)
- **App desktop PyQt6** (`app/` inteira e `main.py`) e o **build/distribuição `.exe`** (Nuitka): `build.bat`,
  `scripts/empacotar.py`, `scripts/versao.py`, `.github/workflows/release.yml`.
- **Auto-update**: `analise_planilha/atualizacao.py`, `servidor/atualizacao.py`, a trava de versão por
  `X-Client-Version`, as rotas `/api/v1/atualizacao*` e o volume `atualizacoes`.
- **API `/api/v1`** (era o backend do cliente desktop) e `analise_planilha/serializacao.py`; sobraram as
  rotas `/web`. `requirements.txt` sem `pyqt6`/`nuitka`; docs 08/17 e DOCS14 removidas.
- Produto único: o **servidor web** (`docker compose up`). CLI `gerar_relatorio.py`/`analisar.py` mantidas.

## [1.0.0] — 2026-10-26

Primeira versão distribuída: executável publicado nas Releases do repositório público, com atualização
automática a partir daqui.

### Alterado (privacidade)
- Nada que vem das planilhas fica no repositório: valores e contagens reais saíram da documentação;
  `config/metas.json` (metas de cada usuário) deixou de ser versionado; o `build.bat` não copia mais
  `ia.toml` (chave de API), `metas.json` e `atualizacao.toml` de quem compila para a pasta do `.exe`.

### Adicionado (distribuição e atualização automática — [08](08_build_e_distribuicao.md))
- **Build automático no GitHub** (`.github/workflows/release.yml`): a tag `vX.Y.Z` roda testes, compila
  com o Nuitka, roda o autoteste do `.exe` e publica `.zip` + `.sha256` nas Releases do repositório público.
- **Atualização automática do `.exe`** (`atualizacao.py` + `app/atualizador.py`): consulta silenciosa ao
  abrir, pergunta antes de instalar, confere o SHA-256 e troca só os arquivos do programa — `dados\`,
  `saida\` e os arquivos já existentes de `config\` são preservados. Desliga com `config\atualizacao.toml`
  (`verificar = false`). Única conexão de saída fora do Modo IA; não envia dados.
- Versão com fonte única (`__version__`), lida pelo `build.bat` e pelo `pyproject.toml`.

### Corrigido (build)
- `build.bat` devolve código de saída ≠ 0 quando testes, compilação ou autoteste falham (antes só
  exibia a mensagem e terminava como sucesso).
- `.gitattributes` garante CRLF nos `.bat` (com LF o `cmd` pode errar o `goto :rótulo`).

### Alterado (organização do código — sem mudança de funcionalidade)
- **`app/janela.py` dividido** (1.431 → 1.009 linhas): peças reutilizáveis em `app/componentes.py`
  (`ListaMarcavel`, `ModeloPandas`, `CarregadorWorker`, montagem de tabelas/painéis, helpers de layout);
  diálogos em `app/dialogo_modelo.py` («Salvar como modelo…») e `app/dialogo_ia.py` (`DialogoIA`,
  `TrabalhoIA`). Novos módulos incluídos no `build.bat`.
- Navegação Pasta › Relatório › Página: o preenchimento dos combos, antes copiado em três métodos, ficou
  num só caminho (`_preencher_relatorios` + `_ao_trocar_relatorio`). Estado da tela conferido idêntico ao
  anterior em todas as pastas, relatórios e páginas.
- Removido código sem uso (funções, constantes, aliases antigos, parâmetro morto de `_col`) e ícones
  antigos de `assets/`.

### Corrigido
- `main.py --autoteste` não quebra mais ao imprimir num console cp1252 (caractere «→»); o
  `autoteste.txt` continua em UTF-8.

### Adicionado (relatórios Garantia / Reembolso / Pagamento — [14](14_garantia_reembolso.md))
- Trazidos do projeto de referência `garantia_atendimento`, **só com modelos `.toml`** (sem tocar nos
  relatórios atuais): **Garantia de Atendimento** (reaproveita o `.sample` já pronto), **Reembolso**
  (taxa de autorização ponderada, tempo abertura → finalização, em aberto, valores) e **Pagamento
  Reembolso**. Cada um na sua pasta em `dados\`; as abas mensais são consolidadas (`abas = "todas"`).
- Novo campo de modelo **`apenas_mapeadas = true`**: a leitura mantém só as colunas declaradas e
  descarta o resto — usado no Pagamento para **deixar CPF, banco, agência, conta e chave PIX de fora**
  (LGPD). Padrão `false` (demais relatórios inalterados).
- **Tela:** o seletor Pasta › Relatório › Página passou a exibir, para modelos que consolidam abas, uma
  página **«Todas as abas (consolidado)»** (acréscimo isolado; não afeta HUNF/Contas Convênio/Sem modelo).
- **Consolidação de arquivo sem abas (CSV/TXT):** `abas = "todas"` agora também lê um CSV como tabela
  única (antes exigia planilha com abas).
- Testes `testes/test_garantia_reembolso.py` (consolidação, taxa/tempo, `apenas_mapeadas`, página na tela).

### Adicionado (filtro de período no HTML — [06](06_relatorio_html.md))
- **Seletor «Período» no relatório HTML** (ao lado do ◐ tema), para relatórios com datas: troca a visão no
  navegador entre **Todo o período · cada ano · Últimos 12 meses** (e o recorte atual, se o usuário estreitou
  o De/até). Cada visão é **calculada no Python** e embutida — números idênticos aos da janela, **sem
  JavaScript de cálculo**. A base detalhada é renderizada uma vez (período todo) para conter o tamanho do
  arquivo. Relatórios sem datas (Contas Convênio) saem sem o seletor. `relatorio_html.gerar`/`montar_html`
  ganharam `ds`/`filtros`; a janela e a CLI passam os dois.

### Adicionado (dashboards financeiros HUNF — [13](13_financeiro_hunf.md))
- **Motor de séries financeiras** (`financeiro.py`, `[analise] tipo = "serie"`, perfis custos/faturamento/
  dre): KPIs (total, média, último mês × anterior e × ano anterior, 12 meses × 12 anteriores, acumulado do
  ano), visão geral (mês a mês empilhado, média mensal por ano, mesmo mês entre anos), composição, contas
  (top 20, curva ABC, maiores aumentos/reduções), **uma seção por bloco** (mini-KPIs, evolução, maiores
  contas, matriz conta × mês), atípicos (meses fora do padrão, picos por conta, estornos) e **conferência
  com a planilha** (soma das contas × subtotal de cada bloco; total = soma das partes; detalhado × contábil).
  DRE: demonstrativo por ano/mês com % da receita, receita × custos × resultado, margem mensal, meses com
  prejuízo e **contas de despesa com sinal positivo** (a conferir).
- **Leitor de matriz**: `a_partir_de` (base a partir de jan/2024), `agrupamento = "secoes"` com
  `[[leitura.secao]]` (blocos declarados; `linha_unica` para bloco só com total, repetida → vale a última),
  `[[leitura.referencia]]` (totais da planilha guardados à parte), `contas` (caixa alta que é conta),
  subtotais guardados para conferência, meses sem lançamento descartados, datas digitadas no lugar de valor
  ignoradas com aviso. `MetaLeitura.extras` leva os totais ao motor.
- **HTML**: painéis em grade (meia largura lado a lado), mini-KPIs por painel, tabelas abertas, gráfico de
  **linhas** com negativos, eixos em R$ compacto, rótulos do eixo X sem sobreposição; frase de resumo e
  metodologia por relatório. Metas de série: média mensal, último mês, total, margem líquida.
- **Versões da mesma planilha** juntadas (mesmos meses): vale o arquivo mais recente por conta × mês, com
  aviso — sem soma em dobro.

### Corrigido
- **DRE HUNF:** «EPI» e «IMPOSTOS» (caixa alta) eram tomados por blocos e a linha «(-) Descontos…» era
  descartada — o resultado do período saía errado. Agora a soma das contas bate com o Resultado
  líquido da planilha em todos os meses.
- Gráfico de linhas aparecia como texto (o SVG era escapado ao somar com a legenda).

### Adicionado (relatórios financeiros HUNF — [13](13_financeiro_hunf.md))
- **Leitor de matriz conta × mês** (`matriz.py`): abas financeiras em que cada linha é uma conta/convênio
  e cada coluna é um mês (não tabulares) são "despivotadas" para uma linha por conta × mês, dando
  evolução mensal, quebras e somas no motor existente. Dirigido pela seção `[leitura]` do `.toml`
  (`formato = "matriz_mensal"`, `coluna_rotulo`, `agrupamento` nenhum/codigo/maiusculas, `grupos_prefixos`,
  `linha_inicio/linha_fim`, `pular`…); a linha de meses e as colunas de mês são detectadas sozinhas.
  Subtotais/cabeçalhos viram a coluna «Grupo» e não entram como dados (sem contagem dobrada).
- **Três relatórios do workbook HUNF** (mesmo arquivo em `dados\HUNF\`, cada um numa aba):
  **Faturamento HUNF** (receita por convênio × mês), **Custos HUNF** (custo por conta/grupo × mês) e
  **DRE HUNF** (receita + / custo − por conta × mês; soma por mês ≈ resultado, quebra por «Grupo» = a DRE).
- Testes `testes/test_matriz.py` (matrizes sintéticas nos três modos).

### Mudado (navegação Pasta › Relatório › Página, com nomes reais)
- A barra lateral tem **três seletores em cascata**, todos com **nomes reais**: **Pasta** (subpasta de
  `dados\`), **Relatório** (os **arquivos** da pasta, pelo nome real) e **Página** (as **abas reais** do
  arquivo reconhecidas pelos modelos, por `ordem`). Abre sempre na 1ª página; com uma só aba, o seletor
  de Página fica oculto. Cada modelo (`.toml`) fixa a `aba` real que lê; um arquivo sem modelo que case
  cai como **Sem modelo**. Campos de modelo `categoria`/`pagina` viraram legado (ignorados); `ordem` fica.
- **Juntar/consolidar** continua em **Arquivos (juntar)** abaixo do menu: por padrão só o arquivo do
  relatório fica marcado (análise por arquivo); marque vários e **Recarregar** para consolidar (ex.:
  2025 + 2026). Arquivo sem a aba da página é ignorado ao juntar (`servico.carregar_varios`).
- **2ª página do «Contas Convênio»: aba «CESARIANA…»** (`resumo_cesariana.toml`) — analisada à parte
  (paciente, faturamento, custo, resultado, margem); só existe em 2025.
- Autoteste passou a testar **um arquivo por relatório** (a aba do modelo), à prova de planilhas
  duplicadas na pasta.
- Removido (de novo) o workbook duplicado `DADOS.xlsx` em `dados\HUNF\` — um processo externo de
  sincronização na máquina parece restaurá-lo; enquanto estiver lá, juntar os dois dobra os números.

### Mudado (pastas e modelos por planilha)
- **Uma pasta de dados por relatório**: `dados\Contas Convênio\` (2025/2026) e `dados\HUNF\` (workbook
  financeiro); `dados\entrada\` fica para o "Sem modelo". Evita que um relatório leia por engano o
  arquivo de outro. `contas_convenio.toml` passou de `pasta = "entrada"` para `pasta = "Contas Convênio"`.
- **Removidos modelos fictícios** que não correspondiam a dado real (`atendimentos2026.toml`,
  `faturamentoecustoshospitalareshunf.toml`, `resultadofinanceirocesariana.toml`) e suas pastas vazias.
  O resumo de cesarianas continua anexado pelo próprio leitor do Contas Convênio.

### Mudado (mesmo desenho do projeto Garantia de Atendimento e Reembolso)
- **Interface refeita no padrão da Garantia** ([05](05_interface.md)): topo com borda verde (título,
  "Relatório: X — análise local", versão); barra lateral com **Relatório** (um por modelo, cada um lendo
  de `dados\<pasta>\`), **Arquivos** (lista marcável + **Adicionar…** que copia para a pasta + **Recarregar**;
  várias marcadas = consolidadas), **Período pela** + De/até, **listas marcáveis com busca** por dimensão
  ("nada marcado = todos"), Anonimizar e o cartão **Aplicar / Limpar filtros**; conteúdo com KPIs,
  **busca que realça na tela**, **⚙ Editar metas** e uma aba por painel começando em **Resumo e achados**;
  rodapé com status colorido, Abrir pasta de saída, Gerar DOCX/PDF (v0.2) e **Gerar HTML**. Carga em thread.
  Recursos próprios mantidos no mesmo estilo: Modo I.A, abas Resumo por coluna e Tipos, Salvar como modelo.
- **Tema com tokens** (PALETA/ESPAÇO/FONTE/RAIO e classes primário/secundário/discreto/kpi/cartão/aviso)
  idênticos à Garantia, mantendo Fusion + paleta clara (nunca segue o modo escuro do Windows).
- **Relatório HTML com Jinja2 + gráficos SVG puros** (`templates/relatorio.html.j2`, `graficos.py`): sem
  JavaScript de terceiros, tema claro/escuro, índice, filtros, resumo e achados, metas ✔/✗, painéis com
  "Ver tabela", leitura e qualidade, base detalhada, metodologia e rodapé LGPD. ~100 KB (era ~4,7 MB com
  Plotly). **Plotly removido** das dependências; `regras_visuais.py` (legado) removido.
- Painel "Evolução mensal" passa a se chamar **Volume mensal** (como na Garantia).

### Adicionado
- **Metas do gestor** (`metas.py`, diálogo `app/dialogo_metas.py`, `config/metas.json` por relatório):
  estatística dos tempos (mediana/média/P90/P95), alvos com sentido e observações; catálogo vindo do
  relatório (taxas, tempos, **ticket médio**, registros). Prevalecem sobre `[[meta]]` do `.toml`.
- **`gerar_relatorio.py`** (CLI para RPA/agendamento): `--listar`, `--relatorio`, `--inicio/--fim`,
  `--data-base`, `--dim COLUNA=VALOR`, `--anonimizar`, `--saida`.
- **Autoteste no padrão da Garantia**: checklist `[ok]/[X ]` (template, ícone, dependências, interface,
  escrita, pipeline sintético e cada relatório com planilha) gravado em `autoteste.txt`.
- **"Período pela"**: escolher qual data recorta o período (`Filtros.coluna_data`).
- Modelo `.toml` aceita `pasta = "…"` (subpasta de `dados\`). Ícone da aplicação em `assets\icon.ico`.

### Removido
- Filtros de **faixa numérica** e os menus suspensos de categoria (substituídos pelas listas marcáveis,
  como na Garantia); botão "Abrir planilha…" (substituído por Arquivos/Adicionar…).

### Corrigido
- Barra lateral com muitos filtros **espremia as listas e sobrepunha os títulos**: o conteúdo agora usa
  tamanho mínimo e a barra rola; listas com altura pelo nº de itens.

### Adicionado (relatório Contas Convênio — [12](12_contas_convenio.md))
- **Leitor de relatório em blocos** (`contas_convenio.py`): o relatório «Contas Convênio» do sistema
  hospitalar (uma conta por atendimento, não tabular) é reconhecido sozinho e vira uma linha por
  atendimento, com um valor por grupo de faturamento. Separa **faturamento bruto** (soma dos grupos) de
  **faturamento apurado / custo / resultado** (só contas apuradas — o «Valor total» delas foi ajustado à
  mão e não é somado com os brutos). Aba-resumo anexada como colunas «… (aba resumo)» com as
  divergências no diagnóstico; anotações manuais ignoradas e contadas; rodapé conferido; ano pelo nome
  do arquivo.
- **Consolidação de vários arquivos** (`servico.carregar_varios`; seleção múltipla na janela): uma base
  só, com «Arquivo de origem»; qualidade aponta arquivo › aba › linha.
- **Indicadores financeiros no motor** (opcionais no `[analise]`): `medidas_quebra` (várias somas por
  quebra, ticket médio e KPIs com cobertura parcial), `composicao` (painel de participação de cada parte),
  `medidas` (restringe o painel Valores); coluna `opcional = true` no modelo.
- **Modelo `contas_convenio.toml`**: margem ponderada, % de contas com custo apurado, peso de OPME e de
  honorários, tipo de atendimento, convênios unificados, cruzamentos por ano.
- Aba **Dados** formatada pelo tipo (R$, %, milhar).

### Mudado
- Alertas genéricos: com modelo, coluna não obrigatória vazia não gera aviso (é regra de negócio);
  outliers viram **um** alerta resumido em vez de um por coluna.
- Achados: não repete a mesma constatação para categorias que são o mesmo grupo de registros (ex.: tipo
  «Cesariana» derivado do procedimento «CESARIANA…»).

### Corrigido
- **Filtro de faixa numérica excluía linhas sem o usuário mexer**: o campo arredondava mín./máx. para
  2 casas, se considerava "ativo" e cortava as pontas (contas das extremidades ficavam de fora). Agora arredonda para fora
  e compara com o valor do próprio campo. Teste de regressão em `testes/test_janela_filtros.py`.

### Corrigido (tema claro)
- A janela ficava com áreas **cinza-escuras** no Windows em modo escuro (o Qt usava a paleta escura do
  SO para o que o QSS não cobria: caixa "Principais achados", aba Indicadores, menus, diálogos). Agora
  `tema.aplicar_tema()` força estilo **Fusion** + **paleta clara** fixa antes do QSS — tema claro em
  qualquer SO. Política em [05](05_interface.md#política-de-front-end-qss--obrigatória).

### Adicionado (Modo I.A — opcional)
- **Autodetecção pela chave**: basta colar a chave e clicar em **Detectar** — o provedor é reconhecido
  pelo formato (`sk-ant…`/`AIza…`/`sk-…`) e o **melhor modelo** é escolhido consultando `/models` da
  própria API. A escolha é dinâmica (família rápida → alias `*-latest` → maior versão), sem nomes de
  modelo fixos no código; e se o Gemini sugerir um substituto para um modelo aposentado (`use models/X`),
  o sistema troca e repete sozinho. Diálogo simplificado: chave em destaque, resto em "Avançado".
  Dialeto padrão `(automático)`.
- **Resiliência a sobrecarga**: HTTP 429/5xx (ex.: 503 "high demand" do Gemini) são repetidos com espera
  crescente (respeitando `Retry-After`) e, persistindo, a chamada passa para outro modelo da mesma chave.
  Progresso exibido no painel; erros mostram só a mensagem legível do provedor.
- **Detecção testa os modelos** (pedido mínimo, em paralelo, 15s de limite) e salva o primeiro que
  responde; fallback da geração percorre até 5 modelos e também troca quando o modelo trava (timeout);
  o modelo que respondeu fica salvo. Chave nova do AI Studio (`AQ.…`) reconhecida como Gemini.
  Validado com chave real: detecção em 2,6s (era 94s) e geração completa em ~13s.
- Provedor **Gemini** (Google) além de OpenAI-compatível e Anthropic: formato `:generateContent`,
  header `x-goog-api-key`, saída JSON; chave `GEMINI_API_KEY`/`GOOGLE_API_KEY`.
- Novo **Modo IA** (`src/analise_planilha/ia.py`, painel na barra lateral): ligado pelo usuário, usa uma
  API de LLM para **gerar automaticamente o modelo do cliente** (mapa de colunas + regras de negócio) a
  partir da planilha aberta. O motor de análise não muda — a IA só MOLDA o `.toml`, que segue pelo
  pipeline normal. Ver [11](11_modo_ia.md).
- **Genérico por configuração** (`config/ia.toml`, ignorado no git): dialeto `openai` (OpenAI, Azure,
  Ollama, gateways) ou `anthropic`; `base_url`, `modelo`, chave (campo ou variável de ambiente). Sem SDK
  pesado — só `urllib` da stdlib (mantém o .exe leve).
- **LGPD**: por padrão só a **estrutura** é enviada (nomes de coluna, tipos, contagens). Com amostra, os
  exemplos são **anonimizados** antes de sair da máquina (nomes → iniciais, dígitos → `#`, e-mails somem)
  e **texto livre nunca tem o conteúdo enviado** (só uma estatística de forma). Chamada em thread (não
  congela a janela). O modelo gerado pode ser salvo como `.toml` para reuso sem a IA.

### Mudado (análise de negócio — padrão do projeto Garantia de Atendimento)
- A análise deixa de ser estatística genérica por tipo (Registros/Colunas/Completude, histogramas,
  correlação) e passa a ser um **motor de indicadores dirigido por especificação**, como o motor tabular
  do projeto Garantia: `especificacao.py` (papéis + regras), `tratamento.py`, `indicadores.py`.
- O `.toml` do cliente ganha regras de negócio: `abas = "todas"`, `[analise]`, `[[classificacao]]`,
  `[[taxa]]`, `[[tempo]]` (dias úteis com feriados, meta por categoria, em aberto), `[[cruzamento]]`,
  `[qualidade]`, `[feriados]`, `[[meta]]`; e por coluna `papel`, `obrigatoria`, `aliases`,
  `ignorar_palavras`, `validar`. Modelos antigos continuam válidos. Exemplo completo:
  `config/modelos/garantia_atendimento.toml.sample`.
- Sem modelo, a especificação é deduzida (entidade pelo nome, dimensões, medidas, tempos entre datas,
  taxas de sim/não, cruzamento).
- Saída: KPIs de negócio, **principais achados** (desvios de taxa/tempo por categoria, concentração,
  tendência, recorrência, qualidade), **metas** ✔/✗, quebra por dimensão com várias métricas por linha,
  evolução mensal, tempos (mediana/P90/dias úteis/meta/faixas), cruzamentos, recorrência, valores e
  **qualidade por aba/linha**.
- Janela: aba **Indicadores** (navegação por painel, tabelas ordenáveis formatadas em pt-BR), achados e
  metas na Visão geral, opção **Anonimizar nomes**, colunas técnicas ocultas na aba Dados.
- Relatório HTML reestruturado: KPIs → metas → achados → recorte → painéis com navegação → leitura e
  qualidade.
- Rastreabilidade: coluna «Linha na planilha» (e «Aba de origem» ao consolidar).
- Validado com a planilha real da Garantia (11 abas): números idênticos ao relatório do projeto de
  referência, exceto 1 linha sem nome de cliente que agora é contada e apontada em Qualidade.
- `regras_visuais.py` deixou de ser usado (legado).

### Corrigido
- Data nativa com ano impossível (ex.: 202) derrubava a leitura (`OutOfBoundsDatetime`); agora vira
  data inválida e é apontada em Qualidade.

### Adicionado (leitura estrutural — "ler qualquer planilha")
- Novo módulo `estrutura.py` ([09](09_leitura_estrutural.md)): localiza a tabela de dados dentro da aba
  por pontuação de cabeçalho (rótulos, cobertura, contraste de tipo, repetição), em vez de "1ª linha
  ~cheia e textual nas 15 primeiras".
- Cabeçalho em dois níveis (grupo mesclado) combinado como `Grupo - Coluna`; células mescladas
  replicadas na área toda.
- Linhas de seção viram a coluna «Seção»; subtotais/total geral (com ou sem rótulo), cabeçalho
  reimpresso por página e notas de rodapé são descartados; leitura para ao achar outra tabela.
- 1ª coluna "agrupada" (valor só na 1ª linha do grupo) é preenchida para baixo.
- Escolha automática da aba (penaliza ocultas e "Instruções/Capa/Listas"); opção "(automática)" na
  janela, que passa a mostrar também a linha do cabeçalho.
- Modelo de cliente guia a leitura (sinônimos acham cabeçalho e aba) e associa cabeçalhos parecidos
  por semelhança (≥ 0,85), avisando para incluir o sinônimo.
- `MetaLeitura` ganha `confianca`, `descartes`, `diagnostico`, `linhas_cabecalho`; tudo vira alerta
  (nada é descartado em silêncio). Aviso "Estrutura incerta" quando a confiança < 0,5.
- Erros de fórmula (`#DIV/0!`, `#REF!`…) viram vazio e são contados; datas mistas (nativas + texto,
  vários formatos) e data em número serial do Excel são convertidas.
- 14 testes novos com planilhas sintéticas bagunçadas (`testes/test_estrutura.py`).

### Corrigido (leitura)
- CSV com linhas de preâmbulo **perdia em silêncio** as linhas de dados com mais campos que a 1ª linha
  (`on_bad_lines="skip"`). Agora o CSV é lido por `csv.reader` com preenchimento e o separador é
  escolhido pela consistência do nº de campos.
- `MetaLeitura.linha_cabecalho` contava linhas após apagar as em branco; agora é a linha real (base 0),
  e o índice do DataFrame é o nº real da linha na planilha (rastreabilidade).
- "transacao", "pedido", "processo", "carteirinha" etc. entram nas dicas de identificador.

### Desempenho
- Tipagem de célula sob demanda e decisão de tipo por amostra (`AMOSTRA_INFERENCIA`): CSV de 100 mil
  linhas de 12,7 s → ~4 s; xlsx lido em modo `read_only` (mesclas extraídas do XML da aba).

### Adicionado (interface desktop)
- **Tema visual padronizado** (claro, sólido): paleta única em `app/tema.py`, cabeçalho de conteúdo
  (título + metadados), cartões de KPI alinhados, tabelas e campos com acabamento consistente, barras
  de rolagem e menus estilizados. (Tentativa de efeito "vidro"/Mica foi descartada por prejudicar a leitura.)
- Filtros ricos na janela: multi-seleção por categoria, faixa numérica (mín/máx) e botão **Limpar**.
- Aba **Resumo por coluna** (tipo, % preenchido, únicos e resumo adequado ao tipo) e, na aba **Dados**,
  busca livre e ordenação por coluna.
- Aba **Tipos** editável: trocar o tipo de uma coluna reprocessa na hora (override, útil sem modelo).
- Botão **Salvar como modelo…**: cria o `.toml` do cliente a partir das colunas da planilha aberta.

### Mudado (pivô de arquitetura)
- O projeto passa a ser uma **estrutura base compilável em .exe** (PyQt6 + Nuitka, padrão da organização),
  adaptável por cliente. A interface Streamlit foi substituída por janela desktop PyQt6 (`app/janela.py`,
  `app/tema.py`); o Streamlit saiu do pacote.
- Nova **camada de modelo** (`modelo.py` + `config/modelos/<cliente>.toml`): mapeia os cabeçalhos reais do
  cliente para colunas canônicas e fixa os tipos. Sem modelo, mantém-se a inferência automática.
- Novo **relatório HTML autônomo** (`relatorio_html.py`): dashboard Plotly interativo, offline, aberto no
  navegador pelo botão da interface — mesmo objeto `Analise` da tela (números idênticos).
- `config.py` resolve os caminhos ao lado do `.exe` quando compilado (pastas de trabalho graváveis).

### Corrigido
- Linhas-gabarito (molde vazio com só o contador "Nº" preenchido) eram lidas como dados,
  inflando o total e disparando falsos alertas de "75% vazio". Agora são descartadas na leitura.
- Contador de linha ("Nº", "Item", "Ordem") e códigos grandes e únicos (nº de transação,
  protocolo) eram tratados como métrica e somados. Agora são classificados como identificador.
- Filtro de período descartava em silêncio as linhas sem data; agora elas são mantidas.

### Adicionado
- Filtros por faixa numérica (slider) e por valor booleano, além dos categóricos.
- `.streamlit/config.toml`: remove o botão **Deploy** (ferramenta é local — LGPD), desliga a
  telemetria e aplica a cor da marca.

## [0.1.0]

### Adicionado
- Leitura de xlsx/xls/ods/csv com detecção de encoding, separador, aba e linha de cabeçalho.
- Inferência de tipos: identificador, booleano, data/data-hora, percentual, moeda, inteiro, decimal,
  categórico, texto livre, vazio (números e datas em pt-BR e ISO).
- KPIs, séries temporais, histogramas, rankings, rosca e correlação gerados por regra tipo → visual.
- Alertas de qualidade (nulos, duplicatas, inválidos, outliers).
- Interface Streamlit com filtros, override manual de tipo e download dos dados tratados.
- CLI `analisar.py`, `main.py --autoteste` e suíte de testes offline.
