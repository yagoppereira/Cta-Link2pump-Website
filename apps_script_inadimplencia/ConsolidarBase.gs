// ==========================================
// CONTROLES MANUAIS PARALELOS
// ==========================================
const CONFIG_ATRIBUICAO = {
  // Vendedores que SÓ recebem clientes por Inserção Manual (ex.: parcerias).
  // As vendas deles na Base_Comercial e as praças deles na Base_Cidades são
  // ignoradas, e o cliente segue para a próxima regra (normalmente a praça,
  // ou seja, o vendedor regional).
  vendedoresSomenteManual: ["LEANDRO SOARES"],

  // Valores aceitos na coluna "vendedor" da Insercoes_Manuais para mandar o
  // cliente ao vendedor REGIONAL (praça Cidade/UF), ignorando o histórico comercial.
  marcadoresRegional: ["REGIONAL", "GESTAO REGIONAL", "VENDEDOR REGIONAL", "PRACA"],

  // GRANDES CONTAS: o pagante dos aparelhos instalados nos clientes destes vendedores
  // (aba Base_Aparelhos, sincronizada do DW) também passa para eles, se pelo menos
  // `limiteGrandesContas` dos aparelhos que esse pagante paga estiverem nesses clientes.
  // Inserção manual, inserção REGIONAL e carteira de parcerias SEMPRE prevalecem.
  vendedoresGrandesContas: ["MARLON SILVA"],
  limiteGrandesContas: 0.5,

  // Grafias diferentes da mesma cidade entre o CIGAM e a lista de praças
  // ("CIDADE_UF" do CIGAM → "CIDADE_UF" da Base_Cidades, já sem acento e em maiúsculas)
  apelidosCidade: {
    "MOJI MIRIM_SP": "MOGI MIRIM_SP",
    "MOJI DAS CRUZES_SP": "MOGI DAS CRUZES_SP",
    "MOJI GUACU_SP": "MOGI GUACU_SP"
  }
};

function normalizarMarcador_(t) {
  return String(t || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/\u00A0/g, " ")
    .toUpperCase().replace(/\s+/g, " ").trim();
}

// ==========================================
// 1. FUNÇÃO PRINCIPAL DE CONSOLIDAÇÃO
// ==========================================
function consolidarBaseInteligente() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  const wsCigam = ss.getSheetByName("Base_CIGAM");
  const wsComercial = ss.getSheetByName("Base_Comercial");
  const wsManuais = ss.getSheetByName("Insercoes_Manuais");
  const wsClientes = ss.getSheetByName("Base_Clientes");
  const wsCidades = ss.getSheetByName("Base_Cidades");
  const wsVendedores = ss.getSheetByName("Lista_Vendedores");

  if (!wsCigam || !wsComercial || !wsManuais || !wsClientes) {
    alertaSeguro("Erro", "Certifique-se de que as abas 'Base_CIGAM', 'Base_Comercial', 'Insercoes_Manuais' e 'Base_Clientes' existem.");
    return;
  }

  console.log("Baixando dados para consolidação...");

  const dadosCigam = wsCigam.getDataRange().getValues();
  const dadosComercial = wsComercial.getDataRange().getValues();
  const dadosManuais = wsManuais.getDataRange().getValues();
  const dadosCidades = wsCidades ? wsCidades.getDataRange().getValues() : [];
  const dadosVendedores = wsVendedores ? wsVendedores.getDataRange().getValues() : [];

  if (dadosCigam.length <= 1) {
    console.log("Base CIGAM vazia.");
    return;
  }

  const dictVendedoresAtivos = {};
  if (dadosVendedores.length > 1) {
    for (let i = 1; i < dadosVendedores.length; i++) {
      let nomeVendedor = String(dadosVendedores[i][0]).replace(/\u00A0/g, ' ').trim().toUpperCase();
      let valCheck = dadosVendedores[i][2]; // Checkbox na Coluna C
      let estaAtivo = (valCheck === true || String(valCheck).toUpperCase() === "TRUE" || String(valCheck).toUpperCase() === "VERDADEIRO");
      if (nomeVendedor) {
        dictVendedoresAtivos[nomeVendedor] = estaAtivo;
      }
    }
  }

  const dictCidadeUf = {};
  if (dadosCidades.length > 1) {
    for (let i = 1; i < dadosCidades.length; i++) {
      let cidadeRaw = String(dadosCidades[i][1] || dadosCidades[i][0]).replace(/\u00A0/g, ' ').trim();
      let vendedorCidade = String(dadosCidades[i][2]).replace(/\u00A0/g, ' ').trim().toUpperCase();
      let ufCidade = String(dadosCidades[i][3] || "").replace(/\u00A0/g, ' ').trim().toUpperCase();

      if (!ufCidade && cidadeRaw.includes(",")) {
        let partes = cidadeRaw.split(",");
        ufCidade = partes[1].trim().toUpperCase();
      }

      let cidadeLimpa = limparNomeCidade(cidadeRaw);
      let chaveCidade = cidadeLimpa + "_" + ufCidade;
      let chaveSemEspacos = cidadeLimpa.replace(/\s+/g, '') + "_" + ufCidade;

      // Vendedor só-manual (parcerias) não responde por praça
      const ignorarPraca = CONFIG_ATRIBUICAO.vendedoresSomenteManual
        .some(v => normalizarMarcador_(v) === normalizarMarcador_(vendedorCidade));
      if (chaveCidade && vendedorCidade && !ignorarPraca) {
        dictCidadeUf[chaveCidade] = vendedorCidade;
        dictCidadeUf[chaveSemEspacos] = vendedorCidade;
      }
    }
  }

  const cabecalhosCigam = dadosCigam[0].map(c => String(c).trim());
  const idxCnpjCigam = cabecalhosCigam.indexOf("CNPJ/CPF");

  let idxNomeCigam = cabecalhosCigam.indexOf("Nome");
  if (idxNomeCigam === -1) idxNomeCigam = cabecalhosCigam.indexOf("Nome Empresa");
  if (idxNomeCigam === -1) idxNomeCigam = 0;

  if (idxCnpjCigam === -1) {
    alertaSeguro("Erro", "Coluna 'CNPJ/CPF' não foi encontrada na aba Base_CIGAM.");
    return;
  }

  let idxDivisaoCigam = cabecalhosCigam.indexOf("Divisão");
  if (idxDivisaoCigam === -1) idxDivisaoCigam = cabecalhosCigam.indexOf("Divisao");
  if (idxDivisaoCigam === -1) idxDivisaoCigam = 1;

  let idxMunicipioCigam = cabecalhosCigam.indexOf("Município");
  if (idxMunicipioCigam === -1) idxMunicipioCigam = cabecalhosCigam.indexOf("Municipio");
  if (idxMunicipioCigam === -1) idxMunicipioCigam = cabecalhosCigam.indexOf("Cidade");
  if (idxMunicipioCigam === -1) idxMunicipioCigam = 6;

  let idxUfCigam = cabecalhosCigam.indexOf("UF");
  if (idxUfCigam === -1) idxUfCigam = 7;

  const cabecalhosComercial = dadosComercial[0].map(c => String(c).trim());
  let idxCnpjComercial = cabecalhosComercial.indexOf("empresa_cnpj_cpf");
  let idxVendedorComercial = cabecalhosComercial.indexOf("vendedor");

  // ----- CASCATA DE FONTES PARA O NOME DA EMPRESA (Comercial) -----
  // Prioriza colunas de razão social "limpas"; usa 'empresa' (que pode
  // vir com sufixo " - Cidade/UF" colado) apenas como último recurso.
  let idxRazaoPag1 = cabecalhosComercial.indexOf("empresa_pag1_razao_social");
  let idxRazaoLoc1 = cabecalhosComercial.indexOf("empresa_loc1_razao_social");
  let idxEmpresaComercial = cabecalhosComercial.indexOf("empresa");

  if (idxCnpjComercial === -1) idxCnpjComercial = 0;
  if (idxVendedorComercial === -1) idxVendedorComercial = 1;
  if (idxEmpresaComercial === -1) idxEmpresaComercial = 2;

  const somenteManual = new Set(CONFIG_ATRIBUICAO.vendedoresSomenteManual.map(v => normalizarMarcador_(v)));
  const ehSomenteManual = (v) => somenteManual.has(normalizarMarcador_(v));
  const ehRegional = (v) => CONFIG_ATRIBUICAO.marcadoresRegional.indexOf(normalizarMarcador_(v)) !== -1;
  const raizesParceria = new Set();   // raízes que só tinham venda de vendedor só-manual (auditoria)
  const nomesParceria = new Set();

  const dictManualExato = {};
  const dictManualRaiz = {};
  const dictCnpjRaiz = {};
  const dictNomeExato = {};
  const listaNomesParciais = [];

  for (let i = 1; i < dadosManuais.length; i++) {
    let cnpjPuro = limparParaChavePura(dadosManuais[i][0]);
    let vendedor = String(dadosManuais[i][1]).replace(/\u00A0/g, ' ').trim().toUpperCase();
    if (cnpjPuro && vendedor) {
      dictManualExato[cnpjPuro] = vendedor;
      if (cnpjPuro.length >= 8) {
        let raiz = cnpjPuro.substring(0, 8).padStart(8, '0');
        dictManualRaiz[raiz] = vendedor;
      }
    }
  }

  for (let i = 1; i < dadosComercial.length; i++) {
    let vendedor = String(dadosComercial[i][idxVendedorComercial]).replace(/\u00A0/g, ' ').trim().toUpperCase();
    if (!vendedor) continue;

    let cnpjRaiz = extrairRaizCnpj(dadosComercial[i][idxCnpjComercial]);

    // Cascata: usa a primeira fonte de nome preenchida, da mais
    // confiável (razão social pura) para a mais suja ('empresa').
    let nomeBruto = "";
    if (idxRazaoPag1 !== -1 && String(dadosComercial[i][idxRazaoPag1] || "").trim()) {
      nomeBruto = dadosComercial[i][idxRazaoPag1];
    } else if (idxRazaoLoc1 !== -1 && String(dadosComercial[i][idxRazaoLoc1] || "").trim()) {
      nomeBruto = dadosComercial[i][idxRazaoLoc1];
    } else {
      nomeBruto = dadosComercial[i][idxEmpresaComercial];
    }

    let nomeLimpo = limparNomeEmpresa(removerSufixoCidade(nomeBruto));

    // Vendas de vendedor só-manual (parcerias) não definem dono: a gestão é do regional
    if (ehSomenteManual(vendedor)) {
      if (cnpjRaiz) raizesParceria.add(cnpjRaiz);
      if (nomeLimpo) nomesParceria.add(nomeLimpo);
      continue;
    }

    if (cnpjRaiz && !dictCnpjRaiz[cnpjRaiz]) {
      dictCnpjRaiz[cnpjRaiz] = vendedor;
    }
    if (nomeLimpo && !dictNomeExato[nomeLimpo]) {
      dictNomeExato[nomeLimpo] = vendedor;
    }
    // Trava de segurança: Nomes com menos de 5 letras são ignorados na busca parcial para evitar falsos positivos
    if (nomeLimpo && nomeLimpo.length >= 5) {
      listaNomesParciais.push([nomeLimpo, vendedor]);
    }
  }

  console.log("Processando motor de atribuição inteligente com cascata de resgate...");

  const resultadoFinal = [["empresa_cnpj_cpf", "vendedor", "empresa", "UF", "Município", "regra_atribuicao"]];
  const cnpjsProcessados = new Set();
  const contadorRegras = {}; // Diagnóstico: contagem de quantos clientes cada regra resolveu

  for (let i = 1; i < dadosCigam.length; i++) {
    let divisaoRaw = dadosCigam[i][idxDivisaoCigam];
    let divisao = String(divisaoRaw).trim();
    if (divisao.endsWith(".0")) divisao = divisao.substring(0, divisao.length - 2);

    if (divisao !== "10" && divisao !== "90" && divisao !== "11" && divisao !== "12") continue;

    let cnpjOriginal = String(dadosCigam[i][idxCnpjCigam]).trim();
    let cnpjPuro = limparParaChavePura(cnpjOriginal);
    let nomeOriginal = String(dadosCigam[i][idxNomeCigam]).replace(/\u00A0/g, ' ').trim();
    let municipioOriginal = String(dadosCigam[i][idxMunicipioCigam]).replace(/\u00A0/g, ' ').trim();
    let ufOriginal = String(dadosCigam[i][idxUfCigam]).replace(/\u00A0/g, ' ').trim().toUpperCase();

    if (!cnpjPuro || cnpjPuro.length < 11 || cnpjsProcessados.has(cnpjPuro)) continue;
    cnpjsProcessados.add(cnpjPuro);

    let cnpjRaiz = extrairRaizCnpj(cnpjOriginal);
    // Aplica a mesma limpeza de sufixo de cidade por segurança, caso
    // o cadastro do CIGAM também tenha vindo com esse padrão colado.
    let nomeLimpo = limparNomeEmpresa(removerSufixoCidade(nomeOriginal));
    let municipioLimpo = limparNomeCidade(municipioOriginal);

    let chaveCidade = municipioLimpo + "_" + ufOriginal;
    if (CONFIG_ATRIBUICAO.apelidosCidade[chaveCidade]) chaveCidade = CONFIG_ATRIBUICAO.apelidosCidade[chaveCidade];
    let chaveCidadeSemEspacos = chaveCidade.replace(/\s+/g, '');

    let vendedorAtribuido = "NÃO MAPEADO";
    let regraUsada = "Nenhuma";
    let vendedorCandidatoInativo = null;
    let regraInativaOriginal = "";

    const eAtivo = (v) => dictVendedoresAtivos[v] === true;

    let candCidade = dictCidadeUf[chaveCidade] || dictCidadeUf[chaveCidadeSemEspacos];
    const manual = dictManualExato[cnpjPuro] ? { vendedor: dictManualExato[cnpjPuro], tipo: "Exata" }
                 : (cnpjRaiz && dictManualRaiz[cnpjRaiz]) ? { vendedor: dictManualRaiz[cnpjRaiz], tipo: "Raiz" } : null;

    // 1a. INSERÇÃO MANUAL "REGIONAL": força o vendedor da praça (Cidade/UF)
    if (manual && ehRegional(manual.vendedor)) {
      if (candCidade && eAtivo(candCidade)) {
        vendedorAtribuido = candCidade;
        regraUsada = "4. Praça (Regional por inserção)";
      } else {
        console.warn(`Inserção REGIONAL sem vendedor de praça ativo: ${nomeOriginal} (${municipioOriginal}/${ufOriginal})`);
      }
    }
    // 1. REGRA MANUAL
    else if (manual) {
      vendedorAtribuido = manual.vendedor;
      regraUsada = "1. Inserção Manual (" + manual.tipo + ")";
    }
    // 2. COMERCIAL CNPJ RAIZ
    else if (cnpjRaiz && dictCnpjRaiz[cnpjRaiz]) {
      let cand = dictCnpjRaiz[cnpjRaiz];
      if (eAtivo(cand)) {
        vendedorAtribuido = cand;
        regraUsada = "2. Comercial (CNPJ Raiz)";
      } else {
        vendedorCandidatoInativo = cand;
        regraInativaOriginal = "Comercial CNPJ (Vendedor Inativo)";
      }
    }
    // 3. COMERCIAL RAZÃO SOCIAL EXATA
    else if (nomeLimpo && dictNomeExato[nomeLimpo]) {
      let cand = dictNomeExato[nomeLimpo];
      if (eAtivo(cand)) {
        vendedorAtribuido = cand;
        regraUsada = "3. Comercial (Razão Social Exata)";
      } else if (!vendedorCandidatoInativo) {
        vendedorCandidatoInativo = cand;
        regraInativaOriginal = "Comercial Razão (Vendedor Inativo)";
      }
    }
    // 3.1 COMERCIAL RAZÃO SOCIAL PARCIAL
    else if (nomeLimpo) {
      for (let j = 0; j < listaNomesParciais.length; j++) {
        let nomeComercial = listaNomesParciais[j][0];
        let cand = listaNomesParciais[j][1];
        if (nomeLimpo.indexOf(nomeComercial) !== -1) {
          if (eAtivo(cand)) {
            vendedorAtribuido = cand;
            regraUsada = "3. Comercial (Razão Social Parcial)";
            break;
          } else if (!vendedorCandidatoInativo) {
            vendedorCandidatoInativo = cand;
            regraInativaOriginal = "Comercial Parcial (Vendedor Inativo)";
          }
        }
      }
    }

    // 4. RESGATE POR PRAÇA / CIDADE + UF (O Coração da Inteligência Espacial)
    const regionalForcado = manual && ehRegional(manual.vendedor);
    if (vendedorAtribuido === "NÃO MAPEADO" && candCidade && !regionalForcado) {
      if (eAtivo(candCidade)) {
        vendedorAtribuido = candCidade;
        regraUsada = "4. Atribuição por Praça (Cidade/UF)";
      }
    }

    // Auditoria: cliente que só tinha venda de parceria e foi para outra regra
    if (!manual && regraUsada !== "Nenhuma" && !regraUsada.startsWith("2.") &&
        ((cnpjRaiz && raizesParceria.has(cnpjRaiz)) || (nomeLimpo && nomesParceria.has(nomeLimpo)))) {
      regraUsada += " · parceria";
    }

    // 5. RETENÇÃO DE SEGURANÇA INATIVA
    if (vendedorAtribuido === "NÃO MAPEADO" && vendedorCandidatoInativo) {
      vendedorAtribuido = vendedorCandidatoInativo;
      regraUsada = "5. Retido - " + regraInativaOriginal;
    }

    contadorRegras[regraUsada] = (contadorRegras[regraUsada] || 0) + 1;

    // ==========================================
    // 🐛 DEBUGGER: ANÁLISE DE CLIENTES NÃO MAPEADOS
    // ==========================================
    if (regraUsada === "Nenhuma") {
      console.log(`\n=== 🚨 DEBUGGER: FALHA DE ATRIBUIÇÃO ===`);
      console.log(`Empresa: ${nomeOriginal}`);
      console.log(`CNPJ: ${cnpjOriginal} | CNPJ Puro: ${cnpjPuro} | CNPJ Raiz (8): ${cnpjRaiz}`);

      let munCigamBruto = dadosCigam[i][idxMunicipioCigam];
      let ufCigamBruto = dadosCigam[i][idxUfCigam];
      console.log(`1. CIGAM Bruto -> Município: [${munCigamBruto}] | UF: [${ufCigamBruto}]`);
      console.log(`2. Chave Limpa Gerada -> [${chaveCidade}] ou [${chaveCidadeSemEspacos}]`);

      let debugVendedorPraca = dictCidadeUf[chaveCidade] || dictCidadeUf[chaveCidadeSemEspacos];
      if (debugVendedorPraca) {
        console.log(`3. Base_Cidades -> Encontrou vendedor: [${debugVendedorPraca}]`);
        let statusAtivo = dictVendedoresAtivos[debugVendedorPraca];
        console.log(`4. Validação Lista_Vendedores -> O nome [${debugVendedorPraca}] é ativo? R: ${statusAtivo === true ? 'SIM (true)' : statusAtivo === false ? 'NÃO (false)' : 'NÃO ENCONTRADO/UNDEFINED no Dicionário'}`);
      } else {
        console.log(`3. Base_Cidades -> [NENHUM VENDEDOR ENCONTRADO PARA ESTA CHAVE]`);
      }

      console.log(`5. Retenção Inativa -> Houve candidato comercial inativo? R: ${vendedorCandidatoInativo ? 'SIM (' + vendedorCandidatoInativo + ')' : 'NÃO'}`);
      console.log(`========================================\n`);
    }
    // ==========================================

    resultadoFinal.push([cnpjOriginal, vendedorAtribuido, nomeOriginal, ufOriginal, municipioOriginal, regraUsada]);
  }

  // 6. GRANDES CONTAS: pagante dos aparelhos instalados nos clientes do vendedor
  try {
    aplicarGrandesContas_(ss, resultadoFinal, contadorRegras, dictVendedoresAtivos, ehSomenteManual);
  } catch (e) {
    console.warn("Regra de grandes contas não aplicada: " + e.message);
  }

  console.log("=== CONTAGEM POR REGRA ===");
  console.log(JSON.stringify(contadorRegras, null, 2));

  console.log("Salvando dados na aba Base_Clientes...");
  wsClientes.clearContents();
  if (wsClientes.getFilter()) wsClientes.getFilter().remove();

  wsClientes.getRange(1, 1, resultadoFinal.length, 6).setValues(resultadoFinal);

  // Resultado da consolidação na aba Relatório (não interrompe se falhar)
  try {
    const totalClientes = resultadoFinal.length - 1;
    registrarConsolidacaoNoRelatorio_(contadorRegras, totalClientes);
    registrarSaude_("clientes", totalClientes + " clientes", "consolidado em " + agoraFormatado_());
  } catch (e) {
    console.warn("Não foi possível atualizar o Relatório: " + e.message);
  }

  alertaSeguro("🚀 Consolidação Concluída", "A aba 'Base_Clientes' foi gerada com sucesso! Todos os resgates por Cidade/UF ativos foram aplicados.");
}

// ==========================================
// GRANDES CONTAS (2ª passada sobre a Base_Clientes já montada)
// ==========================================
function aplicarGrandesContas_(ss, resultado, contador, dictVendedoresAtivos, ehSomenteManual) {
  const vendedoresGc = CONFIG_ATRIBUICAO.vendedoresGrandesContas.map(normalizarMarcador_);
  if (!vendedoresGc.length) return;
  const aba = ss.getSheetByName("Base_Aparelhos");
  if (!aba || aba.getLastRow() < 2) { console.warn("Base_Aparelhos vazia: regra de grandes contas não aplicada."); return; }

  const dados = aba.getDataRange().getValues();
  const cab = dados[0].map(c => normalizarMarcador_(c).replace(/_/g, " "));
  const iLoc = cab.indexOf("CNPJ LOCAL"), iPag = cab.indexOf("CNPJ PAGANTE"),
        iNomePag = cab.indexOf("NOME PAGANTE"), iEq = cab.indexOf("EQUIPAMENTOS");
  if ([iLoc, iPag, iEq].indexOf(-1) !== -1) { console.warn("Base_Aparelhos sem as colunas esperadas."); return; }

  const doc = v => String(v == null ? "" : v).replace(/\D/g, "").padStart(14, "0");
  const linhaDoDoc = {};
  for (let i = 1; i < resultado.length; i++) linhaDoDoc[doc(resultado[i][0])] = i;
  const vendedorDo = d => linhaDoDoc[d] !== undefined ? normalizarMarcador_(resultado[linhaDoDoc[d]][1]) : null;

  const totalPago = {}, emGrandeConta = {}, nomePagante = {};
  for (let i = 1; i < dados.length; i++) {
    const loc = doc(dados[i][iLoc]), pag = doc(dados[i][iPag]), eq = Number(dados[i][iEq]) || 0;
    if (!eq || pag === "00000000000000") continue;
    totalPago[pag] = (totalPago[pag] || 0) + eq;
    const vLoc = vendedorDo(loc);
    if (loc !== pag && vLoc && vendedoresGc.indexOf(vLoc) !== -1) {
      emGrandeConta[pag] = emGrandeConta[pag] || {};
      emGrandeConta[pag][vLoc] = (emGrandeConta[pag][vLoc] || 0) + eq;
      if (iNomePag !== -1) nomePagante[pag] = dados[i][iNomePag];
    }
  }

  const REGRA = "6. Grande conta (pagante de aparelho)";
  let movidos = 0, acrescentados = 0;
  Object.keys(emGrandeConta).forEach(pag => {
    const [vendedor, eq] = Object.entries(emGrandeConta[pag]).sort((a, b) => b[1] - a[1])[0];
    const participacao = eq / (totalPago[pag] || eq);
    if (participacao < CONFIG_ATRIBUICAO.limiteGrandesContas) return;
    if (dictVendedoresAtivos[vendedor] !== true) return;              // grande conta inativa: não move
    const i = linhaDoDoc[pag];
    if (i === undefined) {                                             // pagante fora das divisões de cliente
      resultado.push([pag, vendedor, String(nomePagante[pag] || ""), "", "", REGRA]);
      contador[REGRA] = (contador[REGRA] || 0) + 1;
      acrescentados++;
      return;
    }
    const linha = resultado[i];
    const regraAtual = String(linha[5]), vendedorAtual = normalizarMarcador_(linha[1]);
    if (vendedoresGc.indexOf(vendedorAtual) !== -1) return;           // já é da grande conta
    if (regraAtual.startsWith("1.")) return;                           // inserção manual vence
    if (regraAtual.indexOf("Regional por inserção") !== -1) return;    // inserção REGIONAL vence
    if (ehSomenteManual(vendedorAtual)) return;                        // carteira de parcerias vence
    contador[regraAtual] = (contador[regraAtual] || 1) - 1;
    if (!contador[regraAtual]) delete contador[regraAtual];
    linha[1] = vendedor;
    linha[5] = REGRA;
    contador[REGRA] = (contador[REGRA] || 0) + 1;
    movidos++;
  });
  console.log(`Grandes contas: ${movidos} pagantes movidos, ${acrescentados} acrescentados.`);
}

// ==========================================
// 2. FUNÇÕES AUXILIARES (HELPERS)
// ==========================================

function limparParaChavePura(valor) {
  if (!valor) return "";
  return String(valor).replace(/\D/g, '');
}

function extrairRaizCnpj(valor) {
  let cnpjPuro = limparParaChavePura(valor);
  if (cnpjPuro.length > 0 && cnpjPuro.length < 14 && cnpjPuro.length >= 8) {
     cnpjPuro = cnpjPuro.padStart(14, '0');
  } else if (cnpjPuro.length < 8) {
      return "";
  }

  if (cnpjPuro.length >= 8) {
    return cnpjPuro.substring(0, 8);
  }
  return "";
}

// Remove sufixos do tipo " - Cidade/UF" colados no final do nome da
// empresa (ex: "CONSTRUTORA LUIZ COSTA LTDA - Cabedelo/PB"), comuns
// na coluna 'empresa' da Base_Comercial.
function removerSufixoCidade(nome) {
  if (!nome) return "";
  return String(nome).replace(/\s*-\s*[^-\/]+\/[A-Za-z]{2}\s*$/, '').trim();
}

function limparNomeEmpresa(nome) {
  if (!nome) return "";
  let limpo = String(nome).trim().toUpperCase();

  limpo = limpo.normalize("NFD").replace(/[\u0300-\u036f]/g, "");

  // Trata separadores (hífen, barra, apóstrofos, aspas) como ESPAÇO
  // antes de remover pontuação, para não colar palavras adjacentes
  // (ex: "PECAS S/A" não pode virar "PECASSA").
  limpo = limpo.replace(/['`´"”\-\/\.]/g, ' ');

  limpo = limpo.replace(/[^\w\s]/gi, '');
  limpo = limpo.replace(/\b(LTDA|SA|S A|ME|EPP|EI|EIRELI|SNC|SS|CIA|FILIAL|MATRIZ|(REGISTRO))\b/g, '').trim();
  limpo = limpo.replace(/\s+/g, ' ');

  return limpo;
}

// Helper para padronizar Municípios lidando com acentos e apóstrofos perfeitamente
function limparNomeCidade(cidade) {
  if (!cidade) return "";
  let limpo = String(cidade).split(",")[0].trim().toUpperCase();
  limpo = limpo.normalize("NFD").replace(/[\u0300-\u036f]/g, "");

  // Substitui apóstrofos e crases por ESPAÇO (Garante que Dias D'ávila vire DIAS D AVILA)
  limpo = limpo.replace(/['`´"”-]/g, ' ');

  limpo = limpo.replace(/[^\w\s]/gi, '');
  limpo = limpo.replace(/\s+/g, ' ').trim();
  return limpo;
}
