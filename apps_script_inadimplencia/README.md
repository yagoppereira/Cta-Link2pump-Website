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
| `AnonimizarDemo.gs` | `Anonimizar Demo.gs` (novo) | `gerarDadosLookerDemo()`: cópia anonimizada do Dados_Looker numa planilha nova; `anonimizarDadosLookerNoLugar()` / `restaurarDadosLooker()`: anonimiza a própria aba com backup oculto e desfaz; `gerarCarteiraDemo()`: carteira de vendedor fictício para capturas |
| `Randomizador.gs` | colar só nas cópias **[DEMO]** | `randomizarPlanilhaDemo()`: troca clientes, CNPJs, vendedores, códigos, faturas e valores de forma consistente entre abas, sem backup no arquivo; recusa rodar em produção. `verificarDemo()`: reconfere |
| `MenuAutomacoes.gs` | `Menu Automações.gs` | Menu "⚙️ Automações" na ordem do fluxo |

Fluxo: **Sincronizar bases → Consolidar Base_Clientes → Distribuir títulos**.

Pré-requisito: serviço avançado **BigQuery API** habilitado no projeto (e Drive API, já usado na distribuição).

Os demais scripts da planilha (validação da Lista_Vendedores, geração de
planilhas de vendedores e patch de layout) ainda não estão versionados aqui.

Abas de histórico criadas pela distribuição: `Historico_Distribuicao` (1 linha/dia) e `Historico_Clientes` (1 linha/cliente/dia).
Ajustes manuais no Looker Studio: ver `AJUSTES_LOOKER.md`.

## Controles manuais paralelos (aba Insercoes_Manuais e `CONFIG_ATRIBUICAO` em ConsolidarBase.gs)

| Caso | Como usar | Efeito |
|---|---|---|
| Vendedor de **parcerias** (só recebe o que for inserido à mão) | Nome em `CONFIG_ATRIBUICAO.vendedoresSomenteManual` (hoje: LEANDRO SOARES) | Vendas dele na Base_Comercial e praças dele na Base_Cidades são ignoradas; o cliente segue para a próxima regra (normalmente o vendedor regional). Regra marcada com " · parceria" |
| Cliente que deve ir para o **vendedor regional** | Na Insercoes_Manuais, CNPJ (exato ou do grupo) e `REGIONAL` na coluna vendedor | Ignora o histórico comercial e atribui pela praça (Cidade/UF): regra "4. Praça (Regional por inserção)". Sem praça ativa → fica "NÃO MAPEADO" (visível no Relatório) |
| **Grandes contas** (pagante dos aparelhos do cliente) | Nome em `CONFIG_ATRIBUICAO.vendedoresGrandesContas` (hoje: MARLON SILVA) e `limiteGrandesContas` (0,5) | Depois da cascata, quem PAGA os aparelhos instalados nos clientes do vendedor (aba `Base_Aparelhos`, do DW) passa para ele — se ≥ 50% dos aparelhos que esse pagante paga estiverem nesses clientes. Inserção manual, inserção REGIONAL e carteira de parcerias sempre prevalecem (ex.: Ipiranga fica em parcerias). Regra "6. Grande conta (pagante de aparelho)" |
| Cidade escrita diferente entre CIGAM e praças | `CONFIG_ATRIBUICAO.apelidosCidade` ("MOJI MIRIM_SP" → "MOGI MIRIM_SP") | A praça passa a ser encontrada |
