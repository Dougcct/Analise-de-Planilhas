# 21 — Banco do MV (Consulta SQL) e migração da Docker

Dois temas de infraestrutura: **(1) consulta direta ao banco do MV** (feito) e **(2) migração da stack
Docker para outro servidor** (planejado). Tudo roda na **rede local** do hospital.

## 1. Consulta SQL ao MV (Oracle) — feito

Tela ADM **«Consulta SQL (MV)»** (`/web/admin/consulta-sql`): escolher o ambiente, escrever um `SELECT` e
ver o resultado. Automatiza puxar dados que hoje saem por export manual (complementa o Conversor SQL→Excel).

| Peça | Arquivo | Papel |
|---|---|---|
| Motor (só leitura) | `automacao/mv.py` | `testar(conf)`, `executar(conf, sql)`; **guarda** `validar_select` (só `SELECT`/`WITH`); driver `oracledb` em **modo thick** (Oracle Instant Client na imagem), importado preguiçosamente |
| Conexões | tabela `conexoes_mv` (`servidor/modelos_bd.py`) | um registro por **ambiente** (`teste` \| `producao`): host, porta, service name, usuário, senha. Fonte ÚNICA (migra junto com o sistema) |
| Rotas (ADM) | `servidor/web.py` | `GET /web/admin/consulta-sql`; `POST …/conexao` (salvar), `…/testar` (JSON ok+log), `…/executar` (JSON colunas/linhas) |
| Tela | `templates/web/consulta_sql.html` | cards de conexão + testar; seletor Teste/Produção; editor SQL com **realce offline** (sem CDN); Executar / **F8**; tabela de resultados |
| Atalho | `scripts/painel-controle.py` | botão **«Consulta SQL (MV)»** abre a tela no navegador |

**Driver — modo thick (Oracle Instant Client):** o modo *thin* (padrão) recusa contas cujo verificador
de senha é antigo/não suportado (erro `DPY-3015: password verifier type … is not supported … in thin
mode`, ex.: `0x939`). Por isso a imagem traz o **Instant Client Basic Light** (Dockerfile) e `mv._init_thick()`
liga o modo thick antes de conectar — aceita qualquer verificador. Sem o client (dev/CI), o driver cai
em thin automaticamente. A pasta das libs vem em `ORACLE_CLIENT_LIB_DIR` (definida no Dockerfile).

**Segurança / LGPD:**
- **Só leitura:** `validar_select` bloqueia INSERT/UPDATE/DELETE/DDL, 2º comando (`;`), `SELECT … INTO`,
  `FOR UPDATE`; a consulta é envelopada com `ROWNUM <=` (teto de linhas) e **nunca** faz commit.
- **Só ADM**, na rede local. Produção tem **dado real de paciente** → a tela avisa ao selecioná-la; o dado
  nunca sai da rede e nada é versionado. A auditoria registra ambiente + nº de linhas (não o SQL).
- Senha fica no banco (rede fechada); se um dia sair da rede, evoluir para um cofre de segredos.

**Decisão:** as conexões vivem no **banco** (não num arquivo do painel) porque o **servidor** é quem conecta
no MV e a config precisa **migrar junto** quando a Docker for para outro servidor. O painel é o lançador.

## 2. Migração da Docker — planejado (ainda não implementado)

Objetivo: mover a stack (db + api) para um **servidor dedicado** na rede local, levando os dados.

**Informações necessárias do servidor destino:**
- SO (Linux/distro ou Windows Server) e **Docker + Compose** instalados.
- Rede: atrás do pfSense? IP/hostname fixo, porta 8000, precisa HTTPS/domínio + proxy (nginx)?
- Recursos: CPU/RAM/disco (Postgres + build de imagem).

**O que migra (volumes):** `dados_db` (Postgres: usuários, relatórios, chamados, **conexões MV**),
`cargas` (planilhas + prints de chamado), `modelos` (TOML). **Como:** `pg_dump` do banco + `tar` dos
volumes aqui → restaurar no destino; o código sobe por `git clone` + `docker compose up -d --build`.

**Segredos/env a levar:** `DATABASE_URL`, chave de sessão, `config/ia.toml`, `CARGAS_DIR`.

**Plano:** um assistente (tela/painel) que recebe os dados do destino, **exporta** os volumes aqui e
**importa** lá, com backup e rollback. Mapeado como botão **«Migrar Docker (planejado)»** no painel.
