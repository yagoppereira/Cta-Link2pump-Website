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
'   EmitirRegistro  -> tres abas operacionais CUMULATIVAS, com as mesmas
'                      colunas de entrada das abas da planilha de inadimplencia:
'
'        REG_ACORDO    -> ACORDOS_RESUMO   (1 linha por acordo,   colunas A:J)
'        REG_PARCELAS  -> ACORDOS_PARCELAS (1 linha por pagamento, colunas A:G)
'        REG_TITULOS   -> ACORDOS_TITULOS  (1 linha por titulo x pagamento, A:K)
'
'   As tres tabelas sao ligadas pelo ID ACORDO (AC-<cod cliente>-<aaaammdd>).
'   Depois de gerar, copie as linhas novas de cada aba REG_* e cole (somente
'   valores) no fim da aba correspondente na planilha Google. Status, atraso,
'   diagnostico e conferencia com o CIGAM sao calculados la, nao aqui.
'
' Depende de Module0_Nucleo.
'
' NOTA SOBRE FORMATO DE MOEDA
' Em NumberFormat o "$" NAO e literal: o Excel troca pelo simbolo monetario do
' sistema, que no pt-BR e "R$". Por isso "R$ #,##0.00" renderiza "RR$".
' A forma correta e o literal entre aspas duplas: """R$ ""#,##0.00"
'==============================================================================
Option Explicit

'--- Abas do registro operacional ------------------------------------------
Public Const ABA_REG_ACORDO   As String = "REG_ACORDO"
Public Const ABA_REG_PARCELAS As String = "REG_PARCELAS"
Public Const ABA_REG_TITULOS  As String = "REG_TITULOS"

' REG_ACORDO (= ACORDOS_RESUMO A:J)
Public Const RA_ID       As Long = 1
Public Const RA_DATA     As Long = 2
Public Const RA_RESP     As Long = 3
Public Const RA_EMPRESA  As Long = 4
Public Const RA_CNPJ     As Long = 5
Public Const RA_TOTAL    As Long = 6
Public Const RA_FORMA    As Long = 7
Public Const RA_TERMO    As Long = 8
Public Const RA_SITMAN   As Long = 9
Public Const RA_OBS      As Long = 10

' REG_PARCELAS (= ACORDOS_PARCELAS A:G)
Public Const RP_ID       As Long = 1
Public Const RP_NUM      As Long = 2
Public Const RP_VENC     As Long = 3
Public Const RP_VALOR    As Long = 4
Public Const RP_DTREC    As Long = 5
Public Const RP_VLREC    As Long = 6
Public Const RP_OBS      As Long = 7

' REG_TITULOS (= ACORDOS_TITULOS A:K)
Public Const RT_ID       As Long = 1
Public Const RT_NUM      As Long = 2
Public Const RT_EMPRESA  As Long = 3
Public Const RT_DOC      As Long = 4
Public Const RT_NF       As Long = 5
Public Const RT_VENC     As Long = 6
Public Const RT_VLRORIG  As Long = 7
Public Const RT_JUROS    As Long = 8
Public Const RT_VLRTIT   As Long = 9
Public Const RT_ALOCADO  As Long = 10
Public Const RT_SALDO    As Long = 11

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
    PrimeiraVez   As Boolean   ' TRUE na 1a linha do titulo no plano
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
    ' 5. Dados do registro (perguntados uma vez)
    '    O STATUS nao e mais perguntado: a planilha calcula a partir das
    '    parcelas e dos recebimentos.
    '--------------------------------------------------------------------------
    Dim gerarReg As Boolean
    Dim responsavel As String, forma As String, obs As String

    gerarReg = (MsgBox("Alem da proposta, lancar este acordo nas abas " & _
                       ABA_REG_ACORDO & " / " & ABA_REG_PARCELAS & " / " & _
                       ABA_REG_TITULOS & "?", vbYesNo + vbQuestion, "Registro") = vbYes)
    If gerarReg Then
        responsavel = Trim$(CStr(InputBox("RESPONSAVEL pelo acordo:", "Responsavel", "")))
        forma = Trim$(CStr(InputBox("FORMA de pagamento (Boleto, PIX, Transferencia...):", _
                                    "Forma", "Boleto")))
        obs = Trim$(CStr(InputBox("OBSERVACOES do acordo (pode ficar em branco):", _
                                  "Observacoes", "")))
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

    Dim idAcordo As String, resumoReg As String
    If gerarReg Then
        idAcordo = EmitirRegistro(pags, nPag, cliente, cnpj, dataAcordo, total, _
                                  responsavel, forma, termos, obs, resumoReg)
        If idAcordo = "" Then      ' cancelado no registro
            Turbo False
            ThisWorkbook.Worksheets(ABA_PROPOSTA).Activate
            MsgBox "Proposta gerada. O lancamento no registro foi cancelado.", _
                   vbExclamation, "CTA SMART"
            Exit Sub
        End If
    End If

    Turbo False
    ThisWorkbook.Worksheets(ABA_PROPOSTA).Activate

    MsgBox "Acordo gerado." & vbCrLf & vbCrLf & _
           "Total: R$ " & Format$(total, "#,##0.00") & vbCrLf & _
           "Entrada: R$ " & Format$(valEntrada, "#,##0.00") & " (" & Format$(pct, "0%") & ")" & vbCrLf & _
           "Parcelas: " & nParc & " de R$ " & Format$(valParcela, "#,##0.00") & vbCrLf & vbCrLf & _
           "Proposta: aba " & ABA_PROPOSTA & vbCrLf & _
           IIf(gerarReg, "Registro: acordo " & idAcordo & vbCrLf & resumoReg, _
                         "Registro: nao lancado") & vbCrLf & vbCrLf & _
           "Plano em N/O/P. Coluna L intocada.", _
           vbInformation, "CTA SMART"
    Exit Sub

Falha:
    Turbo False
    MsgBox "Erro ao gerar acordo: " & Err.Description, vbCritical, "CTA SMART"
End Sub


'==============================================================================
' EMISSOR DO REGISTRO OPERACIONAL  (tres abas CUMULATIVAS)
'------------------------------------------------------------------------------
' REG_ACORDO   : 1 linha  -> ID, data, responsavel, empresa, CNPJ, total, forma,
'                            condicao, situacao manual (vazia), observacoes
' REG_PARCELAS : 1 linha por pagamento (0 = entrada) -> vencimento e valor
'                previsto. DATA/VALOR RECEBIDO ficam em branco: sao preenchidos
'                na planilha Google quando o dinheiro entra.
' REG_TITULOS  : 1 linha por par TITULO x PAGAMENTO, em ordem FIFO.
'                Os valores do titulo se repetem em todas as linhas dele; as
'                somas da planilha usam so VALOR ALOCADO, entao nao ha soma
'                dupla:
'                    soma(ALOCADO) por pagamento = valor da parcela
'                    soma(ALOCADO) por titulo    = valor do titulo no acordo
'
' Retorna o ID do acordo, ou "" se o usuario cancelou. Em resumoReg devolve as
' faixas de linhas gravadas em cada aba (para copiar e colar na planilha).
'==============================================================================
Public Function EmitirRegistro(pags() As PagPlano, ByVal nPag As Long, _
                               ByVal empresa As String, ByVal cnpj As String, _
                               ByVal dataAcordo As Date, ByVal total As Double, _
                               ByVal responsavel As String, ByVal forma As String, _
                               ByVal condicao As String, ByVal obs As String, _
                               ByRef resumoReg As String) As String
    Dim wsA As Worksheet, wsP As Worksheet, wsT As Worksheet
    Dim k As Long, i As Long, r As Long
    Dim idAcordo As String

    Set wsA = GarantirAbaRegistro(ABA_REG_ACORDO, Array("ID ACORDO", "DATA DO ACORDO", _
                "RESPONSAVEL", "EMPRESA", "CNPJ", "TOTAL ACORDADO", "FORMA", _
                "CONDICAO / TERMO", "SITUACAO MANUAL", "OBSERVACOES"))
    Set wsP = GarantirAbaRegistro(ABA_REG_PARCELAS, Array("ID ACORDO", _
                "No PGTO (0 = ENTRADA)", "VENCIMENTO", "VALOR PREVISTO", _
                "DATA RECEBIMENTO", "VALOR RECEBIDO", "OBS. RECEBIMENTO"))
    Set wsT = GarantirAbaRegistro(ABA_REG_TITULOS, Array("ID ACORDO", _
                "No PGTO (0 = ENTRADA)", "EMPRESA", "FATURA (DOC)", "NFS-e", _
                "VENCIMENTO ORIGINAL", "VALOR ORIGINAL", "JUROS", _
                "VALOR DO TITULO NO ACORDO", "VALOR ALOCADO NESTA PARCELA", _
                "SALDO DO TITULO APOS A PARCELA"))

    '--- ID: AC-<codigo do cliente>-<aaaammdd> --------------------------------
    Dim codCliente As String
    codCliente = Trim$(empresa)
    If InStr(codCliente, " - ") > 0 Then codCliente = Left$(codCliente, InStr(codCliente, " - ") - 1)
    If Len(codCliente) = 0 Then codCliente = SoDigitos(cnpj)
    idAcordo = "AC-" & codCliente & "-" & Format$(dataAcordo, "yyyymmdd")

    If LinhaDoId(wsA, idAcordo) > 0 Then
        Dim resp As VbMsgBoxResult
        resp = MsgBox("O acordo " & idAcordo & " ja esta no registro." & vbCrLf & vbCrLf & _
                      "SIM      = substituir (apaga as linhas dele nas 3 abas e lanca de novo)" & vbCrLf & _
                      "NAO      = lancar como um acordo novo, com sufixo no ID" & vbCrLf & _
                      "CANCELAR = nao lancar nada" & vbCrLf & vbCrLf & _
                      "Se o acordo antigo ja foi colado na planilha Google, apague-o la tambem " & _
                      "ou marque SITUACAO MANUAL = RENEGOCIADO.", _
                      vbYesNoCancel + vbExclamation, "Acordo ja registrado")
        If resp = vbCancel Then
            EmitirRegistro = ""
            Exit Function
        End If
        If resp = vbYes Then
            ApagarLinhasDoId wsA, idAcordo
            ApagarLinhasDoId wsP, idAcordo
            ApagarLinhasDoId wsT, idAcordo
        Else
            Dim suf As Long: suf = 2
            Do While LinhaDoId(wsA, idAcordo & "-" & suf) > 0
                suf = suf + 1
            Loop
            idAcordo = idAcordo & "-" & suf
        End If
    End If

    '--- REG_ACORDO ----------------------------------------------------------
    Dim iniA As Long, iniP As Long, iniT As Long
    iniA = ProximaLinha(wsA)
    wsA.Cells(iniA, RA_ID).Value = idAcordo
    wsA.Cells(iniA, RA_DATA).Value = dataAcordo
    wsA.Cells(iniA, RA_RESP).Value = responsavel
    wsA.Cells(iniA, RA_EMPRESA).Value = Replace(empresa, vbLf, " ")
    wsA.Cells(iniA, RA_CNPJ).NumberFormat = "@"
    wsA.Cells(iniA, RA_CNPJ).Value = cnpj
    wsA.Cells(iniA, RA_TOTAL).Value = total
    wsA.Cells(iniA, RA_FORMA).Value = forma
    wsA.Cells(iniA, RA_TERMO).Value = condicao
    wsA.Cells(iniA, RA_OBS).Value = obs
    wsA.Cells(iniA, RA_DATA).NumberFormat = "dd/mm/yyyy"
    wsA.Cells(iniA, RA_TOTAL).NumberFormat = FMT_MOEDA

    '--- REG_PARCELAS --------------------------------------------------------
    iniP = ProximaLinha(wsP)
    r = iniP
    For k = 1 To nPag
        wsP.Cells(r, RP_ID).Value = idAcordo
        wsP.Cells(r, RP_NUM).Value = pags(k).Numero
        wsP.Cells(r, RP_VENC).Value = pags(k).Data
        wsP.Cells(r, RP_VALOR).Value = pags(k).Valor
        r = r + 1
    Next k
    wsP.Range(wsP.Cells(iniP, RP_VENC), wsP.Cells(r - 1, RP_VENC)).NumberFormat = "dd/mm/yyyy"
    wsP.Range(wsP.Cells(iniP, RP_VALOR), wsP.Cells(r - 1, RP_VALOR)).NumberFormat = FMT_MOEDA
    Dim fimP As Long: fimP = r - 1

    '--- REG_TITULOS ---------------------------------------------------------
    iniT = ProximaLinha(wsT)
    r = iniT
    For k = 1 To nPag
        For i = 1 To pags(k).NItens
            With pags(k).Itens(i)
                wsT.Cells(r, RT_ID).Value = idAcordo
                wsT.Cells(r, RT_NUM).Value = pags(k).Numero
                wsT.Cells(r, RT_EMPRESA).Value = Replace(empresa, vbLf, " ")
                ' DOC e NF como texto: "165/1" nao pode virar data
                wsT.Cells(r, RT_DOC).NumberFormat = "@"
                wsT.Cells(r, RT_DOC).Value = .Doc
                wsT.Cells(r, RT_NF).NumberFormat = "@"
                wsT.Cells(r, RT_NF).Value = .NF
                wsT.Cells(r, RT_VENC).Value = .Venc
                wsT.Cells(r, RT_VLRORIG).Value = .ValorOriginal
                wsT.Cells(r, RT_JUROS).Value = .Juros
                wsT.Cells(r, RT_VLRTIT).Value = .ValorTotal
                wsT.Cells(r, RT_ALOCADO).Value = .ValorAlocado
                wsT.Cells(r, RT_SALDO).Value = .SaldoApos
                If .Parcial Or Not .PrimeiraVez Then
                    wsT.Cells(r, RT_ALOCADO).Font.Color = RGB(170, 90, 0)
                End If
            End With
            ' Borda superior marca o inicio de cada pagamento
            If i = 1 Then
                wsT.Range(wsT.Cells(r, RT_ID), wsT.Cells(r, RT_SALDO)) _
                   .Borders(xlEdgeTop).LineStyle = xlContinuous
            End If
            r = r + 1
        Next i
    Next k
    Dim fimT As Long: fimT = r - 1
    If fimT >= iniT Then
        wsT.Range(wsT.Cells(iniT, RT_VENC), wsT.Cells(fimT, RT_VENC)).NumberFormat = "dd/mm/yyyy"
        wsT.Range(wsT.Cells(iniT, RT_VLRORIG), wsT.Cells(fimT, RT_SALDO)).NumberFormat = FMT_MOEDA
    End If

    resumoReg = ABA_REG_ACORDO & ": linha " & iniA & vbCrLf & _
                ABA_REG_PARCELAS & ": linhas " & iniP & " a " & fimP & vbCrLf & _
                ABA_REG_TITULOS & ": linhas " & iniT & " a " & fimT & vbCrLf & _
                "Copie essas linhas e cole (somente valores) no fim das abas " & _
                "ACORDOS_RESUMO, ACORDOS_PARCELAS e ACORDOS_TITULOS."
    EmitirRegistro = idAcordo
End Function


'==============================================================================
' Apoio do registro
'==============================================================================
Private Function GarantirAbaRegistro(ByVal nome As String, cab As Variant) As Worksheet
    Dim ws As Worksheet, c As Long
    On Error Resume Next
    Set ws = ThisWorkbook.Worksheets(nome)
    On Error GoTo 0

    If ws Is Nothing Then
        Set ws = ThisWorkbook.Worksheets.Add(After:=ThisWorkbook.Worksheets(ThisWorkbook.Worksheets.Count))
        ws.Name = nome
    End If

    If Len(Trim$(CStr(ws.Cells(1, 1).Value))) = 0 Then
        For c = LBound(cab) To UBound(cab)
            ws.Cells(1, c - LBound(cab) + 1).Value = cab(c)
        Next c
        With ws.Range(ws.Cells(1, 1), ws.Cells(1, UBound(cab) - LBound(cab) + 1))
            .Font.Bold = True
            .Font.Color = vbWhite
            .Interior.Color = RGB(17, 202, 160)
            .HorizontalAlignment = xlCenter
            .WrapText = True
        End With
        ws.Rows(1).RowHeight = 30
        ws.Columns(1).ColumnWidth = 22
        For c = 2 To UBound(cab) - LBound(cab) + 1
            ws.Columns(c).ColumnWidth = 16
        Next c
    End If
    Set GarantirAbaRegistro = ws
End Function

Private Function ProximaLinha(ws As Worksheet) As Long
    Dim u As Long
    u = ws.Cells(ws.Rows.Count, 1).End(xlUp).Row
    If u < 1 Then u = 1
    ProximaLinha = u + 1
End Function

Private Function LinhaDoId(ws As Worksheet, ByVal id As String) As Long
    Dim r As Long, u As Long
    u = ws.Cells(ws.Rows.Count, 1).End(xlUp).Row
    For r = 2 To u
        If Trim$(CStr(ws.Cells(r, 1).Value)) = id Then
            LinhaDoId = r
            Exit Function
        End If
    Next r
End Function

Private Sub ApagarLinhasDoId(ws As Worksheet, ByVal id As String)
    Dim r As Long, u As Long
    u = ws.Cells(ws.Rows.Count, 1).End(xlUp).Row
    For r = u To 2 Step -1
        If Trim$(CStr(ws.Cells(r, 1).Value)) = id Then ws.Rows(r).Delete
    Next r
End Sub

Private Function SoDigitos(ByVal s As String) As String
    Dim i As Long, ch As String
    For i = 1 To Len(s)
        ch = Mid$(s, i, 1)
        If ch Like "#" Then SoDigitos = SoDigitos & ch
    Next i
End Function


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
