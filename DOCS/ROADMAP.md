# Roadmap

Ordem sugerida, não compromissada. Itens entram no [CHANGELOG](CHANGELOG.md) quando concluídos.

## Curto prazo

1. **Anonimização de dados sensíveis** — ✅ nomes da entidade (iniciais) feito. Falta: CPF, telefone e
   outras colunas marcadas no modelo como `sensivel`. **Prioridade por LGPD.**
1a. **Editor de metas na janela** (como o "⚙ Editar metas" da Garantia): hoje as metas ficam no `.toml`.
1b. **Vários arquivos de uma pasta** numa base só (a Garantia lê a pasta inteira); hoje: várias abas de 1 arquivo.
1c. ~~**Gráficos SVG leves** no relatório~~ — feito (Jinja2 + SVG puro, padrão da Garantia; HTML ~100 KB).
2. **Editar modelo existente no assistente** — hoje o "Salvar como modelo…" cria/sobrescreve; carregar um
   `.toml` existente para edição na janela.
3. **Pasta monitorada de verdade** — observar `dados/entrada/` (watchdog) e gerar o relatório a cada
   arquivo novo, para uso em RPA/agendamento.

4. **Leitura estrutural — próximos passos** ([09](09_leitura_estrutural.md)):
   - escolher a linha do cabeçalho na janela quando a confiança for baixa (o motor já aceita `linha_cabecalho`);
   - "despivotar" formato largo (colunas Jan/Fev/Mar → coluna Período + Valor), opcional no modelo;
   - tabelas lado a lado na mesma aba (separar por coluna vazia e deixar escolher);
   - guardar no `.toml` a "assinatura" estrutural do layout (linha do cabeçalho, seções) para leitura 100% determinística.

## Médio prazo

5. **Exportação PDF/DOCX** — mesmo objeto `Analise`, novos renderizadores.
6. **Comparação entre períodos/arquivos** — variação mês a mês e histórico (SQLite/DuckDB).
7. **Empacotamento `.exe`** — finalizar o build Nuitka e validar em máquina limpa (ver [08](08_build_e_distribuicao.md)).

## Longo prazo

8. **Insights automáticos** — resumo em linguagem natural e detecção de anomalias (local/privado por LGPD).
9. **Biblioteca de modelos** — vários clientes/relatórios com seleção e versionamento dos `.toml`.
