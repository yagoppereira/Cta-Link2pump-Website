/**
 * CTA SMART - Atualiza as abas CIGAM_TITULOS e CIGAM_BAIXAS da planilha
 * de inadimplencia.
 *
 * Para cada titulo que esta em ACORDOS_TITULOS, busca no BigQuery
 * (silver.lancamentos_receber, espelho dos lancamentos do CIGAM):
 *   - situacao, valor, saldo, vencimento atual e vencimento original do titulo
 *   - o que entrou contra ele (entradas E ligadas pelo codigoPartida):
 *       L = liquidacao (pagamento), J = juros, U = unificacao,
 *       portador X90/X91/X92 = baixa por perda (nao e pagamento)
 *
 * CIGAM_TITULOS: uma linha por titulo (saldo e totais por tipo de entrada).
 * CIGAM_BAIXAS:  uma linha por entrada L (liquidacao) ou J (juros), com data,
 *                sem perdas (X90/X91/X92) e sem unificacoes. A coluna H
 *                (ID ACORDO) e formula da planilha e nao e tocada aqui.
 *
 * As formulas do ciclo (ACORDOS_RESUMO / ACORDOS_TITULOS) comparam o que
 * foi lancado em ACORDOS_RECEBIMENTOS com o que foi baixado no CIGAM e
 * com o saldo dos titulos.
 *
 * Instalacao (uma vez):
 *   1. Na planilha: Extensoes > Apps Script. Colar este arquivo.
 *   2. Em "Servicos" (+), adicionar "BigQuery API" (identificador BigQuery).
 *   3. Rodar atualizarCigamAcordos() uma vez e autorizar. A conta precisa
 *      ter leitura no dataset silver do projeto abaixo.
 *   4. Rodar instalarGatilhoDiario() para atualizar todo dia de manha.
 */

const PROJETO_BQ = 'hip-bonito-453017-m2';
const ABA_TITULOS = 'ACORDOS_TITULOS';
const ABA_CIGAM = 'CIGAM_TITULOS';
const ABA_BAIXAS = 'CIGAM_BAIXAS';
const CABECALHO_BAIXAS = ['EMPRESA', 'FATURA', 'CHAVE', 'DATA', 'TIPO (L = LIQUIDAÇÃO, J = JUROS)', 'VALOR', 'CONTA'];
const CABECALHO = [
  'EMPRESA', 'FATURA', 'CHAVE', 'TIPO', 'SITUAÇÃO', 'VALOR', 'SALDO',
  'VENC. ATUAL', 'VENC. ORIGINAL', 'PORTADOR', 'LIQUIDADO (E/L)',
  'JUROS RECEBIDOS (E/J)', 'BAIXA POR PERDA (X90)', 'UNIFICADO (E/U)', 'ÚLTIMA ENTRADA'
];

function atualizarCigamAcordos() {
  const ss = SpreadsheetApp.getActive();
  const tit = ss.getSheetByName(ABA_TITULOS);
  const ult = tit.getLastRow();
  if (ult < 2) return;

  // Pares (empresa, fatura) dos titulos em acordo. C = "000123 - NOME", D = "12345/2".
  const linhas = tit.getRange(2, 3, ult - 1, 2).getDisplayValues();
  const pares = {};
  linhas.forEach(function (l) {
    const emp = String(l[0]).substring(0, 6);
    const fat = String(l[1]).split('/')[0].trim();
    if (/^\d{6}$/.test(emp) && /^\d+$/.test(fat)) pares[emp + '|' + fat] = [emp, fat];
  });
  const lista = Object.keys(pares).map(function (k) {
    return "('" + pares[k][0] + "','" + pares[k][1] + "')";
  });
  if (!lista.length) return;

  const sql =
    'WITH alvo AS (SELECT * FROM UNNEST([STRUCT<emp STRING, fat STRING>' + lista.join(',') + '])),\n' +
    'lr AS (SELECT l.* FROM `' + PROJETO_BQ + '.silver.lancamentos_receber` l\n' +
    '       JOIN alvo a ON l.codigoEmpresa = a.emp AND l.fatura = a.fat),\n' +
    'ent AS (SELECT codigoPartida,\n' +
    "  SUM(IF(situacao='L' AND IFNULL(codigoPortador,'') NOT IN ('X90','X91','X92'), SAFE_CAST(valor AS NUMERIC), 0)) liq,\n" +
    "  SUM(IF(situacao='J', SAFE_CAST(valor AS NUMERIC), 0)) jur,\n" +
    "  SUM(IF(IFNULL(codigoPortador,'') IN ('X90','X91','X92'), SAFE_CAST(valor AS NUMERIC), 0)) perda,\n" +
    "  SUM(IF(situacao='U', SAFE_CAST(valor AS NUMERIC), 0)) unif,\n" +
    "  MAX(SAFE.PARSE_DATE('%d/%m/%Y', data)) ult\n" +
    "  FROM lr WHERE codigoTipo='E' GROUP BY 1)\n" +
    "SELECT t.codigoEmpresa, CONCAT(t.fatura,'/',TRIM(IFNULL(t.complemento,''))), t.codigoTipo, t.situacao,\n" +
    '  SAFE_CAST(t.valor AS NUMERIC), SAFE_CAST(t.saldo AS NUMERIC),\n' +
    "  SAFE.PARSE_DATE('%d/%m/%Y', t.dataVencimento), SAFE.PARSE_DATE('%d/%m/%Y', t.vencimentoOriginal),\n" +
    '  t.codigoPortador, IFNULL(e.liq,0), IFNULL(e.jur,0), IFNULL(e.perda,0), IFNULL(e.unif,0), e.ult\n' +
    "FROM lr t LEFT JOIN ent e ON e.codigoPartida = t.codigoLancamento\n" +
    "WHERE t.codigoTipo IN ('R','c')\n" +
    'ORDER BY 1, 2';

  const rows = consultar_(sql);

  const num = function (v) { return v === null || v === undefined || v === '' ? '' : Number(v); };
  const dt = function (v) {
    if (!v) return '';
    const p = String(v).split('-');  // AAAA-MM-DD
    return new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
  };
  const dados = rows.map(function (r) {
    const f = r.f.map(function (c) { return c.v; });
    return [f[0], f[1], f[0] + '|' + f[1], f[2], f[3], num(f[4]), num(f[5]), dt(f[6]), dt(f[7]),
            f[8] || '', num(f[9]), num(f[10]), num(f[11]), num(f[12]), dt(f[13])];
  });

  gravar_(ss, ABA_CIGAM, CABECALHO, dados);

  // Entradas (pagamentos e juros) com data, para o ciclo de baixa.
  const sqlBaixas =
    'WITH alvo AS (SELECT * FROM UNNEST([STRUCT<emp STRING, fat STRING>' + lista.join(',') + '])),\n' +
    "tit AS (SELECT l.codigoLancamento, l.codigoEmpresa emp, l.fatura fat, TRIM(IFNULL(l.complemento,'')) comp\n" +
    '  FROM `' + PROJETO_BQ + '.silver.lancamentos_receber` l\n' +
    "  JOIN alvo a ON l.codigoEmpresa = a.emp AND l.fatura = a.fat WHERE l.codigoTipo IN ('R','c'))\n" +
    "SELECT t.emp, CONCAT(t.fat,'/',t.comp), SAFE.PARSE_DATE('%d/%m/%Y', e.data), e.situacao,\n" +
    "  SAFE_CAST(e.valor AS NUMERIC), IFNULL(e.codigoPortador,'')\n" +
    'FROM tit t JOIN `' + PROJETO_BQ + '.silver.lancamentos_receber` e\n' +
    "  ON e.codigoPartida = t.codigoLancamento AND e.codigoTipo = 'E'\n" +
    "WHERE e.situacao IN ('L','J') AND IFNULL(e.codigoPortador,'') NOT IN ('X90','X91','X92')\n" +
    'ORDER BY 1, 2, 3';
  const baixas = consultar_(sqlBaixas).map(function (r) {
    const f = r.f.map(function (c) { return c.v; });
    return [f[0], f[1], f[0] + '|' + f[1], dt(f[2]), f[3], num(f[4]), f[5]];
  });
  gravar_(ss, ABA_BAIXAS, CABECALHO_BAIXAS, baixas);
}

/** Roda a consulta no BigQuery e devolve todas as linhas (todas as paginas). */
function consultar_(sql) {
  let resp = BigQuery.Jobs.query({ query: sql, useLegacySql: false, timeoutMs: 60000 }, PROJETO_BQ);
  const jobId = resp.jobReference.jobId;
  const local = resp.jobReference.location;
  while (!resp.jobComplete) {
    Utilities.sleep(1000);
    resp = BigQuery.Jobs.getQueryResults(PROJETO_BQ, jobId, { location: local });
  }
  let rows = resp.rows || [];
  let token = resp.pageToken;
  while (token) {
    const pag = BigQuery.Jobs.getQueryResults(PROJETO_BQ, jobId, { pageToken: token, location: local });
    rows = rows.concat(pag.rows || []);
    token = pag.pageToken;
  }
  return rows;
}

/** Substitui os dados da aba (colunas do cabecalho) e grava a data da carga em Q1/R1. */
function gravar_(ss, nome, cabecalho, dados) {
  let aba = ss.getSheetByName(nome);
  if (!aba) aba = ss.insertSheet(nome);
  aba.getRange(2, 1, Math.max(aba.getMaxRows() - 1, 1), cabecalho.length).clearContent();
  aba.getRange(1, 1, 1, cabecalho.length).setValues([cabecalho]);
  if (dados.length) {
    if (aba.getMaxRows() < dados.length + 1) aba.insertRowsAfter(aba.getMaxRows(), dados.length + 1 - aba.getMaxRows());
    aba.getRange(2, 1, dados.length, 3).setNumberFormat('@');   // empresa, fatura e chave como texto
    aba.getRange(2, 1, dados.length, cabecalho.length).setValues(dados);
  }
  aba.getRange('Q1').setValue('ATUALIZADO EM');
  aba.getRange('R1').setValue(new Date()).setNumberFormat('dd/mm/yyyy hh:mm');
}

function instalarGatilhoDiario() {
  ScriptApp.getProjectTriggers()
    .filter(function (t) { return t.getHandlerFunction() === 'atualizarCigamAcordos'; })
    .forEach(function (t) { ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('atualizarCigamAcordos').timeBased().everyDays(1).atHour(7).create();
}
