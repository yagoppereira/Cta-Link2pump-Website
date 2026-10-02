// =========================================================================
// RELATÓRIO — layout e escrita das seções novas da aba "Relatório"
// -------------------------------------------------------------------------
// As células originais (B6, B9:B10, B13:B15, B18:B21) continuam iguais.
// Abaixo delas, cada script grava a sua parte:
//   • Saúde das Bases ........ sincronização, consolidação e distribuição
//   • Consolidação por cliente  consolidarBaseInteligente()
//   • Top 10 sem dono ......... distribuirInadimplenciaPorVendedor()
//   • Desempenho por vendedor . distribuirInadimplenciaPorVendedor()
// =========================================================================

const RELATORIO = {
  aba: "Relatório",
  saude: { titulo: 23, arquivo: 24, conferencia: 25, cigam: 26, cidades: 27, clientes: 28 },
  consolidacao: { titulo: 30, primeiraLinha: 31 },               // 31..38
  semDono: { titulo: 40, cabecalho: 41, primeiraLinha: 42, max: 10 },
  vendedores: { titulo: 53, cabecalho: 54, primeiraLinha: 55, max: 100 }
};

const ROTULOS_SAUDE = {
  arquivo: "Arquivo de inadimplência lido:",
  conferencia: "Conferência do arquivo:",
  cigam: "Base_CIGAM (DW):",
  cidades: "Base_Cidades:",
  clientes: "Base_Clientes (consolidação):"
};

function abaRelatorio_() {
  return SpreadsheetApp.getActiveSpreadsheet().getSheetByName(RELATORIO.aba);
}

function agoraFormatado_() {
  return Utilities.formatDate(new Date(), "GMT-3", "dd/MM/yyyy HH:mm");
}

function formatarReais_(valor) {
  const partes = Number(valor || 0).toFixed(2).split(".");
  return "R$ " + partes[0].replace(/\B(?=(\d{3})+$)/g, ".") + "," + partes[1];
}

function tituloSecao_(aba, linha, textos) {
  aba.getRange(linha, 1, 1, textos.length)
    .setValues([textos])
    .setFontWeight("bold")
    .setBackground("#cfe2f3");
}

// Uma linha da seção "Saúde das Bases": rótulo | status | detalhe
function registrarSaude_(chave, status, detalhe) {
  const aba = abaRelatorio_();
  if (!aba) return;
  tituloSecao_(aba, RELATORIO.saude.titulo, ["SAÚDE DAS BASES", "Status", "Detalhe"]);
  aba.getRange(RELATORIO.saude[chave], 1, 1, 3).setValues([[ROTULOS_SAUDE[chave], status, detalhe]]);
}

// Tabela com título, cabeçalho e área reservada (limpa antes de escrever)
function escreverTabela_(aba, cfg, titulo, cabecalho, linhas) {
  const largura = cabecalho.length;
  tituloSecao_(aba, cfg.titulo, [titulo].concat(new Array(largura - 1).fill("")));
  aba.getRange(cfg.cabecalho, 1, 1, largura).setValues([cabecalho]).setFontWeight("bold");
  aba.getRange(cfg.primeiraLinha, 1, cfg.max, largura).clearContent();
  const visiveis = linhas.slice(0, cfg.max);
  if (visiveis.length) {
    aba.getRange(cfg.primeiraLinha, 1, visiveis.length, largura).setValues(visiveis);
  }
}

// Bloco "Consolidação da base (por cliente)", chamado por consolidarBaseInteligente()
function registrarConsolidacaoNoRelatorio_(contadorRegras, totalClientes) {
  const aba = abaRelatorio_();
  if (!aba) return;

  const somar = filtro => Object.keys(contadorRegras)
    .filter(filtro)
    .reduce((acc, k) => acc + contadorRegras[k], 0);

  const linhas = [
    ["1. Inserção manual (exata/raiz)", somar(k => k.startsWith("1."))],
    ["2. Comercial — CNPJ raiz", somar(k => k.startsWith("2."))],
    ["3. Comercial — razão social exata", somar(k => k.startsWith("3.") && k.includes("Exata"))],
    ["3. Comercial — razão social parcial", somar(k => k.startsWith("3.") && k.includes("Parcial"))],
    ["4. Praça (Cidade/UF)", somar(k => k.startsWith("4."))],
    ["5. Retido (vendedor inativo)", somar(k => k.startsWith("5."))],
    ["Não mapeado", somar(k => k === "Nenhuma")]
  ];
  const comVendedor = linhas.slice(0, 5).reduce((acc, l) => acc + l[1], 0);
  linhas.push(["Cobertura (regras 1 a 4)", comVendedor]);

  const pct = n => totalClientes ? n / totalClientes : 0;
  const tabela = linhas.map(l => [l[0], l[1], pct(l[1])]);

  tituloSecao_(aba, RELATORIO.consolidacao.titulo, ["CONSOLIDAÇÃO DA BASE (por cliente)", "Clientes", "% do total"]);
  const area = aba.getRange(RELATORIO.consolidacao.primeiraLinha, 1, tabela.length, 3);
  area.setValues(tabela);
  aba.getRange(RELATORIO.consolidacao.primeiraLinha, 3, tabela.length, 1).setNumberFormat("0.0%");
  aba.getRange(RELATORIO.consolidacao.primeiraLinha + tabela.length - 1, 1, 1, 3).setFontWeight("bold");
}

// Execução única: remove sobras antigas da aba Relatório antes da apresentação
function limparRelatorioLegado() {
  const aba = abaRelatorio_();
  if (!aba) return;
  aba.getRange("I6").clearContent();      // "Última Atualização: 24/07/2026 às 09:39"
  aba.getRange("G46:I46").clearContent(); // linha solta (GLOBAL ELETRONICS)
}
