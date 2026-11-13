# Faturamento, Convênios e Glosas (MV — DBAMV)

## Tabelas principais e chaves de junção (`WHERE`)
- `DBAMV.REG_FAT` (alias `rf`): Contas hospitalares de internação (`CD_REG_FAT`, `CD_ATENDIMENTO`, `CD_CONVENIO`, `CD_CON_PLA`, `DT_INICIO`, `DT_FINAL`, `DT_FECHAMENTO`, `VL_TOTAL_CONTA`, `SN_FECHADA`).
- `DBAMV.ITREG_FAT` (alias `irf`): Itens lançados na conta hospitalar (`CD_REG_FAT`, `CD_PRO_FAT`, `QT_LANCAMENTO`, `VL_UNITARIO`, `VL_TOTAL_CONTA`, `DT_LANCAMENTO`).
- `DBAMV.REG_AMB` (alias `ra`) / `DBAMV.ITREG_AMB` (alias `ira`): Contas ambulatoriais (`CD_REG_AMB`, `CD_CONVENIO`, `CD_ATENDIMENTO`, `CD_PRO_FAT`, `VL_TOTAL_CONTA`).
- `DBAMV.CONVENIO` (alias `cv`): Convênios (`CD_CONVENIO`, `NM_CONVENIO`, `TP_CONVENIO`).
- `DBAMV.PRO_FAT` (alias `pf`): Procedimentos/itens de faturamento (`CD_PRO_FAT`, `DS_PRO_FAT`, `CD_GRU_PRO`).
- `DBAMV.CON_REC` / `DBAMV.GLOSA`: Contas a receber e glosas (`CD_CON_REC`, `CD_REG_FAT`, `VL_GLOSA`, `VL_RECURSO`).

## Exemplo de junção implícita (padrão MV)
```sql
SELECT cv.nm_convenio, COUNT(DISTINCT rf.cd_reg_fat) AS qtd_contas, SUM(rf.vl_total_conta) AS vl_total
FROM dbamv.reg_fat rf, dbamv.convenio cv
WHERE rf.cd_convenio = cv.cd_convenio
  AND TRUNC(rf.dt_fechamento) BETWEEN TRUNC(SYSDATE, 'MM') AND LAST_DAY(TRUNC(SYSDATE))
GROUP BY cv.nm_convenio
```
