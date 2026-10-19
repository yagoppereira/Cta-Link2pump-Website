// Roda as regras de apps_script/ControleVibra.gs no Node, pra comparar com
// controle_vibra.py (tests/test_apps_script.py). Lê {linhas, aba, desde} do
// stdin e devolve as linhas A a S que o script gravaria, com datas em
// dd/mm/aaaa. Sem os serviços do Apps Script: só as funções de regra.
const fs = require('fs');
const vm = require('vm');

const contexto = {};
vm.createContext(contexto);
// os .gs do projeto dividem o mesmo escopo global, como no Apps Script
const codigo = ['ControleVibra.gs', 'FiltrosVibra.gs']
  .map(nome => fs.readFileSync(__dirname + '/../apps_script/' + nome, 'utf8')).join('\n');
vm.runInContext(codigo + '\nthis.__api = {montarTabela, linhasParaPlanilha, locaisSemCadastro, lerLocaisEntrega, '
  + 'SQL_NOTAS_VIBRA, FILTROS_VIBRA, formulaFiltro, resumirFiltro, OPCOES_FILTRO_RAPIDO, opcaoDoRotulo, '
  + 'textoResumo};', contexto);
const api = contexto.__api;

const entrada = JSON.parse(fs.readFileSync(0, 'utf8'));
const doisDigitos = n => String(n).padStart(2, '0');
const serializar = v => (v && typeof v.getFullYear === 'function')
  ? `${doisDigitos(v.getDate())}/${doisDigitos(v.getMonth() + 1)}/${v.getFullYear()}`
  : v;

if (entrada.filtros) {
  // células {"data": "aaaa-mm-dd"} viram Date, como no getValues
  const celula = v => (v && v.data ? new Date(v.data + 'T00:00:00') : v);
  const { colunas, linhas, de, ate } = entrada.filtros;
  const valores = linhas.map(l => l.map(celula));
  const saida = {};
  Object.keys(api.FILTROS_VIBRA).forEach(opcao => {
    const condicoes = api.FILTROS_VIBRA[opcao].condicoes(de, ate);
    saida[opcao] = { formula: api.formulaFiltro(condicoes, colunas, 3),
                     resumo: api.resumirFiltro(condicoes, colunas, valores) };
  });
  process.stdout.write(JSON.stringify({
    filtros: saida,
    opcoes: Array.from(api.OPCOES_FILTRO_RAPIDO),
    opcao_por_rotulo: Object.fromEntries(api.OPCOES_FILTRO_RAPIDO.map(r => [r, api.opcaoDoRotulo(r)])),
    aviso: api.textoResumo({ titulo: 'Pagos', nfs: 3, valor: 1234567.8, saldo: 0 }),
  }));
} else if (entrada.somente_sql) {
  process.stdout.write(JSON.stringify({ sql: api.SQL_NOTAS_VIBRA }));
} else {
  const tabela = api.montarTabela(entrada.linhas, entrada.aba, entrada.desde, entrada.locais || []);
  const linhas = api.linhasParaPlanilha(tabela).map(l => l.map(serializar));
  const novos = api.locaisSemCadastro(tabela, api.lerLocaisEntrega(entrada.locais || []));
  process.stdout.write(JSON.stringify({ linhas, novos }));
}
