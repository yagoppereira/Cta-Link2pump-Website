# Controle Vibra: Apps Script da planilha

`ControleVibra.gs` atualiza a aba "Controle NFs Vibra" da planilha
PENDENCIAS VIBRA direto do DW, com o login de quem executa. `FiltrosVibra.gs`
são os filtros (filtro rápido na linha 1 e painel lateral). Guia de uso para o time:
[GUIA-DO-TIME.md](GUIA-DO-TIME.md). Não precisa de
service account: basta a pessoa conseguir rodar consultas no projeto
`hip-bonito-453017-m2` e ler as tabelas `bronze.cigam__empresas`,
`bronze.cigam__notas_fiscais`, `silver.lancamentos_receber` e
`silver.cadastro_materiais_cigam`.

## Instalar (uma vez)

1. Na planilha: **Extensões > Apps Script**.
2. Apague o conteúdo de `Código.gs` e cole o de `ControleVibra.gs`.
   Depois, em **Arquivos** (+) > **Script**, crie um arquivo chamado
   `FiltrosVibra` e cole o conteúdo de `FiltrosVibra.gs`.
3. Em **Configurações do projeto** (engrenagem), marque "Mostrar arquivo de
   manifesto appsscript.json"; volte ao editor e substitua o conteúdo de
   `appsscript.json` pelo deste diretório. Isso liga o serviço BigQuery.
   Outra forma: em **Serviços** (+), adicionar "BigQuery API".
4. Salve, escolha a função `atualizarControleVibra` e clique em **Executar**.
   Na primeira vez o Google pede autorização (planilha e BigQuery).
5. Recarregue a planilha: aparece o menu **Controle Vibra**.
6. **Controle Vibra > Criar filtro rápido na linha 1** monta a lista de
   filtros em A1 e as datas do período em E1 / F1 (o extrator em Python
   também monta ao reformatar a aba). Se o item não aparece no menu, o
   `ControleVibra.gs` colado é anterior aos filtros: cole o atual e recarregue.

## Usar

- **Controle Vibra > Atualizar agora**: reescreve as colunas A a N a partir do
  CIGAM e preserva as colunas P a S preenchidas pelo time.
- A coluna O (**Cliente final**) é fórmula: procura a filial Vibra + o nº do
  "Local de Entrega" da aba Transporte da NF no CIGAM na aba **Locais de
  entrega**. Para corrigir ou cadastrar um cliente final, edite só lá: todas
  as NFs daquele local mudam na hora, sem precisar atualizar. Local que
  aparece numa NF e ainda não está na aba é acrescentado no fim dela com o
  cliente final em branco, e a NF mostra "Cadastrar na aba Locais de entrega".
- **Controle Vibra > Agendar atualização diária**: roda todo dia às 7h com o
  login de quem agendou. Se essa pessoa perder o acesso ao DW, o agendamento
  para de funcionar; outra pessoa com acesso agenda de novo.
- **Controle Vibra > Remover agendamento**.
- **Filtro rápido (célula A1)**: escolher uma opção na lista filtra a aba na
  hora, pelo gatilho `onEdit` (funciona também no app do celular). Para
  "Pagos no período", as datas ficam em E1 e F1; sem datas, usa o mês atual.
  O filtro é o filtro comum da aba, igual pra todo mundo que está com a
  planilha aberta; **Todas as NFs** tira o filtro.
- **Controle Vibra > Filtros**: painel lateral com os mesmos filtros, atalhos
  de período e o resumo (NFs, valor e saldo).
- O botão de imagem da versão anterior foi abandonado: imagem sobre a linha
  congelada não aparecia. **Criar filtro rápido na linha 1** apaga esse botão.

O script só grava valores: a formatação, as listas suspensas e as fórmulas das
colunas O, T e U (linha 2) já estão na planilha. Para refazer a formatação do
zero, rode o extrator em Python (`controle_vibra.py`), que reaplica o layout.

## Manutenção

O script é o espelho de `controle_vibra.py`: mesmo SQL e mesmas regras.
`tests/test_apps_script.py` roda as regras do `.gs` no Node e falha se o SQL
ou alguma célula gravada divergir da versão Python; também confere as
fórmulas e as contagens dos filtros do `FiltrosVibra.gs`. Ao mudar uma regra, mude
as duas e cole o `.gs` novo no editor do Apps Script.
