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

// botão "Filtrar NFs" (PNG 280x64, exibido em 140x32)
const BOTAO_FILTROS_PNG = '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';
