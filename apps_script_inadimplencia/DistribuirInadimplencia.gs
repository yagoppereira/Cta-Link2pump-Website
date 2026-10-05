const CONFIG_DISTRIB = {
  pastaId: "1NCmRTqST-ExYklhhUaTaBttj6U70xGKu",
  tentativasLeitura: 3,          // Leituras do arquivo de origem antes de desistir
  esperaEntreLeiturasMs: 30000,  // Pausa entre leituras (arquivo atualiza de hora em hora)
  toleranciaTotalReais: 1.00,    // Diferença aceita entre soma lida e total de referência
  quedaMaximaTitulos: 0.30,      // Aborta se os títulos caírem mais que 30% vs. última execução

  // Distribuidoras identificadas pela RAIZ do CNPJ (a divisão do CIGAM não serve:
  // há distribuidoras na divisão 10 e clientes comuns nas divisões 11/90)
  raizesDistribuidoras: {
    "34274233": "Vibra",
    "33337122": "Ipiranga",
    "33453598": "Raízen",
    "23314594": "Alesat"
  },

  // Mesma curva do campo "Reserva Estimada (R$)" do Looker: (dias/210)² × saldo
  reservaDiasTeto: 210,
  reservaExpoente: 2,

  abaHistoricoResumo: "Historico_Distribuicao",  // 1 linha por dia
  abaHistoricoClientes: "Historico_Clientes",     // 1 linha por cliente por dia

  // "Mensalidade acumulada": meses de emissão distintos em aberto por cliente,
  // contando só produtos recorrentes (comparação pelo início do Tipo de Produto)
  produtosRecorrentes: ["Licenciamentos", "Aluguel"],
  faixasAcumulo: [            // [limite superior de meses, rótulo]
    [1, "1 mês"],
    [3, "2 a 3 meses"],
    [6, "4 a 6 meses"],
    [12, "7 a 12 meses"],
    [Infinity, "Acima de 12 meses"]
  ]
};

function ehProdutoRecorrente_(tipoProduto) {
  const t = String(tipoProduto || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toUpperCase().trim();
  return CONFIG_DISTRIB.produtosRecorrentes.some(p =>
    t.startsWith(p.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toUpperCase()));
}

function faixaAcumulo_(meses) {
  if (!meses) return "Sem mensalidade em aberto";
  return CONFIG_DISTRIB.faixasAcumulo.find(f => meses <= f[0])[1];
}

// Acrescenta a cada linha do Looker: meses de mensalidade em aberto DO CLIENTE
// e a faixa correspondente (valor do cliente repetido em todas as suas linhas,
// para o Looker poder usar como dimensão)
function anexarAcumuloMensalidades_(dadosLookerRows) {
  const cab = dadosLookerRows[0];
  const iCnpj = cab.indexOf("CNPJ"), iProd = cab.indexOf("Tipo de Produto"), iEmis = cab.indexOf("Emissao");
  const mesesPorCliente = {};
  for (let i = 1; i < dadosLookerRows.length; i++) {
    const l = dadosLookerRows[i];
    if (!ehProdutoRecorrente_(l[iProd]) || !(l[iEmis] instanceof Date)) continue;
    const mes = l[iEmis].getFullYear() + "-" + (l[iEmis].getMonth() + 1);
    (mesesPorCliente[l[iCnpj]] = mesesPorCliente[l[iCnpj]] || new Set()).add(mes);
  }
  cab.push("Meses em Aberto", "Faixa de Acúmulo");
  for (let i = 1; i < dadosLookerRows.length; i++) {
    const meses = mesesPorCliente[dadosLookerRows[i][iCnpj]] ? mesesPorCliente[dadosLookerRows[i][iCnpj]].size : 0;
    dadosLookerRows[i].push(meses, faixaAcumulo_(meses));
  }
}

// Reserva estimada de um título (espelha o campo calculado do Looker)
function calcularReserva_(saldo, diasAtraso) {
  const dias = Math.min(Math.max(Number(diasAtraso) || 0, 0), CONFIG_DISTRIB.reservaDiasTeto);
  return Math.pow(dias / CONFIG_DISTRIB.reservaDiasTeto, CONFIG_DISTRIB.reservaExpoente) * saldo;
}

function segmentoDoCnpj_(cnpjLimpo) {
  const raiz = String(cnpjLimpo || "").padStart(14, "0").substring(0, 8);
  const distribuidora = CONFIG_DISTRIB.raizesDistribuidoras[raiz];
  return distribuidora ? "Distribuidora" : "Cliente Final";
}

function distribuirInadimplenciaPorVendedor() {
  const pastaId = CONFIG_DISTRIB.pastaId;
  const ssCentral = SpreadsheetApp.getActiveSpreadsheet();
  const abaRelatorio = ssCentral.getSheetByName("Relatório");
  const abaClientes = ssCentral.getSheetByName("Base_Clientes");
  const abaListaVendedores = ssCentral.getSheetByName("Lista_Vendedores");
 
  if (!abaRelatorio) {
    console.error("Aba 'Relatório' não encontrada.");
    return;
  }

  const hoje = new Date();
  
  // =========================================================================
  // TRAVA 1: ESCUDO DE FIM DE SEMANA (SÁBADO E DOMINGO)
  // =========================================================================
  const diaSemana = hoje.getDay(); // 0 = Domingo, 6 = Sábado
  if (diaSemana === 0 || diaSemana === 6) {
    console.log("Fim de semana (Sábado/Domingo). Execução pulada para preservar a base do Dashboard.");
    abaRelatorio.getRange("B6").setValue("⏸️ Pulado (Fim de Semana)");
    return;
  }
 
  const dataHojeFormatada = Utilities.formatDate(hoje, "GMT-3", "dd/MM/yyyy");
  const diaMesHoje = Utilities.formatDate(hoje, "GMT-3", "dd.MM");
  const diaMesHojeBarra = Utilities.formatDate(hoje, "GMT-3", "dd/MM");
 
  const normalizarTexto = (txt) => {
    if (!txt) return "";
    return String(txt)
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toUpperCase()
      .trim();
  };

  const converterSaldoParaNumero = (val) => {
    if (val === null || val === undefined || val === "") return 0;
    if (typeof val === "number") return val;
    let str = String(val).replace(/[^\d,-.-]/g, "").trim();
    if (!str) return 0;
    if (str.includes(",") && str.includes(".")) {
      str = str.replace(/\./g, "").replace(",", ".");
    } else if (str.includes(",")) {
      str = str.replace(",", ".");
    }
    let num = parseFloat(str);
    return isNaN(num) ? 0 : num;
  };

  // Localiza o cabeçalho e as colunas-chave de uma leitura da aba de origem
  const mapearOrigem = (dados) => {
    let linhaCabecalho = -1;
    for (let r = 0; r < Math.min(10, dados.length); r++) {
      let linhaStr = dados[r].map(c => normalizarTexto(c)).join(" ");
      if ((linhaStr.includes("CNPJ") || linhaStr.includes("CPF")) && (linhaStr.includes("SALDO") || linhaStr.includes("EMPRESA") || linhaStr.includes("NOME"))) {
        linhaCabecalho = r;
        break;
      }
    }
    if (linhaCabecalho === -1) linhaCabecalho = 0;
    const cab = (dados[linhaCabecalho] || []).map(c => normalizarTexto(c));
    return {
      linhaCabecalho: linhaCabecalho,
      cab: cab,
      idxCnpj: cab.findIndex(c => c.includes("CNPJ") || c.includes("CPF")),
      idxSaldo: cab.findIndex(c => c.includes("SALDO") || c.includes("DEVEDOR") || c.includes("VALOR")),
      idxEmpresa: cab.findIndex(c => c.includes("EMPRESA") || c.includes("NOME") || c.includes("RAZAO") || c.includes("CLIENTE"))
    };
  };

  // Resumo de uma leitura: títulos válidos, soma da coluna SALDO e o total
  // de referência que o arquivo traz na linha de cabeçalho (ex.: K1 "R$ 2.423.866,60")
  const resumirLeitura = (dados) => {
    const m = mapearOrigem(dados);
    let titulos = 0, soma = 0;
    for (let i = m.linhaCabecalho + 1; i < dados.length; i++) {
      let saldo = converterSaldoParaNumero(dados[i][m.idxSaldo]);
      soma += saldo;
      let cnpj = String(dados[i][m.idxCnpj] || "").replace(/\D/g, '');
      let nome = String(dados[i][m.idxEmpresa] || "").toUpperCase();
      if (cnpj && saldo > 0 && !nome.includes("TOTAL")) titulos++;
    }
    let referencia = null;
    const linhaCab = dados[m.linhaCabecalho] || [];
    for (let c = linhaCab.length - 1; c > m.idxSaldo; c--) {
      let v = linhaCab[c];
      if (typeof v === "number" || /^\s*R\$/.test(String(v))) {
        referencia = converterSaldoParaNumero(v);
        break;
      }
    }
    return { titulos: titulos, soma: soma, referencia: referencia };
  };

  const dadosClientes = abaClientes ? abaClientes.getDataRange().getValues() : [];
  const mapaClientes = {};

  if (dadosClientes.length > 1) {
    const cabecalhosClientes = dadosClientes[0].map(c => normalizarTexto(c));
    let idxCnpjCliente = cabecalhosClientes.findIndex(c => c.includes("CNPJ") || c.includes("CPF"));
    let idxVendedor = cabecalhosClientes.findIndex(c => c.includes("VENDEDOR"));
    let idxUfCliente = cabecalhosClientes.findIndex(c => c === "UF");
    let idxMunicipioCliente = cabecalhosClientes.findIndex(c => c.includes("MUNICIPIO") || c.includes("CIDADE"));
    let idxRegra = cabecalhosClientes.findIndex(c => c.includes("REGRA"));

    if (idxCnpjCliente === -1) idxCnpjCliente = 0;
    if (idxVendedor === -1) idxVendedor = 1;
    if (idxUfCliente === -1) idxUfCliente = 3;
    if (idxMunicipioCliente === -1) idxMunicipioCliente = 4;
    if (idxRegra === -1) idxRegra = 5;

    for (let i = 1; i < dadosClientes.length; i++) {
      let cnpjOriginal = String(dadosClientes[i][idxCnpjCliente] || "");
      let cnpjLimpo = cnpjOriginal.replace(/\D/g, '');
      let nomeVendedor = String(dadosClientes[i][idxVendedor] || "").trim().toUpperCase();
      let uf = String(dadosClientes[i][idxUfCliente] || "").trim().toUpperCase();
      let municipio = String(dadosClientes[i][idxMunicipioCliente] || "").trim().toUpperCase();
      let regra = String(dadosClientes[i][idxRegra] || "Não Identificado").trim();
     
      if (cnpjLimpo) {
        let registroCliente = { 
          vendedor: nomeVendedor, 
          uf: uf || "SEM UF", 
          municipio: municipio || "SEM MUNICÍPIO", 
          regra: regra 
        };

        mapaClientes[cnpjLimpo] = registroCliente;
        mapaClientes[cnpjLimpo.padStart(14, '0')] = registroCliente;
        mapaClientes[cnpjLimpo.padStart(11, '0')] = registroCliente;
      }
    }
  }

  const dadosVendedores = abaListaVendedores ? abaListaVendedores.getDataRange().getValues() : [];
  const mapaPlanilhas = {};
  const statusVendedores = {}; 
 
  for (let i = 1; i < dadosVendedores.length; i++) {
    let nomeVendedor = String(dadosVendedores[i][0] || "").trim().toUpperCase();
    let idPlanilha = String(dadosVendedores[i][1] || "").trim();
    let estaAtivoAtribuido = dadosVendedores[i][2]; 
   
    if (nomeVendedor) {
      statusVendedores[nomeVendedor] = (estaAtivoAtribuido === true || String(estaAtivoAtribuido).toUpperCase() === "TRUE" || String(estaAtivoAtribuido).toUpperCase() === "VERDADEIRO");

      if (statusVendedores[nomeVendedor] && idPlanilha) {
        if (idPlanilha.includes("/d/")) {
          idPlanilha = idPlanilha.match(/\/d\/([^/]+)/)[1];
        }
        mapaPlanilhas[nomeVendedor] = idPlanilha;
      }
    }
  }

  const pasta = DriveApp.getFolderById(pastaId);
  const queryDrive = `title contains 'INADIMP' and trashed = false`;
  const arquivos = pasta.searchFiles(queryDrive);
  
  let arquivoDeHoje = null;
  let arquivoMaisRecente = null;
  let dataMaisRecente = new Date(0);

  while (arquivos.hasNext()) {
    let arquivo = arquivos.next();
    let nomeNormalizado = normalizarTexto(arquivo.getName());
    let dataUltimaModificacao = arquivo.getLastUpdated();

    if (dataUltimaModificacao > dataMaisRecente) {
      dataMaisRecente = dataUltimaModificacao;
      arquivoMaisRecente = arquivo;
    }

    if (nomeNormalizado.includes(diaMesHoje) || nomeNormalizado.includes(diaMesHojeBarra)) {
      arquivoDeHoje = arquivo;
      break;
    }
  }

  if (!arquivoDeHoje && arquivoMaisRecente) {
    arquivoDeHoje = arquivoMaisRecente;
    console.log("Aviso: Utilizando arquivo mais recente encontrado: " + arquivoDeHoje.getName());
  }

  // =========================================================================
  // TRAVA 2: OBRIGATORIEDADE DO ARQUIVO DO DIA
  // =========================================================================
  if (!arquivoDeHoje) {
    console.log("Nenhum arquivo encontrado para a data de hoje. Execução abortada.");
    abaRelatorio.getRange("B6").setValue("⚠️ Arquivo de hoje não encontrado no Drive");
    registrarSaude_("arquivo", "⚠️ Não encontrado", "nenhum arquivo 'INADIMP' na pasta (" + agoraFormatado_() + ")");
    return;
  }

  // Deixa visível QUAL arquivo foi lido e quando ele foi modificado pela última vez
  const nomeArquivoLido = arquivoDeHoje.getName();
  const modificadoEm = Utilities.formatDate(arquivoDeHoje.getLastUpdated(), "GMT-3", "dd/MM/yyyy HH:mm");
  const ehArquivoDoDia = normalizarTexto(nomeArquivoLido).includes(diaMesHoje) || normalizarTexto(nomeArquivoLido).includes(diaMesHojeBarra);
  registrarSaude_("arquivo", nomeArquivoLido,
    "modificado em " + modificadoEm + (ehArquivoDoDia ? "" : " · ⚠️ nome não tem a data de hoje"));

  try {
    let tempFile = null;
    let tempSpreadsheet = null;
    let mimeTypeOriginal = arquivoDeHoje.getMimeType();

    if (mimeTypeOriginal === MimeType.GOOGLE_SHEETS) {
      tempSpreadsheet = SpreadsheetApp.openById(arquivoDeHoje.getId());
    } else {
      let blob = arquivoDeHoje.getBlob();
      tempFile = Drive.Files.create(
        {name: "Temp_Convert_Router", mimeType: "application/vnd.google-apps.spreadsheet"},
        blob,
        {supportsAllDrives: true}
      );
      tempSpreadsheet = SpreadsheetApp.openById(tempFile.id);
    }
   
    let abaOrigem = tempSpreadsheet.getSheetByName("TÍTULOS UNIFICADOS") || 
                    tempSpreadsheet.getSheetByName("TITULOS UNIFICADOS") || 
                    tempSpreadsheet.getSheets()[0];

    if (!abaOrigem) {
      throw new Error("Aba de dados não encontrada no arquivo do Drive.");
    }

    // OBS: o filtro da aba de origem NÃO é mais removido. getValues() já devolve
    // as linhas ocultas pelo filtro, e o arquivo é vivo (atualizado de hora em
    // hora por outro processo) — o script não deve alterá-lo.

    // =========================================================================
    // TRAVA 4: LEITURA CONFERIDA (proteção contra ler no meio da atualização)
    // -------------------------------------------------------------------------
    // A leitura só é aceita quando:
    //   a) a soma da coluna SALDO bate com o total de referência do arquivo, e
    //   b) os títulos não caíram mais que o limite vs. a última execução.
    // Senão espera e lê de novo. Se duas leituras seguidas derem idênticas
    // (arquivo parado) e só o total divergir, segue com aviso.
    // =========================================================================
    const titulosAnteriores = Number(abaRelatorio.getRange("B9").getValue()) || 0;
    let dadosMaster = null;
    let resumo = null;
    let resumoAnterior = null;
    let statusConferencia = "";

    for (let tentativa = 1; tentativa <= CONFIG_DISTRIB.tentativasLeitura; tentativa++) {
      let leitura = abaOrigem.getDataRange().getValues();
      let r = resumirLeitura(leitura);

      let totalOk = r.referencia !== null && Math.abs(r.soma - r.referencia) <= CONFIG_DISTRIB.toleranciaTotalReais;
      let quedaOk = !titulosAnteriores || r.titulos >= titulosAnteriores * (1 - CONFIG_DISTRIB.quedaMaximaTitulos);
      let estavel = resumoAnterior && resumoAnterior.titulos === r.titulos && Math.abs(resumoAnterior.soma - r.soma) < 0.01;

      if (totalOk && quedaOk) {
        dadosMaster = leitura; resumo = r;
        statusConferencia = "✅ Conferido";
        break;
      }
      if (estavel && quedaOk) {
        dadosMaster = leitura; resumo = r;
        statusConferencia = r.referencia === null ? "⚠️ Sem total de referência" : "⚠️ Soma difere do total do arquivo";
        break;
      }
      console.warn(`Leitura ${tentativa}: ${r.titulos} títulos, soma ${formatarReais_(r.soma)}, referência ${r.referencia === null ? "-" : formatarReais_(r.referencia)}. Aguardando nova leitura...`);
      resumoAnterior = r;
      if (tentativa < CONFIG_DISTRIB.tentativasLeitura) Utilities.sleep(CONFIG_DISTRIB.esperaEntreLeiturasMs);
    }

    if (!dadosMaster) {
      let ultimo = resumoAnterior || { titulos: 0, soma: 0 };
      registrarSaude_("conferencia", "❌ Abortado",
        `origem instável ou com queda > ${CONFIG_DISTRIB.quedaMaximaTitulos * 100}% (${titulosAnteriores} → ${ultimo.titulos} títulos) · ${agoraFormatado_()}`);
      throw new Error("Arquivo de origem não passou na conferência (pode estar sendo atualizado). Nada foi alterado.");
    }

    registrarSaude_("conferencia", statusConferencia,
      `lido ${formatarReais_(resumo.soma)}` + (resumo.referencia !== null ? ` · arquivo ${formatarReais_(resumo.referencia)}` : "") +
      ` · ${resumo.titulos} títulos`);

    const mapaOrigem = mapearOrigem(dadosMaster);
    let linhaCabecalhoIdx = mapaOrigem.linhaCabecalho;
    const cabecalhoMaster = mapaOrigem.cab;

    let idxCnpjMaster = mapaOrigem.idxCnpj;
    let idxSaldoMaster = mapaOrigem.idxSaldo;
    let idxEmpresaMaster = mapaOrigem.idxEmpresa;
    let idxDiasMaster = cabecalhoMaster.findIndex(c => c.includes("DIAS") || c.includes("ATRASO"));
    let idxDescricaoMaster = cabecalhoMaster.findIndex(c => c.includes("DESCRICAO") || c.includes("CONTA") || c.includes("PRODUTO"));
    let idxEmissaoMaster = cabecalhoMaster.findIndex(c => c.includes("EMISSAO") || c.includes("EMIS"));
    let idxVencimentoMaster = cabecalhoMaster.findIndex(c => c.includes("VENCIMENTO") || c.includes("VENC"));
    let idxFaturaMaster = cabecalhoMaster.findIndex(c => c.includes("FATURA") || c.includes("TITULO") || c.includes("DUPLICATA"));

    if (idxDescricaoMaster === -1) idxDescricaoMaster = 7;
    if (idxEmissaoMaster === -1) idxEmissaoMaster = 1;
    if (idxVencimentoMaster === -1) idxVencimentoMaster = 2;
    if (idxFaturaMaster === -1) idxFaturaMaster = 4;
    if (idxDiasMaster === -1) idxDiasMaster = 5;

    if (idxCnpjMaster === -1 || idxSaldoMaster === -1) {
      throw new Error("Colunas 'CNPJ/CPF' ou 'SALDO' não localizadas.");
    }

    const pacotesPorVendedor = {};
    Object.keys(mapaPlanilhas).forEach(v => pacotesPorVendedor[v] = [dadosMaster[linhaCabecalhoIdx]]);

    const deparaRegiao = {
      "SP": "Sudeste", "RJ": "Sudeste", "MG": "Sudeste", "ES": "Sudeste",
      "PR": "Sul", "SC": "Sul", "RS": "Sul",
      "MT": "Centro-Oeste", "MS": "Centro-Oeste", "GO": "Centro-Oeste", "DF": "Centro-Oeste",
      "BA": "Nordeste", "PE": "Nordeste", "CE": "Nordeste", "RN": "Nordeste", "PB": "Nordeste", "AL": "Nordeste", "SE": "Nordeste", "MA": "Nordeste", "PI": "Nordeste",
      "AM": "Norte", "PA": "Norte", "RO": "Norte", "TO": "Norte", "AC": "Norte", "RR": "Norte", "AP": "Norte",
      "NÃO MAPEADO": "Sem Região", "SEM UF": "Sem Região"
    };

    // ESTRUTURA OFICIAL EXATA DE 13 COLUNAS PARA O LOOKER STUDIO
    const dadosLookerRows = [[
      "CNPJ", "Cliente", "Vendedor", "UF", "Município", "Regiao",
      "Tipo de Produto", "Emissao", "Vencimento", "Fatura",
      "Saldo", "Dias Atraso", "Data Atualizacao", "Segmento"
    ]];
   
    // Devolve Date (não texto) para o Looker reconhecer o campo como data
    const formatarDataLimpa = (val) => {
      if (!val) return "";
      if (val instanceof Date) return val;
      const m = String(val).trim().match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
      if (m) return new Date(+m[3], +m[2] - 1, +m[1]);
      return String(val).trim();
    };

    let logTotalProcessado = 0;
    let logIgnorados = 0;
    let logDistribuidoAtivos = 0;
    let logBarradoInativos = 0;
    let logOrfaos = 0;
    let logAcertoCnpjExato = 0;
    let logAcertoCnpjRaiz = 0;
    let logAcertoRazaoSocial = 0;
    let logAcertoPraca = 0;

    // Mesmos indicadores, em R$
    const valor = { total: 0, distribuido: 0, retido: 0, orfao: 0, exato: 0, raiz: 0, razao: 0, praca: 0 };
    // Desempenho por vendedor e clientes sem dono
    const porVendedor = {};
    const semDono = {};

    for (let i = linhaCabecalhoIdx + 1; i < dadosMaster.length; i++) {
      let linha = dadosMaster[i];
      let cnpjMasterLimpo = String(linha[idxCnpjMaster] || "").replace(/\D/g, '');
      let clienteNome = String(linha[idxEmpresaMaster] || "Desconhecido").trim().toUpperCase();
      let saldo = converterSaldoParaNumero(linha[idxSaldoMaster]);

      if (!cnpjMasterLimpo || clienteNome.includes("TOTAL") || clienteNome.includes("SUBTOTAL") || clienteNome === "" || saldo <= 0) {
        logIgnorados++;
        continue;
      }

      logTotalProcessado++;
      valor.total += saldo;
      
      let diasAtraso = Number(linha[idxDiasMaster]) || 0;
      let tipoProduto = String(linha[idxDescricaoMaster] || "Não Identificado").trim();
      let emissao = formatarDataLimpa(linha[idxEmissaoMaster]);
      let vencimento = formatarDataLimpa(linha[idxVencimentoMaster]);
      let fatura = String(linha[idxFaturaMaster] || "").trim();
      
      let vendedorFinal = "NÃO MAPEADO";
      let ufDoCliente = "SEM UF";
      let municipioDoCliente = "SEM MUNICÍPIO";
      let regraUtilizada = "Nenhuma";
      let statusLooker = "Órfão (Não Mapeado)";
      let vendedorOriginal = "";
     
      let matchCliente = mapaClientes[cnpjMasterLimpo] || 
                         mapaClientes[cnpjMasterLimpo.padStart(14, '0')] || 
                         mapaClientes[cnpjMasterLimpo.padStart(11, '0')];
      
      // Cliente consolidado como "NÃO MAPEADO" continua órfão (antes caía em "Retido")
      if (matchCliente && matchCliente.vendedor && matchCliente.vendedor !== "NÃO MAPEADO") {
        vendedorFinal = matchCliente.vendedor;
        ufDoCliente = matchCliente.uf;
        municipioDoCliente = matchCliente.municipio;
        regraUtilizada = matchCliente.regra;

        if (statusVendedores[vendedorFinal] === true && pacotesPorVendedor[vendedorFinal]) {
          statusLooker = "Atribuído (Ativo)";
        } else {
          statusLooker = "Retido (Vendedor Inativo)";
          vendedorOriginal = vendedorFinal;
          vendedorFinal = "NÃO MAPEADO";
        }
      }

      let regiao = deparaRegiao[ufDoCliente] || "Outros/Sem UF";

      if (statusLooker === "Atribuído (Ativo)") {
        pacotesPorVendedor[vendedorFinal].push(linha);
        logDistribuidoAtivos++;
        valor.distribuido += saldo;

        if (!porVendedor[vendedorFinal]) porVendedor[vendedorFinal] = { titulos: 0, clientes: new Set(), saldo: 0 };
        porVendedor[vendedorFinal].titulos++;
        porVendedor[vendedorFinal].clientes.add(cnpjMasterLimpo);
        porVendedor[vendedorFinal].saldo += saldo;

        if (regraUtilizada.includes("Manual") || regraUtilizada.includes("Exata") || regraUtilizada.includes("Exato")) {
          logAcertoCnpjExato++;
          valor.exato += saldo;
        } else if (regraUtilizada.includes("Raiz")) {
          logAcertoCnpjRaiz++;
          valor.raiz += saldo;
        } else if (regraUtilizada.includes("Razão Social") || regraUtilizada.includes("Parcial")) {
          logAcertoRazaoSocial++;
          valor.razao += saldo;
        } else if (regraUtilizada.includes("Praça") || regraUtilizada.includes("Cidade")) {
          logAcertoPraca++;
          valor.praca += saldo;
        }
      } else {
        if (statusLooker === "Retido (Vendedor Inativo)") {
          logBarradoInativos++;
          valor.retido += saldo;
        } else {
          logOrfaos++;
          valor.orfao += saldo;
        }
        if (!semDono[cnpjMasterLimpo]) {
          semDono[cnpjMasterLimpo] = {
            nome: clienteNome, saldo: 0, titulos: 0,
            situacao: vendedorOriginal ? "Retido — " + vendedorOriginal + " inativo" : "Órfão — sem regra"
          };
        }
        semDono[cnpjMasterLimpo].saldo += saldo;
        semDono[cnpjMasterLimpo].titulos++;
      }

      dadosLookerRows.push([
        cnpjMasterLimpo,
        clienteNome,
        vendedorFinal,
        ufDoCliente,
        municipioDoCliente,
        regiao,
        tipoProduto,
        emissao,
        vencimento,
        fatura,
        saldo,
        diasAtraso,  
        dataHojeFormatada,
        segmentoDoCnpj_(cnpjMasterLimpo)
      ]);
    }

    anexarAcumuloMensalidades_(dadosLookerRows);

    // =========================================================================
    // TRAVA 3: PROTEÇÃO DE INTEGRIDADE (ANTI-ESVAZIAMENTO)
    // =========================================================================
    if (dadosLookerRows.length <= 1) {
      throw new Error("Nenhum dado válido foi processado no arquivo de hoje. A base do Looker e dos vendedores NÃO foi alterada por segurança.");
    }
   
    let agoraHora = Utilities.formatDate(new Date(), "GMT-3", "HH:mm");
    const statusPlanilhaVendedor = {};

    Object.keys(pacotesPorVendedor).forEach(vendedor => {
      let urlPlanilha = mapaPlanilhas[vendedor];
      if (!urlPlanilha) return;
      if (pacotesPorVendedor[vendedor].length <= 1) {
        statusPlanilhaVendedor[vendedor] = "⏭️ Sem títulos hoje (planilha não alterada)";
        return;
      }
     
      try {
        let ssDestino = urlPlanilha.includes("http") ? SpreadsheetApp.openByUrl(urlPlanilha) : SpreadsheetApp.openById(urlPlanilha);
        let abaDadosDestino = ssDestino.getSheetByName("Dados");
        
        if (abaDadosDestino) {
          let novosDados = pacotesPorVendedor[vendedor];
          let numLinhas = novosDados.length;
          let numColunas = novosDados[0].length;
          
          abaDadosDestino.clear();
          abaDadosDestino.getRange(1, 1, numLinhas, numColunas).setValues(novosDados);
          statusPlanilhaVendedor[vendedor] = "✅ Atualizada";
        } else {
          statusPlanilhaVendedor[vendedor] = "❌ Aba 'Dados' não existe";
        }
      } catch (e) {
        statusPlanilhaVendedor[vendedor] = "❌ " + e.message;
        console.error("Erro na atualização do vendedor " + vendedor + ": " + e.message);
      }
    });
   
    if (tempFile) {
      try { Drive.Files.remove(tempFile.id); } catch (errClean) {}
    }

    abaRelatorio.getRange("B6").setValue(dataHojeFormatada + " às " + agoraHora);
    abaRelatorio.getRange("B9").setValue(logTotalProcessado);
    abaRelatorio.getRange("B10").setValue(logIgnorados);
    abaRelatorio.getRange("B13").setValue(logDistribuidoAtivos);
    abaRelatorio.getRange("B14").setValue(logBarradoInativos);
    abaRelatorio.getRange("B15").setValue(logOrfaos);
    
    abaRelatorio.getRange("B18").setValue(logAcertoCnpjExato);
    abaRelatorio.getRange("B19").setValue(logAcertoCnpjRaiz);
    abaRelatorio.getRange("B20").setValue(logAcertoRazaoSocial);
    abaRelatorio.getRange("B21").setValue(logAcertoPraca);

    // Coluna C: os mesmos indicadores em R$
    abaRelatorio.getRange("C8").setValue("Valor (R$)").setFontWeight("bold");
    abaRelatorio.getRange("C9").setValue(valor.total);
    abaRelatorio.getRange("C13:C15").setValues([[valor.distribuido], [valor.retido], [valor.orfao]]);
    abaRelatorio.getRange("C18:C21").setValues([[valor.exato], [valor.raiz], [valor.razao], [valor.praca]]);
    abaRelatorio.getRangeList(["C9", "C13:C15", "C18:C21"]).setNumberFormat("R$ #,##0.00");

    // Top 10 clientes sem dono (órfãos + retidos), por saldo
    const linhasSemDono = Object.keys(semDono)
      .map(cnpj => [cnpj, semDono[cnpj].nome, semDono[cnpj].saldo, semDono[cnpj].titulos, semDono[cnpj].situacao])
      .sort((a, b) => b[2] - a[2]);
    escreverTabela_(abaRelatorio, RELATORIO.semDono, "TOP 10 CLIENTES SEM DONO (por saldo)",
      ["CNPJ", "Cliente", "Saldo (R$)", "Títulos", "Situação"],
      linhasSemDono.length ? linhasSemDono : [["—", "Nenhum cliente sem dono 🎉", "", "", ""]]);
    abaRelatorio.getRange(RELATORIO.semDono.primeiraLinha, 3, RELATORIO.semDono.max, 1).setNumberFormat("R$ #,##0.00");

    // Desempenho por vendedor (todas as carteiras ativas com planilha)
    const linhasVendedores = Object.keys(mapaPlanilhas)
      .map(v => {
        let p = porVendedor[v] || { titulos: 0, clientes: new Set(), saldo: 0 };
        return [v, p.titulos, p.clientes.size, p.saldo, statusPlanilhaVendedor[v] || "-"];
      })
      .sort((a, b) => b[3] - a[3]);
    escreverTabela_(abaRelatorio, RELATORIO.vendedores, "DESEMPENHO POR VENDEDOR",
      ["Vendedor", "Títulos", "Clientes", "Saldo (R$)", "Status da planilha"], linhasVendedores);
    abaRelatorio.getRange(RELATORIO.vendedores.primeiraLinha, 4, RELATORIO.vendedores.max, 1).setNumberFormat("R$ #,##0.00");

    let abaLooker = ssCentral.getSheetByName("Dados_Looker");
    if (!abaLooker) {
      abaLooker = ssCentral.insertSheet("Dados_Looker");
    }
    
    if (abaLooker.getFilter()) {
      abaLooker.getFilter().remove();
    }
    
    abaLooker.clearContents(); 
    abaLooker.getRange(1, 1, dadosLookerRows.length, dadosLookerRows[0].length).setValues(dadosLookerRows);
   
    abaLooker.getRange(1, 1, 1, dadosLookerRows[0].length).setFontWeight("bold").setBackground("#cfe2f3");
   
    if (dadosLookerRows.length > 1) {
      let qtdLinhas = dadosLookerRows.length - 1;
      // Coluna 11: Saldo
      abaLooker.getRange(2, 11, qtdLinhas, 1).setNumberFormat("R$ #,##0.00");
      // Colunas 8 e 9: Emissão e Vencimento
      abaLooker.getRange(2, 8, qtdLinhas, 2).setNumberFormat("dd/mm/yyyy");
    }

    // Históricos (não interrompem a distribuição se falharem)
    try {
      registrarHistorico_(ssCentral, dadosLookerRows, {
        distribuido: valor.distribuido, retido: valor.retido, orfao: valor.orfao,
        arquivo: nomeArquivoLido
      });
    } catch (errHist) {
      console.warn("Histórico não gravado: " + errHist.message);
    }

    SpreadsheetApp.flush();
    console.log("Sucesso total! Processados: " + logTotalProcessado + " | Atribuídos: " + logDistribuidoAtivos);

  } catch (e) {
    console.error("Erro na execução: " + e.stack);
    abaRelatorio.getRange("B6").setValue("❌ Erro: " + e.message);
  }
}

// =========================================================================
// HISTÓRICO — base para tendência no Looker e calibração futura da curva
// -------------------------------------------------------------------------
// Historico_Distribuicao: 1 linha por dia (resumo da carteira)
// Historico_Clientes:     1 linha por cliente por dia
// Rodar de novo no mesmo dia SUBSTITUI as linhas daquele dia.
// =========================================================================
function registrarHistorico_(ss, dadosLookerRows, extras) {
  const cab = dadosLookerRows[0];
  const idx = nome => cab.indexOf(nome);
  const iCnpj = idx("CNPJ"), iCliente = idx("Cliente"), iVend = idx("Vendedor"),
        iSaldo = idx("Saldo"), iDias = idx("Dias Atraso"), iSeg = idx("Segmento"), iMeses = idx("Meses em Aberto");

  const hoje = new Date();
  const dataHoje = new Date(hoje.getFullYear(), hoje.getMonth(), hoje.getDate());
  const chaveHoje = Utilities.formatDate(dataHoje, "GMT-3", "yyyy-MM-dd");

  const faixas = { "1-30": 0, "31-60": 0, "61-90": 0, ">90": 0 };
  const segmentos = { "Distribuidora": 0, "Cliente Final": 0 };
  const clientes = {};
  let saldoTotal = 0, reservaTotal = 0;

  for (let i = 1; i < dadosLookerRows.length; i++) {
    const l = dadosLookerRows[i];
    const saldo = Number(l[iSaldo]) || 0;
    const dias = Number(l[iDias]) || 0;
    const reserva = calcularReserva_(saldo, dias);
    saldoTotal += saldo;
    reservaTotal += reserva;

    if (dias <= 30) faixas["1-30"] += saldo;
    else if (dias <= 60) faixas["31-60"] += saldo;
    else if (dias <= 90) faixas["61-90"] += saldo;
    else faixas[">90"] += saldo;
    segmentos[l[iSeg]] = (segmentos[l[iSeg]] || 0) + saldo;

    const c = clientes[l[iCnpj]] || (clientes[l[iCnpj]] = {
      cliente: l[iCliente], vendedor: l[iVend], segmento: l[iSeg], titulos: 0, saldo: 0, reserva: 0, maiorAtraso: 0
    });
    c.titulos++;
    c.saldo += saldo;
    c.reserva += reserva;
    c.maiorAtraso = Math.max(c.maiorAtraso, dias);
    c.mesesEmAberto = iMeses === -1 ? "" : l[iMeses];
  }

  const qtdClientes = Object.keys(clientes).length;
  const resumo = [[
    dataHoje, dadosLookerRows.length - 1, qtdClientes, saldoTotal, reservaTotal,
    saldoTotal ? reservaTotal / saldoTotal : 0,
    faixas["1-30"], faixas["31-60"], faixas["61-90"], faixas[">90"],
    segmentos["Distribuidora"], segmentos["Cliente Final"],
    extras.distribuido, extras.retido, extras.orfao, extras.arquivo
  ]];
  const cabResumo = ["Data", "Títulos", "Clientes", "Saldo Total", "Reserva Estimada", "Índice de Risco",
    "Saldo 1-30", "Saldo 31-60", "Saldo 61-90", "Saldo >90",
    "Saldo Distribuidoras", "Saldo Cliente Final", "Distribuído", "Retido", "Órfão", "Arquivo Lido"];
  gravarDiaNoHistorico_(ss, CONFIG_DISTRIB.abaHistoricoResumo, cabResumo, resumo, chaveHoje);

  const linhasClientes = Object.keys(clientes).map(cnpj => {
    const c = clientes[cnpj];
    return [dataHoje, cnpj, c.cliente, c.vendedor, c.segmento, c.titulos, c.saldo, c.reserva, c.maiorAtraso, c.mesesEmAberto];
  });
  const cabClientes = ["Data", "CNPJ", "Cliente", "Vendedor", "Segmento", "Títulos", "Saldo", "Reserva Estimada", "Maior Atraso (dias)", "Meses em Aberto"];
  gravarDiaNoHistorico_(ss, CONFIG_DISTRIB.abaHistoricoClientes, cabClientes, linhasClientes, chaveHoje);

  console.log(`Histórico gravado: ${qtdClientes} clientes, índice de risco ${(saldoTotal ? reservaTotal / saldoTotal * 100 : 0).toFixed(2)}%.`);
}

// Acrescenta as linhas do dia ao fim da aba; se o dia já existe (as linhas do
// dia ficam sempre no fim), apaga e regrava.
function gravarDiaNoHistorico_(ss, nomeAba, cabecalho, linhas, chaveDia) {
  let aba = ss.getSheetByName(nomeAba);
  if (!aba) {
    aba = ss.insertSheet(nomeAba);
    aba.getRange(1, 1, 1, cabecalho.length).setValues([cabecalho]).setFontWeight("bold").setBackground("#cfe2f3");
    aba.setFrozenRows(1);
  } else {
    aba.getRange(1, 1, 1, cabecalho.length).setValues([cabecalho]).setFontWeight("bold").setBackground("#cfe2f3");
  }

  const ultima = aba.getLastRow();
  if (ultima > 1) {
    const datas = aba.getRange(2, 1, ultima - 1, 1).getValues();
    let primeiraDoDia = -1;
    for (let i = datas.length - 1; i >= 0; i--) {
      const d = datas[i][0];
      const chave = d instanceof Date ? Utilities.formatDate(d, "GMT-3", "yyyy-MM-dd") : "";
      if (chave === chaveDia) primeiraDoDia = i; else break;
    }
    if (primeiraDoDia !== -1) aba.deleteRows(primeiraDoDia + 2, datas.length - primeiraDoDia);
  }

  if (!linhas.length) return;
  const inicio = aba.getLastRow() + 1;
  aba.getRange(inicio, 1, linhas.length, cabecalho.length).setValues(linhas);
  aba.getRange(inicio, 1, linhas.length, 1).setNumberFormat("dd/mm/yyyy");
}
