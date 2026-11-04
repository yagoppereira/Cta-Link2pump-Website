'==============================================================================
' CTA SMART - GERADOR DE PROPOSTA DE NEGOCIACAO  (substitui Module5)
'------------------------------------------------------------------------------
' CORRECOES ESTRUTURAIS EM RELACAO A VERSAO ANTERIOR
'
' [1] A coluna L deixou de ser saida do modulo.
'     Antes o macro gravava em L o VENCIMENTO FUTURO das parcelas. A formula
'     da coluna E le L como data de corte dos juros; logo, gravar uma data
'     futura em L fazia o extrato recalcular juros ate aquela data e o total
'     da planilha divergir da proposta impressa. O plano agora vai para
'     N (venc. acordado), O (parcela) e P (valor congelado).
'
' [2] Titulos ja pagos nao sao mais reescritos.
'     No modo 2, todo titulo com L <= data do acordo tinha L sobrescrito com a
'     data do acordo, destruindo o historico real de pagamento.
'
' [3] Motor de juros unico (Module0_Nucleo). Antes a regra existia em tres
'     lugares (formula H, este modulo e o Module6) e podia divergir.
'
' [4] Knapsack: a versao antiga aceitava a combinacao mais proxima do alvo
'     mesmo estourando muito acima dele. Agora ha penalidade para estouro.
'     O fallback guloso (>15 titulos) passa a ordenar por valor decrescente
'     e nao forca mais o primeiro titulo quando nada cabe.
'
' [5] Conferencia de fechamento: entrada + parcelas tem de bater com o total.
'
' [6] Registro do acordo: ao firmar, as linhas vao para REGISTRO_ACORDO (o
'     mesmo emissor do GerarPropostaPercentil, titulos inteiros: cada titulo
'     cai inteiro em um pagamento) e sao enviadas para a aba ACORDOS da
'     planilha de inadimplencia (Module9_EnvioPlanilha).
'==============================================================================
Option Explicit

Private Type Titulo
    linha       As Long
    chave       As String
    Doc         As String
    NF          As String
    Categoria   As String
    Venc        As Date
    Atraso      As Long
    ValorBase   As Double
    CobraJuros  As Boolean
    Juros       As Double
    ValorAcordo As Double
    EhEntrada   As Boolean
    DataPlano   As Date
    Parcela     As Long
End Type

Sub GerarPropostaNegociacao()
    Dim ws As Worksheet, wsNeg As Worksheet
    Dim ult As Long, i As Long, j As Long, p As Long
    Dim tit() As Titulo, n As Long
    Dim cliente As String, cnpj As String, clienteReg As String
    Dim totalAcordo As Double
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
    ' 1. Data de referencia do acordo
    '--------------------------------------------------------------------------
    Dim entrada As Variant
    Dim sugestao As String
    If IsDate(ws.Range(CEL_DATA_REF).Value) Then
        sugestao = Format$(CDate(ws.Range(CEL_DATA_REF).Value), "dd/mm/yyyy")
    Else
        sugestao = Format$(Date, "dd/mm/yyyy")
    End If

    entrada = InputBox("DATA DE REFERENCIA do acordo (dd/mm/aaaa)." & vbCrLf & _
                       "Marco zero para juros e para o cronograma.", _
                       "Data de Referencia", sugestao)
    If entrada = "" Then Exit Sub
    If Not IsDate(entrada) Then
        MsgBox "Data invalida.", vbCritical, "CTA SMART"
        Exit Sub
    End If
    dataAcordo = CDate(entrada)
    ws.Range(CEL_DATA_REF).Value = dataAcordo   ' mantem a planilha coerente

    '--------------------------------------------------------------------------
    ' 2. Tratamento da coluna L (agora so como FATO, nunca como plano)
    '--------------------------------------------------------------------------
    Dim metodo As Variant
    metodo = InputBox("Como tratar a coluna L (data de pagamento ja realizado)?" & vbCrLf & vbCrLf & _
                      "1 = Respeitar L: titulos com data em L tem os juros " & _
                      "congelados naquela data" & vbCrLf & _
                      "2 = Ignorar L: juros de todos os titulos ate " & Format$(dataAcordo, "dd/mm/yyyy"), _
                      "Metodo de Calculo", "1")
    If metodo = "" Then Exit Sub
    Select Case Trim$(CStr(metodo))
        Case "1": usarPagamento = True
        Case "2": usarPagamento = False
        Case Else
            MsgBox "Opcao invalida.", vbCritical, "CTA SMART"
            Exit Sub
    End Select

    '--------------------------------------------------------------------------
    ' 3. Coleta dos titulos marcados (K = TRUE), respeitando o filtro
    '--------------------------------------------------------------------------
    Dim ocultosMarcados As Long
    n = 0
    ReDim tit(1 To ult - LIN_INI + 1)

    For i = LIN_INI To ult
        If CBool2(ws.Cells(i, C_COBRA_TITULO).Value) Then
            If Not LinhaVisivel(ws, i) Then
                ocultosMarcados = ocultosMarcados + 1
            Else
                Dim vb As Double
                vb = Val2(ws.Cells(i, C_VALOR).Value)
                If vb > 0 Then
                    n = n + 1
                    With tit(n)
                        .linha = i
                        .Doc = CStr(ws.Cells(i, C_DOC).Value)
                        .NF = CStr(ws.Cells(i, C_NF).Value)
                        .chave = "DOC " & .Doc & " / NF " & .NF
                        .Categoria = CStr(ws.Cells(i, C_TIPO).Value)
                        If IsDate(ws.Cells(i, C_VENC).Value) Then
                            .Venc = CDate(ws.Cells(i, C_VENC).Value)
                        End If
                        .ValorBase = vb
                        .CobraJuros = CBool2(ws.Cells(i, C_COBRA_JUROS).Value)

                        Dim dtCorte As Date, dias As Long
                        dtCorte = DataCorteTitulo(ws, i, dataAcordo, usarPagamento)
                        dias = DiasAtraso(.Venc, dtCorte)
                        .Atraso = dias
                        .Juros = CalcularJuros(.ValorBase, dias, .CobraJuros)
                        .ValorAcordo = Round(.ValorBase + .Juros, 2)
                    End With
                    If cliente = "" Then
                        cliente = CStr(ws.Cells(i, C_CLIENTE).Value)
                        clienteReg = cliente      ' "000123 - NOME", como na aba ACORDOS
                        If InStr(cliente, " - ") > 0 Then _
                            cliente = Mid$(cliente, InStr(cliente, " - ") + 3)
                        cnpj = CStr(ws.Cells(i, C_CNPJ).Value)
                    End If
                    totalAcordo = totalAcordo + tit(n).ValorAcordo
                End If
            End If
        End If
    Next i

    If n = 0 Then
        MsgBox "Nenhum titulo marcado com valor valido nas linhas visiveis.", _
               vbExclamation, "CTA SMART"
        Exit Sub
    End If
    ReDim Preserve tit(1 To n)

    If ocultosMarcados > 0 Then
        If MsgBox(ocultosMarcados & " titulo(s) marcados estao ocultos pelo filtro " & _
                  "e ficaram FORA desta proposta." & vbCrLf & vbCrLf & "Continuar?", _
                  vbYesNo + vbExclamation, "Titulos filtrados") = vbNo Then Exit Sub
    End If

    '--------------------------------------------------------------------------
    ' 4. Estrategia
    '--------------------------------------------------------------------------
    Dim modo As Variant
    modo = InputBox("Como definir ENTRADA e PARCELAS?" & vbCrLf & vbCrLf & _
                    "1 = Automatico: informo o % de entrada e o sistema escolhe " & _
                    "quais titulos compoem a entrada" & vbCrLf & _
                    "2 = Guiado pela coluna N: titulos com data ja definida em N " & _
                    "sao respeitados; o resto e distribuido agora", _
                    "Modo de Geracao", "1")
    If modo = "" Then Exit Sub
    If Trim$(CStr(modo)) <> "1" And Trim$(CStr(modo)) <> "2" Then
        MsgBox "Opcao invalida.", vbCritical, "CTA SMART"
        Exit Sub
    End If

    Dim qtdParcelas As Long, aAgendar As Long
    Dim pctAlvo As Double
    Dim precisaCadencia As Boolean

    If Trim$(CStr(modo)) = "1" Then
        Dim inPct As Variant
        inPct = InputBox("Percentual (%) de ENTRADA desejado:", "Entrada", "20")
        If inPct = "" Then Exit Sub
        pctAlvo = ParsePercentual(inPct)
        If pctAlvo < 0 Or pctAlvo > 1 Then
            MsgBox "Percentual deve estar entre 0 e 100.", vbCritical, "CTA SMART"
            Exit Sub
        End If

        SelecionarEntrada tit, n, totalAcordo * pctAlvo

    Else
        ' Modo 2: le o PLANO em N (nao mais a coluna L de pagamento realizado)
        For i = 1 To n
            Dim vN As Variant
            vN = ws.Cells(tit(i).linha, C_PLANO_DATA).Value
            If IsDate(vN) Then
                If CDate(vN) <= dataAcordo Then
                    tit(i).EhEntrada = True
                Else
                    tit(i).DataPlano = CDate(vN)
                End If
            End If
        Next i
    End If

    aAgendar = 0
    For i = 1 To n
        If Not tit(i).EhEntrada And tit(i).DataPlano = 0 Then aAgendar = aAgendar + 1
    Next i

    If aAgendar > 0 Then
        Dim inParc As Variant
        inParc = InputBox(aAgendar & " titulo(s) a agendar." & vbCrLf & _
                          "Em quantas PARCELAS dividir esse saldo?", _
                          "Parcelamento", "3")
        If inParc = "" Then Exit Sub
        qtdParcelas = CLng(ParseValor(inParc))
        If qtdParcelas < 0 Then
            MsgBox "Numero de parcelas invalido.", vbCritical, "CTA SMART"
            Exit Sub
        End If
        If qtdParcelas > aAgendar Then qtdParcelas = aAgendar
        precisaCadencia = (qtdParcelas > 0)
    End If

    '--------------------------------------------------------------------------
    ' 5. Cadencia
    '--------------------------------------------------------------------------
    Dim usaDiaFixo As Boolean, diaFixo As Long, intervalo As Long
    If precisaCadencia Then
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
    ' 5b. Dados do registro (perguntados antes de processar)
    '--------------------------------------------------------------------------
    Dim gerarReg As Boolean
    Dim responsavel As String, forma As String, termo As String

    gerarReg = (MsgBox("Alem da proposta, firmar este acordo (aba " & ABA_REGISTRO & _
                       " e planilha de inadimplencia)?", vbYesNo + vbQuestion, "Registro") = vbYes)
    If gerarReg Then
        responsavel = Trim$(CStr(InputBox("RESPONSAVEL pelo acordo:", "Responsavel", "")))
        forma = Trim$(CStr(InputBox("FORMA de pagamento (Boleto, PIX, Transferencia...):", _
                                    "Forma", "Boleto")))
        termo = Trim$(CStr(InputBox("TERMO / numero do acordo:", "Termo", _
                                    IdAcordoPadrao(clienteReg, cnpj, dataAcordo))))
        If Len(termo) = 0 Then termo = IdAcordoPadrao(clienteReg, cnpj, dataAcordo)
    End If

    On Error GoTo Falha
    Turbo True

    '--------------------------------------------------------------------------
    ' 6. Distribuicao dos titulos sem data (balanceamento por menor soma)
    '--------------------------------------------------------------------------
    If aAgendar > 0 And qtdParcelas > 0 Then
        Dim somaParc() As Double
        ReDim somaParc(1 To qtdParcelas)

        ' Ordem decrescente melhora o balanceamento (heuristica LPT)
        Dim ordem() As Long
        ordem = OrdemPorValorDesc(tit, n)

        For j = 1 To n
            i = ordem(j)
            If Not tit(i).EhEntrada And tit(i).DataPlano = 0 Then
                Dim menor As Long, menorSoma As Double
                menor = 1: menorSoma = somaParc(1)
                For p = 2 To qtdParcelas
                    If somaParc(p) < menorSoma Then
                        menorSoma = somaParc(p)
                        menor = p
                    End If
                Next p

                If usaDiaFixo Then
                    tit(i).DataPlano = VencDiaFixo(dataAcordo, menor, diaFixo)
                Else
                    tit(i).DataPlano = dataAcordo + (menor * intervalo)
                End If
                somaParc(menor) = somaParc(menor) + tit(i).ValorAcordo
            End If
        Next j
    End If

    '--------------------------------------------------------------------------
    ' 7. Consolidacao das parcelas por data unica
    '--------------------------------------------------------------------------
    Dim datas() As Date, nParc As Long
    nParc = 0
    For i = 1 To n
        If Not tit(i).EhEntrada Then
            Dim achou As Boolean: achou = False
            For p = 1 To nParc
                If datas(p) = tit(i).DataPlano Then achou = True: Exit For
            Next p
            If Not achou Then
                nParc = nParc + 1
                ReDim Preserve datas(1 To nParc)
                datas(nParc) = tit(i).DataPlano
            End If
        End If
    Next i

    For i = 1 To nParc - 1                      ' ordenacao cronologica
        For j = i + 1 To nParc
            If datas(j) < datas(i) Then
                Dim tmpD As Date
                tmpD = datas(i): datas(i) = datas(j): datas(j) = tmpD
            End If
        Next j
    Next i

    Dim somaEntrada As Double, somaParcela() As Double
    If nParc > 0 Then ReDim somaParcela(1 To nParc)

    For i = 1 To n
        If tit(i).EhEntrada Then
            tit(i).Parcela = 0
            tit(i).DataPlano = dataAcordo
            somaEntrada = somaEntrada + tit(i).ValorAcordo
        Else
            For p = 1 To nParc
                If datas(p) = tit(i).DataPlano Then
                    tit(i).Parcela = p
                    somaParcela(p) = somaParcela(p) + tit(i).ValorAcordo
                    Exit For
                End If
            Next p
        End If
    Next i

    '--------------------------------------------------------------------------
    ' 8. Gravacao do PLANO em N/O/P  (coluna L nao e tocada)
    '--------------------------------------------------------------------------
    For i = 1 To n
        With ws
            .Cells(tit(i).linha, C_PLANO_DATA).Value = tit(i).DataPlano
            .Cells(tit(i).linha, C_PLANO_DATA).NumberFormat = "dd/mm/yyyy"
            .Cells(tit(i).linha, C_PLANO_PARC).Value = tit(i).Parcela
            .Cells(tit(i).linha, C_PLANO_VALOR).Value = tit(i).ValorAcordo
            .Cells(tit(i).linha, C_PLANO_VALOR).NumberFormat = "#,##0.00"
        End With
    Next i

    '--------------------------------------------------------------------------
    ' 9. Conferencia de fechamento
    '--------------------------------------------------------------------------
    Dim confer As Double
    confer = somaEntrada
    For p = 1 To nParc
        confer = confer + somaParcela(p)
    Next p
    If Abs(confer - totalAcordo) > 0.01 Then
        Turbo False
        MsgBox "Inconsistencia de fechamento:" & vbCrLf & _
               "Soma do plano: " & Format$(confer, "#,##0.00") & vbCrLf & _
               "Total apurado: " & Format$(totalAcordo, "#,##0.00") & vbCrLf & vbCrLf & _
               "Proposta nao gerada.", vbCritical, "CTA SMART"
        Exit Sub
    End If

    '--------------------------------------------------------------------------
    ' 10. Aba de proposta
    '--------------------------------------------------------------------------
    Set wsNeg = MontarAbaProposta()
    EscreverProposta wsNeg, ws, tit, n, cliente, cnpj, dataAcordo, _
                     totalAcordo, somaEntrada, datas, somaParcela, nParc

    '--------------------------------------------------------------------------
    ' 11. Registro (REGISTRO_ACORDO) e envio para a planilha de inadimplencia
    '--------------------------------------------------------------------------
    Dim linhasReg As Long, rIniReg As Long, msgEnvio As String
    If gerarReg Then
        Dim pags() As PagPlano, nPag As Long
        MontarPagamentos tit, n, dataAcordo, somaEntrada, datas, somaParcela, nParc, pags, nPag
        linhasReg = EmitirRegistro(pags, nPag, clienteReg, cnpj, _
                                   responsavel, STATUS_INICIAL, forma, termo, rIniReg)
        If linhasReg > 0 Then
            EnviarLinhasRegistro rIniReg, rIniReg + linhasReg - 1, msgEnvio
        End If
    End If

    Turbo False
    wsNeg.Activate

    MsgBox "Proposta gerada." & vbCrLf & vbCrLf & _
           "Entrada: " & Format$(somaEntrada, "#,##0.00") & vbCrLf & _
           "Parcelado: " & Format$(totalAcordo - somaEntrada, "#,##0.00") & " em " & nParc & " parcela(s)" & vbCrLf & _
           "Total: " & Format$(totalAcordo, "#,##0.00") & vbCrLf & vbCrLf & _
           IIf(gerarReg, IIf(linhasReg > 0, "Registro: " & linhasReg & " linha(s) em " & _
                             ABA_REGISTRO & " (termo " & termo & ")" & vbCrLf & _
                             "Planilha de inadimplencia: " & msgEnvio, _
                             "Registro: cancelado"), "Registro: nao lancado") & vbCrLf & vbCrLf & _
           "O plano foi gravado nas colunas N, O e P." & vbCrLf & _
           "A coluna L (pagamento realizado) nao foi alterada.", _
           vbInformation, "CTA SMART"
    Exit Sub

Falha:
    Turbo False
    MsgBox "Erro ao gerar proposta: " & Err.Description, vbCritical, "CTA SMART"
End Sub


'==============================================================================
' Converte o plano de titulos inteiros no formato do registro (PagPlano):
' entrada (Numero 0) + uma parcela por data, cada titulo inteiro em um
' pagamento, em ordem de vencimento (ordem de trabalho da baixa).
'==============================================================================
Private Sub MontarPagamentos(tit() As Titulo, ByVal n As Long, ByVal dataAcordo As Date, _
                             ByVal somaEntrada As Double, datas() As Date, _
                             somaParcela() As Double, ByVal nParc As Long, _
                             pags() As PagPlano, ByRef nPag As Long)
    Dim temEntrada As Boolean, k As Long, p As Long, i As Long, j As Long
    Dim alvo As Long, ord() As Long, m As Long, t As Long

    For i = 1 To n
        If tit(i).EhEntrada Then temEntrada = True: Exit For
    Next i
    nPag = nParc + IIf(temEntrada, 1, 0)
    If nPag = 0 Then Exit Sub
    ReDim pags(1 To nPag)

    ' indices em ordem de vencimento
    ReDim ord(1 To n)
    For i = 1 To n
        ord(i) = i
    Next i
    For i = 1 To n - 1
        For j = i + 1 To n
            If tit(ord(j)).Venc < tit(ord(i)).Venc Then
                t = ord(i): ord(i) = ord(j): ord(j) = t
            End If
        Next j
    Next i

    k = 0
    For p = IIf(temEntrada, 0, 1) To nParc
        k = k + 1
        pags(k).Numero = p
        If p = 0 Then
            pags(k).Data = dataAcordo
            pags(k).Valor = Round(somaEntrada, 2)
            alvo = 0
        Else
            pags(k).Data = datas(p)
            pags(k).Valor = Round(somaParcela(p), 2)
            alvo = p
        End If
        ReDim pags(k).Itens(1 To n)
        m = 0
        For j = 1 To n
            i = ord(j)
            If tit(i).Parcela = alvo And (tit(i).EhEntrada = (alvo = 0)) Then
                m = m + 1
                With pags(k).Itens(m)
                    .LinhaCalc = tit(i).linha
                    .Doc = tit(i).Doc
                    .NF = tit(i).NF
                    .chave = tit(i).chave
                    .Categoria = tit(i).Categoria
                    .Venc = tit(i).Venc
                    .Atraso = tit(i).Atraso
                    .ValorOriginal = tit(i).ValorBase
                    .Juros = tit(i).Juros
                    .ValorTotal = tit(i).ValorAcordo
                    .CobraJuros = tit(i).CobraJuros
                    .ValorAlocado = tit(i).ValorAcordo
                    .Parcial = False
                    .SaldoApos = 0
                    .PrimeiraVez = True
                End With
            End If
        Next j
        pags(k).NItens = m
        If m > 0 Then ReDim Preserve pags(k).Itens(1 To m)
    Next p
End Sub


'==============================================================================
' Selecao dos titulos que compoem a entrada
' Objetivo: chegar o mais perto possivel do valor alvo, penalizando o estouro.
'==============================================================================
Private Sub SelecionarEntrada(tit() As Titulo, ByVal n As Long, ByVal alvo As Double)
    Dim i As Long, j As Long
    Dim melhorCusto As Double, custo As Double
    Const PENAL_ESTOURO As Double = 3#   ' estourar o alvo custa 3x mais que faltar

    For i = 1 To n
        tit(i).EhEntrada = False
    Next i
    If alvo <= 0 Then Exit Sub

    If n <= 16 Then
        '--- Busca exaustiva -------------------------------------------------
        Dim combos As Long, c As Long
        Dim soma As Double
        Dim melhorCombo As Long
        combos = 2 ^ n
        melhorCusto = 1E+30
        melhorCombo = 0

        For c = 1 To combos - 1
            soma = 0
            For j = 1 To n
                If (c And (2 ^ (j - 1))) <> 0 Then soma = soma + tit(j).ValorAcordo
            Next j
            If soma > alvo Then
                custo = (soma - alvo) * PENAL_ESTOURO
            Else
                custo = alvo - soma
            End If
            If custo < melhorCusto Then
                melhorCusto = custo
                melhorCombo = c
            End If
        Next c

        For j = 1 To n
            tit(j).EhEntrada = ((melhorCombo And (2 ^ (j - 1))) <> 0)
        Next j
    Else
        '--- Guloso por valor decrescente (first-fit decreasing) -------------
        Dim ordem() As Long
        Dim acum As Double
        ordem = OrdemPorValorDesc(tit, n)
        acum = 0
        For j = 1 To n
            i = ordem(j)
            If acum + tit(i).ValorAcordo <= alvo + 0.01 Then
                tit(i).EhEntrada = True
                acum = acum + tit(i).ValorAcordo
            End If
        Next j
        ' Se nada coube, nao forca titulo nenhum: a entrada fica zerada e o
        ' operador decide. (A versao antiga forcava o primeiro da lista.)
    End If
End Sub

Private Function OrdemPorValorDesc(tit() As Titulo, ByVal n As Long) As Long()
    Dim idx() As Long, i As Long, j As Long, t As Long
    ReDim idx(1 To n)
    For i = 1 To n
        idx(i) = i
    Next i
    For i = 1 To n - 1
        For j = i + 1 To n
            If tit(idx(j)).ValorAcordo > tit(idx(i)).ValorAcordo Then
                t = idx(i): idx(i) = idx(j): idx(j) = t
            End If
        Next j
    Next i
    OrdemPorValorDesc = idx
End Function


'==============================================================================
' Montagem da aba de proposta
'==============================================================================
Private Function MontarAbaProposta() As Worksheet
    Dim ws As Worksheet, shp As Shape

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
    ws.Columns("B").ColumnWidth = 38
    ws.Columns("C").ColumnWidth = 26
    ws.Columns("D").ColumnWidth = 18
    Set MontarAbaProposta = ws
End Function

Private Sub EscreverProposta(wsNeg As Worksheet, wsCalc As Worksheet, _
                             tit() As Titulo, ByVal n As Long, _
                             ByVal cliente As String, ByVal cnpj As String, _
                             ByVal dataAcordo As Date, ByVal total As Double, _
                             ByVal somaEntrada As Double, datas() As Date, _
                             somaParcela() As Double, ByVal nParc As Long)

    Dim r As Long, i As Long, p As Long
    Dim pctEfetiva As Double

    With wsNeg.Range("B2:D2")
        .Merge
        .Value = "CTA SMART - AUTOMACAO DE ABASTECIMENTO"
        .Font.Bold = True: .Font.Size = 12: .Font.Color = RGB(0, 80, 136)
        .HorizontalAlignment = xlCenter
    End With
    With wsNeg.Range("B3:D3")
        .Merge
        .Value = "PROPOSTA DE ACORDO DE DEBITOS"
        .Font.Bold = True: .Font.Size = 10: .Font.Color = RGB(17, 202, 160)
        .HorizontalAlignment = xlCenter
    End With

    wsNeg.Range("B5").Value = "CLIENTE: " & cliente
    wsNeg.Range("B5").Font.Bold = True
    wsNeg.Range("B6").Value = "CNPJ/CPF: " & cnpj
    wsNeg.Range("B6").Font.Color = RGB(100, 100, 100)

    With wsNeg.Range("B8:D8")
        .Merge
        .Value = "RESUMO DA PROPOSTA"
        .Font.Bold = True: .Interior.Color = RGB(0, 80, 136)
        .Font.Color = vbWhite: .HorizontalAlignment = xlCenter
    End With

    If total > 0 Then pctEfetiva = somaEntrada / total

    wsNeg.Range("B9").Value = "Total consolidado (com juros ate a data de referencia):"
    wsNeg.Range("D9").Value = total
    wsNeg.Range("B10").Value = "Data de referencia do acordo:"
    wsNeg.Range("D10").Value = dataAcordo
    wsNeg.Range("D10").NumberFormat = "dd/mm/yyyy"
    wsNeg.Range("B11").Value = "Entrada:"
    wsNeg.Range("D11").Value = somaEntrada
    wsNeg.Range("B12").Value = "Saldo parcelado:"
    wsNeg.Range("D12").Value = total - somaEntrada
    wsNeg.Range("B13").Value = "Estrutura:"
    If nParc > 0 Then
        wsNeg.Range("D13").Value = Format$(pctEfetiva, "0%") & " de entrada + " & nParc & " parcela(s)"
    Else
        wsNeg.Range("D13").Value = "Pagamento integral a vista"
    End If
    wsNeg.Range("D13").Font.Bold = True

    wsNeg.Range("D9,D11:D12").NumberFormat = FMT_MOEDA
    wsNeg.Range("B9:D13").Borders(xlInsideHorizontal).LineStyle = xlThin
    wsNeg.Range("D9:D13").HorizontalAlignment = xlRight

    '--- Entrada -------------------------------------------------------------
    r = 16
    With wsNeg.Range(wsNeg.Cells(r, "B"), wsNeg.Cells(r, "D"))
        .Merge
        .Value = "TITULOS DA ENTRADA - vencimento " & Format$(dataAcordo, "dd/mm/yyyy")
        .Font.Bold = True: .Interior.Color = RGB(17, 202, 160)
        .Font.Color = vbWhite: .HorizontalAlignment = xlCenter
    End With

    r = r + 1
    wsNeg.Cells(r, "B").Value = "Documento"
    wsNeg.Cells(r, "C").Value = "Categoria"
    wsNeg.Cells(r, "D").Value = "Valor"
    wsNeg.Range(wsNeg.Cells(r, "B"), wsNeg.Cells(r, "D")).Font.Bold = True

    For i = 1 To n
        If tit(i).EhEntrada Then
            r = r + 1
            wsNeg.Cells(r, "B").Value = tit(i).chave
            wsNeg.Cells(r, "C").Value = tit(i).Categoria
            wsNeg.Cells(r, "D").Value = tit(i).ValorAcordo
            wsNeg.Cells(r, "D").NumberFormat = FMT_MOEDA
        End If
    Next i

    r = r + 1
    wsNeg.Cells(r, "B").Value = "SUBTOTAL ENTRADA"
    wsNeg.Cells(r, "D").Value = somaEntrada
    wsNeg.Cells(r, "D").NumberFormat = FMT_MOEDA
    wsNeg.Range(wsNeg.Cells(r, "B"), wsNeg.Cells(r, "D")).Font.Bold = True
    wsNeg.Range(wsNeg.Cells(r, "B"), wsNeg.Cells(r, "D")).BorderAround xlContinuous, xlMedium

    '--- Parcelas ------------------------------------------------------------
    If nParc > 0 Then
        r = r + 3
        With wsNeg.Range(wsNeg.Cells(r, "B"), wsNeg.Cells(r, "D"))
            .Merge
            .Value = "CRONOGRAMA DO SALDO PARCELADO"
            .Font.Bold = True: .Interior.Color = RGB(0, 80, 136)
            .Font.Color = vbWhite: .HorizontalAlignment = xlCenter
        End With

        For p = 1 To nParc
            r = r + 1
            wsNeg.Cells(r, "B").Value = "PARCELA " & p & " DE " & nParc
            wsNeg.Cells(r, "C").Value = "Vencimento: " & Format$(datas(p), "dd/mm/yyyy")
            wsNeg.Cells(r, "D").Value = somaParcela(p)
            wsNeg.Cells(r, "D").NumberFormat = FMT_MOEDA
            With wsNeg.Range(wsNeg.Cells(r, "B"), wsNeg.Cells(r, "D"))
                .Font.Bold = True
                .Interior.Color = RGB(245, 247, 250)
                .Borders(xlEdgeBottom).LineStyle = xlThin
            End With

            For i = 1 To n
                If tit(i).Parcela = p And Not tit(i).EhEntrada Then
                    r = r + 1
                    wsNeg.Cells(r, "B").Value = "   - " & tit(i).chave
                    wsNeg.Cells(r, "C").Value = tit(i).Categoria
                    wsNeg.Cells(r, "D").Value = tit(i).ValorAcordo
                    wsNeg.Cells(r, "D").NumberFormat = FMT_MOEDA
                    wsNeg.Range(wsNeg.Cells(r, "B"), wsNeg.Cells(r, "D")).Font.Color = RGB(90, 90, 90)
                End If
            Next i
        Next p

        r = r + 1
        wsNeg.Cells(r, "B").Value = "TOTAL GERAL DO ACORDO"
        wsNeg.Cells(r, "D").Value = total
        wsNeg.Cells(r, "D").NumberFormat = FMT_MOEDA
        wsNeg.Range(wsNeg.Cells(r, "B"), wsNeg.Cells(r, "D")).Font.Bold = True
        wsNeg.Range(wsNeg.Cells(r, "B"), wsNeg.Cells(r, "D")).BorderAround xlContinuous, xlMedium
    End If

    r = r + 2
    wsNeg.Cells(r, "B").Value = "Valores congelados na data de referencia. " & _
                                "Nao ha incidencia de juros sobre o prazo do acordo."
    wsNeg.Cells(r, "B").Font.Italic = True
    wsNeg.Cells(r, "B").Font.Color = RGB(120, 120, 120)

    r = r + 3
    wsNeg.Cells(r, "B").Value = "____________________________________"
    wsNeg.Cells(r, "D").Value = "____________________________________"
    r = r + 1
    wsNeg.Cells(r, "B").Value = "CTA SMART - Financeiro"
    wsNeg.Cells(r, "D").Value = cliente
    wsNeg.Range(wsNeg.Cells(r, "B"), wsNeg.Cells(r, "D")).Font.Bold = True
End Sub


'==============================================================================
' Conversores defensivos
'==============================================================================
Private Function CBool2(ByVal v As Variant) As Boolean
    If IsEmpty(v) Or IsNull(v) Then
        CBool2 = False
    ElseIf VarType(v) = vbBoolean Then
        CBool2 = CBool(v)
    ElseIf IsNumeric(v) Then
        CBool2 = (CDbl(v) <> 0)
    Else
        CBool2 = (UCase$(Trim$(CStr(v))) = "TRUE" Or UCase$(Trim$(CStr(v))) = "VERDADEIRO")
    End If
End Function

Private Function Val2(ByVal v As Variant) As Double
    If IsNumeric(v) Then Val2 = CDbl(v) Else Val2 = 0
End Function
