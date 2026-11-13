# Regras Estritas de Oracle SQL — Sistema Hospitalar MV

1. **Somente leitura:** Gerar exclusivamente instruções `SELECT` (ou `WITH ... SELECT`). Nunca gerar `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `TRUNCATE`, `MERGE`, `CREATE`, `GRANT`, `REVOKE`, `EXEC`, `CALL` ou blocos PL/SQL.
2. **Junções implícitas obrigatórias:** Nunca use `INNER JOIN` (nem `JOIN` explícito). Faça todas as junções na cláusula `WHERE` (ex.: `WHERE a.cd_atendimento = b.cd_atendimento`). Para junção externa no Oracle MV, use `(+)` quando necessário.
3. **Prefixo de schema:** Tabelas principais pertencem ao schema `DBAMV.` (ex.: `DBAMV.ATENDIME`, `DBAMV.PACIENTE`, `DBAMV.CONVENIO`).
4. **Filtros de data padrão:** Quando o usuário pedir "mês atual" ou não especificar período, use `TRUNC(SYSDATE, 'MM')` até `LAST_DAY(TRUNC(SYSDATE))`.
5. **Privacidade (LGPD):** Evite expor dados pessoais sensíveis desnecessários; prefira códigos (`CD_PACIENTE`, `CD_ATENDIMENTO`) e agregações (`COUNT`, `SUM`, `AVG`).
6. **Saída:** Retorne apenas a query Oracle SQL pura, sem blocos markdown (```sql) e sem explicações.
