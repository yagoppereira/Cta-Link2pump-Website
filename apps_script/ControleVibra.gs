/**
 * Controle de NFs da Vibra: Apps Script vinculado à planilha PENDENCIAS VIBRA.
 *
 * Consulta o DW (BigQuery) com o login de quem executa, monta a lista de
 * NFs emitidas para a Vibra e grava na aba "Controle NFs Vibra":
 * - colunas A a N ("Do CIGAM") são reescritas a cada execução;
 * - coluna O (cliente final) é fórmula da planilha (linha 2) e não é tocada:
 *   procura a filial Vibra + o nº do local de entrega da NF na aba "Locais
 *   de entrega"; local que aparece nas NFs e não está lá é acrescentado no
 *   fim da aba pra alguém preencher;
 * - colunas P a S (status de entrega, data, observações) são do time: o
 *   script lê o que já está lá e devolve cada valor na linha da mesma NF
 *   (chave = NF + série);
 * - colunas T e U são fórmulas da própria planilha (linha 2) e não são tocadas.
 *
 * Menu "Controle Vibra" na planilha: Atualizar agora, Agendar atualização
 * diária e Remover agendamento. O agendamento roda com o login de quem o
 * criou.
 *
 * É o espelho de controle_vibra.py (repositório Projeto-Consulta-Mensalidades):
 * mesmo SQL e mesmas regras. tests/test_apps_script.py compara as duas
 * versões; ao mudar uma, mude a outra.
 */

const PROJECT_ID = 'hip-bonito-453017-m2';
const RAIZ_CNPJ_VIBRA = '34274233';
const PISO_CONSULTA = '2024-01-01';
const DESDE_PADRAO = '2026-01-01';
const ABA_CONTROLE = 'Controle NFs Vibra';
const ABA_FONTES = 'Fontes';
const ABA_LOCAIS = 'Locais de entrega';
const HORA_AGENDAMENTO = 7;

const STATUS_EM_ABERTO = 'Em aberto';
const STATUS_PAGO_PARCIAL = 'Pago parcial';
const STATUS_PAGO = 'Pago';
const STATUS_DEVOLVIDA = 'Devolvida';
const STATUS_ABATIDA = 'Abatida';
const STATUS_CANCELADA = 'Cancelada';
const STATUS_PERDA = 'Baixa por perda';
const STATUS_SEM_TITULO = 'Sem título';
const STATUS_ABERTOS = [STATUS_EM_ABERTO, STATUS_PAGO_PARCIAL, STATUS_SEM_TITULO];

const COLUNAS_DW = [
  'NF', 'Série', 'Emissão', 'Vencimento', 'Valor (R$)', 'Saldo em aberto (R$)',
  'Nº Pedido Vibra', 'Filial Vibra (CNPJ)', 'Tipo de NF', 'Material',
  'Status financeiro', 'Data pagamento / baixa', 'NF de devolução', 'Local de entrega (nº)',
];
const CABECALHO_LOCAIS = [
  'Filial Vibra (CNPJ)', 'Local de entrega (nº)', 'Cliente final', 'Cód. CIGAM do cliente final', 'Origem',
];
// O é fórmula (cliente final pela aba Locais de entrega); P a S são do time
const COLUNA_CLIENTE_FINAL = 'Cliente final';
const COLUNAS_MANUAIS = ['Status entrega', 'Data entrega / NF assinada', 'Obs. Emissão', 'Obs. financeiro'];
// coluna que a Emissão preenchia à mão antes de virar fórmula: o que foi
// digitado e não bate com a aba Locais de entrega vai pra Obs. Emissão
const COLUNA_CLIENTE_FINAL_DIGITADO = 'Cliente final / local de entrega';
const PRIMEIRA_LINHA_DADOS = 3;
const TOLERANCIA_CENTAVOS = 0.01;

const TABELAS_CONSULTADAS = [
  'bronze.cigam__empresas', 'bronze.cigam__notas_fiscais',
  'silver.lancamentos_receber', 'silver.cadastro_materiais_cigam',
];

// mesmo texto de SQL_NOTAS_VIBRA em controle_vibra.py
const SQL_NOTAS_VIBRA = `
WITH vibra AS (
  SELECT codigo, REGEXP_REPLACE(cnpjCpf, r'\\D', '') AS cnpj
  FROM \`${PROJECT_ID}.bronze.cigam__empresas\`
  WHERE STARTS_WITH(REGEXP_REPLACE(cnpjCpf, r'\\D', ''), @raiz_cnpj)
),
-- NF de saída (N = normal, E = entrega futura). especieNota S = saída
-- válida, N = nula (cancelada); a nula só entra se chegou a ter título.
notas AS (
  SELECT n.nf, n.serie, n.cliente, n.dataEmissao, n.status, n.especieNota,
         NULLIF(TRIM(n.dataCancelamento), '') AS dataCancelamento,
         -- "Local de Entrega" da aba Transporte da NF: o CIGAM guarda o nº
         -- como um caractere em sequência a partir do "!" (! = 1, " = 2,
         -- # = 3...), pulando ' * ? e \\ (não aparecem em NF nenhuma). Então
         -- "(" = 7, ")" = 8, "+" = 9, "," = 10. Conferido com a lista de
         -- endereços da Vibra RJ: a Reiter (cadastrada em 01/10/2026) é a 10ª
         -- e só aparece nas NFs de outubro, com ",".
         -- O nº aponta pra lista de endereços de entrega do cliente (a
         -- filial da Vibra), que não está no DW: o nome do cliente final
         -- vem da aba "Locais de entrega" da planilha.
         IF(TRIM(IFNULL(n.ordemEnderecoEntrega, '')) = '', NULL,
            UNICODE(n.ordemEnderecoEntrega) - 32
            - (SELECT COUNT(*) FROM UNNEST([39, 42, 63, 92]) AS pulado
               WHERE pulado < UNICODE(n.ordemEnderecoEntrega))) AS localEntrega,
         SAFE_CAST(n.totalNF AS NUMERIC) AS totalNF, n.itensNf_json
  FROM \`${PROJECT_ID}.bronze.cigam__notas_fiscais\` n
  WHERE n.dataEmissao >= @piso AND n.cliente IN (SELECT codigo FROM vibra)
    AND n.especieNota IN ('S', 'N') AND n.tipoNota IN ('E', 'N')
),
-- NF de entrada (D = devolução, C = complementar) que a Vibra emite
-- referenciando a nossa NF: é assim que um "cancelamento" depois de 24 h
-- aparece no CIGAM (ex.: NF 22114 devolvida pela 23920).
devolucoes AS (
  SELECT notaReferencia AS nf, serieReferencia AS serie, cliente,
         STRING_AGG(nf, ', ' ORDER BY nf) AS nfs_devolucao,
         MAX(dataEmissao) AS data_devolucao
  FROM \`${PROJECT_ID}.bronze.cigam__notas_fiscais\`
  WHERE dataEmissao >= @piso AND cliente IN (SELECT codigo FROM vibra)
    AND especieNota = 'E' AND tipoNota IN ('D', 'C') AND status = '3'
  GROUP BY 1, 2, 3
),
lanc AS (
  SELECT nf, serie, codigoEmpresa, codigoTipo, codigoLancamento, codigoPartida, codigoPortador,
         SAFE.PARSE_DATE('%d/%m/%Y', dataVencimento) AS vencimento,
         SAFE.PARSE_DATE('%d/%m/%Y', data) AS data,
         SAFE_CAST(valor AS NUMERIC) AS valor
  FROM \`${PROJECT_ID}.silver.lancamentos_receber\`
  WHERE codigoEmpresa IN (SELECT codigo FROM vibra)
),
-- a baixa (E) aponta pro título pelo codigoPartida. O saldo da linha R
-- NÃO serve: ela não é reextraída depois da baixa e fica com saldo cheio
-- (ex.: NF 12121, paga em 27/02/2026 e com R ainda "A" e saldo 7.851,02).
baixas AS (
  SELECT codigoPartida,
         SUM(IF(codigoPortador = 'X30', valor, 0)) AS abatido,
         SUM(IF(REGEXP_CONTAINS(codigoPortador, r'^X9[0-9]$'), valor, 0)) AS perda,
         SUM(IF(codigoPortador = 'X30' OR REGEXP_CONTAINS(codigoPortador, r'^X9[0-9]$'), 0, valor)) AS pago,
         MAX(data) AS data_baixa
  FROM lanc WHERE codigoTipo = 'E'
  GROUP BY 1
),
titulos AS (
  SELECT t.nf, t.serie, t.codigoEmpresa,
         MIN(t.vencimento) AS vencimento,
         SUM(t.valor) AS valor_titulo,
         IFNULL(SUM(b.pago), 0) AS pago,
         IFNULL(SUM(b.abatido), 0) AS abatido,
         IFNULL(SUM(b.perda), 0) AS perda,
         MAX(b.data_baixa) AS data_baixa
  FROM lanc t
  LEFT JOIN baixas b ON b.codigoPartida = t.codigoLancamento
  WHERE t.codigoTipo IN ('R', 'c')
  GROUP BY 1, 2, 3
),
itens AS (
  SELECT n.nf, n.serie, n.cliente,
         TRIM(JSON_VALUE(i, '$.codigoMaterial')) AS material,
         SAFE_CAST(JSON_VALUE(i, '$.quantidade') AS NUMERIC) AS quantidade,
         SAFE_CAST(JSON_VALUE(i, '$.quantidade') AS NUMERIC)
           * SAFE_CAST(JSON_VALUE(i, '$.precoUnitario') AS NUMERIC) AS valor,
         JSON_VALUE(i, '$.descricao') AS texto
  FROM notas n, UNNEST(JSON_QUERY_ARRAY(n.itensNf_json)) i
),
-- o nº do pedido da Vibra (10 dígitos, 45... ou 46...) não tem campo
-- próprio no CIGAM: vem digitado no texto do item ("OC: 4503816077",
-- "Contrato CTA SMART nº 4600213963")
itens_nf AS (
  SELECT i.nf, i.serie, i.cliente,
         STRING_AGG(CONCAT(FORMAT('%g', CAST(i.quantidade AS FLOAT64)), 'x ', IFNULL(m.descricao, i.material)),
                    ' + ' ORDER BY i.valor DESC) AS material,
         LOGICAL_OR(m.descricao_subgrupo = 'TOTEM') AS tem_cta,
         LOGICAL_OR(m.descricao_subgrupo = 'SONDA') AS tem_sonda,
         LOGICAL_OR(STARTS_WITH(i.material, '900001')) AS tem_licenciamento,  -- grupo 900, subgrupo 001
         STRING_AGG(IFNULL(i.texto, ''), ' ') AS textos
  FROM itens i
  LEFT JOIN \`${PROJECT_ID}.silver.cadastro_materiais_cigam\` m ON m.codigo_material = i.material
  GROUP BY 1, 2, 3
)
SELECT n.nf, n.serie, n.cliente, v.cnpj, n.dataEmissao AS emissao, n.status,
       n.dataCancelamento AS data_cancelamento, n.totalNF AS total_nf,
       t.vencimento, t.valor_titulo, t.pago, t.abatido, t.perda, t.data_baixa,
       d.nfs_devolucao, d.data_devolucao, n.localEntrega AS local_entrega,
       i.material, i.tem_cta, i.tem_sonda, i.tem_licenciamento, i.textos
FROM notas n
JOIN vibra v ON v.codigo = n.cliente
LEFT JOIN titulos t ON t.nf = n.nf AND t.serie = n.serie AND t.codigoEmpresa = n.cliente
LEFT JOIN devolucoes d ON d.nf = n.nf AND d.serie = n.serie AND d.cliente = n.cliente
LEFT JOIN itens_nf i ON i.nf = n.nf AND i.serie = n.serie AND i.cliente = n.cliente
WHERE n.especieNota = 'S' OR t.nf IS NOT NULL
`;


// ============================================================================
// Menu e agendamento
// ============================================================================
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Controle Vibra')
    .addItem('Atualizar agora', 'atualizarControleVibra')
    .addItem('Filtros', 'abrirFiltros')
    .addSeparator()
    .addItem('Agendar atualização diária', 'agendarAtualizacaoDiaria')
    .addItem('Remover agendamento', 'removerAgendamento')
    .addSeparator()
    .addItem('Criar filtro rápido na linha 1', 'criarFiltroRapido')
    .addToUi();
}

function agendarAtualizacaoDiaria() {
  removerAgendamento();
  ScriptApp.newTrigger('atualizarControleVibra').timeBased().everyDays(1).atHour(HORA_AGENDAMENTO)
    .inTimezone(fusoDaPlanilha_()).create();
  SpreadsheetApp.getActive().toast(
    `Atualização diária agendada para ${HORA_AGENDAMENTO}h, com o seu login.`, 'Controle Vibra', 8);
}

/** Horário de Brasília da planilha, e não o fuso do projeto do Apps Script,
 * que só é São Paulo se o appsscript.json deste diretório foi colado (com o
 * padrão, a hora de "atualizado em" e do agendamento saía deslocada). */
function fusoDaPlanilha_() {
  return SpreadsheetApp.getActive().getSpreadsheetTimeZone() || 'America/Sao_Paulo';
}

function removerAgendamento() {
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'atualizarControleVibra')
    .forEach(t => ScriptApp.deleteTrigger(t));
}


// ============================================================================
// Execução
// ============================================================================
function atualizarControleVibra() {
  const trava = LockService.getDocumentLock();
  if (!trava.tryLock(30000)) {
    throw new Error('Já existe uma atualização do controle Vibra em andamento.');
  }
  try {
    const planilha = SpreadsheetApp.getActive();
    const aba = planilha.getSheetByName(ABA_CONTROLE);
    if (!aba) throw new Error(`Aba "${ABA_CONTROLE}" não encontrada.`);

    let abaLocais = planilha.getSheetByName(ABA_LOCAIS);
    if (!abaLocais) {
      abaLocais = planilha.insertSheet(ABA_LOCAIS);
      abaLocais.getRange(1, 1, 1, CABECALHO_LOCAIS.length).setValues([CABECALHO_LOCAIS]);
    }
    const valoresLocais = abaLocais.getDataRange().getValues();

    const atual = aba.getDataRange().getValues();
    const tabela = montarTabela(consultarNotasVibra_(), atual, DESDE_PADRAO, valoresLocais);
    const agora = new Date();
    gravarControle_(aba, tabela, agora);
    atualizarFontes_(planilha, agora, tabela.length);
    const novos = locaisSemCadastro(tabela, lerLocaisEntrega(valoresLocais));
    if (novos.length) {
      abaLocais.getRange(abaLocais.getLastRow() + 1, 1, novos.length, CABECALHO_LOCAIS.length).setValues(novos);
    }
    planilha.toast(
      `${tabela.length} NFs atualizadas a partir do CIGAM.` +
      (novos.length ? ` ${novos.length} local(is) de entrega novo(s) na aba "${ABA_LOCAIS}" para preencher.` : ''),
      'Controle Vibra', 10);
  } finally {
    trava.releaseLock();
  }
}

/** Roda SQL_NOTAS_VIBRA com o login de quem executa e devolve uma lista de
 * objetos {coluna: valor}. O BigQuery devolve tudo como texto (DATE como
 * "2026-01-14", NUMERIC como "35861.37", BOOL como "true"). */
function consultarNotasVibra_() {
  const pedido = {
    query: SQL_NOTAS_VIBRA,
    useLegacySql: false,
    parameterMode: 'NAMED',
    queryParameters: [
      { name: 'raiz_cnpj', parameterType: { type: 'STRING' }, parameterValue: { value: RAIZ_CNPJ_VIBRA } },
      { name: 'piso', parameterType: { type: 'DATE' }, parameterValue: { value: PISO_CONSULTA } },
    ],
    timeoutMs: 60000,
  };
  let resposta;
  try {
    resposta = BigQuery.Jobs.query(pedido, PROJECT_ID);
  } catch (erro) {
    throw new Error(
      'Não consegui consultar o DW com o seu login. É preciso poder rodar consultas no projeto ' +
      `${PROJECT_ID} e ler ${TABELAS_CONSULTADAS.join(', ')}. Detalhe: ${erro.message}`);
  }
  const job = resposta.jobReference;
  while (!resposta.jobComplete) {
    Utilities.sleep(1000);
    resposta = BigQuery.Jobs.getQueryResults(PROJECT_ID, job.jobId, { location: job.location });
  }
  let linhas = resposta.rows || [];
  let pagina = resposta.pageToken;
  while (pagina) {
    const proxima = BigQuery.Jobs.getQueryResults(PROJECT_ID, job.jobId, { location: job.location, pageToken: pagina });
    linhas = linhas.concat(proxima.rows || []);
    pagina = proxima.pageToken;
  }
  const campos = resposta.schema.fields.map(c => c.name);
  return linhas.map(linha => {
    const registro = {};
    linha.f.forEach((celula, i) => { registro[campos[i]] = celula.v; });
    return registro;
  });
}

function gravarControle_(aba, tabela, agora) {
  const nDw = COLUNAS_DW.length;
  const nColunas = nDw + 1 + COLUNAS_MANUAIS.length;
  const necessarias = PRIMEIRA_LINHA_DADOS - 1 + tabela.length;
  if (aba.getMaxRows() < necessarias) {
    aba.insertRowsAfter(aba.getMaxRows(), necessarias - aba.getMaxRows());
  }
  const sobra = aba.getMaxRows() - PRIMEIRA_LINHA_DADOS + 1;
  aba.getRange(PRIMEIRA_LINHA_DADOS, 1, sobra, nColunas).clearContent();
  if (tabela.length) {
    // a coluna do cliente final fica vazia pro ARRAYFORMULA da linha 2 se espalhar
    const linhas = linhasParaPlanilha(tabela);
    aba.getRange(PRIMEIRA_LINHA_DADOS, 1, linhas.length, nDw).setValues(linhas.map(l => l.slice(0, nDw)));
    aba.getRange(PRIMEIRA_LINHA_DADOS, nDw + 2, linhas.length, COLUNAS_MANUAIS.length)
      .setValues(linhas.map(l => l.slice(nDw + 1)));
  }
  // o título fica em A1 ou, com o filtro rápido montado (FiltrosVibra.gs), em G1
  const linha1 = aba.getRange(1, 1, 1, aba.getLastColumn()).getDisplayValues()[0];
  const colunaTitulo = Math.max(linha1.findIndex(v => String(v).startsWith('Do CIGAM')), 0) + 1;
  aba.getRange(1, colunaTitulo).setValue(
    `Do CIGAM (extrator, atualizado em ${Utilities.formatDate(agora, fusoDaPlanilha_(), 'dd/MM/yyyy HH:mm')})`);
}

function atualizarFontes_(planilha, agora, linhas) {
  const fontes = planilha.getSheetByName(ABA_FONTES);
  if (!fontes) return;
  const quem = Session.getEffectiveUser().getEmail() || 'agendamento';
  fontes.getRange('D2').setValue('Apps Script da planilha (ControleVibra.gs), com o login de quem executa');
  fontes.getRange('G2:I2').setValues([[
    "'" + Utilities.formatDate(agora, fusoDaPlanilha_(), 'dd/MM/yyyy HH:mm'), quem, linhas]]);
}


// ============================================================================
// Regras (espelho de controle_vibra.py)
// ============================================================================
function vazio_(valor) {
  return valor === null || valor === undefined || (typeof valor === 'number' && isNaN(valor));
}

function texto_(valor) {
  return vazio_(valor) ? '' : String(valor).trim();
}

function numero_(valor) {
  const n = parseFloat(valor);
  return isNaN(n) ? 0 : n;
}

function inteiro_(valor) {
  const n = parseInt(texto_(valor), 10);
  return isNaN(n) ? null : n;
}

function verdadeiro_(valor) {
  return valor === true || valor === 'true';
}

function arredondar_(valor) {
  return Math.round(valor * 100) / 100;
}

/** Date local à meia-noite a partir de Date, "aaaa-mm-dd" ou "dd/mm/aaaa". */
function data_(valor) {
  if (vazio_(valor)) return null;
  if (valor instanceof Date) return new Date(valor.getFullYear(), valor.getMonth(), valor.getDate());
  const texto = String(valor).trim();
  let m = /^(\d{4})-(\d{2})-(\d{2})/.exec(texto);
  if (m) return new Date(+m[1], +m[2] - 1, +m[3]);
  m = /^(\d{2})\/(\d{2})\/(\d{4})/.exec(texto);
  if (m) return new Date(+m[3], +m[2] - 1, +m[1]);
  return null;
}

function classificarStatus(linha) {
  if (texto_(linha.status) === '5') {
    return { status: STATUS_CANCELADA, data: data_(linha.data_cancelamento), saldo: 0 };
  }
  if (vazio_(linha.valor_titulo)) {
    return { status: STATUS_SEM_TITULO, data: null, saldo: null };
  }
  const valorTitulo = numero_(linha.valor_titulo);
  const pago = numero_(linha.pago);
  const abatido = numero_(linha.abatido);
  const perda = numero_(linha.perda);
  const baixado = pago + abatido + perda;
  const saldo = arredondar_(Math.max(valorTitulo - baixado, 0));
  const dataBaixa = data_(linha.data_baixa);

  if (saldo > TOLERANCIA_CENTAVOS) {
    if (baixado > TOLERANCIA_CENTAVOS) return { status: STATUS_PAGO_PARCIAL, data: dataBaixa, saldo };
    return { status: STATUS_EM_ABERTO, data: null, saldo };
  }
  if (perda > TOLERANCIA_CENTAVOS) return { status: STATUS_PERDA, data: dataBaixa, saldo: 0 };
  if (pago > TOLERANCIA_CENTAVOS) return { status: STATUS_PAGO, data: dataBaixa, saldo: 0 };
  if (texto_(linha.nfs_devolucao)) {
    return { status: STATUS_DEVOLVIDA, data: data_(linha.data_devolucao) || dataBaixa, saldo: 0 };
  }
  return { status: STATUS_ABATIDA, data: dataBaixa, saldo: 0 };
}

function classificarTipo(linha) {
  const serie = texto_(linha.serie).toUpperCase();
  if (serie.startsWith('S')) return verdadeiro_(linha.tem_licenciamento) ? 'Mensalidade' : 'Serviço';
  if (verdadeiro_(linha.tem_cta)) return 'Venda de CTA';
  if (verdadeiro_(linha.tem_sonda)) return 'Venda de Sonda';
  return 'Peças e periféricos';
}

function extrairPedidoVibra(textos) {
  const achados = texto_(textos).match(/(?<!\d)(4[56]\d{8})(?!\d)/g) || [];
  return Array.from(new Set(achados)).join(', ');
}

function formatarCnpj(digitos) {
  const d = texto_(digitos).replace(/\D/g, '');
  if (d.length !== 14) return d;
  return `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8, 12)}-${d.slice(12)}`;
}

function montarControle(linhasDw) {
  return linhasDw.map(linha => {
    const st = classificarStatus(linha);
    const totalNf = numero_(linha.total_nf) || numero_(linha.valor_titulo);
    return {
      'NF': texto_(linha.nf),
      'Série': texto_(linha.serie),
      'Emissão': data_(linha.emissao),
      'Vencimento': data_(linha.vencimento),
      'Valor (R$)': arredondar_(totalNf),
      'Saldo em aberto (R$)': st.saldo,
      'Nº Pedido Vibra': extrairPedidoVibra(linha.textos),
      'Filial Vibra (CNPJ)': formatarCnpj(linha.cnpj),
      'Tipo de NF': classificarTipo(linha),
      'Material': texto_(linha.material),
      'Status financeiro': st.status,
      'Data pagamento / baixa': st.data,
      'NF de devolução': texto_(linha.nfs_devolucao),
      'Local de entrega (nº)': inteiro_(linha.local_entrega),
    };
  });
}

function chaveNf(nf, serie) {
  let numero = texto_(nf).replace(/\D/g, '');
  numero = numero.replace(/^0+/, '') || numero;
  return `${numero}|${texto_(serie).toUpperCase()}`;
}

/** {chave: {coluna manual: valor}} a partir dos valores da aba. Acha o
 * cabeçalho pela linha cuja primeira célula é "NF" e as colunas pelo nome.
 * Data digitada volta como Date (getValues), texto como texto. */
function lerPreenchimentoManual(valoresAba) {
  const indiceCabecalho = (valoresAba || []).slice(0, 10).findIndex(l => l && texto_(l[0]) === 'NF');
  if (indiceCabecalho < 0) return {};
  const cabecalho = valoresAba[indiceCabecalho].map(texto_);
  const posicoes = {};
  const lidas = COLUNAS_MANUAIS.concat(['Nº Pedido Vibra', COLUNA_CLIENTE_FINAL_DIGITADO]);
  lidas.concat(['Série']).forEach(nome => {
    const pos = cabecalho.indexOf(nome);
    if (pos >= 0) posicoes[nome] = pos;
  });
  if (!('Série' in posicoes)) return {};

  const manuais = {};
  valoresAba.slice(indiceCabecalho + 1).forEach(linha => {
    if (!linha || !texto_(linha[0])) return;
    const celula = nome => {
      const pos = posicoes[nome];
      if (pos === undefined || pos >= linha.length) return '';
      const valor = linha[pos];
      return valor instanceof Date ? valor : texto_(valor);
    };
    const registro = {};
    lidas.forEach(nome => { registro[nome] = celula(nome); });
    manuais[chaveNf(linha[0], celula('Série'))] = registro;
  });
  return manuais;
}

function statusEntregaInicial(linha) {
  if (linha['Série'].toUpperCase().startsWith('S')) return 'Não se aplica';
  if (STATUS_ABERTOS.indexOf(linha['Status financeiro']) >= 0) return 'A validar';
  return '';
}

function selecionarLinhas(controle, manuais, desde) {
  const limite = data_(desde);
  const aberta = l => STATUS_ABERTOS.indexOf(l['Status financeiro']) >= 0;
  const selecionado = controle.filter(l =>
    (l['Emissão'] && l['Emissão'] >= limite) || aberta(l) || chaveNf(l['NF'], l['Série']) in manuais);
  const tempo = d => (d ? d.getTime() : Infinity);
  const abertas = selecionado.filter(aberta)
    .sort((a, b) => (tempo(a['Vencimento']) - tempo(b['Vencimento'])) || (tempo(a['Emissão']) - tempo(b['Emissão'])));
  const fechadas = selecionado.filter(l => !aberta(l))
    .sort((a, b) => tempo(b['Emissão']) - tempo(a['Emissão']));
  return abertas.concat(fechadas);
}

/** O nº do local de entrega é por cadastro de cliente: o local 4 da Vibra
 * Santo André (Louis Dreyfus) não é o local 4 da Vibra BA (Ferbasa). */
function chaveLocal(cnpj, numero) {
  const digitos = texto_(cnpj).replace(/\D/g, '');
  const n = inteiro_(numero);
  return !digitos || n === null ? null : `${digitos}|${n}`;
}

/** {chave: cliente final} da aba Locais de entrega, mantida pelo time. */
function lerLocaisEntrega(valoresAba) {
  const indice = (valoresAba || []).slice(0, 10).findIndex(l => l && texto_(l[0]) === CABECALHO_LOCAIS[0]);
  if (indice < 0) return {};
  const locais = {};
  valoresAba.slice(indice + 1).forEach(linha => {
    const chave = chaveLocal(linha[0], linha[1]);
    if (chave !== null) locais[chave] = texto_(linha[2]);
  });
  return locais;
}

/** Linhas pra acrescentar na aba Locais de entrega: cada (filial, nº) que
 * aparece nas NFs e ainda não está lá, com as NFs onde apareceu. */
function locaisSemCadastro(tabela, locais) {
  const vistos = {};
  tabela.forEach(l => {
    const chave = chaveLocal(l['Filial Vibra (CNPJ)'], l['Local de entrega (nº)']);
    if (chave === null || chave in locais) return;
    if (!vistos[chave]) vistos[chave] = { cnpj: l['Filial Vibra (CNPJ)'], numero: l['Local de entrega (nº)'], nfs: [] };
    vistos[chave].nfs.push(l['NF']);
  });
  return Object.keys(vistos)
    .map(chave => vistos[chave])
    .sort((a, b) => (a.cnpj.replace(/\D/g, '') < b.cnpj.replace(/\D/g, '') ? -1
      : a.cnpj.replace(/\D/g, '') > b.cnpj.replace(/\D/g, '') ? 1 : a.numero - b.numero))
    .map(v => {
      const nfs = v.nfs.slice().sort((x, y) => (Number(x) || 0) - (Number(y) || 0)).join(', ');
      const origem = v.nfs.length === 1 ? `Preencher: visto na NF ${nfs}` : `Preencher: visto nas NFs ${nfs}`;
      return [`'${v.cnpj}`, v.numero, '', '', origem];
    });
}

function mesclarManuais(selecionado, manuais, locais) {
  locais = locais || {};
  return selecionado.map(original => {
    const linha = Object.assign({}, original);
    COLUNAS_MANUAIS.forEach(nome => { linha[nome] = ''; });
    const anterior = manuais[chaveNf(linha['NF'], linha['Série'])];
    if (!anterior) {
      linha['Status entrega'] = statusEntregaInicial(linha);
    } else {
      COLUNAS_MANUAIS.forEach(nome => { linha[nome] = anterior[nome] === undefined ? '' : anterior[nome]; });
      if (!linha['Nº Pedido Vibra'] && anterior['Nº Pedido Vibra']) {
        linha['Nº Pedido Vibra'] = anterior['Nº Pedido Vibra'];
      }
    }
    const cliente = locais[chaveLocal(linha['Filial Vibra (CNPJ)'], linha['Local de entrega (nº)'])] || '';
    linha[COLUNA_CLIENTE_FINAL] = cliente;
    const digitado = anterior ? anterior[COLUNA_CLIENTE_FINAL_DIGITADO] || '' : '';
    if (digitado && digitado !== cliente) {
      const obs = linha['Obs. Emissão'];
      linha['Obs. Emissão'] = `Cliente final: ${digitado}` + (obs ? ` | ${obs}` : '');
    }
    return linha;
  });
}

function montarTabela(linhasDw, valoresAba, desde, valoresLocais) {
  const manuais = lerPreenchimentoManual(valoresAba);
  return mesclarManuais(selecionarLinhas(montarControle(linhasDw), manuais, desde), manuais,
    lerLocaisEntrega(valoresLocais));
}

/** Linhas A a S prontas pro setValues: texto que a planilha não deve
 * converter (série, pedido, CNPJ, NF de devolução) vai com apóstrofo. A
 * coluna O (cliente final) vai vazia: é fórmula e gravarControle_ pula. */
function linhasParaPlanilha(tabela) {
  const protegido = v => (v ? `'${v}` : '');
  return tabela.map(l => {
    const nf = l['NF'].replace(/\D/g, '');
    const saldo = l['Saldo em aberto (R$)'];
    return [
      nf ? Number(nf) : l['NF'],
      protegido(l['Série']),
      l['Emissão'] || '',
      l['Vencimento'] || '',
      l['Valor (R$)'],
      saldo === null || saldo === 0 ? '' : saldo,
      protegido(l['Nº Pedido Vibra']),
      protegido(l['Filial Vibra (CNPJ)']),
      l['Tipo de NF'],
      l['Material'],
      l['Status financeiro'],
      l['Data pagamento / baixa'] || '',
      protegido(l['NF de devolução']),
      l['Local de entrega (nº)'] === null ? '' : l['Local de entrega (nº)'],
      '',
    ].concat(COLUNAS_MANUAIS.map(nome => l[nome]));
  });
}
