/**
 * CTA SMART - Imagem do CIGAM para o acompanhamento de acordos.
 *
 * Regrava a aba CIGAM_IMAGEM com os lancamentos do CIGAM (BigQuery,
 * silver.lancamentos_receber) de cada titulo que esta em ACORDOS_REGISTRO:
 *
 *   TITULO      -> o proprio titulo (valor, saldo, vencimento, portador)
 *   PAGAMENTO   -> entrada E/L ligada ao titulo (baixa de principal)
 *   JUROS       -> entrada E/J
 *   UNIFICACAO  -> entrada E/U (o saldo foi para outro titulo)
 *   PERDA (X90) -> entrada com portador X90/X91/X92 (baixa por perda, nao e dinheiro)
 *
 * A aba e so uma copia do ERP: nada nela e digitado e tudo pode ser refeito
 * rodando atualizarCigamAcordos(). As formulas de ACORDOS_REGISTRO e
 * ACORDOS_ACOMPANHAMENTO leem daqui.
 *
 * Instalacao (uma vez):
 *   1. Na planilha: Extensoes > Apps Script. Colar este arquivo.
 *   2. Em "Servicos" (+), adicionar "BigQuery API" (identificador BigQuery).
 *   3. Rodar atualizarCigamAcordos() uma vez e autorizar. A conta precisa
 *      ter leitura no dataset silver do projeto abaixo.
 *   4. Rodar instalarGatilhoDiario() para atualizar todo dia de manha.
 */

const PROJETO_BQ = 'hip-bonito-453017-m2';
const ABA_REGISTRO = 'ACORDOS_REGISTRO';
const ABA_IMAGEM = 'CIGAM_IMAGEM';
const CABECALHO = ['EMPRESA', 'FATURA', 'CHAVE', 'LANÇAMENTO', 'DATA', 'VENCIMENTO',
                   'VALOR', 'SALDO', 'PORTADOR'];

function atualizarCigamAcordos() {
  const ss = SpreadsheetApp.getActive();
  const reg = ss.getSheetByName(ABA_REGISTRO);
  const ult = reg.getLastRow();
  if (ult < 2) return;

  // Pares (empresa, fatura). D = "000123 - NOME", G = "12345/2".
  const linhas = reg.getRange(2, 1, ult - 1, 7).getDisplayValues();
  const pares = {};
  linhas.forEach(function (l) {
    const emp = String(l[3]).substring(0, 6);
    const fat = String(l[6]).split('/')[0].trim();
    if (/^\d{6}$/.test(emp) && /^\d+$/.test(fat)) pares[emp + '|' + fat] = [emp, fat];
  });
  const lista = Object.keys(pares).map(function (k) {
    return "('" + pares[k][0] + "','" + pares[k][1] + "')";
  });
  if (!lista.length) return;

  const tabela = '`' + PROJETO_BQ + '.silver.lancamentos_receber`';
  const sql =
    'WITH alvo AS (SELECT * FROM UNNEST([STRUCT<emp STRING, fat STRING>' + lista.join(',') + '])),\n' +
    'tit AS (SELECT l.* FROM ' + tabela + ' l JOIN alvo a ON l.codigoEmpresa = a.emp AND l.fatura = a.fat\n' +
    "        WHERE l.codigoTipo IN ('R','c')),\n" +
    "ent AS (SELECT e.*, t.codigoEmpresa emp_t, CONCAT(t.fatura,'/',TRIM(IFNULL(t.complemento,''))) chave_t\n" +
    '        FROM ' + tabela + " e JOIN tit t ON e.codigoPartida = t.codigoLancamento AND e.codigoTipo = 'E')\n" +
    "SELECT codigoEmpresa, CONCAT(fatura,'/',TRIM(IFNULL(complemento,''))), 'TÍTULO',\n" +
    "  SAFE.PARSE_DATE('%d/%m/%Y', data), SAFE.PARSE_DATE('%d/%m/%Y', dataVencimento),\n" +
    "  SAFE_CAST(valor AS NUMERIC), SAFE_CAST(saldo AS NUMERIC), IFNULL(codigoPortador,'')\n" +
    'FROM tit\n' +
    'UNION ALL\n' +
    'SELECT emp_t, chave_t,\n' +
    "  CASE WHEN IFNULL(codigoPortador,'') IN ('X90','X91','X92') THEN 'PERDA (X90)'\n" +
    "       WHEN situacao = 'L' THEN 'PAGAMENTO' WHEN situacao = 'J' THEN 'JUROS'\n" +
    "       WHEN situacao = 'U' THEN 'UNIFICAÇÃO' ELSE CONCAT('OUTRO (', IFNULL(situacao,''), ')') END,\n" +
    "  SAFE.PARSE_DATE('%d/%m/%Y', data), NULL, SAFE_CAST(valor AS NUMERIC), NULL, IFNULL(codigoPortador,'')\n" +
    'FROM ent\n' +
    'ORDER BY 1, 2, 3 DESC, 4';

  const num = function (v) { return v === null || v === undefined || v === '' ? '' : Number(v); };
  const dt = function (v) {
    if (!v) return '';
    const p = String(v).split('-');  // AAAA-MM-DD
    return new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
  };
  const dados = consultar_(sql).map(function (r) {
    const f = r.f.map(function (c) { return c.v; });
    return [f[0], f[1], f[0] + '|' + f[1], f[2], dt(f[3]), dt(f[4]), num(f[5]), num(f[6]), f[7] || ''];
  });

  let aba = ss.getSheetByName(ABA_IMAGEM);
  if (!aba) aba = ss.insertSheet(ABA_IMAGEM);
  aba.getRange(2, 1, Math.max(aba.getMaxRows() - 1, 1), CABECALHO.length).clearContent();
  aba.getRange(1, 1, 1, CABECALHO.length).setValues([CABECALHO]);
  if (dados.length) {
    if (aba.getMaxRows() < dados.length + 1) aba.insertRowsAfter(aba.getMaxRows(), dados.length + 1 - aba.getMaxRows());
    aba.getRange(2, 1, dados.length, 3).setNumberFormat('@');   // empresa, fatura e chave como texto
    aba.getRange(2, 1, dados.length, CABECALHO.length).setValues(dados);
  }
  aba.getRange('K1').setValue('IMAGEM DE');
  aba.getRange('L1').setValue(new Date()).setNumberFormat('dd/mm/yyyy hh:mm');
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

function instalarGatilhoDiario() {
  ScriptApp.getProjectTriggers()
    .filter(function (t) { return t.getHandlerFunction() === 'atualizarCigamAcordos'; })
    .forEach(function (t) { ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('atualizarCigamAcordos').timeBased().everyDays(1).atHour(7).create();
}
