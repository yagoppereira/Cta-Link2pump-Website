/**
 * Painel de filtros da aba "Controle NFs Vibra" (mesmo projeto do
 * ControleVibra.gs: as constantes ABA_CONTROLE, STATUS_* etc. vêm de lá).
 *
 * - Menu Controle Vibra > Filtros abre o painel lateral, que fica aberto
 *   enquanto se navega pela planilha.
 * - Menu Controle Vibra > Criar botão de filtros põe na linha 1 da aba um
 *   botão "Filtrar NFs" que abre o mesmo painel.
 *
 * Cada filtro é uma lista de condições (coluna + regra) que vira duas
 * coisas: a fórmula do filtro da planilha e a mesma regra em JavaScript, que
 * conta as NFs e soma os valores pro resumo do painel. A fórmula só usa
 * comparações, + e * (nenhuma função com mais de um argumento), então não
 * depende do separador ";" ou "," da localidade da planilha.
 *
 * O filtro é o filtro comum da aba: vale pra todo mundo que está com a
 * planilha aberta.
 */

// status de entrega (coluna Status entrega) que liberam a cobrança
const ENTREGA_CONCLUIDA = ['NF assinada recebida', 'Não se aplica'];

const FILTROS_VIBRA = {
  pendentes_pagamento: {
    titulo: 'Pendentes de pagamento (entregue ou não se aplica)',
    condicoes: () => [
      { coluna: 'Status financeiro', em: [STATUS_EM_ABERTO, STATUS_PAGO_PARCIAL] },
      { coluna: 'Status entrega', em: ENTREGA_CONCLUIDA },
    ],
  },
  pendentes_vencidos: {
    titulo: 'Pendentes de pagamento e vencidos',
    condicoes: () => [
      { coluna: 'Status financeiro', em: [STATUS_EM_ABERTO, STATUS_PAGO_PARCIAL] },
      { coluna: 'Status entrega', em: ENTREGA_CONCLUIDA },
      { coluna: 'Dias em atraso', acimaDe: 0 },
    ],
  },
  aguardando_emissao: {
    titulo: 'Em aberto aguardando a Emissão (entrega não confirmada)',
    condicoes: () => [
      { coluna: 'Status financeiro', em: STATUS_ABERTOS },
      { coluna: 'Status entrega', foraDe: ENTREGA_CONCLUIDA },
    ],
  },
  pagos: {
    titulo: 'Pagos',
    condicoes: () => [{ coluna: 'Status financeiro', em: [STATUS_PAGO] }],
  },
  pagos_periodo: {
    titulo: 'Pagos no período',
    periodo: true,
    condicoes: (de, ate) => [
      { coluna: 'Status financeiro', em: [STATUS_PAGO] },
      { coluna: 'Data pagamento / baixa', de: de, ate: ate },
    ],
  },
  encerradas_sem_pagamento: {
    titulo: 'Canceladas, devolvidas, abatidas e perdas',
    condicoes: () => [
      { coluna: 'Status financeiro', em: [STATUS_CANCELADA, STATUS_DEVOLVIDA, STATUS_ABATIDA, STATUS_PERDA] },
    ],
  },
};


// ============================================================================
// Painel e botão
// ============================================================================
function abrirFiltros() {
  const html = HtmlService.createHtmlOutput(HTML_PAINEL_FILTROS).setTitle('Filtros NFs Vibra');
  SpreadsheetApp.getUi().showSidebar(html);
}

/** Põe o botão "Filtrar NFs" no canto da linha 1 (que fica congelada, então
 * o botão não some ao rolar a lista). Rodar de novo troca o botão antigo. */
function criarBotaoFiltros() {
  const aba = abaControle_();
  aba.getImages().filter(i => i.getScript() === 'abrirFiltros').forEach(i => i.remove());
  aba.setRowHeight(1, 36);
  const imagem = Utilities.newBlob(Utilities.base64Decode(BOTAO_FILTROS_PNG), 'image/png', 'filtrar.png');
  aba.insertImage(imagem, 1, 1, 4, 2).setWidth(140).setHeight(32).assignScript('abrirFiltros');
  SpreadsheetApp.getActive().toast('Botão "Filtrar NFs" criado na linha 1.', 'Controle Vibra', 6);
}


// ============================================================================
// Chamadas do painel
// ============================================================================
/** Aplica o filtro escolhido no painel e devolve o resumo das NFs que ficaram
 * visíveis. `de` e `ate` vêm do painel como "aaaa-mm-dd". */
function aplicarFiltroVibra(opcao, de, ate) {
  const filtro = FILTROS_VIBRA[opcao];
  if (!filtro) throw new Error(`Filtro desconhecido: ${opcao}`);
  if (filtro.periodo && (!de || !ate)) throw new Error('Informe o início e o fim do período.');
  if (filtro.periodo && de > ate) throw new Error('O início do período é depois do fim.');
  const condicoes = filtro.condicoes(de, ate);

  const aba = abaControle_();
  const filtroAba = filtroDaAba_(aba);
  const linhaCabecalho = filtroAba.getRange().getRow();
  const { colunas, linhas } = lerTabela_(aba, linhaCabecalho);

  limparCriterios_(filtroAba);
  const formula = formulaFiltro(condicoes, colunas, linhaCabecalho + 1);
  filtroAba.setColumnFilterCriteria(1, SpreadsheetApp.newFilterCriteria().whenFormulaSatisfied(formula).build());

  const titulo = filtro.periodo ? `${filtro.titulo}: ${dataBr_(de)} a ${dataBr_(ate)}` : filtro.titulo;
  return Object.assign({ titulo: titulo }, resumirFiltro(condicoes, colunas, linhas));
}

function limparFiltroVibra() {
  const aba = abaControle_();
  const filtroAba = filtroDaAba_(aba);
  limparCriterios_(filtroAba);
  const { colunas, linhas } = lerTabela_(aba, filtroAba.getRange().getRow());
  return Object.assign({ titulo: 'Todas as NFs' }, resumirFiltro([], colunas, linhas));
}

function abaControle_() {
  const aba = SpreadsheetApp.getActive().getSheetByName(ABA_CONTROLE);
  if (!aba) throw new Error(`Aba "${ABA_CONTROLE}" não encontrada.`);
  return aba;
}

/** O filtro da aba (criado pelo extrator na linha do cabeçalho). Se alguém
 * removeu, cria de novo a partir da linha 2. */
function filtroDaAba_(aba) {
  return aba.getFilter()
    || aba.getRange(PRIMEIRA_LINHA_DADOS - 1, 1, aba.getMaxRows() - PRIMEIRA_LINHA_DADOS + 2, aba.getLastColumn())
      .createFilter();
}

function limparCriterios_(filtroAba) {
  const faixa = filtroAba.getRange();
  for (let c = faixa.getColumn(); c < faixa.getColumn() + faixa.getNumColumns(); c++) {
    if (filtroAba.getColumnFilterCriteria(c)) filtroAba.removeColumnFilterCriteria(c);
  }
}

/** {colunas: {nome do cabeçalho: índice}, linhas: linhas com NF}. As colunas
 * são achadas pelo nome, então o filtro segue certo se o layout mudar. */
function lerTabela_(aba, linhaCabecalho) {
  const valores = aba.getRange(linhaCabecalho, 1, aba.getLastRow() - linhaCabecalho + 1, aba.getLastColumn())
    .getValues();
  const colunas = {};
  valores[0].forEach((nome, i) => { colunas[texto_(nome)] = i; });
  return { colunas: colunas, linhas: valores.slice(1).filter(l => texto_(l[0])) };
}


// ============================================================================
// Regras (sem serviços do Apps Script: testadas no Node)
// ============================================================================
function letraColuna_(indice) {
  let letra = '';
  for (let n = indice + 1; n > 0; n = Math.floor((n - 1) / 26)) {
    letra = String.fromCharCode(65 + ((n - 1) % 26)) + letra;
  }
  return letra;
}

/** "aaaa-mm-dd" -> nº de série de data da planilha (dias desde 30/12/1899). */
function serialData_(iso) {
  const [a, m, d] = iso.split('-').map(Number);
  return Date.UTC(a, m - 1, d) / 86400000 + 25569;
}

function serialCelula_(valor) {
  if (valor && typeof valor.getFullYear === 'function') {
    return Date.UTC(valor.getFullYear(), valor.getMonth(), valor.getDate()) / 86400000 + 25569;
  }
  return null;
}

function dataBr_(iso) {
  const [a, m, d] = iso.split('-');
  return `${d}/${m}/${a}`;
}

function indiceColuna_(colunas, nome) {
  if (!(nome in colunas)) throw new Error(`Coluna "${nome}" não encontrada no cabeçalho da aba ${ABA_CONTROLE}.`);
  return colunas[nome];
}

/** Fórmula personalizada do filtro, relativa à primeira linha de dados. Ex.:
 * =((($K3="Em aberto")+($K3="Pago parcial")+0>0)*(($P3="Não se aplica")+0>0)*1)>0
 * O "+0" e o "*1" não são enfeite: na planilha VERDADEIRO/FALSO é maior que
 * qualquer número (FALSO>0 dá VERDADEIRO) e nunca igual a um número (FALSO=0
 * dá FALSO). Um lógico sozinho comparado com 0 deixava passar todas as
 * linhas (o "Pagos" mostrava as devolvidas). Somar 0 / multiplicar por 1
 * converte o lógico em 1/0 antes de comparar. */
function formulaFiltro(condicoes, colunas, primeiraLinha) {
  const partes = condicoes.map(c => {
    const ref = `$${letraColuna_(indiceColuna_(colunas, c.coluna))}${primeiraLinha}`;
    const iguais = valores => valores.map(v => `(${ref}="${v}")`).join('+');
    if (c.em) return `(${iguais(c.em)}+0>0)`;
    if (c.foraDe) return `(${iguais(c.foraDe)}+0=0)`;
    if (c.acimaDe !== undefined) return `(${ref}>${c.acimaDe})`;
    if (c.de) return `((${ref}>=${serialData_(c.de)})*(${ref}<=${serialData_(c.ate)})>0)`;
    throw new Error('Condição de filtro inválida');
  });
  return partes.length ? `=(${partes.join('*')}*1)>0` : '=TRUE';
}

/** A mesma regra da fórmula, em JavaScript: a planilha compara texto sem
 * diferenciar maiúsculas, e célula vazia vale 0 em comparação com número. */
function atendeCondicoes(linha, condicoes, colunas) {
  const minusculo = v => String(v === null || v === undefined ? '' : v).trim().toLowerCase();
  return condicoes.every(c => {
    const valor = linha[indiceColuna_(colunas, c.coluna)];
    if (c.em) return c.em.some(v => minusculo(v) === minusculo(valor));
    if (c.foraDe) return !c.foraDe.some(v => minusculo(v) === minusculo(valor));
    if (c.acimaDe !== undefined) return typeof valor === 'number' && valor > c.acimaDe;
    if (c.de) {
      const serial = serialCelula_(valor);
      return serial !== null && serial >= serialData_(c.de) && serial <= serialData_(c.ate);
    }
    return false;
  });
}

function resumirFiltro(condicoes, colunas, linhas) {
  const valor = indiceColuna_(colunas, 'Valor (R$)');
  const saldo = indiceColuna_(colunas, 'Saldo em aberto (R$)');
  const numero = v => (typeof v === 'number' ? v : 0);
  const visiveis = linhas.filter(l => atendeCondicoes(l, condicoes, colunas));
  return {
    nfs: visiveis.length,
    valor: Math.round(visiveis.reduce((s, l) => s + numero(l[valor]), 0) * 100) / 100,
    saldo: Math.round(visiveis.reduce((s, l) => s + numero(l[saldo]), 0) * 100) / 100,
  };
}


// ============================================================================
// HTML do painel e imagem do botão
// ============================================================================
const HTML_PAINEL_FILTROS = `<!DOCTYPE html>
<html>
<head>
<base target="_top">
<style>
  body { font-family: Arial, sans-serif; font-size: 13px; color: #202124; margin: 12px; }
  h3 { font-size: 12px; text-transform: uppercase; color: #356854; margin: 16px 0 6px; }
  button.filtro { display: block; width: 100%; text-align: left; margin: 4px 0; padding: 8px 10px;
    border: 1px solid #dadce0; border-radius: 6px; background: #fff; cursor: pointer; font-size: 13px; }
  button.filtro:hover { background: #e6f0ec; border-color: #356854; }
  button.filtro small { display: block; color: #5f6368; font-size: 11px; margin-top: 2px; }
  .periodo { border: 1px solid #dadce0; border-radius: 6px; padding: 8px 10px; margin: 4px 0; }
  .periodo label { display: inline-block; width: 30px; }
  .periodo input { margin: 3px 0; font-size: 13px; }
  .atalhos a { color: #356854; font-size: 11px; margin-right: 8px; cursor: pointer; text-decoration: underline; }
  button.aplicar { margin-top: 6px; padding: 6px 12px; background: #356854; color: #fff; border: 0;
    border-radius: 6px; cursor: pointer; }
  button.limpar { margin-top: 14px; padding: 6px 12px; background: #fff; color: #356854;
    border: 1px solid #356854; border-radius: 6px; cursor: pointer; width: 100%; }
  #resultado { margin-top: 14px; padding: 10px; background: #f1f3f4; border-radius: 6px; min-height: 18px; }
  #resultado b { display: block; margin-bottom: 4px; }
  .erro { color: #c5221f; }
</style>
</head>
<body>
  <h3>Financeiro</h3>
  <button class="filtro" onclick="aplicar('pendentes_pagamento')">Pendentes de pagamento
    <small>Em aberto ou pago parcial, com entrega confirmada (NF assinada recebida) ou não se aplica</small></button>
  <button class="filtro" onclick="aplicar('pendentes_vencidos')">Pendentes de pagamento vencidos
    <small>Os de cima com vencimento já passado</small></button>
  <button class="filtro" onclick="aplicar('pagos')">Pagos
    <small>Todos com status financeiro Pago</small></button>

  <div class="periodo">
    <b>Pagos no período</b> <small>(data de pagamento / baixa)</small><br>
    <label>De</label><input type="date" id="de"><br>
    <label>Até</label><input type="date" id="ate"><br>
    <div class="atalhos">
      <a onclick="periodo('mes')">Este mês</a><a onclick="periodo('mes_passado')">Mês passado</a>
      <a onclick="periodo('30')">Últimos 30 dias</a><a onclick="periodo('ano')">Este ano</a>
    </div>
    <button class="aplicar" onclick="aplicarPeriodo()">Filtrar</button>
  </div>

  <h3>Emissão</h3>
  <button class="filtro" onclick="aplicar('aguardando_emissao')">Aguardando a Emissão
    <small>Em aberto e entrega ainda não confirmada (a validar, aguardando, problema ou em branco)</small></button>

  <h3>Outros</h3>
  <button class="filtro" onclick="aplicar('encerradas_sem_pagamento')">Canceladas, devolvidas e abatidas
    <small>Inclui baixas por perda</small></button>

  <button class="limpar" onclick="limpar()">Mostrar todas as NFs</button>
  <div id="resultado">Escolha um filtro.</div>

<script>
  const moeda = v => v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
  const iso = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-'
    + String(d.getDate()).padStart(2, '0');
  function mostrar(r) {
    document.getElementById('resultado').innerHTML = '<b>' + r.titulo + '</b>' + r.nfs + ' NF(s) · valor '
      + moeda(r.valor) + (r.saldo ? ' · saldo em aberto ' + moeda(r.saldo) : '');
  }
  function erro(e) {
    document.getElementById('resultado').innerHTML = '<span class="erro">' + (e.message || e) + '</span>';
  }
  function aguarde() { document.getElementById('resultado').textContent = 'Filtrando...'; }
  function aplicar(opcao, de, ate) {
    aguarde();
    google.script.run.withSuccessHandler(mostrar).withFailureHandler(erro).aplicarFiltroVibra(opcao, de || '', ate || '');
  }
  function aplicarPeriodo() {
    aplicar('pagos_periodo', document.getElementById('de').value, document.getElementById('ate').value);
  }
  function limpar() {
    aguarde();
    google.script.run.withSuccessHandler(mostrar).withFailureHandler(erro).limparFiltroVibra();
  }
  function periodo(tipo) {
    const hoje = new Date();
    let de, ate = hoje;
    if (tipo === 'mes') de = new Date(hoje.getFullYear(), hoje.getMonth(), 1);
    if (tipo === 'mes_passado') {
      de = new Date(hoje.getFullYear(), hoje.getMonth() - 1, 1);
      ate = new Date(hoje.getFullYear(), hoje.getMonth(), 0);
    }
    if (tipo === '30') de = new Date(hoje.getFullYear(), hoje.getMonth(), hoje.getDate() - 30);
    if (tipo === 'ano') de = new Date(hoje.getFullYear(), 0, 1);
    document.getElementById('de').value = iso(de);
    document.getElementById('ate').value = iso(ate);
    aplicarPeriodo();
  }
</script>
</body>
</html>`;

// botão "Filtrar NFs" (PNG 280x64, exibido em 140x32): amarelo com borda branca pra
// destacar da faixa verde da linha 1, onde fica
const BOTAO_FILTROS_PNG = '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';
