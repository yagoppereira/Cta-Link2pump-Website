/**
 * Filtros da aba "Controle NFs Vibra" (mesmo projeto do ControleVibra.gs: as
 * constantes ABA_CONTROLE, STATUS_* etc. vêm de lá).
 *
 * - Filtro rápido na linha 1, que é congelada e fica sempre à vista: lista em
 *   A1:D1 e as datas do período em E1 / F1. Escolher uma opção filtra na hora
 *   (onEdit, funciona também no app do celular).
 * - Menu Controle Vibra > Filtros abre o painel lateral com os mesmos filtros
 *   e o resumo (quantidade de NFs, valor e saldo em aberto).
 * - Menu Controle Vibra > Criar filtro rápido na linha 1 monta a linha 1 na
 *   planilha (o extrator em Python também monta, ao reformatar a aba).
 *
 * Cada filtro é uma lista de condições (coluna + regra) que vira duas
 * coisas: a fórmula do filtro da planilha e a mesma regra em JavaScript, que
 * conta as NFs e soma os valores pro resumo. A fórmula só usa comparações,
 * + e * (nenhuma função com mais de um argumento), então não depende do
 * separador ";" ou "," da localidade da planilha.
 *
 * O filtro é o filtro comum da aba: vale pra todo mundo que está com a
 * planilha aberta.
 */

// status de entrega (coluna Status entrega) que liberam a cobrança
const ENTREGA_CONCLUIDA = ['NF assinada recebida', 'Não se aplica'];

const FILTROS_VIBRA = {
  pendentes_pagamento: {
    rotulo: 'Pendentes de pagamento',
    titulo: 'Pendentes de pagamento (entregue ou não se aplica)',
    condicoes: () => [
      { coluna: 'Status financeiro', em: [STATUS_EM_ABERTO, STATUS_PAGO_PARCIAL] },
      { coluna: 'Status entrega', em: ENTREGA_CONCLUIDA },
    ],
  },
  pendentes_vencidos: {
    rotulo: 'Pendentes vencidos',
    titulo: 'Pendentes de pagamento e vencidos',
    condicoes: () => [
      { coluna: 'Status financeiro', em: [STATUS_EM_ABERTO, STATUS_PAGO_PARCIAL] },
      { coluna: 'Status entrega', em: ENTREGA_CONCLUIDA },
      { coluna: 'Dias em atraso', acimaDe: 0 },
    ],
  },
  aguardando_emissao: {
    rotulo: 'Aguardando a Emissão',
    titulo: 'Em aberto aguardando a Emissão (entrega não confirmada)',
    condicoes: () => [
      { coluna: 'Status financeiro', em: STATUS_ABERTOS },
      { coluna: 'Status entrega', foraDe: ENTREGA_CONCLUIDA },
    ],
  },
  pagos: {
    rotulo: 'Pagos',
    titulo: 'Pagos',
    condicoes: () => [{ coluna: 'Status financeiro', em: [STATUS_PAGO] }],
  },
  pagos_periodo: {
    rotulo: 'Pagos no período',
    titulo: 'Pagos no período',
    periodo: true,
    condicoes: (de, ate) => [
      { coluna: 'Status financeiro', em: [STATUS_PAGO] },
      { coluna: 'Data pagamento / baixa', de: de, ate: ate },
    ],
  },
  encerradas_sem_pagamento: {
    rotulo: 'Canceladas / devolvidas',
    titulo: 'Canceladas, devolvidas, abatidas e perdas',
    condicoes: () => [
      { coluna: 'Status financeiro', em: [STATUS_CANCELADA, STATUS_DEVOLVIDA, STATUS_ABATIDA, STATUS_PERDA] },
    ],
  },
};

// filtro rápido da linha 1 (mesmo layout de controle_vibra.py; colunas a partir de 1)
const OPCAO_TODAS = 'Todas as NFs';
const OPCOES_FILTRO_RAPIDO = [OPCAO_TODAS].concat(Object.keys(FILTROS_VIBRA).map(k => FILTROS_VIBRA[k].rotulo));
const COLUNAS_FILTRO_RAPIDO = 4;  // A a D, mescladas
const COLUNA_PERIODO_DE = 5;      // E
const COLUNA_PERIODO_ATE = 6;     // F
const COLUNA_TITULO = 7;          // G: "Do CIGAM (...)" vai de G até o cliente final
const VERDE_PLANILHA = '#356854';


// ============================================================================
// Filtro rápido da linha 1
// ============================================================================
/** Gatilho simples: roda pra quem editar a planilha, sem autorização. Só
 * reage à lista e às datas do filtro rápido. */
function onEdit(e) {
  if (!e || !e.range) return;
  const aba = e.range.getSheet();
  if (aba.getName() !== ABA_CONTROLE || e.range.getRow() !== 1 || e.range.getColumn() > COLUNA_PERIODO_ATE) return;
  try {
    aba.getParent().toast(textoResumo(aplicarFiltroRapido_(aba)), 'Filtro', 8);
  } catch (erro) {
    aba.getParent().toast(erro.message, 'Filtro', 8);
  }
}

function aplicarFiltroRapido_(aba) {
  const opcao = opcaoDoRotulo(texto_(aba.getRange(1, 1).getValue()));
  if (!opcao) return filtrar_(aba, null);
  let de = '', ate = '';
  if (FILTROS_VIBRA[opcao].periodo) {
    const fuso = fusoDaPlanilha_();
    const celulaDe = aba.getRange(1, COLUNA_PERIODO_DE);
    const celulaAte = aba.getRange(1, COLUNA_PERIODO_ATE);
    const iso = valor => (valor && typeof valor.getFullYear === 'function'
      ? Utilities.formatDate(valor, fuso, 'yyyy-MM-dd') : '');
    de = iso(celulaDe.getValue());
    ate = iso(celulaAte.getValue());
    if (!de || !ate) {  // sem datas: mês atual até hoje
      ate = Utilities.formatDate(new Date(), fuso, 'yyyy-MM-dd');
      de = ate.slice(0, 8) + '01';
      celulaDe.setValue(dataBr_(de));
      celulaAte.setValue(dataBr_(ate));
    }
    validarPeriodo_(de, ate);
  }
  return filtrar_(aba, opcao, de, ate);
}

/** Monta a linha 1: lista do filtro em A1:D1, datas do período em E1 / F1 e
 * o título "Do CIGAM (...)" de G até o cliente final. Tira também o botão de
 * imagem da versão anterior. */
function criarFiltroRapido() {
  const aba = abaControle_();
  aba.getImages().filter(i => i.getScript() === 'abrirFiltros').forEach(i => i.remove());
  const ultima = COLUNAS_DW.length + 1;  // coluna do cliente final
  const titulo = aba.getRange(1, 1, 1, ultima).getDisplayValues()[0].find(v => v.startsWith('Do CIGAM'))
    || 'Do CIGAM (extrator)';
  aba.getRange(1, 1, 1, ultima).breakApart().clearContent().clearDataValidations().clearNote();
  aba.setRowHeight(1, 30);

  aba.getRange(1, 1, 1, COLUNAS_FILTRO_RAPIDO).merge().setValue(OPCAO_TODAS)
    .setDataValidation(SpreadsheetApp.newDataValidation().requireValueInList(OPCOES_FILTRO_RAPIDO, true)
      .setAllowInvalid(false).build())
    .setBackground('#ffffff').setFontColor(VERDE_PLANILHA).setFontWeight('bold').setHorizontalAlignment('center')
    .setNote('Filtro rápido: escolha uma opção e a lista é filtrada na hora (vale pra todo mundo com a '
      + 'planilha aberta). Para Pagos no período, informe as datas nas duas células ao lado. '
      + 'Volte para Todas as NFs ao terminar.');
  [[COLUNA_PERIODO_DE, 'de'], [COLUNA_PERIODO_ATE, 'até']].forEach(([coluna, rotulo]) => {
    aba.getRange(1, coluna)
      .setDataValidation(SpreadsheetApp.newDataValidation().requireDate().setAllowInvalid(false)
        .setHelpText('Período do filtro Pagos no período (dd/mm/aaaa)').build())
      .setNumberFormat(`"${rotulo} "dd/mm/yyyy`)
      .setBackground('#ffffff').setFontColor(VERDE_PLANILHA).setFontWeight('bold').setHorizontalAlignment('center');
  });
  aba.getRange(1, COLUNA_TITULO, 1, ultima - COLUNA_TITULO + 1).merge().setValue(titulo)
    .setBackground(VERDE_PLANILHA).setFontColor('#ffffff').setFontWeight('bold').setHorizontalAlignment('center');
  limparCriterios_(filtroDaAba_(aba));
  SpreadsheetApp.getActive().toast('Filtro rápido criado na linha 1 (célula A1).', 'Controle Vibra', 8);
}

function filtroRapidoMontado_(aba) {
  return aba.getRange(1, 1).getDataValidation() !== null;
}


// ============================================================================
// Painel lateral
// ============================================================================
function abrirFiltros() {
  const html = HtmlService.createHtmlOutput(HTML_PAINEL_FILTROS).setTitle('Filtros NFs Vibra');
  SpreadsheetApp.getUi().showSidebar(html);
}

/** Aplica o filtro escolhido no painel e devolve o resumo das NFs que ficaram
 * visíveis. `de` e `ate` vêm do painel como "aaaa-mm-dd". A lista da linha 1
 * passa a mostrar o filtro escolhido. */
function aplicarFiltroVibra(opcao, de, ate) {
  const filtro = FILTROS_VIBRA[opcao];
  if (!filtro) throw new Error(`Filtro desconhecido: ${opcao}`);
  if (filtro.periodo) validarPeriodo_(de, ate);
  const aba = abaControle_();
  if (filtroRapidoMontado_(aba)) {
    aba.getRange(1, 1).setValue(filtro.rotulo);
    if (filtro.periodo) {
      aba.getRange(1, COLUNA_PERIODO_DE).setValue(dataBr_(de));
      aba.getRange(1, COLUNA_PERIODO_ATE).setValue(dataBr_(ate));
    }
  }
  return filtrar_(aba, opcao, de, ate);
}

function limparFiltroVibra() {
  const aba = abaControle_();
  if (filtroRapidoMontado_(aba)) aba.getRange(1, 1).setValue(OPCAO_TODAS);
  return filtrar_(aba, null);
}


// ============================================================================
// Aplicação do filtro na aba
// ============================================================================
/** Troca o critério do filtro da aba pelo da opção (null = sem filtro) e
 * devolve {titulo, nfs, valor, saldo} das NFs que ficaram visíveis. */
function filtrar_(aba, opcao, de, ate) {
  const filtroAba = filtroDaAba_(aba);
  const linhaCabecalho = filtroAba.getRange().getRow();
  const { colunas, linhas } = lerTabela_(aba, linhaCabecalho);
  limparCriterios_(filtroAba);
  if (!opcao) return Object.assign({ titulo: OPCAO_TODAS }, resumirFiltro([], colunas, linhas));

  const filtro = FILTROS_VIBRA[opcao];
  const condicoes = filtro.condicoes(de, ate);
  const formula = formulaFiltro(condicoes, colunas, linhaCabecalho + 1);
  filtroAba.setColumnFilterCriteria(1, SpreadsheetApp.newFilterCriteria().whenFormulaSatisfied(formula).build());
  const titulo = filtro.periodo ? `${filtro.titulo}: ${dataBr_(de)} a ${dataBr_(ate)}` : filtro.titulo;
  return Object.assign({ titulo: titulo }, resumirFiltro(condicoes, colunas, linhas));
}

function validarPeriodo_(de, ate) {
  if (!de || !ate) throw new Error('Informe o início e o fim do período.');
  if (de > ate) throw new Error('O início do período é depois do fim.');
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

/** Opção do FILTROS_VIBRA pelo rótulo da lista da linha 1; null = todas. */
function opcaoDoRotulo(rotulo) {
  return Object.keys(FILTROS_VIBRA).find(k => FILTROS_VIBRA[k].rotulo === rotulo) || null;
}

function moedaBr_(valor) {
  const [inteiro, centavos] = Math.abs(valor).toFixed(2).split('.');
  return `${valor < 0 ? '-' : ''}R$ ${inteiro.replace(/\B(?=(\d{3})+(?!\d))/g, '.')},${centavos}`;
}

/** Texto do aviso que aparece depois do filtro rápido. */
function textoResumo(resumo) {
  return `${resumo.titulo}: ${resumo.nfs} NF(s) · valor ${moedaBr_(resumo.valor)}`
    + (resumo.saldo ? ` · saldo em aberto ${moedaBr_(resumo.saldo)}` : '');
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
// HTML do painel
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
