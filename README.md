# Análise de Planilhas

> **Da planilha ao relatório, automaticamente.**

**O problema** — cada setor mantém planilhas no seu próprio formato, e virar indicador confiável é trabalho
manual, refeito todo mês. **A solução** — uma base única que lê a planilha do cliente *como ela é*, reconhece
os tipos de dado, aplica as regras de negócio daquele relatório e entrega os indicadores prontos. Sem
reprogramar para cada planilha nova: basta descrever o cliente num arquivo de modelo.

O produto é um **servidor web** (FastAPI + Docker) com login e **controle por setor**: cada equipe envia suas
planilhas (`xlsx`, `ods`, `csv`), o sistema padroniza os dados e publica um **relatório analítico HTML** no
navegador — no mesmo desenho do projeto **Garantia de Atendimento e Reembolso**.

**Versão:** 3.0.0 · **Saídas:** HTML (PDF e DOCX previstos)

---

## O que você ganha

- **Relatório por modelo do cliente** (`dominio/modelos/*.toml`) — colunas e regras de negócio do cliente
  (taxas, tempos, metas…); ou **sem modelo**, com tipos e indicadores deduzidos automaticamente.
- **Painel Executivo** no topo de cada relatório, com KPIs, destaque e gráficos — **editável** pelo gestor
  (escolher KPIs, título, layout e promover gráficos ao topo).
- **Várias planilhas num só relatório** (ex.: um ano por arquivo), com **filtros** por período e por dimensão
  (Convênio, Ano, Arquivo de origem…) na própria tela.
- **Envio guiado**: prévia com **vínculo automático do modelo** e **selos de situação**, tela de rascunhos,
  publicar ou descartar.
- **Controle por setor**: login, papéis (ADM / gestor), isolamento de dados por equipe, autoatendimento de
  senha (trocar / esqueci, com aviso ao ADM) e compartilhamento de versão curada entre setores.
- **Agentes Especialistas por Setor** (determinísticos, sem IA em execução): quando a planilha é de um
  setor conhecido (ex.: **Faturamento**, **Custos**), um agente limpa o export de ERP bagunçado (acha o
  cabeçalho real, descarta subtotais, blinda códigos, arruma números) e **acrescenta a análise do setor**
  ao relatório (glosa, orçado × realizado, Curva ABC, aging…). Escolha/troca na prévia. [dominio/docs/19](dominio/docs/19_agentes_por_setor.md).
- **Dashboard Feedback / NPS** (setor **Diretoria**): tipo de relatório de **layout fixo** que reproduz o
  painel da pesquisa de pacientes (NPS, tempo de espera, expectativas, por serviço) a partir do CSV cru —
  gráficos de rosca com % e tooltip. Escolha **«Feedback / NPS»** no seletor de modelo. [dominio/docs/20](dominio/docs/20_feedback_nps.md).

Exemplo pronto: **Contas Convênio** (contas hospitalares em blocos — [dominio/docs/12](dominio/docs/12_contas_convenio.md)).

---

## Uso

```powershell
docker compose up      # sobe o servidor (banco + API/web)
```

Abra **http://localhost:8000/web**, faça login e:

- **Relatório** → veja KPIs, gráficos e tabelas, com filtros de período/dimensão.
- **Enviar** (gestor) → escolha a planilha → prévia → publicar.

Passo a passo em [POP-01](dominio/docs/pops/POP-01_operacao.md).

> **Modo I.A** (opcional) envia apenas estrutura anonimizada — nunca os valores ([dominio/docs/11](dominio/docs/11_modo_ia.md)).

---

## Adaptar a um novo cliente

1. Copie `dominio/modelos/exemplo.toml.sample` → `dominio/modelos/<cliente>.toml`
   (ou gere pelo **Cérebro**, a partir das planilhas de `dados/setores/`).
2. Ajuste colunas e regras de negócio ([dominio/docs/04](dominio/docs/04_modelo_de_cliente.md)).
3. Pronto — aparece como relatório. **Nenhuma mudança de código.**

---

## Desenvolvimento

```powershell
pip install -r requirements-dev.txt
python scripts/gerar_relatorio.py   # relatório pela linha de comando  (--listar, --relatorio, --dim…)
python scripts/analisar.py arq.xlsx # resumo da inferência de uma planilha no terminal
python -m pytest                    # suíte offline (fixtures sintéticas)
ruff check .                        # lint
```

Requisitos: **Python 3.11+** (testado em 3.12) e **Docker** para subir o servidor.

### Estrutura

```
dominio/                DEFINIÇÕES DE NEGÓCIO (um lugar só — ver dominio/README.md):
  ├─ Agentes/           Agentes Especialistas por Setor (Escudo de ERP + análise setorial; determinístico)
  ├─ modelos/           modelos de cliente (.toml)        └─ docs/  documentação, POPs, changelog, roadmap
src/analise_planilha/   o motor: lógica pura (leitura, modelo, inferência, indicadores, relatório, Cérebro)
servidor/               servidor web (FastAPI + Docker): web.py (rotas), app.py (API), bd, segurança…
templates/              relatório HTML (Jinja2) + casca web (templates/web/)
scripts/                CLIs e utilitários: gerar_relatorio.py, analisar.py, painel-controle.py, *.bat
automacao/              conversor SQL → Excel     assets/  ícone e logo     config/  ia.toml (Modo I.A)
testes/                 suíte offline (sem rede, sem dados reais)
dados/  dados/saida/          planilhas a analisar / relatórios gerados — não versionar (LGPD)
docker-compose*.yml     orquestração (dev/override/prod)   pyproject.toml  config de build/testes/lint
```

Documentação completa: [dominio/docs/README.md](dominio/docs/README.md) · histórico em [dominio/docs/CHANGELOG.md](dominio/docs/CHANGELOG.md).

---

## LGPD

`dados/` e `dados/saida/` **nunca** são versionados. Nos testes, use apenas dados sintéticos. O relatório HTML pode
conter dados pessoais — uso interno; não publicar em serviços externos. Marque **Anonimizar nomes** antes de
mostrar a tela ou o relatório a terceiros.
