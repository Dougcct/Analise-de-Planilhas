# 16 · Arquitetura v2.0 — Servidor web por Centro de Custo

> **Status: v2 em produção — é o produto.** Servidor web (FastAPI + Docker): login, controle por setor e
> relatórios HTML no navegador. As fases 0–6 estão implementadas e rodando; a fase 7 está montada como
> infraestrutura (TLS/backup), pendente de deploy em servidor Linux antes de qualquer dado real.
> Reforços de "defesa em profundidade" ainda pendentes: RLS no Postgres, grant append-only da auditoria
> e Alembic (hoje o esquema é `create_all`). Ver o [§8](#8-plano-em-fases).
> Complemento: [18 · Segurança e LGPD v2](18_seguranca_lgpd_v2.md).
> Origem: rascunhos em `Planejamento/` (out/2026), consolidados e revisados contra o código.

## 1. Por que a v2 existe

**Controle, não desempenho.** Os volumes são pequenos (o motor processa as planilhas atuais em segundos);
o que faltava era governança: antes, os dados e relatórios ficavam espalhados nas máquinas dos operadores.
Na v2:

- cada **centro de custo** (setor) enxerga só os **próprios** relatórios e dados;
- planilhas, modelos `.toml`, metas e chaves ficam no **servidor**, atrás do pfSense;
- o acesso é pelo navegador: sem conta válida no servidor, nada abre;
- tudo o que importa fica registrado (quem enviou, publicou, abriu, exportou, compartilhou).

**Mudança consciente de princípio.** A versão anterior tinha "dados estritamente locais". A v2 **concentra**
os dados num servidor — mais controlável, mas um alvo único. Por isso a regra de implantação:

> **Na máquina do desenvolvedor (homologação em Docker), só dados sintéticos.** Dado real entra apenas no
> servidor de produção, atrás do pfSense, depois da fase 7 ([§8](#8-plano-em-fases)).

Contexto de uso: **uma rede interna**, vários setores, crescendo aos poucos — cada modelo de planilha novo
traz o seu centro de custo e o seu gestor.

## 2. Visão geral

```
 Navegador do setor (cliente web)            Servidor (Docker, atrás do pfSense)
 ┌──────────────────────────┐   HTTPS (LAN)   ┌───────────────────────────────────────────┐
 │ login · lista de relat.   │ ─────────────▶ │ proxy TLS (Caddy)                          │
 │ relatórios HTML            │ ◀───────────── │   └─ API (FastAPI) ── motor analise_planilha│
 │ (KPIs, painéis, tabelas)   │  HTML / JSON    │         │        (o MESMO das CLIs)        │
 │ nada gravado em disco      │                 │         ├─ PostgreSQL (usuários, cargas,   │
 └──────────────────────────┘                 │         │   modelos, metas, auditoria)     │
                                               │         └─ volume privado (planilhas brutas)│
                                               └───────────────────────────────────────────┘
```

O ponto central do desenho: **o motor `src/analise_planilha/` não muda de papel.** Ele é chamado
pelas CLIs e pela API do servidor web; nenhuma regra de negócio é reescrita.

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

### 3.2 Exibição no cliente — relatório HTML no navegador

O cliente é o **navegador**: o servidor renderiza o relatório HTML (cartões de KPI, painéis, tabelas,
resumo e busca com realce) e o entrega pela web. O motor produz o mesmo objeto `Analise` de sempre; o
servidor o serializa em HTML (e em JSON quando a tela precisa recarregar um recorte filtrado).

Consequências boas: nada é instalado no PC do setor; e o que trafega é só o recorte filtrado, não a
planilha bruta.

### 3.3 Filtros rápidos (cache)

Fluxo por requisição: o cliente envia os `Filtros` → a API pega o `Dataset` daquela carga **já tratado em
memória** → `servico.analisar(ds, filtros)` → `Analise` em JSON.

- O `Dataset` é montado **uma vez** por carga (`servico.carregar` sobre o arquivo bruto do volume) e fica
  num cache em memória (LRU, por `carga_id`). No volume atual a montagem leva segundos e a análise
  filtrada, milissegundos.
- A **Base detalhada** vai **paginada** (o HTML já limita a 5.000 linhas pelo mesmo motivo).
- Persistir o tratado em Parquet só se o tempo de montagem virar problema medido.

### 3.4 Convivência com testes e CLIs

```
src/analise_planilha/   motor — compartilhado, sem dependência de rede ou banco
  └─ serializacao.py    Analise ⇄ JSON (usado pela API e pela web)
servidor/               API + web (rotas, banco, segurança), Dockerfile, migrações
docker-compose.yml      sobe db + api
testes/                 testes do motor + testes/servidor/ (API, isolamento, auditoria)
```

- **Nada é duplicado:** a API/web e as CLIs chamam o mesmo `servico.py`.
- `pytest`, `gerar_relatorio.py` e `analisar.py` continuam locais e offline, usando o motor diretamente.

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
| `GET /api/v1/status/versao` | público | versão do servidor |
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

## 7. Interface web

- **Tela de login.**
- **Barra lateral:** a lista de relatórios **permitidos** (seletor Pasta › Relatório › Página), mais a
  seção **"Compartilhados comigo"** (com dias restantes). O ADM ganha um seletor de centro de custo.
- **Telas de análise** com os relatórios HTML, alimentadas pela API.
- **Gestor:** envio de planilha (Rascunho → conferir → Publicar), metas, usuários do setor, autorização
  temporária.
- **ADM:** centros de custo, gestores, modelos `.toml`, consulta à auditoria.
- Botões que o papel não pode usar ficam **ocultos**, e o servidor também recusa — a trava real é sempre
  no servidor.

## 8. Plano em fases (histórico)

Histórico do plano que levou à v2. Cada fase terminava com algo **utilizável e testado**.

| Fase | Entrega | Pronto quando |
|---|---|---|
| **0 · Fundação** | `serializacao.py` (Analise ⇄ JSON) | testes OK; análise serializada igual à do motor direto |
| **1 · Servidor mínimo** | `docker compose` (proxy, api, banco); `status/versao`; login com sessão; 1 centro de custo; carga sintética enviada pelo ADM; tela de login | o navegador **sem nenhum arquivo local** mostra o relatório sintético; sem sessão → 401 |
| **2 · Isolamento + auditoria** | escopo obrigatório por centro de custo + RLS no Postgres; auditoria só-inserção | teste automático: usuário do setor A tentando **toda** rota contra recursos do setor B recebe 404; eventos auditados |
| **3 · Papéis e travas** | Usuário/Gestor/ADM; troca de senha obrigatória; bloqueio por tentativas; gestor cadastra usuários | matriz do §4 coberta por testes, rota a rota |
| **4 · Carga e publicação** | upload validado ([18 §4](18_seguranca_lgpd_v2.md#4-upload-seguro)), Rascunho → Publicada, substituição/consolidação, metas no servidor | planilhas sintéticas e arquivos maliciosos de teste (zip bomb, extensão falsa) tratados corretamente |
| **5 · Compartilhamento + anonimização** | acesso temporário; anonimização no servidor por coluna sensível; marca d'água | convidado com `anonimizar` nunca recebe o nome real (teste inspecionando o JSON) |
| **6 · Versão do servidor** ✅ | checagem de versão + `426` para cliente web antigo | cliente antigo é barrado |
| **7 · Produção** 🧱 | servidor Linux atrás do pfSense, TLS, backup criptografado, retenção definida | infraestrutura pronta (Caddy/TLS, `backup.sh`/`restore.sh` cifrados, `.env`); falta o deploy no Linux e o checklist de [18 §8](18_seguranca_lgpd_v2.md#8-checklist-antes-do-primeiro-dado-real) — **só então dados reais** |

As fases 0–6 (fundação, servidor, isolamento, papéis, carga, compartilhamento, versão) estão ✅ concluídas e
testadas (ver os commits da branch `v2` e o [18](18_seguranca_lgpd_v2.md)).

**Piloto com dado real:** começar pelo **HUNF** (Faturamento/Custos/DRE), que **não tem dado de
paciente**. As **Contas Convênio** (nome de paciente) entram só depois da fase 5 em produção.

Se o projeto parar na fase 2, o objetivo principal (cada setor com os próprios dados, isolado e auditado)
já estará atendido.

## 9. Decisões pendentes

| # | Decisão | Recomendação |
|---|---|---|
| 1 | Docker Desktop (licença) × Docker Engine no WSL2/Podman | verificar o porte da Unimed; se passar do limite, WSL2 |
| 2 | Certificado TLS: a Unimed tem CA interna? | se tiver, usar; senão, CA do próprio Caddy distribuída aos PCs |
| 3 | Política de retenção dos arquivos brutos | definir com o DPO antes da fase 7 |
| 4 | Primeiro centro de custo piloto | HUNF (sem dado de paciente) |
