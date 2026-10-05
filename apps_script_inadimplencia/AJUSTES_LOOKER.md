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
- **"Acúmulo de Mensalidades Pendentes"**: o gráfico tem dois eixos e nomes cortados.
  Substituir por **Reserva Estimada por Faixa de Atraso** (barras, uma métrica, ordenado por *Ordem Aging*)
  — mostra que o risco está concentrado acima de 90 dias.

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
