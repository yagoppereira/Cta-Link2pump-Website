// =========================================================================
// DIAGNÓSTICO DO SISTEMA
// -------------------------------------------------------------------------
// Confere estrutura, versões dos scripts, acessos, gatilhos, frescor e
// consistência das bases. Só LÊ — o único lugar onde escreve é a aba
// "Diagnóstico". Substitui o antigo debugger.gs / aba DEBUG_LOG.
// =========================================================================

function diagnosticarSistema() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const resultados = []; // [Área, Verificação, Status, Detalhe]
  const ok = (area, item, detalhe) => resultados.push([area, item, "✅", detalhe || ""]);
  const alerta = (area, item, detalhe) => resultados.push([area, item, "⚠️", detalhe || ""]);
  const erro = (area, item, detalhe) => resultados.push([area, item, "❌", detalhe || ""]);
  const testar = (area, item, fn) => {
    try { fn(); } catch (e) { erro(area, item, e.message); }
  };
  const normalizar = t => String(t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase().trim();

  // ---------------------------------------------------------------- 1. ABAS
  const abasObrigatorias = ["Relatório", "Dados_Looker", "Insercoes_Manuais", "Base_CIGAM",
    "Base_Cidades", "Base_Comercial", "Base_Clientes", "Lista_Vendedores"];
  abasObrigatorias.forEach(nome => {
    const aba = ss.getSheetByName(nome);
    if (aba) ok("Abas", nome, (aba.getLastRow() - 1) + " linhas de dados");
    else erro("Abas", nome, "aba não encontrada");
  });
  if (ss.getSheetByName("DEBUG_LOG")) alerta("Abas", "DEBUG_LOG", "aba antiga do debugger — pode ser excluída");

  // ------------------------------------------------- 2. SCRIPTS E VERSÕES
  // Cada função precisa existir E conter o trecho que identifica a versão atual
  const versoes = [
    ["distribuirInadimplenciaPorVendedor", "resumirLeitura", "Distribuição de Inadimplência.gs"],
    ["consolidarBaseInteligente", "registrarConsolidacaoNoRelatorio_", "Cruzamento de Bases/Atribuição Manual.gs"],
    ["atualizarBaseCigamDoDW", "registrarSaude_", "Cruzamento de Bases/Sincronizar Bases.gs"],
    ["atualizarBaseCidades", "registrarSaude_", "Cruzamento de Bases/Sincronizar Bases.gs"],
    ["atualizarBasesEConsolidar", "consolidarBaseInteligente", "Cruzamento de Bases/Sincronizar Bases.gs"],
    ["registrarSaude_", "ROTULOS_SAUDE", "Relatório.gs"],
    ["onOpen", "atualizarBasesEConsolidar", "Menu Automações.gs"],
    ["sincronizarEValidarVendedores", "", "Validação URL/Vendedor.gs"],
    ["gerarPlanilhasVendedoresFaltantes", "", "Criação de Planilhas.gs"],
    ["aplicarPatchLayoutVendedores", "", "Atualização Layout Planilha.gs"]
  ];
  const escopo = globalThis;
  versoes.forEach(([fn, marcador, arquivo]) => {
    const f = escopo[fn];
    if (typeof f !== "function") return erro("Scripts", fn + "()", "não existe — falta o arquivo " + arquivo);
    if (marcador && !f.toString().includes(marcador)) return alerta("Scripts", fn + "()", "versão antiga — cole de novo " + arquivo + " do repositório");
    ok("Scripts", fn + "()", arquivo);
  });

  // Espaço inseparável que virou espaço comum na colagem (regex / / quebrada)
  if (typeof escopo.consolidarBaseInteligente === "function") {
    const fonte = escopo.consolidarBaseInteligente.toString();
    if (fonte.includes(".replace(/ /g, ' ')")) {
      alerta("Scripts", "Regex de espaço inseparável", "aparece como /\\ /g comum em consolidarBaseInteligente — cole a versão com \\u00A0");
    } else {
      ok("Scripts", "Regex de espaço inseparável", "íntegra");
    }
  }

  // ----------------------------------------------- 3. SERVIÇOS E ACESSOS
  testar("Acessos", "BigQuery (DW)", () => {
    if (typeof BigQuery === "undefined") throw new Error("serviço avançado BigQuery não habilitado");
    const r = BigQuery.Jobs.query({ query: "SELECT 1", useLegacySql: false }, CONFIG_SYNC.bqProjeto);
    if (!r.jobComplete) throw new Error("query de teste não completou");
    ok("Acessos", "BigQuery (DW)", "consulta de teste OK no projeto " + CONFIG_SYNC.bqProjeto);
  });
  testar("Acessos", "Drive API (serviço avançado)", () => {
    if (typeof Drive === "undefined") throw new Error("serviço avançado Drive não habilitado (necessário só para arquivos .xlsx)");
    ok("Acessos", "Drive API (serviço avançado)", "habilitado");
  });
  testar("Acessos", "Planilha 'Cidades por Vendedor'", () => {
    const aba = SpreadsheetApp.openById(CONFIG_SYNC.idPlanilhaCidades).getSheetByName(CONFIG_SYNC.abaOrigemCidades);
    if (!aba) throw new Error("aba '" + CONFIG_SYNC.abaOrigemCidades + "' não encontrada");
    ok("Acessos", "Planilha 'Cidades por Vendedor'", (aba.getLastRow() - 1) + " cidades na origem");
  });
  testar("Acessos", "Arquivo de inadimplência", () => {
    const arquivos = DriveApp.getFolderById(CONFIG_DISTRIB.pastaId).searchFiles("title contains 'INADIMP' and trashed = false");
    const lista = [];
    while (arquivos.hasNext()) lista.push(arquivos.next());
    if (!lista.length) throw new Error("nenhum arquivo 'INADIMP' na pasta");
    const hojeTxt = Utilities.formatDate(new Date(), "GMT-3", "dd.MM");
    const arq = lista.sort((a, b) => b.getLastUpdated() - a.getLastUpdated())[0];
    const detalhe = arq.getName() + " · modificado " + Utilities.formatDate(arq.getLastUpdated(), "GMT-3", "dd/MM HH:mm") +
      (lista.length > 1 ? " · ⚠️ " + lista.length + " arquivos na pasta" : "");
    const doDia = normalizar(arq.getName()).includes(hojeTxt);
    (doDia ? ok : alerta)("Acessos", "Arquivo de inadimplência", detalhe + (doDia ? "" : " · nome sem a data de hoje"));
  });

  // ------------------------------------------------------- 4. GATILHOS
  testar("Gatilhos", "Gatilhos do projeto", () => {
    const gatilhos = ScriptApp.getProjectTriggers();
    const porFuncao = {};
    gatilhos.forEach(t => {
      porFuncao[t.getHandlerFunction()] = (porFuncao[t.getHandlerFunction()] || []).concat(String(t.getEventType()));
    });
    ["atualizarBasesEConsolidar", "distribuirInadimplenciaPorVendedor"].forEach(fn => {
      if (porFuncao[fn]) ok("Gatilhos", fn, porFuncao[fn].join(", "));
      else alerta("Gatilhos", fn, "sem gatilho automático — roda só pelo menu");
    });
    Object.keys(porFuncao)
      .filter(fn => fn !== "atualizarBasesEConsolidar" && fn !== "distribuirInadimplenciaPorVendedor")
      .forEach(fn => {
        const existe = typeof escopo[fn] === "function";
        (existe ? ok : erro)("Gatilhos", fn, porFuncao[fn].join(", ") + (existe ? "" : " · função não existe mais"));
      });
  });

  // ---------------------------------------------------------- 5. FRESCOR
  const lerCarimbo = (abaNome, celula) => {
    const aba = ss.getSheetByName(abaNome);
    const txt = aba ? String(aba.getRange(celula).getValue()) : "";
    const m = txt.match(/(\d{2})\/(\d{2})\/(\d{4})\s*(?:às\s*)?(\d{2}):(\d{2})/);
    // Carimbos são gravados em GMT-3; parseDate evita depender do fuso do projeto
    return m ? Utilities.parseDate(`${m[1]}/${m[2]}/${m[3]} ${m[4]}:${m[5]}`, "GMT-3", "dd/MM/yyyy HH:mm") : null;
  };
  const avaliarFrescor = (rotulo, data) => {
    if (!data) return alerta("Frescor", rotulo, "sem carimbo de data");
    const horas = (new Date() - data) / 36e5;
    const txt = Utilities.formatDate(data, "GMT-3", "dd/MM HH:mm") + " (há " + horas.toFixed(1) + " h)";
    (horas <= 26 ? ok : alerta)("Frescor", rotulo, txt + (horas <= 26 ? "" : " · desatualizado"));
  };
  avaliarFrescor("Base_CIGAM (DW)", lerCarimbo("Base_CIGAM", "J1"));
  avaliarFrescor("Base_Cidades", lerCarimbo("Base_Cidades", "F1"));
  avaliarFrescor("Última distribuição (Relatório B6)", lerCarimbo("Relatório", "B6"));
  testar("Frescor", "Histórico diário", () => {
    const aba = ss.getSheetByName(CONFIG_DISTRIB.abaHistoricoResumo);
    if (!aba || aba.getLastRow() < 2) return alerta("Frescor", "Histórico diário", "ainda sem registros — começa na próxima distribuição");
    const ultima = aba.getRange(aba.getLastRow(), 1).getValue();
    if (!(ultima instanceof Date)) return alerta("Frescor", "Histórico diário", "última linha sem data");
    const dias = (new Date() - ultima) / 864e5;
    (dias <= 4 ? ok : alerta)("Frescor", "Histórico diário",
      (aba.getLastRow() - 1) + " dias registrados · último " + Utilities.formatDate(ultima, "GMT-3", "dd/MM/yyyy"));
  });

  // ---------------------------------------------------- 6. CONSISTÊNCIA
  testar("Consistência", "Bases", () => {
    const lista = ss.getSheetByName("Lista_Vendedores").getDataRange().getValues().slice(1);
    const ativos = new Set(), todos = new Set();
    lista.forEach(l => {
      const nome = String(l[0]).trim().toUpperCase();
      if (!nome) return;
      todos.add(nome);
      if (l[2] === true) {
        ativos.add(nome);
        if (!String(l[1]).trim()) alerta("Consistência", "Carteira ativa sem planilha", nome);
      }
    });
    ok("Consistência", "Lista_Vendedores", ativos.size + " ativos de " + todos.size);

    // Vendedores de praça que não existem na Lista_Vendedores: a regra 4 falha em silêncio para eles
    const cidades = ss.getSheetByName("Base_Cidades").getDataRange().getValues().slice(1);
    const vendPraca = new Set(cidades.map(l => String(l[2]).replace(/ /g, " ").trim().toUpperCase()).filter(Boolean));
    const fora = [...vendPraca].filter(v => !todos.has(v));
    const inativos = [...vendPraca].filter(v => todos.has(v) && !ativos.has(v));
    (fora.length ? alerta : ok)("Consistência", "Vendedores da Base_Cidades fora da Lista_Vendedores",
      fora.length ? fora.join(", ") + " — cidades deles nunca são atribuídas" : "todos cadastrados");
    if (inativos.length) alerta("Consistência", "Praças de vendedores inativos", inativos.join(", "));

    // Base_Clientes: regras e vendedores
    const clientes = ss.getSheetByName("Base_Clientes").getDataRange().getValues().slice(1);
    const regras = {};
    let naoMapeados = 0;
    const vendClientesFora = new Set();
    clientes.forEach(l => {
      const regra = String(l[5]).split("(")[0].trim() || "(vazio)";
      regras[regra] = (regras[regra] || 0) + 1;
      const v = String(l[1]).trim().toUpperCase();
      if (v === "NÃO MAPEADO") naoMapeados++;
      else if (v && !todos.has(v)) vendClientesFora.add(v);
    });
    ok("Consistência", "Base_Clientes por regra", Object.keys(regras).sort().map(k => k + ": " + regras[k]).join(" · "));
    (naoMapeados ? alerta : ok)("Consistência", "Clientes NÃO MAPEADO", naoMapeados + " de " + clientes.length);
    if (vendClientesFora.size) alerta("Consistência", "Vendedores na Base_Clientes fora da Lista_Vendedores",
      [...vendClientesFora].join(", ") + " — rode 'Validar Planilhas' para incluí-los");

    // Base_CIGAM x Base_Clientes
    const cigam = ss.getSheetByName("Base_CIGAM").getLastRow() - 1;
    ok("Consistência", "Base_CIGAM → Base_Clientes", cigam + " cadastros → " + clientes.length + " clientes (dedup por CNPJ)");

    // Dados_Looker x Relatório
    const looker = ss.getSheetByName("Dados_Looker").getLastRow() - 1;
    const b9 = Number(ss.getSheetByName("Relatório").getRange("B9").getValue());
    (looker === b9 ? ok : alerta)("Consistência", "Dados_Looker x Relatório B9", looker + " linhas x " + b9 + " títulos");
  });

  // -------------------------------------------------------- 7. RELATÓRIO
  testar("Relatório", "Seções", () => {
    const aba = ss.getSheetByName("Relatório");
    const secoes = [
      ["Saúde: arquivo lido", "B" + RELATORIO.saude.arquivo],
      ["Saúde: conferência", "B" + RELATORIO.saude.conferencia],
      ["Saúde: Base_CIGAM", "B" + RELATORIO.saude.cigam],
      ["Saúde: Base_Cidades", "B" + RELATORIO.saude.cidades],
      ["Saúde: Base_Clientes", "B" + RELATORIO.saude.clientes],
      ["Consolidação por cliente", "B" + RELATORIO.consolidacao.primeiraLinha],
      ["Desempenho por vendedor", "A" + RELATORIO.vendedores.primeiraLinha]
    ];
    secoes.forEach(([rotulo, celula]) => {
      const v = aba.getRange(celula).getValue();
      (v !== "" ? ok : alerta)("Relatório", rotulo, v !== "" ? String(v) : celula + " vazio — preenchido na próxima execução da etapa correspondente");
    });
  });

  // ------------------------------------------------------------ SAÍDA
  let abaDiag = ss.getSheetByName("Diagnóstico") || ss.insertSheet("Diagnóstico");
  abaDiag.clearContents();
  const tabela = [["Área", "Verificação", "Status", "Detalhe"]].concat(resultados);
  abaDiag.getRange(1, 1, tabela.length, 4).setValues(tabela);
  abaDiag.getRange(1, 1, 1, 4).setFontWeight("bold").setBackground("#cfe2f3");
  abaDiag.getRange(1, 6).setValue("Diagnóstico em: " + agoraFormatado_());

  const n = s => resultados.filter(r => r[2] === s).length;
  const resumo = `✅ ${n("✅")}  ·  ⚠️ ${n("⚠️")}  ·  ❌ ${n("❌")}\n\nDetalhes na aba 'Diagnóstico'.`;
  console.log(resumo);
  resultados.filter(r => r[2] !== "✅").forEach(r => console.log(r.join(" | ")));
  alertaSeguro("Diagnóstico concluído", resumo);
}
