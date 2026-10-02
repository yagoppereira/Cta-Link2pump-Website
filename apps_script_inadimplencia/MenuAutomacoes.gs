function onOpen() {
  const ui = SpreadsheetApp.getUi();
  ui.createMenu('⚙️ Automações')
    .addItem('1. Atualizar Bases e Base de Clientes (DW + Cidades + Regras)', 'atualizarBasesEConsolidar')
    .addItem('2. Distribuir Inadimplência', 'distribuirInadimplenciaPorVendedor')
    .addSeparator()
    .addItem('3. Validar Planilhas', 'sincronizarEValidarVendedores')
    .addItem('4. Gerar Planilhas de Vendedores Faltantes', 'gerarPlanilhasVendedoresFaltantes')
    .addItem('5. Atualizar Layout Planilha de Vendedores (do Template)', 'aplicarPatchLayoutVendedores')
    .addSeparator()
    .addItem('Só reconsolidar Base de Clientes (sem atualizar bases)', 'consolidarBaseInteligente')
    .addItem('🩺 Diagnóstico do sistema', 'diagnosticarSistema')
    .addToUi();
}
