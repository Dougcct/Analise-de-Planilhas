# Exames, Laboratório e Imagem (MV — DBAMV)

## Tabelas principais e chaves de junção (`WHERE`)
- `DBAMV.PED_LAB` (alias `pl`) / `DBAMV.ITPED_LAB` (alias `ipl`): Pedidos e itens de exames laboratoriais (`CD_PED_LAB`, `CD_ATENDIMENTO`, `CD_SETOR`, `CD_PRESTADOR`, `DT_PEDIDO`, `CD_EXA_LAB`, `DT_COLETA`, `DT_LIBERADO`).
- `DBAMV.EXA_LAB` (alias `el`): Cadastro de exames laboratoriais (`CD_EXA_LAB`, `NM_EXA_LAB`).
- `DBAMV.PED_RX` (alias `prx`) / `DBAMV.ITPED_RX` (alias `iprx`): Pedidos de exames de imagem (`CD_PED_RX`, `CD_ATENDIMENTO`, `CD_SETOR`, `CD_PRESTADOR`, `DT_PEDIDO`, `CD_EXA_RX`, `DT_REALIZADO`).
- `DBAMV.EXA_RX` (alias `erx`): Cadastro de exames de imagem (`CD_EXA_RX`, `DS_EXA_RX`).
- `DBAMV.SETOR` (alias `s`) / `DBAMV.PRESTADOR` (alias `pt`): Setor e médico solicitante (`CD_SETOR`, `NM_SETOR`, `CD_PRESTADOR`, `NM_PRESTADOR`).

## Exemplo de junção implícita (padrão MV)
```sql
SELECT el.nm_exa_lab, COUNT(ipl.cd_itped_lab) AS qtd_exames
FROM dbamv.ped_lab pl, dbamv.itped_lab ipl, dbamv.exa_lab el
WHERE pl.cd_ped_lab = ipl.cd_ped_lab
  AND ipl.cd_exa_lab = el.cd_exa_lab
  AND TRUNC(pl.dt_pedido) BETWEEN TRUNC(SYSDATE, 'MM') AND LAST_DAY(TRUNC(SYSDATE))
GROUP BY el.nm_exa_lab
```
