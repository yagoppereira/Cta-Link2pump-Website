# Planilha Central de Inadimplência — Apps Script

Scripts do projeto Apps Script vinculado à planilha
"Planilha Central Inadimplência por Carteira de Vendedor".

| Arquivo no repo | Arquivo no Apps Script | O que faz |
|---|---|---|
| `SincronizarBases.gs` | `Cruzamento de Bases/Sincronizar Bases.gs` | Base_CIGAM ← DW (BigQuery) · Base_Cidades ← "Cidades por Vendedor" · orquestrador `atualizarBasesEConsolidar()` |
| `ConsolidarBase.gs` | `Cruzamento de Bases/Atribuição Manual.gs` | `consolidarBaseInteligente()`: cascata de regras que gera a Base_Clientes |
| `DistribuirInadimplencia.gs` | `Distribuição de Inadimplência.gs` | `distribuirInadimplenciaPorVendedor()`: lê o arquivo do dia, confere, distribui para as carteiras e alimenta o Looker |
| `Relatorio.gs` | `Relatório.gs` | Layout e escrita das seções da aba Relatório (compartilhado pelos três acima) |
| `Diagnostico.gs` | `Diagnóstico.gs` (novo; substitui `debugger.gs`) | `diagnosticarSistema()`: confere estrutura, versões, acessos, gatilhos, frescor e consistência e grava na aba Diagnóstico |
| `MenuAutomacoes.gs` | `Menu Automações.gs` | Menu "⚙️ Automações" na ordem do fluxo |

Fluxo: **Sincronizar bases → Consolidar Base_Clientes → Distribuir títulos**.

Pré-requisito: serviço avançado **BigQuery API** habilitado no projeto (e Drive API, já usado na distribuição).

Os demais scripts da planilha (validação da Lista_Vendedores, geração de
planilhas de vendedores e patch de layout) ainda não estão versionados aqui.
