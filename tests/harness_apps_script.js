// Roda as regras de apps_script/ControleVibra.gs no Node, pra comparar com
// controle_vibra.py (tests/test_apps_script.py). Lê {linhas, aba, desde} do
// stdin e devolve as linhas A a S que o script gravaria, com datas em
// dd/mm/aaaa. Sem os serviços do Apps Script: só as funções de regra.
const fs = require('fs');
const vm = require('vm');

const contexto = {};
vm.createContext(contexto);
const codigo = fs.readFileSync(__dirname + '/../apps_script/ControleVibra.gs', 'utf8');
vm.runInContext(codigo + '\nthis.__api = {montarTabela, linhasParaPlanilha, locaisSemCadastro, lerLocaisEntrega, SQL_NOTAS_VIBRA};', contexto);
const api = contexto.__api;

const entrada = JSON.parse(fs.readFileSync(0, 'utf8'));
const doisDigitos = n => String(n).padStart(2, '0');
const serializar = v => (v && typeof v.getFullYear === 'function')
  ? `${doisDigitos(v.getDate())}/${doisDigitos(v.getMonth() + 1)}/${v.getFullYear()}`
  : v;

if (entrada.somente_sql) {
  process.stdout.write(JSON.stringify({ sql: api.SQL_NOTAS_VIBRA }));
} else {
  const tabela = api.montarTabela(entrada.linhas, entrada.aba, entrada.desde, entrada.locais || []);
  const linhas = api.linhasParaPlanilha(tabela).map(l => l.map(serializar));
  const novos = api.locaisSemCadastro(tabela, api.lerLocaisEntrega(entrada.locais || []));
  process.stdout.write(JSON.stringify({ linhas, novos }));
}
