# Controle de NFs da Vibra: guia do time

Planilha **PENDENCIAS VIBRA**, aba **Controle NFs Vibra**. Ela lista as NFs
emitidas para a Vibra (todas as filiais), com a situação de pagamento vinda do
CIGAM e a situação de entrega informada pela Emissão.

## De onde vêm os dados

- Um script da própria planilha consulta o CIGAM (pelo data warehouse) e
  reescreve a lista **todo dia às 7h**. Para atualizar na hora: menu
  **Controle Vibra > Atualizar agora** (só funciona pra quem tem acesso ao DW).
- O DW recebe os dados do CIGAM com até 1 dia de atraso: uma NF emitida ou
  paga hoje pode aparecer só amanhã.
- Entram as NFs emitidas desde 01/01/2026, mais as NFs antigas (desde 2024)
  que ainda estejam em aberto. NF que já estava na planilha nunca some.

## Quem preenche o quê

A linha 1 mostra, em cada bloco de colunas, quem cuida dele.

| Colunas | Bloco | Quem preenche |
|---|---|---|
| A a N | **Do CIGAM**: NF, série, emissão, vencimento, valor, saldo, nº do pedido, filial Vibra, tipo, material, status financeiro, data de pagamento, NF de devolução, nº do local de entrega | O script. **Não edite**: tudo é reescrito na próxima atualização. |
| O | **Cliente final** | Fórmula. Vem da aba **Locais de entrega** (ver abaixo). |
| P a R | **Emissão preenche**: status entrega, data da entrega / NF assinada, obs. Emissão | Emissão |
| S | **Financeiro preenche**: obs. financeiro | Financeiro |
| T e U | **Automático**: dias em atraso, próxima ação | Fórmulas |

O que o time escreve em P a S fica preso à NF (número + série): pode reordenar
ou filtrar à vontade que, na atualização, cada informação volta pra linha
certa.

## Status financeiro (coluna K)

Calculado pelo script a partir do título no CIGAM:

| Status | Significa |
|---|---|
| Em aberto | Título sem nenhuma baixa. |
| Pago parcial | Parte recebida; o saldo (coluna F) segue em aberto. |
| Pago | Título liquidado por recebimento. A data está na coluna L. |
| Devolvida | Baixado por abatimento e com NF de devolução da Vibra (coluna M). |
| Abatida | Baixado por abatimento, sem NF de devolução. |
| Cancelada | NF cancelada no CIGAM. |
| Baixa por perda | Baixado como perda. |
| Sem título | NF sem título a receber no DW. Costuma ser NF de ontem que o DW ainda não trouxe. Se passar de 1 dia, o Financeiro confere no CIGAM. |

## Status de entrega e próxima ação

A Emissão escolhe o **Status entrega** (coluna P) na lista suspensa. A
**Próxima ação** (coluna U) se ajusta sozinha:

| Status entrega | Próxima ação (se a NF está em aberto) |
|---|---|
| A validar | Emissão: confirmar entrega |
| Aguardando entrega | Emissão: acompanhar entrega |
| Aguardando NF assinada | Emissão: obter NF assinada |
| Problema na entrega | Emissão: resolver entrega |
| NF assinada recebida | Financeiro: cobrar Vibra |
| Não se aplica | Financeiro: cobrar Vibra |

- NF nova e em aberto entra como **A validar**. Serviço e mensalidade entram
  como **Não se aplica**.
- NF paga, devolvida, cancelada etc. mostra **Encerrada** e fica em cinza.
- NF em aberto com o status de entrega em branco mostra a próxima ação
  "Preencher status entrega", em vermelho.
- As opções da lista ficam na aba **Listas**. Para criar uma nova, acrescente
  lá com a próxima ação correspondente.

## Cliente final e aba "Locais de entrega"

Nas vendas triangulares, a NF sai para a Vibra mas o material vai para outro
cliente. No CIGAM, isso fica na aba Transporte da NF, no campo **Local de
Entrega**: um número que aponta para a lista de endereços de entrega da filial
da Vibra. A coluna N mostra esse número.

A aba **Locais de entrega** traduz o número para o cliente, por filial: o local
4 da Vibra Santo André é diferente do local 4 da Vibra BA.

- Para corrigir ou cadastrar um cliente final, edite **só a aba Locais de
  entrega**. Todas as NFs daquele local mudam na hora.
- Quando aparece um local novo numa NF, o script acrescenta uma linha no fim
  da aba Locais com o cliente em branco. Enquanto ninguém preenche, a NF mostra
  **"Cadastrar na aba Locais de entrega"**. Para descobrir o cliente, abra a NF
  no CIGAM, aba Transporte, campo Local de Entrega.
- NF sem local de entrega (serviço, mensalidade, venda direta) fica com o
  cliente final em branco.

## Filtros

Clique no botão verde **Filtrar NFs** no topo da aba (ou menu **Controle Vibra
> Filtros**). Abre um painel à direita, que fica aberto enquanto você navega:

| Filtro | Mostra |
|---|---|
| Pendentes de pagamento | Em aberto ou pago parcial, com entrega concluída (NF assinada recebida) ou "Não se aplica": o que já pode ser cobrado |
| Pendentes de pagamento vencidos | Os de cima com vencimento já passado |
| Pagos | Todas as NFs com status Pago |
| Pagos no período | Pagas entre duas datas (pela data de pagamento, coluna L). Tem atalhos: este mês, mês passado, últimos 30 dias, este ano |
| Aguardando a Emissão | Em aberto com entrega ainda não confirmada (a validar, aguardando, problema ou em branco) |
| Canceladas, devolvidas e abatidas | Inclui baixas por perda |
| Mostrar todas as NFs | Tira o filtro |

O painel mostra quantas NFs ficaram, o valor total e o saldo em aberto.

Cuidados:
- O filtro vale **para todo mundo** que está com a planilha aberta. Ao
  terminar, clique em **Mostrar todas as NFs**.
- Na primeira vez que alguém clica no botão, o Google pede autorização para o
  script. É só aceitar.
- O botão só funciona no navegador do computador. No celular, use o filtro
  normal da planilha (ícone de funil no cabeçalho).

## Rotina sugerida

- **Emissão**: filtro **Aguardando a Emissão**. Para cada NF, atualize o
  status de entrega (P). Quando a NF assinada chegar, marque **NF assinada
  recebida** e informe a data (Q). Detalhes vão em Obs. Emissão (R).
- **Financeiro**: filtro **Pendentes de pagamento vencidos** para cobrar a
  Vibra, e **Pagos no período** para conferir os recebimentos. Anotações em
  Obs. financeiro (S).

## Dúvidas comuns

- **Escrevi em uma coluna de A a N e sumiu.** Essas colunas são reescritas a
  cada atualização. Use as colunas de observação (R ou S).
- **A NF foi paga ontem e continua em aberto.** O DW atualiza com até 1 dia de
  atraso. Se continuar no dia seguinte, confira a baixa no CIGAM.
- **Uma NF não aparece.** Ela entra na próxima atualização (7h) ou ao clicar em
  **Atualizar agora**, desde que já esteja no DW.
- **O "Atualizar agora" deu erro de permissão.** Só quem tem acesso ao DW
  consegue atualizar. Os demais usam a planilha normalmente: a atualização das
  7h roda com o login de quem a agendou.
