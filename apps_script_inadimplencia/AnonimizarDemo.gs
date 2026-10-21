// =========================================================================
// DADOS DE DEMONSTRAÇÃO (ANONIMIZADOS) PARA APRESENTAÇÕES
// -------------------------------------------------------------------------
// gerarDadosLookerDemo()
//   Lê a aba Dados_Looker e grava uma CÓPIA randomizada numa PLANILHA NOVA
//   ("Dados_Looker DEMO"), na mesma pasta da Planilha Central.
//   A Planilha Central NÃO é alterada.
//
// gerarCarteiraDemo()
//   Copia o template das carteiras e preenche a aba "Dados" com os títulos
//   de um vendedor fictício da planilha DEMO — para capturar o dashboard
//   do vendedor sem expor ninguém.
//
// O que é trocado / preservado:
//   • Cliente, CNPJ, Fatura .......... substituídos por fictícios (CNPJ válido)
//   • Vendedor ....................... nomes fictícios (NÃO MAPEADO continua)
//   • Distribuidoras ................. "Distribuidora Alfa/Beta/Gama/Delta"
//   • Município ...................... embaralhado dentro da mesma UF
//   • Saldo .......................... fator global ±20% × fator por cliente ±40% × ±10% por título
//   • Dias de atraso ................. ±7 dias; Emissão e Vencimento recalculados
//   • UF, Região, Produto, Segmento .. preservados (o mapa e os gráficos continuam realistas)
//   Nenhuma tabela de-para é salva: não há como voltar ao dado real.
// =========================================================================

const CONFIG_DEMO = {
  abaOrigem: "Dados_Looker",
  nomePlanilhaDemo: "Dados_Looker DEMO (anonimizado)",
  idTemplateCarteira: "1Ehkon-uKpHuT_U_ubozYz6kDH15xUlUhjFKx_6ZHzPw",
  celulaCabecalhoDashboard: "C3",
  celulaCabecalhoConsulta: "H1"
};

// Nomes fictícios (nenhum coincide com vendedores reais)
const VENDEDORES_FICTICIOS = [
  "BRUNA TAVARES", "CAIO MENDES", "FERNANDA LOPES", "GUSTAVO PRADO", "HELENA DUARTE",
  "IGOR MATOS", "JULIANA ROCHA", "LUCAS BARROS", "MARINA TEIXEIRA", "OTÁVIO PIRES",
  "PAULA CORREIA", "RAFAEL NUNES", "SABRINA COELHO", "THIAGO LACERDA", "VANESSA MOURA",
  "WAGNER CAMPOS", "YASMIN FREITAS", "ELISA CARDOSO", "RENATO VIEIRA", "CLARA FONTES",
  "DIEGO MARTINS", "BEATRIZ AMARAL", "FÁBIO REZENDE", "LARISSA PRATES", "MURILO SANTANA"
];
const NOMES_EMPRESA_A = ["TRANSPORTES", "LOGÍSTICA", "AGROPECUÁRIA", "CONSTRUTORA", "MINERAÇÃO",
  "AUTO POSTO", "USINA", "FRIGORÍFICO", "COOPERATIVA", "LOCADORA", "TERRAPLENAGEM", "EXPRESSO",
  "COMÉRCIO DE COMBUSTÍVEIS", "CONCRETEIRA", "ARMAZÉNS GERAIS", "FRETAMENTO", "PAVIMENTAÇÃO"];
const NOMES_EMPRESA_B = ["HORIZONTE", "SERRA AZUL", "VALE VERDE", "AURORA", "ATLÂNTICO", "CERRADO",
  "PAMPA", "RIO CLARO", "BOA VISTA", "SOL NASCENTE", "MONTE ALTO", "TRÊS LAGOAS", "NOVA ERA",
  "SÃO BENTO", "PEDRA BRANCA", "ALVORADA", "BANDEIRANTE", "CANAÃ", "PLANALTO", "ESTRELA DO SUL",
  "LITORAL", "SERRANA", "IPÊ AMARELO", "JATOBÁ", "BURITI", "CAATINGA", "MARAJÓ", "TOCANTINS"];
const SUFIXOS_EMPRESA = ["LTDA", "LTDA", "LTDA", "S.A.", "EIRELI", "LTDA ME"];
const DISTRIBUIDORAS_FICTICIAS = ["DISTRIBUIDORA ALFA S.A.", "DISTRIBUIDORA BETA S.A.",
  "DISTRIBUIDORA GAMA S.A.", "DISTRIBUIDORA DELTA S.A."];

// ---------------------------------------------------------------- utilitários
function aleatorio_(min, max) { return min + Math.random() * (max - min); }
function inteiroAleatorio_(min, max) { return Math.floor(aleatorio_(min, max + 1)); }
function escolher_(lista) { return lista[Math.floor(Math.random() * lista.length)]; }
function embaralhar_(lista) {
  const a = lista.slice();
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}

function cnpjFicticio_() {
  const base = String(inteiroAleatorio_(10000000, 99999999)) + "0001";
  const dv = (b, pesos) => { const r = b.split("").reduce((s, d, i) => s + Number(d) * pesos[i], 0) % 11; return r < 2 ? 0 : 11 - r; };
  const d1 = dv(base, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]);
  const d2 = dv(base + d1, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]);
  return base + d1 + d2;
}

function paraData_(v) {
  if (v instanceof Date) return new Date(v.getFullYear(), v.getMonth(), v.getDate());
  const m = String(v || "").trim().match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/);
  return m ? new Date(+m[3], +m[2] - 1, +m[1]) : null;
}

function avisarDemo_(titulo, mensagem) {
  try { SpreadsheetApp.getUi().alert(titulo, mensagem, SpreadsheetApp.getUi().ButtonSet.OK); }
  catch (e) { console.log(`[${titulo}] ${mensagem}`); }
}

const RAIZES_DISTRIBUIDORAS_DEMO = ["34274233", "33337122", "33453598", "23314594"];

// ---------------------------------------------------------------- 1. Looker
// Recebe os valores da aba (com cabeçalho) e devolve { tabela, resumo }.
function anonimizarTabela_(dados) {
  if (dados.length < 2) throw new Error("Dados_Looker está vazia.");

  const cab = dados[0].map(c => String(c).trim());
  const col = nome => cab.indexOf(nome);
  const iCnpj = col("CNPJ"), iCli = col("Cliente"), iVend = col("Vendedor"), iUf = col("UF"),
        iMun = col("Município"), iEmis = col("Emissao"), iVenc = col("Vencimento"), iFat = col("Fatura"),
        iSaldo = col("Saldo"), iDias = col("Dias Atraso"), iAtual = col("Data Atualizacao"), iSeg = col("Segmento");
  [iCnpj, iCli, iVend, iSaldo, iDias].forEach((i, k) => {
    if (i === -1) throw new Error("Coluna obrigatória ausente: " + ["CNPJ", "Cliente", "Vendedor", "Saldo", "Dias Atraso"][k]);
  });

  const linhas = dados.slice(1);

  // Clientes → identidade fictícia (consistente em todas as linhas do cliente)
  const clientes = {};
  const nomesUsados = new Set();
  let idxDistribuidora = 0;
  const distribuidoraPorRaiz = {};
  linhas.forEach(l => {
    const real = String(l[iCnpj]).replace(/\D/g, "");
    if (clientes[real]) return;
    const raiz = real.padStart(14, "0").substring(0, 8);
    const ehDistribuidora = RAIZES_DISTRIBUIDORAS_DEMO.includes(raiz) || (iSeg !== -1 && l[iSeg] === "Distribuidora");
    let nome;
    if (ehDistribuidora) {
      if (!distribuidoraPorRaiz[raiz]) distribuidoraPorRaiz[raiz] = DISTRIBUIDORAS_FICTICIAS[idxDistribuidora++ % DISTRIBUIDORAS_FICTICIAS.length];
      nome = distribuidoraPorRaiz[raiz];
    } else {
      do {
        nome = `${escolher_(NOMES_EMPRESA_A)} ${escolher_(NOMES_EMPRESA_B)} ${escolher_(SUFIXOS_EMPRESA)}`;
      } while (nomesUsados.has(nome) && nomesUsados.size < 5000);
    }
    nomesUsados.add(nome);
    clientes[real] = { cnpj: cnpjFicticio_(), nome: nome, fator: aleatorio_(0.6, 1.4) };
  });

  // Vendedores → nomes fictícios
  const vendedoresReais = [...new Set(linhas.map(l => String(l[iVend]).trim()))].filter(v => v && v !== "NÃO MAPEADO");
  if (vendedoresReais.length > VENDEDORES_FICTICIOS.length) throw new Error("Mais vendedores que nomes fictícios; amplie a lista.");
  const ficticios = embaralhar_(VENDEDORES_FICTICIOS);
  const vendedores = {};
  vendedoresReais.forEach((v, i) => vendedores[v] = ficticios[i]);

  // Municípios embaralhados dentro da mesma UF
  const municipios = {};
  if (iMun !== -1 && iUf !== -1) {
    const porUf = {};
    linhas.forEach(l => { (porUf[l[iUf]] = porUf[l[iUf]] || new Set()).add(l[iMun]); });
    Object.keys(porUf).forEach(uf => {
      const reais = [...porUf[uf]];
      const trocados = embaralhar_(reais);
      reais.forEach((m, i) => municipios[uf + "|" + m] = trocados[i]);
    });
  }

  const fatorGlobal = aleatorio_(0.8, 1.2);
  const faturasUsadas = new Set();
  const saida = linhas.map(l => {
    const n = l.slice();
    const c = clientes[String(l[iCnpj]).replace(/\D/g, "")];
    n[iCnpj] = c.cnpj;
    n[iCli] = c.nome;
    const v = String(l[iVend]).trim();
    n[iVend] = vendedores[v] || v;
    if (iMun !== -1 && iUf !== -1) n[iMun] = municipios[l[iUf] + "|" + l[iMun]] || l[iMun];

    n[iSaldo] = Math.round((Number(l[iSaldo]) || 0) * fatorGlobal * c.fator * aleatorio_(0.9, 1.1) * 100) / 100;

    const dias = Math.max(1, (Number(l[iDias]) || 0) + inteiroAleatorio_(-7, 7));
    n[iDias] = dias;
    const atual = iAtual !== -1 ? paraData_(l[iAtual]) : null;
    const vencOrig = iVenc !== -1 ? paraData_(l[iVenc]) : null;
    const emisOrig = iEmis !== -1 ? paraData_(l[iEmis]) : null;
    if (atual && iVenc !== -1) {
      const venc = new Date(atual.getTime() - dias * 864e5);
      n[iVenc] = venc;
      if (iEmis !== -1) {
        const prazo = vencOrig && emisOrig ? Math.round((vencOrig - emisOrig) / 864e5) : 30;
        n[iEmis] = new Date(venc.getTime() - prazo * 864e5);
      }
    }
    if (iFat !== -1) {
      let f;
      do { f = String(inteiroAleatorio_(10000000, 29999999)); } while (faturasUsadas.has(f));
      faturasUsadas.add(f);
      n[iFat] = f.replace(/(\d{2})(\d{3})(\d{3})/, "$1.$2.$3");
    }
    if (iAtual !== -1 && atual) n[iAtual] = atual;
    return n;
  });

  const tabela = [cab].concat(embaralhar_(saida));
  const resumo = `${tabela.length - 1} títulos · ${Object.keys(clientes).length} clientes · ${vendedoresReais.length} vendedores anonimizados`;
  return { tabela: tabela, resumo: resumo, idx: { iSaldo: iSaldo, iEmis: iEmis, iVenc: iVenc, iAtual: iAtual } };
}

function formatarAbaDemo_(aba, tabela, idx) {
  const n = tabela.length - 1, largura = tabela[0].length;
  aba.getRange(1, 1, 1, largura).setFontWeight("bold").setBackground("#cfe2f3");
  if (n < 1) return;
  if (idx.iSaldo !== -1) aba.getRange(2, idx.iSaldo + 1, n, 1).setNumberFormat("R$ #,##0.00");
  [idx.iEmis, idx.iVenc, idx.iAtual].filter(i => i !== -1).forEach(i => aba.getRange(2, i + 1, n, 1).setNumberFormat("dd/mm/yyyy"));
}

function gerarDadosLookerDemo() {
  const ssCentral = SpreadsheetApp.getActiveSpreadsheet();
  const origem = ssCentral.getSheetByName(CONFIG_DEMO.abaOrigem);
  if (!origem) throw new Error("Aba " + CONFIG_DEMO.abaOrigem + " não encontrada.");
  const { tabela, resumo, idx } = anonimizarTabela_(origem.getDataRange().getValues());
  const cab = tabela[0];

  // Planilha nova, na mesma pasta da Central
  const demo = SpreadsheetApp.create(CONFIG_DEMO.nomePlanilhaDemo + " " + Utilities.formatDate(new Date(), "GMT-3", "dd-MM-yyyy HH'h'mm"));
  const pasta = DriveApp.getFileById(ssCentral.getId()).getParents();
  if (pasta.hasNext()) DriveApp.getFileById(demo.getId()).moveTo(pasta.next());
  const aba = demo.getSheets()[0];
  aba.setName(CONFIG_DEMO.abaOrigem);
  aba.getRange(1, 1, tabela.length, cab.length).setValues(tabela);
  aba.setFrozenRows(1);
  formatarAbaDemo_(aba, tabela, idx);
  aba.getRange("A1").setNote("Dados FICTÍCIOS gerados a partir de Dados_Looker em " +
    Utilities.formatDate(new Date(), "GMT-3", "dd/MM/yyyy HH:mm") + ". Não usar para decisões.");

  const msg = `${resumo}.\n\nPlanilha DEMO: ${demo.getUrl()}\n\nA Planilha Central não foi alterada.`;
  console.log(msg);
  avisarDemo_("Dados de demonstração gerados", msg);
  return demo.getUrl();
}

// ---------------------------------------------------------------- 1b. No lugar (com backup)
// Anonimiza a PRÓPRIA aba Dados_Looker, para capturar o relatório de produção.
// Antes, guarda os valores reais numa aba oculta; restaurarDadosLooker() desfaz.
// ATENÇÃO: enquanto estiver anonimizada, quem abrir o Looker vê dados fictícios.
const ABA_BACKUP_DEMO = "_Backup_Dados_Looker";
const MARCA_DEMO = "DEMO_ANONIMIZADO";

// Impressão digital do conteúdo da aba: muda se a distribuição regravar os dados
function impressaoDigital_(valores) {
  const cab = valores[0].map(c => String(c).trim());
  const iSaldo = cab.indexOf("Saldo"), iCnpj = cab.indexOf("CNPJ");
  const soma = valores.slice(1).reduce((s, l) => s + (Number(l[iSaldo]) || 0), 0);
  return [valores.length, soma.toFixed(2), valores.length > 1 ? String(valores[1][iCnpj]) : ""].join("|");
}

function anonimizarDadosLookerNoLugar() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const aba = ss.getSheetByName(CONFIG_DEMO.abaOrigem);
  if (!aba) throw new Error("Aba " + CONFIG_DEMO.abaOrigem + " não encontrada.");
  if (ss.getSheetByName(ABA_BACKUP_DEMO)) {
    throw new Error("Já existe um backup (" + ABA_BACKUP_DEMO + "). Rode restaurarDadosLooker() antes de anonimizar de novo.");
  }
  const dados = aba.getDataRange().getValues();
  const { tabela, resumo, idx } = anonimizarTabela_(dados);

  // Backup completo (valores + formatos) numa aba oculta da própria planilha
  const backup = aba.copyTo(ss).setName(ABA_BACKUP_DEMO);
  backup.hideSheet();

  aba.clearContents();
  aba.getRange(1, 1, tabela.length, tabela[0].length).setValues(tabela);
  formatarAbaDemo_(aba, tabela, idx);
  aba.getRange("A1").setNote(MARCA_DEMO + " — dados fictícios. Desfazer: restaurarDadosLooker()");
  SpreadsheetApp.flush();
  PropertiesService.getDocumentProperties().setProperty(MARCA_DEMO, impressaoDigital_(aba.getDataRange().getValues()));

  const msg = `${resumo}.\n\nA aba ${CONFIG_DEMO.abaOrigem} agora tem dados FICTÍCIOS.\n` +
    `No Looker: Exibir → Atualizar dados antes de capturar.\n` +
    `Ao terminar: rode restaurarDadosLooker() (funciona também no fim de semana).`;
  console.log(msg);
  avisarDemo_("Dados_Looker anonimizado", msg);
}

// Desfaz anonimizarDadosLookerNoLugar(). Se a distribuição já regravou a aba
// com dados reais mais novos, só descarta o backup (não volta para dado velho).
function restaurarDadosLooker() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const aba = ss.getSheetByName(CONFIG_DEMO.abaOrigem);
  const backup = ss.getSheetByName(ABA_BACKUP_DEMO);
  const props = PropertiesService.getDocumentProperties();
  if (!backup) {
    props.deleteProperty(MARCA_DEMO);
    return avisarDemo_("Nada a restaurar", "Não há backup de " + CONFIG_DEMO.abaOrigem + ".");
  }
  const aindaDemo = props.getProperty(MARCA_DEMO) === impressaoDigital_(aba.getDataRange().getValues());
  let msg;
  if (aindaDemo) {
    const dados = backup.getDataRange().getValues();
    aba.clearContents();
    aba.getRange(1, 1, dados.length, dados[0].length).setValues(dados);
    backup.getDataRange().copyTo(aba.getRange(1, 1), SpreadsheetApp.CopyPasteType.PASTE_FORMAT, false);
    msg = `Dados reais restaurados (${dados.length - 1} linhas). No Looker: Exibir → Atualizar dados.`;
  } else {
    msg = "A distribuição já regravou a aba com dados reais mais recentes; o backup foi só descartado.";
  }
  aba.getRange("A1").clearNote();   // clearContents() da distribuição não apaga notas
  ss.deleteSheet(backup);
  props.deleteProperty(MARCA_DEMO);
  SpreadsheetApp.flush();
  console.log(msg);
  avisarDemo_("Dados_Looker restaurado", msg);
}

// ---------------------------------------------------------------- 2. Carteira demo
// Usa a planilha DEMO mais recente da pasta e o vendedor fictício com maior saldo.
function gerarCarteiraDemo() {
  const ssCentral = SpreadsheetApp.getActiveSpreadsheet();
  const pasta = DriveApp.getFileById(ssCentral.getId()).getParents().next();
  const arquivos = pasta.searchFiles(`title contains '${CONFIG_DEMO.nomePlanilhaDemo}' and trashed = false`);
  let maisRecente = null;
  while (arquivos.hasNext()) {
    const a = arquivos.next();
    if (!maisRecente || a.getDateCreated() > maisRecente.getDateCreated()) maisRecente = a;
  }
  if (!maisRecente) throw new Error("Rode gerarDadosLookerDemo() antes.");

  const dados = SpreadsheetApp.openById(maisRecente.getId()).getSheetByName(CONFIG_DEMO.abaOrigem).getDataRange().getValues();
  const cab = dados[0];
  const c = nome => cab.indexOf(nome);
  const saldoPorVendedor = {};
  dados.slice(1).forEach(l => {
    const v = l[c("Vendedor")];
    if (v && v !== "NÃO MAPEADO") saldoPorVendedor[v] = (saldoPorVendedor[v] || 0) + Number(l[c("Saldo")]);
  });
  const vendedor = Object.keys(saldoPorVendedor).sort((a, b) => saldoPorVendedor[b] - saldoPorVendedor[a])[0];

  // Mesmo layout da aba TÍTULOS UNIFICADOS, que é o que as carteiras recebem
  const cabCarteira = ["CNPJ_CPF", "EMISSAO", "VENCIMENTO", "DIAS", "FATURA", "SALDO", "EMPRESA", "CONTA DESCRICAO", "PORTADOR"];
  const linhas = dados.slice(1).filter(l => l[c("Vendedor")] === vendedor).map(l => [
    l[c("CNPJ")], l[c("Emissao")], l[c("Vencimento")], l[c("Dias Atraso")], l[c("Fatura")],
    l[c("Saldo")], l[c("Cliente")], l[c("Tipo de Produto")], "BANCO DEMO"
  ]);

  const copia = DriveApp.getFileById(CONFIG_DEMO.idTemplateCarteira).makeCopy("Carteira DEMO " + vendedor, pasta);
  const ss = SpreadsheetApp.openById(copia.getId());
  const abaDados = ss.getSheetByName("Dados") || ss.insertSheet("Dados");
  abaDados.clearContents();
  abaDados.getRange(1, 1, linhas.length + 1, cabCarteira.length).setValues([cabCarteira].concat(linhas));
  const dash = ss.getSheetByName("Dashboard");
  if (dash) dash.getRange(CONFIG_DEMO.celulaCabecalhoDashboard).setValue("Carteira: " + vendedor);
  const consulta = ss.getSheetByName("Consulta");
  if (consulta) consulta.getRange(CONFIG_DEMO.celulaCabecalhoConsulta).setValue("Carteira: " + vendedor);
  SpreadsheetApp.flush();

  const msg = `Carteira DEMO de ${vendedor} (${linhas.length} títulos): ${ss.getUrl()}`;
  console.log(msg);
  avisarDemo_("Carteira de demonstração criada", msg);
  return ss.getUrl();
}
