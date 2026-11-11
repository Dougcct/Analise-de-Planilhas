# 20 — Dashboard Feedback / NPS (setor Diretoria)

Tipo de relatório de **layout FIXO** que reproduz o dashboard da pesquisa de satisfação de pacientes
(NPS) a partir do **CSV cru** do export. Ao contrário dos relatórios genéricos (KPIs + painéis do
`Analise`), aqui o desenho é fixo: só os números mudam, calculados do CSV.

## Quando usar

Planilha de pesquisa de feedback de pacientes (colunas `Escala de Recomendação`, `Tempo para Atendimento`,
`Atingiu as Expectativas?`, `Serviço(s) utilizado(s)`, `Data de envio`). Vive no setor **Diretoria**.

## Como ligar (no envio)

No formulário de envio, campo **Modelo de análise**, escolher **«Feedback / NPS (pesquisa de pacientes)»**.
Isso marca `rel.modelo = "feedback_nps"` (`feedback.SLUG`) e o dashboard é renderizado garantidamente.
Sem escolher, o sistema ainda reconhece pelo cabeçalho (rede de segurança), mas **prefira selecionar**.

## As 4 páginas (saída)

| Página | Fonte no CSV | Conteúdo |
|---|---|---|
| 1 · NPS | `Escala de Recomendação` (0‑10) | 0‑6 Detrator · 7‑8 Neutro · 9‑10 Promotor · vazio Sem resposta; rosca + chips de % |
| 2 · Tempo de espera | `Tempo para Atendimento` | Ruim / Regular / Bom / Ótimo; rosca + chips |
| 3 · Expectativas | `Atingiu as Expectativas?` | Sim / Não; rosca + chips |
| 4 · Por serviço | `Serviço(s) utilizado(s)` × expectativa | Catálogo FIXO de 30 serviços, split Sim/Não |

`%` é sempre sobre o **total de pesquisas**. `Data de envio` define o mês/ano do cabeçalho.
**Total de Atendimentos** NÃO vem do CSV — é um campo que o gestor/ADM preenche na tela.

## Arquitetura (por que fora do motor)

O dashboard tem desenho próprio e **não** passa por `servico.carregar/analisar` (que renomeia colunas e
trataria a planilha como série financeira, quebrando). Lê os **bytes crus** do CSV.

| Camada | Arquivo | Papel |
|---|---|---|
| Motor (puro) | `src/analise_planilha/feedback.py` | `calcular` (métricas), `render_html` (HTML), `e_feedback`, `SLUG`, cores, catálogo |
| Servidor | `servidor/app.py` | `feedback_linhas(s, rel)` / `feedback_linhas_carga` — leem as cargas cruas (só `.csv`/`.txt`) |
| Rotas (web.py) | `conteudo_relatorio`, `modelo_relatorio` (PDF), `enviar_previa`, `enviar_previa_conteudo` | desviam para o dashboard **antes** do motor |
| Envio/publicação | `enviar_carga`, `enviar_previa_publicar` | pulam motor e auto-modelo quando é feedback |
| Casca | `templates/web/relatorio.html` | esconde o filtro de data (`sem_filtros`) |
| CLI | `scripts/gerar_feedback_nps.py` | CSV → PDF (Chrome/Edge headless ou WeasyPrint) |

**Editar o total de atendimentos:** `POST /web/r/{slug}/feedback/atendimentos` → `rel.config_exec["atendimentos"]`.

## Regras / cuidados

- **LGPD:** o dashboard mostra só agregados (sem nome de paciente) → sem anonimização necessária.
- **Deploy:** o código é COPIADO para a imagem Docker — `reiniciar` não recompila; use **Reconstruir**
  (`docker compose up -d --build`, botão no `painel-controle.py` ou `scripts/reconstruir-docker.bat`).
- **Robustez:** só `.csv`/`.txt` são testados como feedback; erro de parse não derruba relatórios normais.
- Testes: `testes/test_feedback.py`. Para ajustar o mapeamento, mexer em `feedback.calcular`.
