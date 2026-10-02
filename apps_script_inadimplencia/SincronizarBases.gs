// =========================================================================
// SINCRONIZAÇÃO AUTOMÁTICA DAS BASES DE ENTRADA
// -------------------------------------------------------------------------
// Substitui o preenchimento manual de duas abas da Planilha Central:
//   • Base_CIGAM   → lida direto do DW (BigQuery, bronze.cigam__empresas)
//   • Base_Cidades → cópia da aba "Cidades" da planilha "Cidades por Vendedor"
//
// Pré-requisito: no editor do Apps Script, em "Serviços" (+), adicionar
// "BigQuery API" (identificador: BigQuery).
// =========================================================================

const CONFIG_SYNC = {
  bqProjeto: "hip-bonito-453017-m2",
  // Mesmas divisões que consolidarBaseInteligente() aceita como cliente.
  divisoesCliente: ["10", "11", "12", "90"],
  idPlanilhaCidades: "13ELKZhNZwTGTaxxOljyyX4UlUThiVfn_IQvjzINyi14",
  abaOrigemCidades: "Cidades",
  minimoLinhasCidades: 100 // Trava anti-esvaziamento da cópia de cidades
};

// ==========================================
// 1. BASE_CIGAM ← DW
// ==========================================
function atualizarBaseCigamDoDW() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const aba = ss.getSheetByName("Base_CIGAM") || ss.insertSheet("Base_CIGAM");

  const divisoes = CONFIG_SYNC.divisoesCliente.map(d => `'${d}'`).join(", ");
  // A ordem das colunas respeita os índices de fallback usados em
  // consolidarBaseInteligente(): Nome=0, Divisão=1, Município=6, UF=7.
  const sql = `
    SELECT
      TRIM(nomeCompleto)        AS nome,
      divisao.codigoDivisao     AS divisao,
      codigo,
      TRIM(fantasia)            AS fantasia,
      TRIM(cnpjCpf)             AS cnpj_cpf,
      ativo,
      TRIM(municipio)           AS municipio,
      UPPER(TRIM(uf))           AS uf
    FROM \`${CONFIG_SYNC.bqProjeto}.bronze.cigam__empresas\`
    WHERE divisao.codigoDivisao IN (${divisoes})
    QUALIFY ROW_NUMBER() OVER (PARTITION BY codigo ORDER BY inserted_at DESC) = 1
    ORDER BY nome
  `;

  const linhas = executarQueryBigQuery(sql);

  // TRAVA: nunca limpa a aba se o DW não devolveu nada
  if (linhas.length === 0) {
    throw new Error("DW não retornou nenhum cliente. Base_CIGAM NÃO foi alterada.");
  }

  const cabecalho = ["Nome", "Divisão", "Código", "Fantasia", "CNPJ/CPF", "Ativo", "Município", "UF"];
  const tabela = [cabecalho].concat(linhas.map(l => l.map(v => v === null ? "" : v)));

  if (aba.getFilter()) aba.getFilter().remove();
  aba.clearContents();
  // Código e CNPJ como texto, para preservar zeros à esquerda
  aba.getRange(1, 3, tabela.length, 1).setNumberFormat("@");
  aba.getRange(1, 5, tabela.length, 1).setNumberFormat("@");
  aba.getRange(1, 1, tabela.length, cabecalho.length).setValues(tabela);
  aba.getRange(1, 1, 1, cabecalho.length).setFontWeight("bold");

  const carimbo = Utilities.formatDate(new Date(), "GMT-3", "dd/MM/yyyy HH:mm");
  aba.getRange(1, cabecalho.length + 2).setValue("Atualizado do DW em: " + carimbo);

  console.log(`Base_CIGAM atualizada do DW: ${linhas.length} clientes.`);
  return linhas.length;
}

// Executa uma query no BigQuery e devolve todas as linhas (com paginação).
function executarQueryBigQuery(sql) {
  const projeto = CONFIG_SYNC.bqProjeto;
  let resp = BigQuery.Jobs.query({ query: sql, useLegacySql: false, timeoutMs: 60000 }, projeto);
  const jobId = resp.jobReference.jobId;
  const location = resp.jobReference.location;

  let tentativas = 0;
  while (!resp.jobComplete) {
    if (++tentativas > 30) throw new Error("Timeout aguardando a query no BigQuery.");
    Utilities.sleep(2000);
    resp = BigQuery.Jobs.getQueryResults(projeto, jobId, { location: location });
  }

  const linhas = [];
  const coletar = r => (r.rows || []).forEach(row => linhas.push(row.f.map(c => c.v)));
  coletar(resp);

  let pageToken = resp.pageToken;
  while (pageToken) {
    const pagina = BigQuery.Jobs.getQueryResults(projeto, jobId, { pageToken: pageToken, location: location });
    coletar(pagina);
    pageToken = pagina.pageToken;
  }
  return linhas;
}

// ==========================================
// 2. BASE_CIDADES ← "Cidades por Vendedor"
// ==========================================
function atualizarBaseCidades() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const abaDestino = ss.getSheetByName("Base_Cidades") || ss.insertSheet("Base_Cidades");

  const abaOrigem = SpreadsheetApp.openById(CONFIG_SYNC.idPlanilhaCidades)
    .getSheetByName(CONFIG_SYNC.abaOrigemCidades);
  if (!abaOrigem) {
    throw new Error(`Aba '${CONFIG_SYNC.abaOrigemCidades}' não encontrada na planilha de cidades.`);
  }

  // Lê só as 4 colunas que a consolidação usa: Cidade, Sem Acento, Vendedor Nome, UF
  const dados = abaOrigem.getRange(1, 1, abaOrigem.getLastRow(), 4).getValues()
    .filter((l, i) => i === 0 || String(l[0]).trim() !== "");

  // TRAVA: confere se o layout da origem continua o esperado
  const cab = dados[0].map(c => String(c).trim().toUpperCase());
  if (!cab[2].includes("VENDEDOR") || cab[3] !== "UF") {
    throw new Error("Layout da aba Cidades mudou (esperado: Cidade | Sem Acento | Vendedor Nome | UF). Base_Cidades NÃO foi alterada.");
  }
  // TRAVA: anti-esvaziamento
  if (dados.length - 1 < CONFIG_SYNC.minimoLinhasCidades) {
    throw new Error(`Origem retornou só ${dados.length - 1} cidades. Base_Cidades NÃO foi alterada.`);
  }

  if (abaDestino.getFilter()) abaDestino.getFilter().remove();
  abaDestino.clearContents();
  abaDestino.getRange(1, 1, dados.length, 4).setValues(dados);
  abaDestino.getRange(1, 1, 1, 4).setFontWeight("bold");

  const carimbo = Utilities.formatDate(new Date(), "GMT-3", "dd/MM/yyyy HH:mm");
  abaDestino.getRange(1, 6).setValue("Copiado de 'Cidades por Vendedor' em: " + carimbo);

  console.log(`Base_Cidades atualizada: ${dados.length - 1} cidades.`);
  return dados.length - 1;
}

// ==========================================
// 3. ORQUESTRADOR
// ==========================================
// Atualiza as duas bases e, na sequência, roda a consolidação da Base_Clientes.
function atualizarBasesEConsolidar() {
  const qtdClientes = atualizarBaseCigamDoDW();
  const qtdCidades = atualizarBaseCidades();
  SpreadsheetApp.flush();
  console.log(`Bases prontas (${qtdClientes} clientes, ${qtdCidades} cidades). Consolidando...`);
  consolidarBaseInteligente();
}

// Alerta que não quebra em gatilhos automáticos (onde getUi() não existe).
// Para rodar consolidarBaseInteligente() por gatilho de tempo, troque nela:
//   "SpreadsheetApp.getUi().alert("           → "alertaSeguro("
//   ", SpreadsheetApp.getUi().ButtonSet.OK)"  → ")"
function alertaSeguro(titulo, mensagem) {
  try {
    const ui = SpreadsheetApp.getUi();
    ui.alert(titulo, mensagem, ui.ButtonSet.OK);
  } catch (e) {
    console.log(`[${titulo}] ${mensagem}`);
  }
}
