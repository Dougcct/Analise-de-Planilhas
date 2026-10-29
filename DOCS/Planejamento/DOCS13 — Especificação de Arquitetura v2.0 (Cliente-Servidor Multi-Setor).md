# DOCS/13 — Especificação de Arquitetura v2.0 (Cliente-Servidor Multi-Setor)

> **Instrução de Contexto para o Agente de IA (Claude):**
> Este documento é o guia mestre da evolução do projeto **Análise de Planilhas** (v1.0 local -> v2.0 Cliente-Servidor em Docker), mantendo o cliente desktop em **PyQt6 + Nuitka**.
>
> **DOCUMENTOS COMPLEMENTARES OBRIGATÓRIOS:**
> Leia este arquivo em conjunto com:
> * [DOCS/14_auto_update_github.md](14_auto_update_github.md) — Fluxo de atualização e trava de versão.
> * [DOCS/15_seguranca_e_lgpd.md](15_seguranca_e_lgpd.md) — Blindagem de dados, LGPD e auditoria.
>
> **COMO VOCÊ DEVE AGIR:**
> 1. **Não altere o código imediatamente.** Inspecione primeiro a estrutura atual (`app/`, `src/analise_planilha/`, `config/`, `templates/`, `build.bat`).
> 2. Responda aos questionamentos técnicos do final deste documento e dos documentos `14` e `15`, apontando melhorias, riscos e um **Plano de Migração em Fases** para aprovação.

---

## 1. Contexto Atual vs. Objetivo da v2.0

### O que já temos hoje (v1.0 - Local)
* **Interface Desktop:** `app/` em Python 3.11+/3.12 com **PyQt6**, compilada em `.exe` via **Nuitka** (`build_nuitka\main.dist\AnalisePlanilhas.exe`) e integrada ao **GitHub** para atualizações.
* **Motor Analítico Desacoplado:** `src/analise_planilha/` realiza leitura (`.xlsx`, `.ods`, `.csv`), inferência, aplicação de regras `.toml` (`config/modelos/*.toml`), cálculo de indicadores, metas (`metas.json`) e geração de HTML via **Jinja2**.
* **Automação e Testes:** CLIs `gerar_relatorio.py` e `analisar.py`, autoteste (`--autoteste`) e suíte offline em `pytest` (`testes/`).

### Onde queremos chegar (v2.0 - Multi-Setor)
Disponibilizar o sistema para múltiplos setores usando o executável PyQt6 como uma "casca leve" de visualização e operação, enquanto **armazenamento, regras `.toml`, controle de acesso e cálculos pesados ficam centralizados no Servidor (Docker)**.
* **Premissa "PC da Xuxa":** Máquinas antigas ou modestas nos setores devem abrir relatórios grandes sem engasgar, pois todo o processamento pesado acontece no servidor.
* **Ambiente do Servidor:** Homologação inicial via **Docker Desktop** (Windows) e subida futura transparente via `docker-compose` para servidor **Linux** dedicado.

---

## 2. Arquitetura do Sistema

### 2.1. Servidor (Containers Docker)
1. **API Backend (Porteiro Único):** Único canal de comunicação com o PyQt6. Valida versão mínima do cliente, autenticação (Token JWT), permissões por Centro de Custo/Papel e entrega indicadores e HTML prontos.
2. **Motor Analítico (`src/analise_planilha/`):** Roda dentro do container da API/Worker. Processa a planilha no upload e guarda o resultado estruturado para resposta instantânea aos filtros da tela.
3. **Banco de Dados Relacional:** Guarda usuários, centros de custo, vínculo de modelos `.toml`, metadados das planilhas, metas por setor, acessos temporários e trilha de auditoria LGPD.
4. **Storage Interno Isolado:** Volume Docker privado contendo os arquivos brutos enviados, modelos `.toml` e chaves sensíveis (como credenciais do Modo I.A, antes locais em `config/ia.toml`).

### 2.2. Cliente Desktop (PyQt6 + Nuitka)
1. **Zero Dados Persistidos no Cliente:** Não usa mais `dados/` nem `saida/` locais em produção (ver [DOCS/15](15_seguranca_e_lgpd.md)).
2. **Handshake de Versão e Auto-Update:** Verifica obrigatoriamente a compatibilidade de versão antes do login e aciona o atualizador via GitHub quando necessário (ver [DOCS/14](14_auto_update_github.md)).
3. **Renderização Interna:** Exibe relatórios HTML dentro da própria janela PyQt6, respeitando travas de exportação conforme o papel do usuário.

---

## 3. Regras de Negócio: Isolamento, Papéis e Permissões

### 3.1. Isolamento Estrito por Centro de Custo
* **Cadastro Único:** Cada pessoa possui **1 único Centro de Custo fixo** e **1 único Papel** (`ADM`, `Gestor` ou `Usuário`).
* **Invisibilidade entre Setores:** Nenhum usuário ou gestor sabe da existência de relatórios ou planilhas de outros Centros de Custo, exceto quando convidado temporariamente.

### 3.2. Matriz de Permissões (RBAC)

| Ação / Recurso | Usuário | Gestor | ADM |
|---|:---:|:---:|:---:|
| Ver relatórios `Publicados` do seu Centro de Custo | ✅ | ✅ | ✅ (Todos) |
| Filtrar indicadores na tela | ✅ | ✅ | ✅ |
| Ver relatórios na aba **"Compartilhados comigo"** (vigentes) | ✅ | ✅ | ✅ |
| Exportar HTML ou baixar planilha original | ❌ | ✅ (Próprio setor) | ✅ |
| Enviar planilha, testar em `Rascunho` e `Publicar` | ❌ | ✅ (Próprio setor) | ✅ |
| Editar metas do próprio Centro de Custo | ❌ | ✅ (Próprio setor) | ✅ |
| Cadastrar/Bloquear **Usuários** do próprio Centro de Custo | ❌ | ✅ (Apenas papel Usuário) | ✅ (Todos) |
| Autorizar **Acesso Temporário** para pessoa de outro setor | ❌ | ✅ (Próprio setor) | ✅ |
| Gerenciar Centros de Custo, Gestores, `.toml` e Auditoria | ❌ | ❌ | ✅ |

### 3.3. Regra de Autorização Temporária (Empréstimo entre Setores)
1. O Gestor dono da planilha (ex: Financeiro) escolhe um relatório seu e clica em **Autorizar Acesso Externo**.
2. Seleciona o destinatário (ex: Gestor do Faturamento), define a **data/dias de expiração** e marca se exige **Anonimização de Nomes** (`True/False`).
3. **Escopo Sempre Somente Leitura:** Na planilha emprestada, o convidado atua estritamente como **`Usuário`** (apenas visualiza dentro do app; não baixa, não altera metas e não repassa a terceiros), mesmo que ele seja Gestor no setor de origem dele.
4. Venceu o prazo ou foi revogado pelo Gestor dono/ADM, o item some imediatamente da aba **"Compartilhados comigo"**.

---

## 4. Modelo Conceitual de Dados

* **`centros_custo`**: `id`, `codigo`, `nome`, `ativo`.
* **`usuarios`**: `id`, `nome`, `login`, `senha_hash`, `papel` (`ADM` | `GESTOR` | `USUARIO`), `centro_custo_id`, `ativo`, `precisa_trocar_senha`, `ultimo_acesso`.
* **`modelos_relatorio`**: `id`, `slug`, `nome`, `caminho_toml`, `centro_custo_id`, `metas_json`, `ativo`.
* **`cargas_planilhas`**: `id`, `modelo_id`, `centro_custo_id`, `enviado_por_id`, `competencia` (`MM/YYYY`), `status` (`RASCUNHO` | `PUBLICADO`), `hash_arquivo`, `caminho_arquivo_bruto`, `cache_processado`, `criado_em`.
* **`acessos_temporarios`**: `id`, `carga_id`, `usuario_destino_id`, `autorizado_por_id`, `expira_em`, `anonimizar_nomes`, `revogado`, `criado_em`.
* **`auditoria_logs`**: detalhado em [DOCS/15](15_seguranca_e_lgpd.md).

---

## 5. Adaptações na Interface (PyQt6)

* **Tela Inicial de Login:** Validação de versão ([DOCS/14](14_auto_update_github.md)) + Autenticação.
* **Barra Lateral Dinâmica:** Exibe o Centro de Custo fixo (ou seletor livre para `ADM`), lista apenas os relatórios permitidos e adiciona a seção **"Compartilhados comigo"** (mostrando dias restantes de acesso).
* **Gestão de Carga (Gestor/ADM):** Upload com escolha de Competência (`Mês/Ano`) e chaveamento `Rascunho` / `Publicado`.
* **Gestão do Setor (Gestor):** Cadastro de usuários comuns do próprio setor + modal de Autorização Temporária Externa.
* **Painel Admin (ADM):** Gestão global de Centros de Custo, Usuários/Gestores, modelos `.toml` e consulta de Auditoria LGPD.

---

## 6. Revisão Geral de Arquitetura para o Agente (Claude)

Analise o código atual e opine sobre:
1. **Stack Docker Ideal:** Qual banco relacional e framework de API Python se encaixam melhor na nossa realidade visando baixo consumo no Docker Desktop hoje e estabilidade em Linux amanhã?
2. **Visualizador HTML no PyQt6 + Nuitka:** Qual o impacto de empacotar um visualizador HTML interno no `build.bat` (Nuitka `main.dist`) e qual a melhor alternativa técnica?
3. **Cache de Filtros Rápidos:** Como persistir a planilha já processada no servidor (ex: Parquet, DuckDB ou JSON estruturado) para que os filtros na tela respondam em milissegundos?
4. **Convivência com Testes e CLI:** Como organizar as pastas para manter `pytest`, `--autoteste` e `gerar_relatorio.py` funcionando sem duplicar lógica?
5. **Plano de Execução:** Sugira um roadmap dividido em entregas curtas e testáveis.