// =========================================================================
// RANDOMIZADOR DE DEMONSTRAÇÃO — roda DENTRO da planilha (cópia DEMO)
// -------------------------------------------------------------------------
// randomizarPlanilhaDemo()
//   Troca por fictícios, de forma CONSISTENTE entre todas as abas:
//   • clientes (com ou sem código "000123 - ", em maiúsculas ou não)
//   • CNPJ/CPF (mesma raiz real → mesma raiz fictícia; dígito verificador válido;
//     mantém o formato: com máscara ou só dígitos)
//   • vendedores (mesmo vendedor → mesmo nome fictício em qualquer aba/caixa)
//   • códigos de cliente, nomes fantasia, faturas, IDs
//   • valores em R$ (um único fator aleatório para a planilha inteira, para os
//     totais continuarem batendo entre abas)
//   • links das planilhas dos vendedores (apagados)
//   Datas, dias de atraso, UF, município, produto e regras ficam como estão.
//
// SEGURANÇA
//   • Recusa rodar nas planilhas de PRODUÇÃO (Central e Template).
//   • Não guarda backup nem de-para dentro do arquivo: o arquivo pode ser
//     compartilhado sem levar dado real junto.
//   • Fórmulas não são tocadas; abas só de fórmulas (Dashboard, Cálculos,
//     Consulta) recalculam sozinhas a partir da aba Dados.
// =========================================================================

const CONFIG_RANDOM = {
  idsProducao: [
    "1KSd7cdHUiotmE6WAePq0WnXzhLZz8vggwPkcn1ZGBv4",   // Planilha Central
    "1Ehkon-uKpHuT_U_ubozYz6kDH15xUlUhjFKx_6ZHzPw"    // [TEMPLATE] Planilha Piloto
  ],
  abasSoFormulas: ["Dashboard", "Cálculos", "Consulta"],
  abasIgnoradas: [],
  vendedorDaCarteira: "BRUNA TAVARES",   // aparece em "Carteira: ..." no Dashboard/Consulta
  raizesDistribuidoras: { "34274233": "ALFA", "33337122": "BETA", "33453598": "GAMA", "23314594": "DELTA" },
  linhasDeCabecalhoProcuradas: 120       // procura tabelas (cabeçalhos) até esta linha
};

const VENDEDORES_FAKE_ = [
  "BRUNA TAVARES", "CAIO MENDES", "FERNANDA LOPES", "GUSTAVO PRADO", "HELENA DUARTE", "IGOR MATOS",
  "JULIANA ROCHA", "LUCAS BARROS", "MARINA TEIXEIRA", "OTÁVIO PIRES", "PAULA CORREIA", "RAFAEL NUNES",
  "SABRINA COELHO", "THIAGO LACERDA", "VANESSA MOURA", "WAGNER CAMPOS", "YASMIN FREITAS", "ELISA CARDOSO",
  "RENATO VIEIRA", "CLARA FONTES", "DIEGO MARTINS", "BEATRIZ AMARAL", "FÁBIO REZENDE", "LARISSA PRATES",
  "MURILO SANTANA", "NATÁLIA BRAGA", "PEDRO VASCONCELOS", "RAQUEL DANTAS", "SÉRGIO MOTA", "TATIANE BORGES",
  "VITOR GUSMÃO", "ALINE QUEIROZ", "BRENO FALCÃO", "CAMILA ESTEVES", "DANILO PAIVA", "ESTER MACEDO",
  "FELIPE ARANTES", "GABRIELA SALES", "HENRIQUE LEMOS", "ISABELA VALENTE", "JOÃO CORDEIRO", "KARINA BASTOS",
  "LEONARDO TORRES", "MELISSA AGUIAR", "NICOLAS PEIXOTO", "OLÍVIA RAMALHO", "PAULO FRANCO", "RENATA SIQUEIRA",
  "SAMUEL ANDRADE", "TERESA MONTEIRO", "ULISSES REIS", "VALÉRIA CUNHA", "WILLIAM DORNELES", "XAVIER BRITO",
  "YURI MEDEIROS", "ZÉLIA NOGUEIRA", "ANDRÉ VILELA", "BIANCA FRAGA", "CÉSAR TOLEDO", "DÉBORA PACHECO"
];
const EMPRESA_A_ = ["TRANSPORTES", "LOGÍSTICA", "AGROPECUÁRIA", "CONSTRUTORA", "MINERAÇÃO", "AUTO POSTO", "USINA",
  "FRIGORÍFICO", "COOPERATIVA", "LOCADORA", "TERRAPLENAGEM", "EXPRESSO", "CONCRETEIRA", "FRETAMENTO",
  "PAVIMENTAÇÃO", "ARMAZÉNS", "COMÉRCIO DE COMBUSTÍVEIS", "ENGENHARIA", "AGRÍCOLA", "RODOVIÁRIO"];
const EMPRESA_B_ = ["HORIZONTE", "SERRA AZUL", "VALE VERDE", "AURORA", "ATLÂNTICO", "CERRADO", "PAMPA", "RIO CLARO",
  "BOA VISTA", "SOL NASCENTE", "MONTE ALTO", "TRÊS LAGOAS", "NOVA ERA", "PEDRA BRANCA", "ALVORADA", "BANDEIRANTE",
  "PLANALTO", "ESTRELA DO SUL", "IPÊ AMARELO", "JATOBÁ", "BURITI", "MARAJÓ", "CANAÃ", "SÃO BENTO", "LITORAL",
  "SERRANA", "CAATINGA", "TOCANTINS", "ARAGUAIA", "PARANAPANEMA", "CAPIBARIBE", "VERA CRUZ", "BELA VISTA",
  "PORTO SEGURO", "SANTA CLARA", "MATA ATLÂNTICA", "GUAPORÉ", "PIRATINI", "ITATIAIA", "MANTIQUEIRA"];
const SUFIXO_ = ["LTDA", "LTDA", "LTDA", "S/A", "EIRELI", "LTDA ME", "LTDA EPP"];

// ---------------------------------------------------------------- utilidades
function normalizar_(t) {
  return String(t == null ? "" : t).normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replace(/ /g, " ").toUpperCase().replace(/\s+/g, " ").trim();
}
function sortear_(lista) { return lista[Math.floor(Math.random() * lista.length)]; }
function digitosAleatorios_(n) { let s = String(1 + Math.floor(Math.random() * 9)); while (s.length < n) s += Math.floor(Math.random() * 10); return s; }
function dv_(base, pesos) { const r = base.split("").reduce((s, d, i) => s + Number(d) * pesos[i], 0) % 11; return r < 2 ? "0" : String(11 - r); }
function cnpjCompleto_(base12) {
  const d1 = dv_(base12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]);
  return base12 + d1 + dv_(base12 + d1, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]);
}
function cpfCompleto_(base9) {
  const d1 = dv_(base9, [10, 9, 8, 7, 6, 5, 4, 3, 2]);
  return base9 + d1 + dv_(base9 + d1, [11, 10, 9, 8, 7, 6, 5, 4, 3, 2]);
}
function mascaraCnpj_(d) { return `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8, 12)}-${d.slice(12)}`; }
function mascaraCpf_(d) { return `${d.slice(0, 3)}.${d.slice(3, 6)}.${d.slice(6, 9)}-${d.slice(9)}`; }
function tituloCaixa_(s) { return s.toLowerCase().replace(/(^|\s)(\S)/g, (m, a, b) => a + b.toUpperCase()); }
function ehMaiusculo_(s) { return s === s.toUpperCase(); }

// ---------------------------------------------------------------- dicionário
function novoDicionario_() {
  return { raiz: {}, cpf: {}, vendedor: {}, empresa: {}, codigo: {}, fatura: {}, fantasia: {},
           usados: { raiz: new Set(), nome: new Set(), codigo: new Set(), vendedor: new Set() },
           reais: { vendedores: new Set(), docs: new Set(), empresas: new Set() } };
}

function cpfValido_(d) { return d.length === 11 && !/^(\d)\1+$/.test(d) && cpfCompleto_(d.slice(0, 9)) === d; }

function fakeDocumento_(dic, valor) {
  if (valor === "" || valor == null) return valor;
  const texto = String(valor).trim();
  let dig = texto.replace(/\D/g, "");
  if (!dig || dig.length > 14) return valor;
  const formatado = /[.\/-]/.test(texto);
  // CPF: máscara 000.000.000-00, ou 11 dígitos sem barra com dígito verificador de CPF
  if (!/\//.test(texto) && dig.length <= 11 && (/^\d{3}\.\d{3}\.\d{3}-\d{2}$/.test(texto) || cpfValido_(dig.padStart(11, "0")))) {
    dig = dig.padStart(11, "0");
    dic.reais.docs.add(dig);
    if (!dic.cpf[dig]) dic.cpf[dig] = cpfCompleto_(digitosAleatorios_(9));
    return formatado ? mascaraCpf_(dic.cpf[dig]) : dic.cpf[dig];
  }
  dig = dig.padStart(14, "0");
  dic.reais.docs.add(dig);
  const raiz = dig.slice(0, 8);
  if (!dic.raiz[raiz]) {
    let nova;
    do { nova = digitosAleatorios_(8); } while (dic.usados.raiz.has(nova));
    dic.usados.raiz.add(nova);
    dic.raiz[raiz] = nova;
  }
  const novo = cnpjCompleto_(dic.raiz[raiz] + dig.slice(8, 12));
  return formatado ? mascaraCnpj_(novo) : novo;
}

function fakeCodigo_(dic, codigo) {
  if (!dic.codigo[codigo]) {
    let novo;
    do { novo = String(100 + Math.floor(Math.random() * 6900)).padStart(codigo.length, "0"); } while (dic.usados.codigo.has(novo));
    dic.usados.codigo.add(novo);
    dic.codigo[codigo] = novo;
  }
  return dic.codigo[codigo];
}

function fakeVendedor_(dic, valor) {
  const texto = String(valor == null ? "" : valor).trim();
  const chave = normalizar_(texto);
  if (!chave || chave === "NAO MAPEADO" || chave === "VENDEDOR" || chave === "-") return valor;
  dic.reais.vendedores.add(texto);
  if (!dic.vendedor[chave]) {
    const livres = VENDEDORES_FAKE_.filter(n => !dic.usados.vendedor.has(n) && !dic.reais.vendedores.has(n));
    const nome = livres.length ? sortear_(livres) : `VENDEDOR ${dic.usados.vendedor.size + 1}`;
    dic.usados.vendedor.add(nome);
    dic.vendedor[chave] = nome;
  }
  return ehMaiusculo_(texto) ? dic.vendedor[chave] : tituloCaixa_(dic.vendedor[chave]);
}

// Chave do nome: sem código, sem sufixos jurídicos, sem " - Cidade/UF", sem pontuação
function chaveEmpresa_(t) {
  let s = String(t).replace(/^\s*\d{4,6}\s*-\s*/, "").replace(/\s*-\s*[^-\/]+\/[A-Za-z]{2}\s*$/, "");
  s = normalizar_(s).replace(/['`´"”\-\/\.,()]/g, " ");
  s = s.replace(/\b(LTDA|SA|S A|ME|EPP|EI|EIRELI|SNC|SS|CIA|FILIAL|MATRIZ|REGISTRO)\b/g, " ");
  return s.replace(/\s+/g, " ").trim();
}

function fakeEmpresa_(dic, valor, raizDaLinha) {
  const texto = String(valor == null ? "" : valor).trim();
  if (!texto || texto === "-" || normalizar_(texto) === "DESCONHECIDO") return valor;
  dic.reais.empresas.add(texto);
  const chave = chaveEmpresa_(texto);
  if (!chave) return valor;
  if (!dic.empresa[chave]) {
    const dist = raizDaLinha && CONFIG_RANDOM.raizesDistribuidoras[raizDaLinha];
    let nome;
    if (dist) nome = `DISTRIBUIDORA ${dist} S/A`;
    else do { nome = `${sortear_(EMPRESA_A_)} ${sortear_(EMPRESA_B_)} ${sortear_(SUFIXO_)}`; } while (dic.usados.nome.has(nome) && dic.usados.nome.size < 4000);
    dic.usados.nome.add(nome);
    dic.empresa[chave] = nome;
  }
  let saida = dic.empresa[chave];
  const cod = texto.match(/^\s*(\d{4,6})\s*-\s*/);
  if (cod) saida = `${fakeCodigo_(dic, cod[1])} - ${saida}`;
  if (!ehMaiusculo_(texto)) saida = tituloCaixa_(saida);
  const cidade = texto.match(/\s*-\s*([^-\/]+\/[A-Za-z]{2})\s*$/);
  if (cidade && !cod) saida += ` - ${cidade[1]}`;      // cidade/UF original, sem mudar a caixa
  return saida;
}

function fakeFantasia_(dic, valor, nomeFake) {
  const texto = String(valor == null ? "" : valor).trim();
  if (!texto) return valor;
  const chave = normalizar_(texto);
  if (!dic.fantasia[chave]) {
    const base = nomeFake ? String(nomeFake).replace(/^\d+\s*-\s*/, "").split(" ").slice(0, 2).join(" ")
                          : `${sortear_(EMPRESA_A_)} ${sortear_(EMPRESA_B_)}`;
    dic.fantasia[chave] = base.slice(0, 20);
  }
  return dic.fantasia[chave];
}

function fakeFatura_(dic, valor) {
  if (valor === "" || valor == null) return valor;
  let texto = valor;
  if (valor instanceof Date) texto = `${valor.getFullYear()}/${valor.getMonth() + 1}`;   // "8932/1" lido como data
  if (typeof valor === "number") {
    const k = String(Math.round(valor));
    if (!dic.fatura[k]) dic.fatura[k] = digitosAleatorios_(k.length);
    return Number(dic.fatura[k]);
  }
  texto = String(texto);
  return texto.replace(/\d+/, base => {
    if (!dic.fatura[base]) dic.fatura[base] = digitosAleatorios_(base.length);
    return dic.fatura[base];
  });
}

// ---------------------------------------------------------------- papéis das colunas
function papelDaColuna_(cabecalho) {
  const h = normalizar_(cabecalho).replace(/_/g, " ");
  if (!h) return null;
  if (h.includes("CNPJ") || h.includes("CPF")) return "doc";
  if (h.includes("VENDEDOR")) return "vendedor";
  if (h.includes("URL")) return "url";
  if (h.includes("NOME REAL DO ARQUIVO")) return "arquivo";
  if (h === "FANTASIA") return "fantasia";
  if (h === "CODIGO" || h.startsWith("CODIGO ")) return "codigo";
  if (h.startsWith("NOME ")) return "empresa";
  if (h.includes("FATURA") || h === "SERIE/NF" || h === "N NOTA" || h === "NO NOTA") return "fatura";
  if (h === "ID") return "id";
  if (h.includes("SALDO") || h.includes("RESERVA") || h === "VALOR" || h.includes("VALOR DA NOTA") || h.includes("TOTAL ACUMULADO") || h.includes("DISTRIBUIDO") || h === "RETIDO" || h === "ORFAO") return "dinheiro";
  if (h === "CLIENTE" || h === "EMPRESA" || h === "NOME" || h.includes("RAZAO SOCIAL") || h.startsWith("EMPRESA ")) return "empresa";
  return null;
}

// ---------------------------------------------------------------- principal
function randomizarPlanilhaDemo() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  if (CONFIG_RANDOM.idsProducao.indexOf(ss.getId()) !== -1) {
    throw new Error("Esta é a planilha de PRODUÇÃO. Rode o randomizador numa cópia (ex.: '[DEMO] ...').");
  }
  const dic = novoDicionario_();
  const fator = Math.round((0.8 + Math.random() * 0.4) * 1000) / 1000;
  const log = [];

  ss.getSheets().forEach(aba => {
    const nome = aba.getName();
    if (CONFIG_RANDOM.abasIgnoradas.indexOf(nome) !== -1) return;
    if (CONFIG_RANDOM.abasSoFormulas.indexOf(nome) !== -1) { cabecalhoCarteira_(aba, log); return; }
    const n = randomizarAba_(aba, dic, fator);
    if (n) log.push(`${nome}: ${n} células`);
  });

  // Textos livres (ex.: "Retido — FULANO inativo", "Carteira Fulano") com nomes de vendedores
  ss.getSheets().forEach(aba => {
    if (CONFIG_RANDOM.abasSoFormulas.indexOf(aba.getName()) === -1) trocarVendedoresEmTexto_(aba, dic);
  });
  randomizarRelatorio_(ss, fator);

  SpreadsheetApp.flush();
  const vazamentos = verificarVazamentos_(ss, dic);
  const msg = `Fator de valores: ×${fator}\n${log.join("\n")}\n\n` +
    `Vendedores: ${Object.keys(dic.vendedor).length} · Empresas: ${Object.keys(dic.empresa).length} · Raízes de CNPJ: ${Object.keys(dic.raiz).length}\n` +
    (vazamentos.length ? `⚠️ Restaram ${vazamentos.length} ocorrências reais, ex.: ${vazamentos.slice(0, 5).join(" | ")}`
                       : "✅ Nenhum nome, CNPJ ou vendedor real encontrado após a troca.");
  console.log(msg);
  try { SpreadsheetApp.getUi().alert("Randomização concluída", msg, SpreadsheetApp.getUi().ButtonSet.OK); } catch (e) {}
}

// Procura blocos de tabela (linha de cabeçalho com ≥ 2 colunas reconhecidas) e troca coluna a coluna
function randomizarAba_(aba, dic, fator) {
  const ultimaLinha = aba.getLastRow(), ultimaCol = aba.getLastColumn();
  if (ultimaLinha < 2 || ultimaCol < 1) return 0;
  const rng = aba.getRange(1, 1, ultimaLinha, ultimaCol);
  const valores = rng.getValues();
  const formulas = rng.getFormulas();
  let alteradas = 0;

  let r = 0;
  const limite = Math.min(valores.length, CONFIG_RANDOM.linhasDeCabecalhoProcuradas);
  while (r < valores.length) {
    const papeis = valores[r].map(papelDaColuna_);
    const reconhecidas = papeis.filter(Boolean).length;
    if (r >= limite || reconhecidas < (r === 0 ? 1 : 2)) { r++; continue; }

    // linhas da tabela: até a primeira linha totalmente vazia
    let fim = r + 1;
    while (fim < valores.length && valores[fim].some(v => v !== "" && v !== null)) fim++;
    const iDoc = papeis.indexOf("doc");
    // documento "dono" de cada coluna: o mais próximo à esquerda (ex.: cnpj_pagante → nome_pagante)
    const docDaColuna = papeis.map((p, c) => { let k = -1; for (let j = 0; j < c; j++) if (papeis[j] === "doc") k = j; return k !== -1 ? k : iDoc; });

    for (let c = 0; c < papeis.length; c++) {
      const papel = papeis[c];
      if (!papel) continue;
      if (formulas.slice(r + 1, fim).some(l => l[c])) continue;   // nunca sobrescreve fórmula
      const coluna = [];
      for (let i = r + 1; i < fim; i++) {
        const v = valores[i][c];
        const iDocCol = docDaColuna[c];
        const raiz = iDocCol !== -1 ? String(valores[i][iDocCol]).replace(/\D/g, "").padStart(14, "0").slice(0, 8) : "";
        let novo = v;
        if (papel === "doc") novo = fakeDocumento_(dic, v);
        else if (papel === "vendedor") novo = fakeVendedor_(dic, v);
        else if (papel === "empresa") novo = fakeEmpresa_(dic, v, raiz);
        else if (papel === "fantasia") {
          const iEmp = papeis.indexOf("empresa");
          novo = fakeFantasia_(dic, v, iEmp !== -1 ? fakeEmpresa_(dic, valores[i][iEmp], raiz) : null);
        }
        else if (papel === "codigo") novo = v === "" ? v : fakeCodigo_(dic, String(v).padStart(6, "0"));
        else if (papel === "fatura") novo = fakeFatura_(dic, v);
        else if (papel === "id") novo = v === "" ? v : (typeof v === "number" ? Number(digitosAleatorios_(String(v).length)) : digitosAleatorios_(String(v).length));
        else if (papel === "url") novo = "";
        else if (papel === "arquivo") novo = (v === "" || v === "-") ? v : "Carteira " + tituloCaixa_(fakeVendedorDaLinha_(dic, valores[i], papeis));
        else if (papel === "dinheiro") novo = typeof v === "number" ? Math.round(v * fator * 100) / 100 : v;
        coluna.push([novo]);
        if (novo !== v) alteradas++;
      }
      if (!coluna.length) continue;
      const destino = aba.getRange(r + 2, c + 1, coluna.length, 1);
      if (papel === "doc" || papel === "codigo" || (papel === "fatura" && coluna.some(x => typeof x[0] === "string"))) destino.setNumberFormat("@");
      destino.setValues(coluna);
    }
    r = fim;
  }
  return alteradas;
}

function fakeVendedorDaLinha_(dic, linha, papeis) {
  const i = papeis.indexOf("vendedor");
  return i !== -1 ? String(fakeVendedor_(dic, linha[i])) : "DEMO";
}

// "Carteira: FULANO" no Dashboard e na Consulta do template
function cabecalhoCarteira_(aba, log) {
  [["Dashboard", "C3"], ["Consulta", "H1"]].forEach(([nome, cel]) => {
    if (aba.getName() !== nome) return;
    const c = aba.getRange(cel);
    if (!c.getFormula() && /^\s*Carteira/i.test(String(c.getValue()))) {
      c.setValue("Carteira: " + CONFIG_RANDOM.vendedorDaCarteira);
      log.push(`${nome}!${cel}: cabeçalho da carteira`);
    }
  });
}

function trocarVendedoresEmTexto_(aba, dic) {
  const reais = Object.keys(dic.vendedor);
  if (!reais.length || aba.getLastRow() < 1) return;
  const rng = aba.getDataRange();
  const valores = rng.getValues(), formulas = rng.getFormulas();
  const alteradas = new Set();
  // regex por vendedor, sem acento e sem diferenciar maiúsculas
  const regras = reais.map(chave => ({
    re: new RegExp(chave.split(" ").map(p => p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("\\s+"), "i"),
    fake: dic.vendedor[chave]
  }));
  for (let i = 0; i < valores.length; i++) for (let j = 0; j < valores[i].length; j++) {
    const v = valores[i][j];
    if (typeof v !== "string" || formulas[i][j] || v.length < 5) continue;
    const semAcento = v.normalize("NFD").replace(/[̀-ͯ]/g, "");
    let novo = semAcento, achou = false;
    regras.forEach(r => { if (r.re.test(novo)) { novo = novo.replace(new RegExp(r.re.source, "gi"), m => ehMaiusculo_(m) ? r.fake : tituloCaixa_(r.fake)); achou = true; } });
    if (achou) { aba.getRange(i + 1, j + 1).setValue(novo); alteradas.add(i); }
  }
  return alteradas.size;
}

// Relatório: valores em R$ soltos (coluna C do resumo) e textos com "R$ ..."
function randomizarRelatorio_(ss, fator) {
  const aba = ss.getSheetByName("Relatório");
  if (!aba) return;
  const ultima = Math.min(aba.getLastRow(), 39);
  if (ultima < 1) return;
  const rng = aba.getRange(1, 1, ultima, Math.max(3, aba.getLastColumn()));
  const valores = rng.getValues(), formulas = rng.getFormulas();
  for (let i = 0; i < valores.length; i++) for (let j = 0; j < valores[i].length; j++) {
    if (formulas[i][j]) continue;
    const v = valores[i][j];
    let novo = v;
    if (j === 2 && typeof v === "number" && i >= 7 && i <= 20) novo = Math.round(v * fator * 100) / 100;
    else if (typeof v === "string" && /R\$\s*[\d.]+,\d{2}/.test(v)) {
      novo = v.replace(/R\$\s*([\d.]+,\d{2})/g, (m, num) => {
        const n = Number(num.replace(/\./g, "").replace(",", ".")) * fator;
        return "R$ " + n.toFixed(2).replace(".", ",").replace(/\B(?=(\d{3})+,)/g, ".");
      });
    }
    if (novo !== v) aba.getRange(i + 1, j + 1).setValue(novo);
  }
}

// Confere se sobrou algum valor real (CNPJ, vendedor ou nome de empresa) em qualquer aba
function verificarVazamentos_(ss, dic) {
  const docs = dic.reais.docs, vend = new Set([...dic.reais.vendedores].map(normalizar_)),
        emp = new Set([...dic.reais.empresas].map(e => normalizar_(e)).filter(e => e.length >= 6));
  const achados = [];
  ss.getSheets().forEach(aba => {
    if (aba.getLastRow() < 1) return;
    aba.getDataRange().getDisplayValues().forEach(l => l.forEach(v => {
      if (!v || achados.length > 50) return;
      const n = normalizar_(v), d = v.replace(/\D/g, "");
      if ((d.length >= 11 && (docs.has(d) || docs.has(d.padStart(14, "0")))) || vend.has(n) || emp.has(n)) achados.push(`${aba.getName()}: ${v}`);
    }));
  });
  return achados;
}

// Reconfere a planilha a qualquer momento (ex.: depois que Dashboard/Cálculos/Consulta recalcularem).
// Como nada real fica guardado, ela procura o que ainda pareceria real: nomes e raízes de CNPJ das
// distribuidoras e links de planilhas.
function verificarDemo() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const raizes = Object.keys(CONFIG_RANDOM.raizesDistribuidoras);
  const achados = [];
  ss.getSheets().forEach(aba => {
    if (aba.getLastRow() < 1) return;
    aba.getDataRange().getDisplayValues().forEach((l, i) => l.forEach((v, j) => {
      if (!v || achados.length > 30) return;
      const d = v.replace(/\D/g, "");
      if ((d.length >= 12 && raizes.indexOf(d.padStart(14, "0").slice(0, 8)) !== -1) || /docs\.google\.com/.test(v) ||
          /IPIRANGA|VIBRA|RAIZEN|RAÍZEN|ALESAT/i.test(v))
        achados.push(`${aba.getName()}!${String.fromCharCode(65 + j)}${i + 1}: ${v.slice(0, 60)}`);
    }));
  });
  const msg = achados.length ? "Verifique:\n" + achados.join("\n") : "✅ Nenhuma distribuidora real, raiz de CNPJ real conhecida ou link de planilha encontrado.";
  console.log(msg);
  try { SpreadsheetApp.getUi().alert("Verificação da DEMO", msg, SpreadsheetApp.getUi().ButtonSet.OK); } catch (e) {}
}
