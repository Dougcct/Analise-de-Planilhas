# servidor/ — API v2 (em desenvolvimento, branch `v2`)

Backend cliente-servidor da v2.0 (ver [DOCS/16](../DOCS/16_arquitetura_v2.md)). **Fase 1 (atual):** API
mínima, sem banco e sem login, servindo um relatório sintético — só para provar o fim a fim HTTP.

## Rodar em desenvolvimento

```powershell
.venv\Scripts\python -m uvicorn servidor.app:app --port 8000
```

- `GET  /api/v1/status/versao` — versão do servidor e mínima/recomendada do cliente
- `GET  /api/v1/relatorios` — relatórios disponíveis (na fase 1, um fixo)
- `POST /api/v1/relatorios/sintetico/analise` — corpo: `Filtros` → `Analise` em JSON
- Documentação interativa: `http://localhost:8000/docs`

As dependências de servidor estão em `requirements.txt` (usadas pela imagem Docker; em dev já entram pelo
`requirements-dev.txt`). Docker/compose e os detalhes das próximas fases: [DOCS/16 §8](../DOCS/16_arquitetura_v2.md#8-plano-em-fases).
