/**
 * CTA SMART - Acordos na planilha "14.10 INADIMPLENCIA" (aba ACORDOS).
 *
 * 1. doPost: recebe da Calculadora (macro, Module9_EnvioPlanilha) as linhas
 *    do acordo firmado, no layout A:U da aba ACORDOS, e grava no fim da aba.
 *    Se ja existir acordo com o mesmo CNPJ + TERMO, as linhas antigas sao
 *    substituidas (reenvio nao duplica).
 *
 * 2. atualizarStatusAcordos (gatilho diario): recalcula a coluna A
 *    (STATUS ACORDO) das linhas de acordo feitas pela macro (coluna S =
 *    "ENTRADA" ou "PARCELA n/m") a partir das baixas do CIGAM (BigQuery,
 *    silver.lancamentos_receber):
 *      Quitado          - a parte do titulo desta linha ja foi baixada no CIGAM
 *                         (ou VALOR PAGO preenchido >= VALOR ALOCADO)
 *      Acordo Quebrado  - nao baixada e DATA DE PAGAMENTO vencida ha
 *                         DIAS_PARA_QUEBRAR dias ou mais
 *      Em Dia           - nao baixada e ainda no prazo
 *    Linhas com status manual de encerramento (Cancelado, Renegociado,
 *    Juridico, Suspenso) e linhas antigas sem o formato da macro nao sao
 *    tocadas. A aba Bloqueios continua lendo a coluna A como sempre.
 *    Quando um acordo passa a "Acordo Quebrado", um e-mail e enviado ao dono
 *    do script com a lista.
 *
 *    Como a baixa e lida: a macro grava em VALOR ORIGINAL o saldo do titulo
 *    no dia do acordo. Principal baixado depois disso =
 *      VALOR ORIGINAL - (valor do titulo no CIGAM - liquidacoes E/L).
 *    Esse valor cobre as linhas do titulo na ordem da aba (ENTRADA, PARCELA
 *    1, 2...), cada linha valendo VALOR ALOCADO x (VALOR ORIGINAL / VALOR NF
 *    TOTAL), ou seja, so o principal (o CIGAM abate principal na baixa
 *    parcial e lanca os juros na quitacao). Titulo liquidado no CIGAM =
 *    todas as linhas dele Quitado. Baixa por perda (X90) nao conta.
 *
 * Instalacao (uma vez), na planilha: Extensoes > Apps Script, colar este
 * arquivo e:
 *   a) Servicos (+) > BigQuery API.
 *   b) Rodar gerarToken() e copiar o token mostrado (vai no Module9 da
 *      Calculadora, TOKEN_PLANILHA).
 *   c) Implantar > Nova implantacao > App da Web: Executar como "Eu",
 *      Quem pode acessar "Qualquer pessoa". Copiar a URL (vai em URL_PLANILHA).
 *   d) Rodar simularStatusAcordos() e conferir a aba STATUS_SIMULACAO
 *      (nada e alterado na ACORDOS). Estando de acordo, rodar
 *      instalarGatilhoDiario() (atualiza todo dia as 7h).
 */

const ABA_ACORDOS = 'ACORDOS';
const ABA_SIMULACAO = 'STATUS_SIMULACAO';
const LIN_INI = 3;             // linha 1 = totais, linha 2 = cabecalho
const N_COLS = 21;             // A:U
const PROJETO_BQ = 'hip-bonito-453017-m2';
const DIAS_PARA_QUEBRAR = 1;   // parcela vencida ha N dias sem baixa = quebrado
const TOL = 1;                 // tolerancia em R$
const STATUS_MANUAIS = ['CANCELADO', 'RENEGOCIADO', 'JURIDICO', 'JURÍDICO', 'SUSPENSO'];
const RE_PGTO = /^(ENTRADA|PARCELA \d+\/\d+)$/i;

// Colunas (0-based) do layout A:U
const C = { STATUS: 0, RESP: 1, EMPRESA: 2, CNPJ: 3, DOC: 4, NF: 5, ATRASO: 6, VENC: 7,
            ORIG: 8, JUROS: 9, TOTAL: 10, CJUROS: 11, CTIT: 12, DTPGTO: 13, PAGO: 14,
            PARC: 15, FORMA: 16, TERMO: 17, NPGTO: 18, ALOC: 19, SALDO: 20 };

/* ========================================================================== */
/* 1. Recebimento das linhas da Calculadora                                   */
/* ========================================================================== */

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const corpo = JSON.parse(e.postData.contents);
    const token = PropertiesService.getScriptProperties().getProperty('TOKEN');
    if (!token || corpo.token !== token) return resposta_({ ok: false, erro: 'token invalido' });

    const linhas = corpo.linhas || [];
    if (!linhas.length) return resposta_({ ok: false, erro: 'nenhuma linha' });
    if (linhas.some(function (l) { return !Array.isArray(l) || l.length !== N_COLS; })) {
      return resposta_({ ok: false, erro: 'cada linha precisa ter ' + N_COLS + ' colunas (A:U)' });
    }
    const dados = linhas.map(converterLinha_);
    const cnpj = texto_(dados[0][C.CNPJ]);
    const termo = texto_(dados[0][C.TERMO]);

    const aba = planilha_().getSheetByName(ABA_ACORDOS);
    const removidas = termo ? removerAcordo_(aba, cnpj, termo) : 0;
    const ini = ultimaLinha_(aba) + 1;
    if (aba.getMaxRows() < ini + dados.length - 1) {
      aba.insertRowsAfter(aba.getMaxRows(), ini + dados.length - 1 - aba.getMaxRows());
    }
    // texto antes de gravar: "165/1" nao pode virar data, CNPJ nao pode virar numero
    aba.getRange(ini, C.CNPJ + 1, dados.length, 3).setNumberFormat('@');
    aba.getRange(ini, 1, dados.length, N_COLS).setValues(dados);
    aba.getRange(ini, C.VENC + 1, dados.length, 1).setNumberFormat('dd/mm/yyyy');
    aba.getRange(ini, C.DTPGTO + 1, dados.length, 1).setNumberFormat('dd/mm/yyyy');
    aba.getRange(ini, C.ORIG + 1, dados.length, 3).setNumberFormat('"R$ "#,##0.00');
    aba.getRange(ini, C.PAGO + 1, dados.length, 2).setNumberFormat('"R$ "#,##0.00');
    aba.getRange(ini, C.ALOC + 1, dados.length, 2).setNumberFormat('"R$ "#,##0.00');

    return resposta_({ ok: true, linhas: dados.length, primeira: ini, substituidas: removidas });
  } catch (err) {
    return resposta_({ ok: false, erro: String(err) });
  } finally {
    lock.releaseLock();
  }
}

function converterLinha_(l) {
  const numericas = [C.ATRASO, C.ORIG, C.JUROS, C.TOTAL, C.PAGO, C.PARC, C.ALOC, C.SALDO];
  return l.map(function (v, i) {
    if (i === C.VENC || i === C.DTPGTO) return data_(v) || texto_(v);
    if (numericas.indexOf(i) >= 0) return v === '' || v === null ? '' : Number(v);
    return texto_(v);
  });
}

function removerAcordo_(aba, cnpj, termo) {
  const ult = ultimaLinha_(aba);
  if (ult < LIN_INI) return 0;
  const vals = aba.getRange(LIN_INI, 1, ult - LIN_INI + 1, N_COLS).getDisplayValues();
  let n = 0;
  for (let i = vals.length - 1; i >= 0; i--) {
    if (vals[i][C.CNPJ].trim() === cnpj && vals[i][C.TERMO].trim() === termo &&
        RE_PGTO.test(vals[i][C.NPGTO].trim())) {
      aba.deleteRow(LIN_INI + i);
      n++;
    }
  }
  return n;
}

/* ========================================================================== */
/* 2. Status pelas baixas do CIGAM                                            */
/* ========================================================================== */

function atualizarStatusAcordos() {
  calcularStatus_(true);
}

/** Mostra o que mudaria, na aba STATUS_SIMULACAO, sem alterar a ACORDOS. */
function simularStatusAcordos() {
  calcularStatus_(false);
}

function calcularStatus_(aplicar) {
  const ss = planilha_();
  const aba = ss.getSheetByName(ABA_ACORDOS);
  const ult = ultimaLinha_(aba);
  if (ult < LIN_INI) return;
  const faixa = aba.getRange(LIN_INI, 1, ult - LIN_INI + 1, N_COLS);
  const vals = faixa.getValues();
  const disp = faixa.getDisplayValues();
  const hoje = new Date(); hoje.setHours(0, 0, 0, 0);

  // Linhas da macro, agrupadas por titulo dentro do acordo (CNPJ | TERMO | DOC)
  const grupos = {};
  const ordemGrupos = [];
  const pares = {};
  for (let i = 0; i < vals.length; i++) {
    const npgto = disp[i][C.NPGTO].trim();
    if (!RE_PGTO.test(npgto)) continue;
    if (STATUS_MANUAIS.indexOf(disp[i][C.STATUS].trim().toUpperCase()) >= 0) continue;
    const emp = disp[i][C.EMPRESA].substring(0, 6);
    const doc = disp[i][C.DOC].trim();
    const chave = disp[i][C.CNPJ].trim() + '|' + disp[i][C.TERMO].trim() + '|' + doc;
    if (!grupos[chave]) { grupos[chave] = { emp: emp, doc: doc, linhas: [] }; ordemGrupos.push(chave); }
    grupos[chave].linhas.push(i);
    const fat = doc.split('/')[0].trim();
    if (/^\d{6}$/.test(emp) && /^\d+$/.test(fat)) pares[emp + '|' + fat] = [emp, fat];
  }
  if (!ordemGrupos.length) return;

  const cigam = consultarTitulos_(pares);   // emp|fatura/parcela -> {valor, liq}

  const novos = disp.map(function (l) { return l[C.STATUS]; });
  const motivos = {};
  ordemGrupos.forEach(function (chave) {
    const g = grupos[chave];
    const t = cigam[g.emp + '|' + g.doc];
    const prim = vals[g.linhas[0]];
    const orig = num_(prim[C.ORIG]);
    const total = num_(prim[C.TOTAL]) || g.linhas.reduce(function (s, i) { return s + num_(vals[i][C.ALOC]); }, 0);
    const fator = orig > 0 && total > 0 ? orig / total : 1;

    let liquidado = false, pago = 0, origem = 'titulo nao encontrado no CIGAM';
    if (t) {
      const saldoPagto = t.valor - t.liq;
      liquidado = saldoPagto <= TOL;
      pago = Math.max(0, Math.min(t.liq, orig - saldoPagto));
      origem = liquidado ? 'titulo liquidado no CIGAM'
                         : 'principal baixado no CIGAM desde o acordo: ' + pago.toFixed(2);
    }

    let acum = 0;
    g.linhas.forEach(function (i) {
      const parte = num_(vals[i][C.ALOC]) * fator;
      const pagoManual = num_(vals[i][C.PAGO]);
      let status, motivo;
      if (liquidado || acum + parte <= pago + TOL || (pagoManual > 0 && pagoManual >= num_(vals[i][C.ALOC]) - TOL)) {
        status = 'Quitado';
        motivo = pagoManual > 0 && !liquidado && acum + parte > pago + TOL ? 'VALOR PAGO preenchido' : origem;
      } else {
        const venc = data_(vals[i][C.DTPGTO]) || data_(disp[i][C.DTPGTO]);
        const dias = venc ? Math.floor((hoje - venc) / 86400000) : null;
        if (dias !== null && dias >= DIAS_PARA_QUEBRAR) {
          status = 'Acordo Quebrado';
          motivo = 'parcela vencida ha ' + dias + ' dia(s) sem baixa; ' + origem;
        } else {
          status = 'Em Dia';
          motivo = venc ? 'no prazo; ' + origem : 'sem DATA DE PAGAMENTO; ' + origem;
        }
      }
      acum += parte;
      novos[i] = status;
      motivos[i] = motivo;
    });
  });

  // Mudancas
  const mudancas = [];
  Object.keys(motivos).forEach(function (k) {
    const i = Number(k);
    if (novos[i] !== disp[i][C.STATUS]) {
      mudancas.push([LIN_INI + i, disp[i][C.EMPRESA], disp[i][C.DOC], disp[i][C.NPGTO],
                     disp[i][C.DTPGTO], disp[i][C.STATUS], novos[i], motivos[i]]);
    }
  });

  if (!aplicar) {
    let sim = ss.getSheetByName(ABA_SIMULACAO);
    if (!sim) sim = ss.insertSheet(ABA_SIMULACAO);
    sim.clear();
    sim.getRange(1, 1, 1, 8).setValues([['LINHA NA ACORDOS', 'EMPRESA', 'DOC', 'Nº PGTO',
      'DATA DE PAGAMENTO', 'STATUS ATUAL', 'STATUS CALCULADO', 'MOTIVO']]).setFontWeight('bold');
    if (mudancas.length) sim.getRange(2, 1, mudancas.length, 8).setValues(mudancas);
    sim.getRange(1, 10).setValue('Simulado em ' + Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'dd/MM/yyyy HH:mm') +
      ' - ' + mudancas.length + ' linha(s) mudariam. Nada foi alterado na ACORDOS.');
    return;
  }

  aba.getRange(LIN_INI, 1, novos.length, 1).setValues(novos.map(function (s) { return [s]; }));
  aba.getRange('Q1').setValue('STATUS ATUALIZADO EM');
  aba.getRange('R1').setValue(new Date()).setNumberFormat('dd/mm/yyyy hh:mm');
  avisarQuebrados_(mudancas);
}

function avisarQuebrados_(mudancas) {
  const quebrados = mudancas.filter(function (m) { return m[6] === 'Acordo Quebrado'; });
  if (!quebrados.length) return;
  const porEmpresa = {};
  quebrados.forEach(function (m) { (porEmpresa[m[1]] = porEmpresa[m[1]] || []).push(m); });
  const corpo = Object.keys(porEmpresa).map(function (emp) {
    return emp + '\n' + porEmpresa[emp].map(function (m) {
      return '   linha ' + m[0] + ' - DOC ' + m[2] + ' - ' + m[3] + ' - venc. ' + m[4];
    }).join('\n');
  }).join('\n\n');
  MailApp.sendEmail(Session.getEffectiveUser().getEmail(),
    'Acordos quebrados hoje: ' + Object.keys(porEmpresa).length + ' cliente(s)',
    'Parcelas que passaram a "Acordo Quebrado" na aba ACORDOS:\n\n' + corpo + '\n\n' +
    SpreadsheetApp.getActive().getUrl());
}

/** Valor e liquidacoes (E/L, sem X90) de cada titulo no CIGAM. */
function consultarTitulos_(pares) {
  const lista = Object.keys(pares).map(function (k) { return "('" + pares[k][0] + "','" + pares[k][1] + "')"; });
  if (!lista.length) return {};
  const tabela = '`' + PROJETO_BQ + '.silver.lancamentos_receber`';
  const sql =
    'WITH alvo AS (SELECT * FROM UNNEST([STRUCT<emp STRING, fat STRING>' + lista.join(',') + '])),\n' +
    'tit AS (SELECT l.* FROM ' + tabela + ' l JOIN alvo a ON l.codigoEmpresa = a.emp AND l.fatura = a.fat\n' +
    "        WHERE l.codigoTipo IN ('R','c')),\n" +
    "liq AS (SELECT codigoPartida, SUM(SAFE_CAST(valor AS NUMERIC)) v FROM " + tabela + "\n" +
    "        WHERE codigoTipo = 'E' AND situacao = 'L' AND IFNULL(codigoPortador,'') NOT IN ('X90','X91','X92')\n" +
    '        GROUP BY 1)\n' +
    "SELECT t.codigoEmpresa, CONCAT(t.fatura,'/',TRIM(IFNULL(t.complemento,''))),\n" +
    '  SUM(SAFE_CAST(t.valor AS NUMERIC)), SUM(IFNULL(q.v,0))\n' +
    'FROM tit t LEFT JOIN liq q ON q.codigoPartida = t.codigoLancamento\n' +
    'GROUP BY 1, 2';
  const out = {};
  consultar_(sql).forEach(function (r) {
    const f = r.f.map(function (c) { return c.v; });
    out[f[0] + '|' + f[1]] = { valor: Number(f[2]), liq: Number(f[3]) };
  });
  return out;
}

/* ========================================================================== */
/* Instalacao                                                                 */
/* ========================================================================== */

function gerarToken() {
  const token = Utilities.getUuid().replace(/-/g, '');
  PropertiesService.getScriptProperties().setProperty('TOKEN', token);
  PropertiesService.getScriptProperties().setProperty('PLANILHA_ID', SpreadsheetApp.getActive().getId());
  Logger.log('Token (copie para TOKEN_PLANILHA no Module9 da Calculadora): ' + token);
  try { SpreadsheetApp.getUi().alert('Token gerado (copie para o Module9 da Calculadora):\n\n' + token); } catch (e) {}
}

function instalarGatilhoDiario() {
  ScriptApp.getProjectTriggers()
    .filter(function (t) { return t.getHandlerFunction() === 'atualizarStatusAcordos'; })
    .forEach(function (t) { ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('atualizarStatusAcordos').timeBased().everyDays(1).atHour(7).create();
}

/* ========================================================================== */
/* Apoio                                                                      */
/* ========================================================================== */

function planilha_() {
  const id = PropertiesService.getScriptProperties().getProperty('PLANILHA_ID');
  return id ? SpreadsheetApp.openById(id) : SpreadsheetApp.getActive();
}

function ultimaLinha_(aba) {
  const col = aba.getRange(1, C.EMPRESA + 1, aba.getMaxRows(), 1).getValues();
  for (let i = col.length - 1; i >= 0; i--) if (String(col[i][0]).trim() !== '') return i + 1;
  return LIN_INI - 1;
}

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

function resposta_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function texto_(v) { return v === null || v === undefined ? '' : String(v).trim(); }

/** Numero a partir de valor da celula ou texto "R$ 1.234,56" / "1234.56". */
function num_(v) {
  if (typeof v === 'number') return v;
  let s = String(v || '').replace(/R\$/g, '').trim();
  if (!s) return 0;
  if (s.indexOf(',') >= 0) s = s.replace(/\./g, '').replace(',', '.');
  const n = Number(s);
  return isNaN(n) ? 0 : n;
}

/** Data a partir de Date, serial do Sheets ou texto "dd/mm/aaaa..." (ignora sufixos como "(PARCIAL)"). */
function data_(v) {
  if (v instanceof Date && !isNaN(v)) { const d = new Date(v); d.setHours(0, 0, 0, 0); return d; }
  if (typeof v === 'number' && v > 30000 && v < 80000) {
    const u = new Date(Math.round((v - 25569) * 86400000));
    return new Date(u.getUTCFullYear(), u.getUTCMonth(), u.getUTCDate());
  }
  const m = String(v || '').match(/(\d{1,2})\/(\d{1,2})\/(\d{4})/);
  return m ? new Date(Number(m[3]), Number(m[2]) - 1, Number(m[1])) : null;
}
