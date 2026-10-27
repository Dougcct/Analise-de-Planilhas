# 16 · Arquitetura v2.0 — Cliente-Servidor por Centro de Custo

> **Status: em desenvolvimento na branch `v2`. Fases 0–6 IMPLEMENTADAS e rodando; fase 7 montada como
> infraestrutura (TLS/backup), pendente de deploy em servidor Linux antes de qualquer dado real.**
> Reforços de "defesa em profundidade" ainda pendentes: RLS no Postgres, grant append-only da auditoria
> e Alembic (hoje o esquema é `create_all`). Ver o [§8](#8-plano-em-fases).
> A v1.0 (desktop local) segue intacta no `main`, com ponto de retorno na tag `base-1.0.0`.
> Complementos: [17 · Atualização v2](17_atualizacao_v2.md) · [18 · Segurança e LGPD v2](18_seguranca_lgpd_v2.md).
> Origem: rascunhos em `Planejamento/` (out/2026), consolidados e revisados contra o código.

## 1. Por que a v2 existe

**Controle, não desempenho.** Os volumes são pequenos (o motor processa as planilhas atuais em segundos);
o que falta na v1 é governança: hoje o `.exe` e as planilhas ficam onde o operador os colocar. Na v2:

- cada **centro de custo** (setor) enxerga só os **próprios** relatórios e dados;
- planilhas, modelos `.toml`, metas e chaves ficam no **servidor**, atrás do pfSense;
- o cliente é uma casca: sem conta válida no servidor, um `.exe` copiado não abre nada;
- tudo o que importa fica registrado (quem enviou, publicou, abriu, exportou, compartilhou).

**Mudança consciente de princípio.** A v1 tinha "dados estritamente locais". A v2 **concentra** os dados
num servidor — mais controlável, mas um alvo único. Por isso a regra de implantação:

> **Na máquina do desenvolvedor (homologação em Docker), só dados sintéticos.** Dado real entra apenas no
> servidor de produção, atrás do pfSense, depois da fase 7 ([§8](#8-plano-em-fases)).

Contexto de uso: **uma rede interna**, vários setores, crescendo aos poucos — cada modelo de planilha novo
traz o seu centro de custo e o seu gestor.

## 2. Visão geral

```
 PC do setor (cliente PyQt6)                 Servidor (Docker, atrás do pfSense)
 ┌──────────────────────────┐   HTTPS (LAN)   ┌───────────────────────────────────────────┐
 │ login · lista de relat.   │ ─────────────▶ │ proxy TLS (Caddy)                          │
 │ mesmas telas da v1         │ ◀───────────── │   └─ API (FastAPI) ── motor analise_planilha│
 │ (KPIs, painéis, tabelas)   │  Analise JSON   │         │            (o MESMO da v1)       │
 │ nada gravado em disco      │                 │         ├─ PostgreSQL (usuários, cargas,   │
 └──────────────────────────┘                 │         │   modelos, metas, auditoria)     │
                                               │         └─ volume privado (planilhas brutas)│
                                               └───────────────────────────────────────────┘
```

O ponto central do desenho: **o motor `src/analise_planilha/` não muda de papel.** Hoje ele é chamado
pela janela, pelas CLIs e pelo autoteste; na v2 ganha um quarto chamador, a API. Nenhuma regra de negócio
é reescrita.

## 3. Decisões técnicas (respostas às questões do planejamento)

### 3.1 Stack do servidor

| Peça | Escolha | Por quê |
|---|---|---|
| API | **FastAPI + Uvicorn** | Python (reusa o motor sem ponte), leve, validação de entrada embutida, dependências por rota (base do isolamento — [18 §5](18_seguranca_lgpd_v2.md#5-isolamento-por-centro-de-custo-anti-bypass)) |
| Banco | **PostgreSQL 16** desde o início | nº de setores incerto; mesmo banco da homologação à produção (sem migração SQLite→Postgres); **Row-Level Security** como 2ª trava de isolamento |
| Acesso a dados | **SQLAlchemy 2 + Alembic** | migrações versionadas — o esquema vai crescer fase a fase |
| Sessão | **Token opaco guardado no banco** (não JWT) | inativar usuário ou revogar sessão tem efeito **imediato**; com JWT isso exige consultar o banco a cada requisição, o que anula a vantagem |
| Senha | **Argon2id** (`argon2-cffi`) | padrão atual; troca obrigatória no 1º acesso |
| TLS | **Caddy** como proxy reverso | certificado interno com 1 linha de configuração; ver [18 §7](18_seguranca_lgpd_v2.md#7-rede-retenção-e-backup) |
| Orquestração | `docker compose` (proxy, api, banco) | o mesmo arquivo roda na máquina de homologação e no Linux de produção |

**Adiado de propósito** (o volume atual não justifica): fila/worker (Celery/RQ), Parquet/DuckDB, cache
distribuído. Entram só se uma medição mostrar necessidade.

> ⚠ **Licença do Docker Desktop:** é gratuito só para empresas com menos de 250 funcionários **e** menos
> de US$ 10 mi de faturamento anual. Se a Unimed passar de um dos limites, a homologação deve usar
> **Docker Engine no WSL2** ou **Podman** (gratuitos, mesmos `compose`). Verificar antes da fase 1.

### 3.2 Exibição no cliente — sem navegador embutido

O rascunho previa renderizar HTML dentro do PyQt6. Isso exigiria o `QWebEngineView` (Chromium), que
**aumenta o `.exe` em centenas de MB** — o oposto de cliente leve. Não é necessário:

- a janela da v1 **já desenha a análise de forma nativa**: cartões de KPI, painéis com `ModeloPandas`,
  resumo em `QTextBrowser`, busca com realce;
- na v2, o servidor devolve o objeto `Analise` **serializado em JSON** e o cliente alimenta as mesmas
  telas com ele;
- o relatório HTML continua existindo **só para exportação** (papel Gestor), gerado no servidor.

Consequências boas: o cliente fica do tamanho de hoje; nada de "Salvar como…/Exibir código-fonte/DevTools"
para bloquear, porque não há navegador; e o que trafega é só o recorte filtrado, não a planilha.

### 3.3 Filtros rápidos (cache)

Fluxo por requisição: o cliente envia os `Filtros` → a API pega o `Dataset` daquela carga **já tratado em
memória** → `servico.analisar(ds, filtros)` → `Analise` em JSON.

- O `Dataset` é montado **uma vez** por carga (`servico.carregar` sobre o arquivo bruto do volume) e fica
  num cache em memória (LRU, por `carga_id`). No volume atual a montagem leva segundos e a análise
  filtrada, milissegundos.
- A **Base detalhada** vai **paginada** (o HTML já limita a 5.000 linhas pelo mesmo motivo).
- Persistir o tratado em Parquet só se o tempo de montagem virar problema medido.

### 3.4 Convivência com testes, CLIs e autoteste

```
src/analise_planilha/   motor — compartilhado, sem dependência de rede ou banco (como hoje)
  └─ serializacao.py    NOVO: Analise ⇄ JSON (usado pela API e pelo cliente)
app/                    cliente PyQt6
  └─ fonte.py           NOVO: FonteAnalise — FonteLocal (v1, chama servico) | FonteRemota (v2, chama a API)
servidor/               NOVO: API (rotas, banco, segurança), Dockerfile, migrações Alembic
docker-compose.yml      NOVO
testes/                 os 116 atuais seguem; + testes/servidor/ (API, isolamento, auditoria)
```

- **Nada é duplicado:** API, janela (local), CLIs e autoteste chamam o mesmo `servico.py`.
- A janela passa a falar com uma `FonteAnalise`. Com `FonteLocal` ela é **exatamente a v1** — é isso que
  permite construir a v2 sem quebrar a v1 (padrão *strangler*).
- `pytest`, `gerar_relatorio.py`, `analisar.py` e `--autoteste` continuam locais e offline.

**Decisão pendente:** o `.exe` distribuído aos setores deve ter o **modo local desligado** (só servidor);
senão qualquer um abre planilha na própria máquina e o controle se perde. O modo local fica para o build
de desenvolvimento/ADM.

## 4. Papéis e permissões (RBAC)

Cada pessoa tem **um** centro de custo fixo e **um** papel. Ninguém sabe da existência de relatórios de
outro centro de custo (a API responde **404**, não 403, para o que é de outro setor).

| Ação | Usuário | Gestor | ADM |
|---|:---:|:---:|:---:|
| Ver relatórios **publicados** do seu centro de custo e filtrar | ✅ | ✅ | ✅ todos¹ |
| Ver "Compartilhados comigo" (vigentes, somente leitura) | ✅ | ✅ | ✅ |
| Exportar HTML / baixar planilha original | ❌ | ✅ próprio setor | ✅ |
| Enviar planilha, testar em Rascunho, Publicar | ❌ | ✅ próprio setor | ✅ |
| Editar metas | ❌ | ✅ próprio setor | ✅ |
| Cadastrar/bloquear usuários | ❌ | ✅ só papel Usuário, do próprio setor | ✅ todos |
| Autorizar acesso temporário a pessoa de outro setor | ❌ | ✅ próprio setor | ✅ |
| Centros de custo, gestores, modelos `.toml`, consulta à auditoria | ❌ | ❌ | ✅ |

¹ Revisão em relação ao rascunho: o ADM vê tudo, mas **todo acesso do ADM a dados de um setor é
auditado** como qualquer outro. "Ver tudo" não pode ser "ver sem deixar rastro".

**Acesso temporário entre setores:** o gestor dono autoriza um destinatário, com prazo e a opção de
anonimizar. O convidado atua **sempre como Usuário** naquele relatório (mesmo que seja Gestor no setor
dele). Vencido ou revogado, some na hora — a verificação é feita a cada requisição, não no login.

**Limitação aceita na 2.0:** quem atende dois setores precisa de acesso temporário renovável. Vínculo
N:N pessoa × centro de custo fica para depois, se aparecer o caso.

**Primeiro ADM:** criado por comando dentro do contêiner (sem senha padrão no código).

## 5. Modelo de dados

| Tabela | Campos principais | Observação |
|---|---|---|
| `centros_custo` | id, codigo, nome, ativo | |
| `usuarios` | id, nome, login, senha_hash, papel, centro_custo_id, ativo, precisa_trocar_senha, tentativas_falhas, bloqueado_ate, ultimo_acesso | |
| `sessoes` | id, usuario_id, token_hash, criada_em, expira_em, revogada, ip, versao_cliente | **nova**: viabiliza revogação imediata |
| `modelos_relatorio` | id, slug, nome, toml_texto, versao, centro_custo_id, ativo | o `.toml` mora no banco, editado só pelo ADM |
| `metas` | modelo_id, metas_json, atualizado_por, atualizado_em | **separada** do modelo: metas são do gestor, o `.toml` é do ADM |
| `cargas` | id, modelo_id, centro_custo_id, enviado_por, nome_original, hash_sha256, arquivo_uuid, tamanho, competencia (opcional), status, publicado_por, publicado_em, criado_em | arquivo no volume com nome **aleatório**, nunca o nome enviado |
| `acessos_temporarios` | id, modelo_id, usuario_destino, autorizado_por, expira_em, anonimizar, revogado_por, revogado_em | escopo por **relatório**, não por carga |
| `auditoria` | id, quando, usuario_id, centro_custo_id, acao, alvo, detalhes, ip, versao_cliente | **só inserção** ([18 §6](18_seguranca_lgpd_v2.md#6-auditoria-só-inserção)) |

**Ajuste ao rascunho — competência:** relatórios em matriz (Faturamento/Custos/DRE do HUNF) trazem
**vários meses num arquivo só**; "uma carga = uma competência" não serve para eles. Regra proposta:

- modelo em **matriz**: a nova carga publicada **substitui** a anterior (status `SUBSTITUIDA`) — é o que
  o `servico` já faz hoje com "versões da mesma planilha";
- modelo em **registros** (ex.: Contas Convênio, um arquivo por ano): as cargas publicadas **convivem** e
  podem ser consolidadas, como o "Arquivos (juntar)" da v1.

Status de carga: `RASCUNHO` → `PUBLICADA` → (`SUBSTITUIDA` | `EXCLUIDA`). Exclusão é lógica e auditada.

## 6. API (primeira versão)

| Rota | Quem | O quê |
|---|---|---|
| `GET /api/v1/status/versao` | público | versão do servidor, mínima e recomendada do cliente ([17](17_atualizacao_v2.md)) |
| `POST /api/v1/sessao` · `DELETE /api/v1/sessao` | público · autenticado | login / logout |
| `POST /api/v1/sessao/senha` | autenticado | troca de senha |
| `GET /api/v1/relatorios` | todos | relatórios permitidos: do setor + compartilhados (com dias restantes) |
| `POST /api/v1/relatorios/{slug}/analise` | todos | corpo: `Filtros` → `Analise` em JSON (já anonimizada se for o caso) |
| `GET /api/v1/relatorios/{slug}/base?pagina=` | todos | Base detalhada paginada |
| `GET /api/v1/relatorios/{slug}/html` | Gestor, ADM | relatório HTML para exportar (com marca d'água) |
| `POST /api/v1/cargas` · `POST /api/v1/cargas/{id}/publicar` | Gestor, ADM | upload validado · publicação |
| `PUT /api/v1/relatorios/{slug}/metas` | Gestor, ADM | metas do setor |
| `/api/v1/usuarios` · `/api/v1/acessos-temporarios` | Gestor, ADM | gestão do setor |
| `/api/v1/admin/...` | ADM | centros de custo, gestores, modelos, auditoria |

Toda requisição autenticada envia `Authorization` e `X-Client-Version`.

## 7. Interface do cliente (o que muda)

- **Tela de login**, precedida da checagem de versão.
- **Barra lateral:** o seletor Pasta › Relatório › Página da v1 vira a lista de relatórios **permitidos**,
  mais a seção **"Compartilhados comigo"** (com dias restantes). O ADM ganha um seletor de centro de custo.
- **Mesmas telas de análise** da v1, alimentadas pela API.
- **Gestor:** envio de planilha (Rascunho → conferir → Publicar), metas, usuários do setor, autorização
  temporária.
- **ADM:** centros de custo, gestores, modelos `.toml`, consulta à auditoria.
- Botões que o papel não pode usar ficam **ocultos**, e o servidor também recusa — a trava real é sempre
  no servidor.

## 8. Plano em fases

Cada fase termina com algo **utilizável e testado**. A v1 continua funcionando em todas.

| Fase | Entrega | Pronto quando |
|---|---|---|
| **0 · Fundação** | `serializacao.py` (Analise ⇄ JSON); `FonteAnalise` na janela com `FonteLocal` | 116 testes + autoteste OK; janela **idêntica** à v1 (mesma comparação de estados feita na divisão do `janela.py`) |
| **1 · Servidor mínimo** | `docker compose` (proxy, api, banco); `status/versao`; login com sessão; 1 centro de custo; carga sintética enviada pelo ADM; `FonteRemota` + tela de login | um cliente **sem nenhum arquivo local** mostra o relatório sintético; sem sessão → 401 |
| **2 · Isolamento + auditoria** | escopo obrigatório por centro de custo + RLS no Postgres; auditoria só-inserção | teste automático: usuário do setor A tentando **toda** rota contra recursos do setor B recebe 404; eventos auditados |
| **3 · Papéis e travas** | Usuário/Gestor/ADM; troca de senha obrigatória; bloqueio por tentativas; gestor cadastra usuários | matriz do §4 coberta por testes, rota a rota |
| **4 · Carga e publicação** | upload validado ([18 §4](18_seguranca_lgpd_v2.md#4-upload-seguro)), Rascunho → Publicada, substituição/consolidação, metas no servidor | planilhas sintéticas e arquivos maliciosos de teste (zip bomb, extensão falsa) tratados corretamente |
| **5 · Compartilhamento + anonimização** | acesso temporário; anonimização no servidor por coluna sensível; marca d'água | convidado com `anonimizar` nunca recebe o nome real (teste inspecionando o JSON) |
| **6 · Atualização v2** ✅ | checagem de versão + `426`; espelho da release no servidor; rollback ([17](17_atualizacao_v2.md)) | cliente antigo é barrado (feito); espelho+aprovação do ADM (feito); *rollback automático depende do 1º build `.exe`* |
| **7 · Produção** 🧱 | servidor Linux atrás do pfSense, TLS, backup criptografado, retenção definida | infraestrutura pronta (Caddy/TLS, `backup.sh`/`restore.sh` cifrados, `.env`); falta o deploy no Linux e o checklist de [18 §8](18_seguranca_lgpd_v2.md#8-checklist-antes-do-primeiro-dado-real) — **só então dados reais** |

As fases 0–5 (fundação, servidor, isolamento, papéis, carga, compartilhamento) estão ✅ concluídas e
testadas (ver os commits da branch `v2` e o [17](17_atualizacao_v2.md)/[18](18_seguranca_lgpd_v2.md)).

**Piloto com dado real:** começar pelo **HUNF** (Faturamento/Custos/DRE), que **não tem dado de
paciente**. As **Contas Convênio** (nome de paciente) entram só depois da fase 5 em produção.

Se o projeto parar na fase 2, o objetivo principal (cada setor com os próprios dados, isolado e auditado)
já estará atendido.

## 9. Decisões pendentes

| # | Decisão | Recomendação |
|---|---|---|
| 1 | Docker Desktop (licença) × Docker Engine no WSL2/Podman | verificar o porte da Unimed; se passar do limite, WSL2 |
| 2 | Modo local no `.exe` dos setores | desligado; modo local só no build de dev/ADM |
| 3 | Certificado TLS: a Unimed tem CA interna? | se tiver, usar; senão, CA do próprio Caddy distribuída aos PCs |
| 4 | Política de retenção dos arquivos brutos | definir com o DPO antes da fase 7 |
| 5 | Primeiro centro de custo piloto | HUNF (sem dado de paciente) |
