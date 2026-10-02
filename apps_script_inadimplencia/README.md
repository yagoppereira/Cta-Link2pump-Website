# Planilha Central de Inadimplência — Apps Script

Scripts do projeto Apps Script vinculado à planilha
"Planilha Central Inadimplência por Carteira de Vendedor".

| Arquivo | O que faz |
|---|---|
| `SincronizarBases.gs` | Base_CIGAM ← DW (BigQuery) · Base_Cidades ← "Cidades por Vendedor" · orquestrador `atualizarBasesEConsolidar()` |
| `ConsolidarBase.gs` | `consolidarBaseInteligente()`: cascata de regras que gera a Base_Clientes |
| `DistribuirInadimplencia.gs` | `distribuirInadimplenciaPorVendedor()`: lê o arquivo do dia, confere, distribui para as carteiras e alimenta o Looker |
| `Relatorio.gs` | Layout e escrita das seções da aba Relatório (compartilhado pelos três acima) |

Fluxo: **Sincronizar bases → Consolidar Base_Clientes → Distribuir títulos**.

Pré-requisito: serviço avançado **BigQuery API** habilitado no projeto (e Drive API, já usado na distribuição).

Os demais scripts da planilha (validação da Lista_Vendedores, geração de
planilhas de vendedores e patch de layout) ainda não estão versionados aqui.
