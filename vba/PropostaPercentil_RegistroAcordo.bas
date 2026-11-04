'==============================================================================
' CTA SMART - PROPOSTA PERCENTIL + REGISTRO DE ACORDO
'------------------------------------------------------------------------------
'   Module5  -> aloca TITULOS INTEIROS. Parcelas de valores irregulares.
'   Module6  -> parte do FLUXO DE CAIXA. Regular, mas sobra caixa na ultima.
'   ESTE     -> entrada = X% do total; saldo em N parcelas IGUAIS derivadas do
'               proprio total. Alocacao FIFO. Fecha exatamente, sem sobra.
'
' Duas saidas a partir do MESMO plano:
'   EmitirProposta  -> PROPOSTA_NEGOCIACAO (documento do cliente; a aba e
'                      refeita a cada geracao)
'   EmitirRegistro  -> REGISTRO_ACORDO (planilha operacional da baixa;
'                      CUMULATIVA - so acrescenta, nunca limpa). As linhas
'                      gravadas sao ENVIADAS para a aba ACORDOS da planilha de
'                      inadimplencia (Module9_EnvioPlanilha).
'
' O STATUS ACORDO nao e mais perguntado: entra como "Em Dia" e a planilha de
' inadimplencia recalcula todo dia pelas baixas do CIGAM (Quitado / Em Dia /
' Acordo Quebrado). O TERMO, se ficar em branco, recebe o ID do acordo
' (AC-<cod cliente>-<aaaammdd>), que agrupa as linhas do mesmo acordo.
'
' Depende de Module0_Nucleo e Module9_EnvioPlanilha.
'
' NOTA SOBRE FORMATO DE MOEDA
' Em NumberFormat o "$" NAO e literal: o Excel troca pelo simbolo monetario do
' sistema, que no pt-BR e "R$". Por isso "R$ #,##0.00" renderiza "RR$".
' A forma correta e o literal entre aspas duplas: """R$ ""#,##0.00"
'==============================================================================
Option Explicit

'--- Layout da aba REGISTRO_ACORDO (= aba ACORDOS da planilha de inadimplencia)
Public Const ABA_REGISTRO As String = "REGISTRO_ACORDO"
Public Const REG_LIN_CAB  As Long = 2     ' linha 1 = totais, linha 2 = cabecalho
Public Const REG_LIN_INI  As Long = 3

Public Const RG_STATUS   As String = "A"
Public Const RG_RESP     As String = "B"
Public Const RG_EMPRESA  As String = "C"
Public Const RG_CNPJ     As String = "D"
Public Const RG_DOC      As String = "E"
Public Const RG_NF       As String = "F"
Public Const RG_ATRASO   As String = "G"
Public Const RG_VENC     As String = "H"
Public Const RG_VLRORIG  As String = "I"
Public Const RG_JUROS    As String = "J"
Public Const RG_VLRTOT   As String = "K"
Public Const RG_CJUROS   As String = "L"
Public Const RG_CTITULO  As String = "M"
Public Const RG_DTPGTO   As String = "N"
Public Const RG_VLRPAGO  As String = "O"
Public Const RG_VLRPARC  As String = "P"
Public Const RG_FORMA    As String = "Q"
Public Const RG_TERMO    As String = "R"
' --- acrescentadas: sem elas o registro nao fecha quando um titulo e partido
Public Const RG_NPGTO    As String = "S"
Public Const RG_ALOCADO  As String = "T"
Public Const RG_SALDO    As String = "U"
' --- V = resultado do envio para a planilha (Module9_EnvioPlanilha.RG_ENVIO)

Public Const STATUS_INICIAL As String = "Em Dia"
Public Const FMT_MOEDA   As String = """R$ ""#,##0.00"

'--- Um titulo (ou fracao de titulo) dentro de UM pagamento ------------------
Public Type AlocItem
    LinhaCalc     As Long
    Doc           As String
    NF            As String
    chave         As String    ' "DOC x / NF y" - usada na proposta
    Categoria     As String
    Venc          As Date
    Atraso        As Long
    ValorOriginal As Double
    Juros         As Double
    ValorTotal    As Double
    CobraJuros    As Boolean
    ValorAlocado  As Double    ' fracao deste titulo NESTE pagamento
    Parcial       As Boolean
    SaldoApos     As Double
    PrimeiraVez   As Boolean   ' TRUE na 1a linha do titulo no registro
End Type

'--- Um pagamento do plano (0 = entrada) ------------------------------------
Public Type PagPlano
    Numero As Long
    Data   As Date
    Valor  As Double
    NItens As Long
    Itens() As AlocItem
End Type

'--- Titulo em processamento (interno) --------------------------------------
Private Type TitPct
    linha         As Long
    Doc           As String
    NF            As String
    chave         As String
    Categoria     As String
    Venc          As Date
    Atraso        As Long
    ValorOriginal As Double
    Juros         As Double
    ValorAcordo   As Double
    CobraJuros    As Boolean
    saldo         As Double
    JaApareceu    As Boolean
    PagFinal      As Long
    DataFinal     As Date
End Type


'==============================================================================
' MACRO PRINCIPAL
'==============================================================================
Sub GerarPropostaPercentil()
    Dim ws As Worksheet
    Dim ult As Long, i As Long, j As Long, p As Long
    Dim t() As TitPct, n As Long
    Dim cliente As String, cnpj As String
    Dim total As Double
    Dim dataAcordo As Date
    Dim usarPagamento As Boolean

    Set ws = ActiveSheet
    If Not ValidaAba(ws) Then Exit Sub

    ult = UltimaLinha(ws)
    If ult < LIN_INI Then
        MsgBox "Nenhum dado na Calculadora.", vbExclamation, "CTA SMART"
        Exit Sub
    End If

    '--------------------------------------------------------------------------
    ' 1. Data de referencia
    '--------------------------------------------------------------------------
    Dim inRef As Variant, sug As String
    If IsDate(ws.Range(CEL_DATA_REF).Value) Then
        sug = Format$(CDate(ws.Range(CEL_DATA_REF).Value), "dd/mm/yyyy")
    Else
        sug = Format$(Date, "dd/mm/yyyy")
    End If
    inRef = InputBox("DATA DE REFERENCIA do acordo (dd/mm/aaaa)." & vbCrLf & _
                     "Juros congelados nesta data. Tambem e o vencimento da entrada.", _
                     "Data de Referencia", sug)
    If inRef = "" Then Exit Sub
    If Not IsDate(inRef) Then
        MsgBox "Data invalida.", vbCritical, "CTA SMART"
        Exit Sub
    End If
    dataAcordo = CDate(inRef)
    ws.Range(CEL_DATA_REF).Value = dataAcordo

    usarPagamento = (MsgBox("Respeitar a coluna L (pagamento ja realizado) como " & _
                            "corte dos juros dos titulos que a tiverem preenchida?", _
                            vbYesNo + vbQuestion, "Tratamento da coluna L") = vbYes)

    '--------------------------------------------------------------------------
    ' 2. Coleta (K = TRUE, linhas visiveis)
    '--------------------------------------------------------------------------
    Dim ocultos As Long
    n = 0
    ReDim t(1 To ult - LIN_INI + 1)

    For i = LIN_INI To ult
        If Bool7(ws.Cells(i, C_COBRA_TITULO).Value) Then
            If Not LinhaVisivel(ws, i) Then
                ocultos = ocultos + 1
            ElseIf Num7(ws.Cells(i, C_VALOR).Value) > 0 Then
                n = n + 1
                With t(n)
                    .linha = i
                    .Doc = CStr(ws.Cells(i, C_DOC).Value)
                    .NF = CStr(ws.Cells(i, C_NF).Value)
                    .chave = "DOC " & .Doc & " / NF " & .NF
                    .Categoria = CStr(ws.Cells(i, C_TIPO).Value)
                    If IsDate(ws.Cells(i, C_VENC).Value) Then
                        .Venc = CDate(ws.Cells(i, C_VENC).Value)
                    Else
                        .Venc = dataAcordo
                    End If
                    .ValorOriginal = Num7(ws.Cells(i, C_VALOR).Value)
                    .CobraJuros = Bool7(ws.Cells(i, C_COBRA_JUROS).Value)
                    .Atraso = DiasAtraso(.Venc, _
                                DataCorteTitulo(ws, i, dataAcordo, usarPagamento))
                    .Juros = CalcularJuros(.ValorOriginal, .Atraso, .CobraJuros)
                    .ValorAcordo = Round(.ValorOriginal + .Juros, 2)
                    .saldo = .ValorAcordo
                End With
                If cliente = "" Then
                    cliente = CStr(ws.Cells(i, C_CLIENTE).Value)
                    cnpj = CStr(ws.Cells(i, C_CNPJ).Value)
                End If
                total = total + t(n).ValorAcordo
            End If
        End If
    Next i

    If n = 0 Then
        MsgBox "Nenhum titulo marcado com valor valido nas linhas visiveis.", _
               vbExclamation, "CTA SMART"
        Exit Sub
    End If
    ReDim Preserve t(1 To n)
    total = Round(total, 2)

    If ocultos > 0 Then
        If MsgBox(ocultos & " titulo(s) marcados estao ocultos pelo filtro e " & _
                  "ficaram FORA do acordo." & vbCrLf & vbCrLf & "Continuar?", _
                  vbYesNo + vbExclamation, "Titulos filtrados") = vbNo Then Exit Sub
    End If

    '--- Ordenacao FIFO -----------------------------------------------------
    Dim tmp As TitPct
    For i = 1 To n - 1
        For j = i + 1 To n
            If t(j).Venc < t(i).Venc Or _
               (t(j).Venc = t(i).Venc And t(j).chave < t(i).chave) Then
                tmp = t(i): t(i) = t(j): t(j) = tmp
            End If
        Next j
    Next i

    '--------------------------------------------------------------------------
    ' 3. Parametros do acordo
    '--------------------------------------------------------------------------
    Dim inPct As Variant, pct As Double, valEntrada As Double
    inPct = InputBox("Percentual (%) de ENTRADA sobre o total de " & _
                     Format$(total, "#,##0.00") & ":", "Entrada", "20")
    If inPct = "" Then Exit Sub
    pct = ParsePercentual(inPct)
    If pct < 0 Or pct > 1 Then
        MsgBox "Percentual deve estar entre 0 e 100.", vbCritical, "CTA SMART"
        Exit Sub
    End If
    valEntrada = Round(total * pct, 2)

    Dim saldo As Double
    saldo = Round(total - valEntrada, 2)

    Dim nParc As Long
    If saldo > 0.004 Then
        Dim inN As Variant
        inN = InputBox("Saldo a parcelar: " & Format$(saldo, "#,##0.00") & vbCrLf & _
                       "Em quantas PARCELAS IGUAIS dividir?", "Parcelas", "3")
        If inN = "" Then Exit Sub
        nParc = CLng(ParseValor(inN))
        If nParc < 1 Then
            MsgBox "Numero de parcelas invalido.", vbCritical, "CTA SMART"
            Exit Sub
        End If
    End If

    '--------------------------------------------------------------------------
    ' 4. Cadencia
    '--------------------------------------------------------------------------
    Dim usaDiaFixo As Boolean, diaFixo As Long, intervalo As Long
    If nParc > 0 Then
        Dim inCad As Variant
        inCad = InputBox("Vencimento das parcelas:" & vbCrLf & _
                         "1 = Dia fixo do mes" & vbCrLf & _
                         "2 = Intervalo de dias", "Cadencia", "1")
        If inCad = "" Then Exit Sub
        Select Case Trim$(CStr(inCad))
            Case "1"
                usaDiaFixo = True
                Dim inDia As Variant
                inDia = InputBox("Dia fixo do mes (1 a 31):", "Dia Fixo", "10")
                If inDia = "" Then Exit Sub
                diaFixo = CLng(ParseValor(inDia))
                If diaFixo < 1 Or diaFixo > 31 Then
                    MsgBox "Dia deve estar entre 1 e 31.", vbCritical, "CTA SMART"
                    Exit Sub
                End If
            Case "2"
                usaDiaFixo = False
                Dim inInt As Variant
                inInt = InputBox("Intervalo em dias entre parcelas:", "Intervalo", "30")
                If inInt = "" Then Exit Sub
                intervalo = CLng(ParseValor(inInt))
                If intervalo < 1 Then
                    MsgBox "Intervalo deve ser maior que zero.", vbCritical, "CTA SMART"
                    Exit Sub
                End If
            Case Else
                MsgBox "Opcao invalida.", vbCritical, "CTA SMART"
                Exit Sub
        End Select
    End If

    '--------------------------------------------------------------------------
    ' 5. Dados do registro (perguntados uma vez, aplicados a todas as linhas)
    '    STATUS nao e perguntado: entra STATUS_INICIAL e a planilha recalcula.
    '--------------------------------------------------------------------------
    Dim gerarReg As Boolean
    Dim responsavel As String, statusAcordo As String, forma As String, termo As String

    gerarReg = (MsgBox("Alem da proposta, firmar este acordo (aba " & ABA_REGISTRO & _
                       " e planilha de inadimplencia)?", vbYesNo + vbQuestion, "Registro") = vbYes)
    If gerarReg Then
        responsavel = Trim$(CStr(InputBox("RESPONSAVEL pelo acordo:", "Responsavel", "")))
        statusAcordo = STATUS_INICIAL
        forma = Trim$(CStr(InputBox("FORMA de pagamento (Boleto, PIX, Transferencia...):", _
                                    "Forma", "Boleto")))
        termo = Trim$(CStr(InputBox("TERMO / numero do acordo:", "Termo", _
                                    IdAcordoPadrao(cliente, cnpj, dataAcordo))))
        If Len(termo) = 0 Then termo = IdAcordoPadrao(cliente, cnpj, dataAcordo)
    End If

    On Error GoTo Falha
    Turbo True

    '--------------------------------------------------------------------------
    ' 6. Montagem dos pagamentos
    '    A ULTIMA parcela absorve o residuo, entao soma(pagamentos) = total.
    '--------------------------------------------------------------------------
    Dim pags() As PagPlano, nPag As Long
    Dim temEntrada As Boolean
    temEntrada = (valEntrada > 0.004)

    nPag = nParc + IIf(temEntrada, 1, 0)
    If nPag = 0 Then
        Turbo False
        MsgBox "Plano vazio: entrada de 0% e nenhuma parcela.", vbExclamation, "CTA SMART"
        Exit Sub
    End If
    ReDim pags(1 To nPag)

    Dim k As Long: k = 0
    If temEntrada Then
        k = k + 1
        pags(k).Numero = 0
        pags(k).Data = dataAcordo
        pags(k).Valor = valEntrada
    End If

    Dim valParcela As Double, acum As Double
    If nParc > 0 Then
        valParcela = Round(saldo / nParc, 2)
        acum = 0
        For p = 1 To nParc
            k = k + 1
            pags(k).Numero = p
            If usaDiaFixo Then
                pags(k).Data = VencDiaFixo(dataAcordo, p, diaFixo)
            Else
                pags(k).Data = dataAcordo + (p * intervalo)
            End If
            If p < nParc Then
                pags(k).Valor = valParcela
                acum = acum + valParcela
            Else
                pags(k).Valor = Round(saldo - acum, 2)
            End If
        Next p
    End If

    '--------------------------------------------------------------------------
    ' 7. Alocacao FIFO dos titulos sobre os pagamentos
    '--------------------------------------------------------------------------
    Dim idx As Long: idx = 1
    Dim disp As Double, need As Double

    For k = 1 To nPag
        pags(k).NItens = 0
        ReDim pags(k).Itens(1 To n)
        disp = pags(k).Valor

        Do While disp > 0.004 And idx <= n
            need = t(idx).saldo
            pags(k).NItens = pags(k).NItens + 1

            With pags(k).Itens(pags(k).NItens)
                .LinhaCalc = t(idx).linha
                .Doc = t(idx).Doc
                .NF = t(idx).NF
                .chave = t(idx).chave
                .Categoria = t(idx).Categoria
                .Venc = t(idx).Venc
                .Atraso = t(idx).Atraso
                .ValorOriginal = t(idx).ValorOriginal
                .Juros = t(idx).Juros
                .ValorTotal = t(idx).ValorAcordo
                .CobraJuros = t(idx).CobraJuros
                .PrimeiraVez = Not t(idx).JaApareceu
            End With
            t(idx).JaApareceu = True

            If disp >= need - 0.004 Then
                pags(k).Itens(pags(k).NItens).ValorAlocado = need
                pags(k).Itens(pags(k).NItens).Parcial = False
                pags(k).Itens(pags(k).NItens).SaldoApos = 0
                disp = Round(disp - need, 2)
                t(idx).saldo = 0
                t(idx).PagFinal = pags(k).Numero
                t(idx).DataFinal = pags(k).Data
                idx = idx + 1
            Else
                pags(k).Itens(pags(k).NItens).ValorAlocado = disp
                pags(k).Itens(pags(k).NItens).Parcial = True
                t(idx).saldo = Round(need - disp, 2)
                pags(k).Itens(pags(k).NItens).SaldoApos = t(idx).saldo
                disp = 0
            End If
        Loop

        If pags(k).NItens > 0 Then
            ReDim Preserve pags(k).Itens(1 To pags(k).NItens)
        End If
    Next k

    '--- Conferencia -------------------------------------------------------
    Dim somaPag As Double
    For k = 1 To nPag
        somaPag = somaPag + pags(k).Valor
    Next k
    If Abs(somaPag - total) > 0.01 Or idx <= n Then
        Turbo False
        MsgBox "Inconsistencia no plano:" & vbCrLf & _
               "Soma dos pagamentos: " & Format$(somaPag, "#,##0.00") & vbCrLf & _
               "Total apurado: " & Format$(total, "#,##0.00") & vbCrLf & _
               "Titulos nao alocados: " & IIf(idx <= n, n - idx + 1, 0) & vbCrLf & vbCrLf & _
               "Nada foi gerado.", vbCritical, "CTA SMART"
        Exit Sub
    End If

    '--------------------------------------------------------------------------
    ' 8. Gravacao do plano em N/O/P da Calculadora (coluna L intocada)
    '--------------------------------------------------------------------------
    For i = 1 To n
        With ws
            .Cells(t(i).linha, C_PLANO_DATA).Value = t(i).DataFinal
            .Cells(t(i).linha, C_PLANO_DATA).NumberFormat = "dd/mm/yyyy"
            .Cells(t(i).linha, C_PLANO_PARC).Value = t(i).PagFinal
            .Cells(t(i).linha, C_PLANO_VALOR).Value = t(i).ValorAcordo
            .Cells(t(i).linha, C_PLANO_VALOR).NumberFormat = FMT_MOEDA
        End With
    Next i

    '--------------------------------------------------------------------------
    ' 9. Saidas
    '--------------------------------------------------------------------------
    Dim nomeLimpo As String
    nomeLimpo = cliente
    If InStr(nomeLimpo, " - ") > 0 Then _
        nomeLimpo = Mid$(nomeLimpo, InStr(nomeLimpo, " - ") + 3)

    Dim termos As String
    If nParc > 0 Then
        termos = Format$(pct, "0%") & " de entrada + " & nParc & " parcela(s) de R$ " & _
                 Format$(valParcela, "#,##0.00")
    Else
        termos = "Pagamento integral a vista"
    End If

    EmitirProposta pags, nPag, nomeLimpo, cnpj, dataAcordo, total, termos

    Dim linhasReg As Long, rIniReg As Long, msgEnvio As String
    If gerarReg Then
        linhasReg = EmitirRegistro(pags, nPag, cliente, cnpj, _
                                   responsavel, statusAcordo, forma, termo, rIniReg)
        If linhasReg < 0 Then      ' cancelado no registro
            Turbo False
            ThisWorkbook.Worksheets(ABA_PROPOSTA).Activate
            MsgBox "Proposta gerada. O lancamento no registro foi cancelado.", _
                   vbExclamation, "CTA SMART"
            Exit Sub
        End If
        EnviarLinhasRegistro rIniReg, rIniReg + linhasReg - 1, msgEnvio
    End If

    Turbo False
    ThisWorkbook.Worksheets(ABA_PROPOSTA).Activate

    MsgBox "Acordo gerado." & vbCrLf & vbCrLf & _
           "Total: R$ " & Format$(total, "#,##0.00") & vbCrLf & _
           "Entrada: R$ " & Format$(valEntrada, "#,##0.00") & " (" & Format$(pct, "0%") & ")" & vbCrLf & _
           "Parcelas: " & nParc & " de R$ " & Format$(valParcela, "#,##0.00") & vbCrLf & vbCrLf & _
           "Proposta: aba " & ABA_PROPOSTA & vbCrLf & _
           IIf(gerarReg, "Registro: " & linhasReg & " linha(s) em " & ABA_REGISTRO & _
                         " (termo " & termo & ")" & vbCrLf & _
                         "Planilha de inadimplencia: " & msgEnvio, _
                         "Registro: nao lancado") & vbCrLf & vbCrLf & _
           "Plano em N/O/P. Coluna L intocada.", _
           vbInformation, "CTA SMART"
    Exit Sub

Falha:
    Turbo False
    MsgBox "Erro ao gerar acordo: " & Err.Description, vbCritical, "CTA SMART"
End Sub


'==============================================================================
' EMISSOR DO REGISTRO OPERACIONAL  (aba CUMULATIVA)
'------------------------------------------------------------------------------
' Uma linha por par TITULO x PAGAMENTO, ordenada por No PGTO e, dentro de cada
' pagamento, por VENCIMENTO (ordem FIFO = ordem de trabalho da baixa).
'
' Regras que mantem a soma das colunas integra quando um titulo e partido:
'   VALOR ORIGINAL / JUROS / VALOR NF TOTAL -> so na PRIMEIRA linha do titulo
'   VALOR DE PARCELA                        -> so na PRIMEIRA linha do pagamento
'   VALOR ALOCADO                           -> em TODAS as linhas
'        soma por titulo   = VALOR NF TOTAL
'        soma por pagamento = VALOR DE PARCELA
'   VALOR PAGO                              -> sempre em branco (a colega baixa)
'
' Usado pelas duas macros (GerarPropostaPercentil e GerarPropostaNegociacao).
' Retorna quantas linhas gravou, ou -1 se o usuario cancelou. Em linhaIni
' devolve a primeira linha gravada (para o envio a planilha).
'==============================================================================
Public Function EmitirRegistro(pags() As PagPlano, ByVal nPag As Long, _
                               ByVal empresa As String, ByVal cnpj As String, _
                               ByVal responsavel As String, ByVal statusAcordo As String, _
                               ByVal forma As String, ByVal termo As String, _
                               Optional ByRef linhaIni As Long) As Long
    Dim ws As Worksheet
    Dim r As Long, k As Long, i As Long, nEscritas As Long
    Dim existentes As Long, primeira As Long

    '--- Aba: cria se nao existir; se existir, NUNCA limpa -------------------
    On Error Resume Next
    Set ws = ThisWorkbook.Worksheets(ABA_REGISTRO)
    On Error GoTo 0

    If ws Is Nothing Then
        Set ws = ThisWorkbook.Worksheets.Add(After:=ThisWorkbook.Worksheets(ThisWorkbook.Worksheets.Count))
        ws.Name = ABA_REGISTRO
        MontarCabecalhoRegistro ws
    ElseIf Len(Trim$(CStr(ws.Cells(REG_LIN_CAB, RG_EMPRESA).Value))) = 0 Then
        MontarCabecalhoRegistro ws
    End If

    '--- Ja existe acordo lancado para este CNPJ? ----------------------------
    Dim ultReg As Long
    ultReg = ws.Cells(ws.Rows.Count, RG_EMPRESA).End(xlUp).Row
    If ultReg < REG_LIN_INI Then ultReg = REG_LIN_INI - 1

    For r = REG_LIN_INI To ultReg
        If Trim$(CStr(ws.Cells(r, RG_CNPJ).Value)) = Trim$(cnpj) Then
            existentes = existentes + 1
            If primeira = 0 Then primeira = r
        End If
    Next r

    If existentes > 0 Then
        Dim resp As VbMsgBoxResult
        resp = MsgBox("Ja existem " & existentes & " linha(s) para o CNPJ " & cnpj & _
                      " no registro (a partir da linha " & primeira & ")." & vbCrLf & vbCrLf & _
                      "SIM      = substituir (apaga as antigas e lanca as novas)" & vbCrLf & _
                      "NAO      = acrescentar mesmo assim (acordo novo)" & vbCrLf & _
                      "CANCELAR = nao lancar nada" & vbCrLf & vbCrLf & _
                      "Na planilha de inadimplencia, o acordo com o mesmo TERMO e " & _
                      "substituido; com TERMO diferente, entra como acordo novo.", _
                      vbYesNoCancel + vbExclamation, "Acordo ja registrado")
        If resp = vbCancel Then
            EmitirRegistro = -1
            Exit Function
        End If
        If resp = vbYes Then
            For r = ultReg To REG_LIN_INI Step -1
                If Trim$(CStr(ws.Cells(r, RG_CNPJ).Value)) = Trim$(cnpj) Then
                    ws.Rows(r).Delete
                End If
            Next r
            ultReg = ws.Cells(ws.Rows.Count, RG_EMPRESA).End(xlUp).Row
            If ultReg < REG_LIN_INI Then ultReg = REG_LIN_INI - 1
        End If
    End If

    '--- Gravacao ------------------------------------------------------------
    Dim rIni As Long
    rIni = ultReg + 1
    r = rIni

    Dim nParcelas As Long
    For k = 1 To nPag
        If pags(k).Numero > 0 Then nParcelas = nParcelas + 1
    Next k

    For k = 1 To nPag
        For i = 1 To pags(k).NItens
            With pags(k).Itens(i)
                ws.Cells(r, RG_STATUS).Value = statusAcordo
                ws.Cells(r, RG_RESP).Value = responsavel
                ws.Cells(r, RG_EMPRESA).Value = empresa
                ws.Cells(r, RG_CNPJ).NumberFormat = "@"
                ws.Cells(r, RG_CNPJ).Value = cnpj
                ' DOC e NF como texto: "165/1" nao pode virar data
                ws.Cells(r, RG_DOC).NumberFormat = "@"
                ws.Cells(r, RG_DOC).Value = .Doc
                ws.Cells(r, RG_NF).NumberFormat = "@"
                ws.Cells(r, RG_NF).Value = .NF
                ws.Cells(r, RG_VENC).Value = .Venc
                ws.Cells(r, RG_CJUROS).Value = IIf(.CobraJuros, "SIM", "NAO")
                ws.Cells(r, RG_CTITULO).Value = "SIM"
                ws.Cells(r, RG_DTPGTO).Value = pags(k).Data
                ws.Cells(r, RG_FORMA).Value = forma
                ws.Cells(r, RG_TERMO).Value = termo

                ws.Cells(r, RG_NPGTO).Value = IIf(pags(k).Numero = 0, "ENTRADA", _
                                                  "PARCELA " & pags(k).Numero & "/" & nParcelas)
                ws.Cells(r, RG_ALOCADO).Value = .ValorAlocado
                ws.Cells(r, RG_SALDO).Value = .SaldoApos

                ' Valores do TITULO so na primeira linha dele: evita soma dupla
                If .PrimeiraVez Then
                    ws.Cells(r, RG_ATRASO).Value = .Atraso
                    ws.Cells(r, RG_VLRORIG).Value = .ValorOriginal
                    ws.Cells(r, RG_JUROS).Value = .Juros
                    ws.Cells(r, RG_VLRTOT).Value = .ValorTotal
                End If

                ' Destaque quando a linha e fracao de titulo
                If .Parcial Or Not .PrimeiraVez Then
                    ws.Range(ws.Cells(r, RG_STATUS), ws.Cells(r, RG_SALDO)).Font.Italic = True
                    ws.Cells(r, RG_ALOCADO).Font.Color = RGB(170, 90, 0)
                End If
            End With

            ' VALOR DE PARCELA so na primeira linha do bloco do pagamento
            If i = 1 Then
                ws.Cells(r, RG_VLRPARC).Value = pags(k).Valor
                ws.Cells(r, RG_VLRPARC).Font.Bold = True
                ws.Range(ws.Cells(r, RG_STATUS), ws.Cells(r, RG_SALDO)) _
                  .Borders(xlEdgeTop).LineStyle = xlContinuous
            End If

            r = r + 1
            nEscritas = nEscritas + 1
        Next i
    Next k

    '--- Formatos do bloco recem-escrito -------------------------------------
    If nEscritas > 0 Then
        ws.Range(ws.Cells(rIni, RG_VENC), ws.Cells(r - 1, RG_VENC)).NumberFormat = "dd/mm/yyyy"
        ws.Range(ws.Cells(rIni, RG_DTPGTO), ws.Cells(r - 1, RG_DTPGTO)).NumberFormat = "dd/mm/yyyy"
        ws.Range(ws.Cells(rIni, RG_VLRORIG), ws.Cells(r - 1, RG_VLRTOT)).NumberFormat = FMT_MOEDA
        ws.Range(ws.Cells(rIni, RG_VLRPAGO), ws.Cells(r - 1, RG_VLRPARC)).NumberFormat = FMT_MOEDA
        ws.Range(ws.Cells(rIni, RG_ALOCADO), ws.Cells(r - 1, RG_SALDO)).NumberFormat = FMT_MOEDA
        ws.Range(ws.Cells(rIni, RG_ATRASO), ws.Cells(r - 1, RG_ATRASO)).NumberFormat = "0"
    End If

    AtualizarTotaisRegistro ws
    linhaIni = rIni
    EmitirRegistro = nEscritas
End Function


'==============================================================================
Private Sub MontarCabecalhoRegistro(ws As Worksheet)
    Dim c As Long

    ws.Cells(1, RG_DTPGTO).Value = "TOTAL EM ACORDO:"
    ws.Cells(1, RG_DTPGTO).Font.Bold = True
    ws.Cells(1, RG_DTPGTO).HorizontalAlignment = xlRight

    ws.Cells(REG_LIN_CAB, RG_STATUS).Value = "STATUS ACORDO"
    ws.Cells(REG_LIN_CAB, RG_RESP).Value = "RESPONS" & Chr(193) & "VEL"
    ws.Cells(REG_LIN_CAB, RG_EMPRESA).Value = "EMPRESA"
    ws.Cells(REG_LIN_CAB, RG_CNPJ).Value = "CNPJ"
    ws.Cells(REG_LIN_CAB, RG_DOC).Value = "DOC"
    ws.Cells(REG_LIN_CAB, RG_NF).Value = "NFS-e"
    ws.Cells(REG_LIN_CAB, RG_ATRASO).Value = "ATRASO"
    ws.Cells(REG_LIN_CAB, RG_VENC).Value = "VENCIMENTO"
    ws.Cells(REG_LIN_CAB, RG_VLRORIG).Value = "VALOR ORIGINAL"
    ws.Cells(REG_LIN_CAB, RG_JUROS).Value = "JUROS"
    ws.Cells(REG_LIN_CAB, RG_VLRTOT).Value = "VALOR NF TOTAL"
    ws.Cells(REG_LIN_CAB, RG_CJUROS).Value = "COBRA JUROS?"
    ws.Cells(REG_LIN_CAB, RG_CTITULO).Value = "COBRA T" & Chr(205) & "TULO?"
    ws.Cells(REG_LIN_CAB, RG_DTPGTO).Value = "DATA DE PAGAMENTO"
    ws.Cells(REG_LIN_CAB, RG_VLRPAGO).Value = "VALOR PAGO"
    ws.Cells(REG_LIN_CAB, RG_VLRPARC).Value = "VALOR DE PARCELA"
    ws.Cells(REG_LIN_CAB, RG_FORMA).Value = "FORMA"
    ws.Cells(REG_LIN_CAB, RG_TERMO).Value = "TERMO"
    ws.Cells(REG_LIN_CAB, RG_NPGTO).Value = "N" & Chr(186) & " PGTO"
    ws.Cells(REG_LIN_CAB, RG_ALOCADO).Value = "VALOR ALOCADO"
    ws.Cells(REG_LIN_CAB, RG_SALDO).Value = "SALDO AP" & Chr(211) & "S"
    ws.Cells(REG_LIN_CAB, RG_ENVIO).Value = "ENVIO PLANILHA"

    With ws.Range(ws.Cells(REG_LIN_CAB, RG_STATUS), ws.Cells(REG_LIN_CAB, RG_ENVIO))
        .Font.Bold = True
        .Interior.Color = RGB(0, 80, 136)
        .Font.Color = vbWhite
        .HorizontalAlignment = xlCenter
        .WrapText = True
    End With
    ws.Rows(REG_LIN_CAB).RowHeight = 30

    ' Coluna que a colega preenche fica destacada
    ws.Cells(REG_LIN_CAB, RG_VLRPAGO).Interior.Color = RGB(17, 202, 160)

    ws.Columns(RG_STATUS).ColumnWidth = 14
    ws.Columns(RG_RESP).ColumnWidth = 12
    ws.Columns(RG_EMPRESA).ColumnWidth = 38
    ws.Columns(RG_CNPJ).ColumnWidth = 19
    ws.Columns(RG_DOC).ColumnWidth = 11
    ws.Columns(RG_NF).ColumnWidth = 11
    ws.Columns(RG_ATRASO).ColumnWidth = 8
    ws.Columns(RG_VENC).ColumnWidth = 12
    For c = ws.Columns(RG_VLRORIG).Column To ws.Columns(RG_VLRTOT).Column
        ws.Columns(c).ColumnWidth = 15
    Next c
    ws.Columns(RG_CJUROS).ColumnWidth = 12
    ws.Columns(RG_CTITULO).ColumnWidth = 12
    ws.Columns(RG_DTPGTO).ColumnWidth = 16
    ws.Columns(RG_VLRPAGO).ColumnWidth = 15
    ws.Columns(RG_VLRPARC).ColumnWidth = 16
    ws.Columns(RG_FORMA).ColumnWidth = 13
    ws.Columns(RG_TERMO).ColumnWidth = 20
    ws.Columns(RG_NPGTO).ColumnWidth = 14
    ws.Columns(RG_ALOCADO).ColumnWidth = 15
    ws.Columns(RG_SALDO).ColumnWidth = 14
    ws.Columns(RG_ENVIO).ColumnWidth = 30

    On Error Resume Next
    ws.Range(ws.Cells(REG_LIN_CAB, RG_STATUS), ws.Cells(REG_LIN_CAB, RG_ENVIO)).AutoFilter
    On Error GoTo 0
End Sub


'==============================================================================
' Totais de controle na linha 1.
' A conferencia central: SOMA(VALOR ALOCADO) - SOMA(VALOR NF TOTAL) = 0.
' Se der diferente de zero, a celula fica vermelha: algum titulo foi alocado
' a mais ou a menos.
'==============================================================================
Private Sub AtualizarTotaisRegistro(ws As Worksheet)
    Dim ult As Long
    ult = ws.Cells(ws.Rows.Count, RG_EMPRESA).End(xlUp).Row
    If ult < REG_LIN_INI Then Exit Sub

    ws.Cells(1, RG_VLRPAGO).Formula = _
        "=SUM(" & RG_VLRTOT & REG_LIN_INI & ":" & RG_VLRTOT & ult & ")"
    ws.Cells(1, RG_VLRPAGO).NumberFormat = FMT_MOEDA
    ws.Cells(1, RG_VLRPAGO).Font.Bold = True

    ws.Cells(1, RG_NPGTO).Value = "CONFERENCIA:"
    ws.Cells(1, RG_NPGTO).HorizontalAlignment = xlRight
    ws.Cells(1, RG_NPGTO).Font.Bold = True

    ws.Cells(1, RG_ALOCADO).Formula = _
        "=SUM(" & RG_ALOCADO & REG_LIN_INI & ":" & RG_ALOCADO & ult & ")-SUM(" & _
        RG_VLRTOT & REG_LIN_INI & ":" & RG_VLRTOT & ult & ")"
    ws.Cells(1, RG_ALOCADO).NumberFormat = FMT_MOEDA
    ws.Cells(1, RG_ALOCADO).Font.Bold = True

    On Error Resume Next
    ws.Cells(1, RG_ALOCADO).FormatConditions.Delete
    With ws.Cells(1, RG_ALOCADO).FormatConditions.Add(xlCellValue, xlNotEqual, "=0")
        .Font.Color = RGB(200, 0, 0)
        .Interior.Color = RGB(255, 220, 220)
    End With
    On Error GoTo 0
End Sub


'==============================================================================
' RENDERIZADOR DA PROPOSTA (documento do cliente)
'==============================================================================
Public Sub EmitirProposta(pags() As PagPlano, ByVal nPag As Long, _
                          ByVal cliente As String, ByVal cnpj As String, _
                          ByVal dataRef As Date, ByVal total As Double, _
                          ByVal termos As String)
    Dim ws As Worksheet, shp As Shape
    Dim r As Long, k As Long, i As Long
    Dim nParcelas As Long, temParcial As Boolean

    For k = 1 To nPag
        If pags(k).Numero > 0 Then nParcelas = nParcelas + 1
        For i = 1 To pags(k).NItens
            If pags(k).Itens(i).Parcial Then temParcial = True
        Next i
    Next k

    On Error Resume Next
    Set ws = ThisWorkbook.Worksheets(ABA_PROPOSTA)
    On Error GoTo 0
    If ws Is Nothing Then
        Set ws = ThisWorkbook.Worksheets.Add(After:=ThisWorkbook.Worksheets(ThisWorkbook.Worksheets.Count))
        ws.Name = ABA_PROPOSTA
    Else
        ws.Cells.Clear
        For Each shp In ws.Shapes
            shp.Delete
        Next shp
    End If

    ws.Columns("A").ColumnWidth = 3
    ws.Columns("B").ColumnWidth = 40
    ws.Columns("C").ColumnWidth = 28
    ws.Columns("D").ColumnWidth = 18

    With ws.Range("B2:D2")
        .Merge
        .Value = "CTA SMART - AUTOMACAO DE ABASTECIMENTO"
        .Font.Bold = True: .Font.Size = 12: .Font.Color = RGB(0, 80, 136)
        .HorizontalAlignment = xlCenter
    End With
    With ws.Range("B3:D3")
        .Merge
        .Value = "PROPOSTA DE ACORDO DE DEBITOS"
        .Font.Bold = True: .Font.Size = 10: .Font.Color = RGB(17, 202, 160)
        .HorizontalAlignment = xlCenter
    End With

    ws.Range("B5").Value = "CLIENTE: " & cliente
    ws.Range("B5").Font.Bold = True
    ws.Range("B6").Value = "CNPJ/CPF: " & cnpj
    ws.Range("B6").Font.Color = RGB(100, 100, 100)

    With ws.Range("B8:D8")
        .Merge
        .Value = "RESUMO DA PROPOSTA"
        .Font.Bold = True: .Interior.Color = RGB(0, 80, 136)
        .Font.Color = vbWhite: .HorizontalAlignment = xlCenter
    End With

    ws.Range("B9").Value = "Total consolidado (juros ate a data de referencia):"
    ws.Range("D9").Value = total
    ws.Range("B10").Value = "Data de referencia:"
    ws.Range("D10").Value = dataRef
    ws.Range("D10").NumberFormat = "dd/mm/yyyy"
    ws.Range("B11").Value = "Termos:"
    ws.Range("D11").Value = termos
    ws.Range("D11").Font.Italic = True
    ws.Range("B12").Value = "Numero de pagamentos:"
    ws.Range("D12").Value = nPag & " (" & IIf(nPag - nParcelas > 0, "entrada + ", "") & _
                            nParcelas & " parcela(s))"
    ws.Range("D9").NumberFormat = FMT_MOEDA
    ws.Range("B9:D12").Borders(xlInsideHorizontal).LineStyle = xlThin
    ws.Range("D9:D12").HorizontalAlignment = xlRight

    r = 15
    For k = 1 To nPag
        With ws.Range(ws.Cells(r, "B"), ws.Cells(r, "D"))
            .Merge
            If pags(k).Numero = 0 Then
                .Value = "ENTRADA - vencimento " & Format$(pags(k).Data, "dd/mm/yyyy")
                .Interior.Color = RGB(17, 202, 160)
            Else
                .Value = "PARCELA " & pags(k).Numero & " DE " & nParcelas & _
                         " - vencimento " & Format$(pags(k).Data, "dd/mm/yyyy")
                .Interior.Color = RGB(0, 80, 136)
            End If
            .Font.Bold = True: .Font.Color = vbWhite
            .HorizontalAlignment = xlCenter
        End With

        r = r + 1
        ws.Cells(r, "B").Value = "Documento"
        ws.Cells(r, "C").Value = "Categoria"
        ws.Cells(r, "D").Value = "Valor"
        With ws.Range(ws.Cells(r, "B"), ws.Cells(r, "D"))
            .Font.Bold = True: .Font.Size = 9
            .Interior.Color = RGB(235, 238, 242)
        End With

        For i = 1 To pags(k).NItens
            r = r + 1
            With pags(k).Itens(i)
                ws.Cells(r, "B").Value = "   " & .chave & _
                    IIf(.Parcial, "   (abatimento parcial - resta " & _
                        Format$(.SaldoApos, "#,##0.00") & ")", "")
                ws.Cells(r, "C").Value = .Categoria
                ws.Cells(r, "D").Value = .ValorAlocado
                If .Parcial Then
                    ws.Range(ws.Cells(r, "B"), ws.Cells(r, "D")).Font.Italic = True
                    ws.Cells(r, "B").Font.Color = RGB(170, 90, 0)
                Else
                    ws.Cells(r, "B").Font.Color = RGB(70, 70, 70)
                End If
            End With
            ws.Cells(r, "D").NumberFormat = FMT_MOEDA
        Next i

        r = r + 1
        ws.Cells(r, "B").Value = IIf(pags(k).Numero = 0, "SUBTOTAL ENTRADA", _
                                     "SUBTOTAL PARCELA " & pags(k).Numero)
        ws.Cells(r, "D").Value = pags(k).Valor
        ws.Cells(r, "D").NumberFormat = FMT_MOEDA
        With ws.Range(ws.Cells(r, "B"), ws.Cells(r, "D"))
            .Font.Bold = True
            .Borders(xlEdgeTop).LineStyle = xlContinuous
        End With

        r = r + 2
    Next k

    ws.Cells(r, "B").Value = "TOTAL GERAL DO ACORDO"
    ws.Cells(r, "D").Value = total
    ws.Cells(r, "D").NumberFormat = FMT_MOEDA
    With ws.Range(ws.Cells(r, "B"), ws.Cells(r, "D"))
        .Font.Bold = True: .Font.Size = 11
        .BorderAround xlContinuous, xlMedium
    End With

    r = r + 2
    ws.Cells(r, "B").Value = "Valores congelados em " & Format$(dataRef, "dd/mm/yyyy") & _
                             ". Nao ha incidencia de juros sobre o prazo do acordo."
    ws.Cells(r, "B").Font.Italic = True
    ws.Cells(r, "B").Font.Color = RGB(120, 120, 120)

    If temParcial Then
        r = r + 1
        ws.Cells(r, "B").Value = "Itens marcados como abatimento parcial sao quitados " & _
                                 "ao longo de mais de um pagamento."
        ws.Cells(r, "B").Font.Italic = True
        ws.Cells(r, "B").Font.Color = RGB(170, 90, 0)
    End If

    r = r + 3
    ws.Cells(r, "B").Value = "____________________________________"
    ws.Cells(r, "D").Value = "____________________________________"
    r = r + 1
    ws.Cells(r, "B").Value = "CTA SMART - Financeiro"
    ws.Cells(r, "D").Value = cliente
    ws.Range(ws.Cells(r, "B"), ws.Cells(r, "D")).Font.Bold = True
End Sub


'==============================================================================
Private Function Bool7(ByVal v As Variant) As Boolean
    If IsEmpty(v) Or IsNull(v) Then
        Bool7 = False
    ElseIf VarType(v) = vbBoolean Then
        Bool7 = CBool(v)
    ElseIf IsNumeric(v) Then
        Bool7 = (CDbl(v) <> 0)
    Else
        Bool7 = (UCase$(Trim$(CStr(v))) = "TRUE" Or UCase$(Trim$(CStr(v))) = "VERDADEIRO")
    End If
End Function

Private Function Num7(ByVal v As Variant) As Double
    If IsNumeric(v) Then Num7 = CDbl(v) Else Num7 = 0
End Function
