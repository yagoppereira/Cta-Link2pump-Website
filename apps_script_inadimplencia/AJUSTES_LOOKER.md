# Ajustes no Dashboard Executivo de Inadimplência (Looker Studio)

Pré-requisito: rodar a distribuição com a versão nova de `DistribuirInadimplencia.gs`
(coluna **Segmento**, datas como data e as abas de histórico já existirem).

## 1. Atualizar os campos da fonte de dados
Recurso → Gerenciar fontes de dados → *Dados_Looker* → Editar → **Atualizar campos**.
- Confirme o novo campo **Segmento** (Texto).
- Confirme **Emissao** e **Vencimento** como **Data** (antes eram texto).
- **Reserva Estimada (R$)** → tipo **Moeda → Real brasileiro (R$)** (hoje aparece "$").
- **Saldo** → tipo **Moeda → Real brasileiro (R$)**, se ainda não estiver.

## 2. Corrigir a coluna "Índice de Risco" nas tabelas por vendedor e por cliente
A coluna não bate com Reserva ÷ Saldo linha a linha (ex.: ARTHUR ALEM 14.339 ÷ 123,3 mil
= 11,6%, tabela mostra 44,71%). Em cada tabela, clique no campo da coluna e confira:
- o campo é **Índice de Risco (%)** (não um campo antigo/duplicado);
- **Cálculo de comparação** = Nenhum e **Cálculo cumulativo** = Nenhum.
Se continuar divergente, recrie a coluna arrastando o campo de novo.

## 3. Campos calculados novos
**Saldo por Cliente**
```
SUM(Saldo) / COUNT_DISTINCT(CNPJ)
```
**Índice de Risco – Cliente Final** (exclui distribuidoras)
```
SUM(CASE WHEN Segmento = "Cliente Final" THEN Reserva Estimada (R$) ELSE 0 END)
/ SUM(CASE WHEN Segmento = "Cliente Final" THEN Saldo ELSE 0 END)
```

## 4. Página 2 (executiva)
- **Ticket Médio**: renomear para **Saldo médio por título**, e adicionar o cartão **Saldo por Cliente**.
- Adicionar o cartão **Índice de Risco – Cliente Final** ao lado do Índice geral.
- Adicionar controle de filtro **Segmento** ao lado do filtro de Vendedor.
- **"Acúmulo de Mensalidades Pendentes"**: mantido, mas redesenhado (ver seção 4.1).

### 4.1 Acúmulo de mensalidades — novo desenho
O gráfico atual cruza R$ (eixo esquerdo) com quantidade de meses (eixo direito) em 5 clientes
com nomes cortados. A distribuição agora grava duas colunas novas em Dados_Looker:
- **Meses em Aberto**: meses de emissão distintos com mensalidade em aberto **do cliente**
  (só produtos recorrentes: Licenciamentos e Aluguel — ajustável em `CONFIG_DISTRIB.produtosRecorrentes`).
  O valor é do cliente e se repete em todas as linhas dele → no Looker use **MAX**, nunca SUM.
- **Faixa de Acúmulo**: 1 mês · 2 a 3 · 4 a 6 · 7 a 12 · Acima de 12 meses · Sem mensalidade em aberto.

Campo de ordenação **Ordem Acúmulo**:
```
CASE Faixa de Acúmulo
  WHEN "1 mês" THEN 1
  WHEN "2 a 3 meses" THEN 2
  WHEN "4 a 6 meses" THEN 3
  WHEN "7 a 12 meses" THEN 4
  WHEN "Acima de 12 meses" THEN 5
  ELSE 6
END
```
Campo **Mensalidade Média (R$)** (por cliente, para a tabela):
```
SUM(CASE WHEN Produto (Resumido) IN ("Licenciamentos", "Aluguel") THEN Saldo ELSE 0 END) / MAX(Meses em Aberto)
```

Substituir o gráfico atual por dois componentes (uma métrica por eixo):
1. **Barras — Clientes por faixa de acúmulo**: dimensão *Faixa de Acúmulo* (ordenar por *Ordem Acúmulo*),
   métrica `COUNT_DISTINCT(CNPJ)`; na dica de ferramenta, *Saldo*. Lê-se: "X clientes com mais de 12 meses acumulados".
2. **Tabela — Maiores acúmulos**: Cliente · Vendedor · **MAX(Meses em Aberto)** · Saldo · Mensalidade Média ·
   Reserva Estimada; ordenada por meses (desc), barras no Saldo, 10 linhas.

O campo antigo `FORMAT_DATETIME("%Y-%m", Emissao)` continua funcionando (Emissao agora é data de verdade)
e pode ficar para quem quiser contar meses de **todos** os produtos; a coluna nova conta só os recorrentes.

## 5. Página 1 (mapa)
- Cor do mapa: métrica **Índice de Risco (%)** (onde está o risco); deixe **Saldo** e
  **Reserva Estimada** na dica de ferramenta (tooltip).
- Adicionar filtro **Segmento**.

## 6. Página nova: Tendência
Adicionar a fonte **Historico_Distribuicao** (mesma planilha). Uma métrica por gráfico — sem eixo duplo:
- Série temporal **Saldo Total** por **Data**.
- Série temporal **Índice de Risco** — crie o campo `SUM(Reserva Estimada) / SUM(Saldo Total)`
  em vez de somar a coluna de índice.
- Barras empilhadas 100% por **Data**: *Saldo 1-30, 31-60, 61-90, >90* (evolução do envelhecimento).
- Opcional: fonte **Historico_Clientes** para a evolução de um cliente (filtro por Cliente).

## 7. Antes de publicar no LinkedIn
Anonimizar nomes de clientes, vendedores e CNPJs nas capturas (ou usar uma cópia do relatório
com campos mascarados), e arredondar valores se necessário.
