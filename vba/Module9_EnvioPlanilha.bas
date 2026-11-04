'==============================================================================
' CTA SMART - ENVIO DO REGISTRO DE ACORDO PARA A PLANILHA DE INADIMPLENCIA
'------------------------------------------------------------------------------
' Quando um acordo e firmado na Calculadora (GerarPropostaPercentil ou
' GerarPropostaNegociacao), as linhas gravadas em REGISTRO_ACORDO (colunas A:U,
' o mesmo layout da aba ACORDOS) sao enviadas para a planilha
' "14.10 INADIMPLENCIA" pelo app da web do Apps Script (apps_script/Acordos.gs).
'
' A coluna V de REGISTRO_ACORDO guarda o resultado do envio:
'   "ENVIADO dd/mm/aaaa hh:mm"  ou  "PENDENTE - <motivo>"
' Se o envio falhar (sem internet, URL nao configurada...), rode
' EnviarPendentes depois: ele reenvia todos os acordos PENDENTE. Reenviar o
' mesmo acordo nao duplica: a planilha substitui as linhas de mesmo CNPJ+TERMO.
'
' Configuracao (uma vez): cole em URL_PLANILHA a URL do app da web e em
' TOKEN_PLANILHA o token gerado por gerarToken() no Apps Script.
'==============================================================================
Option Explicit

Public Const URL_PLANILHA   As String = "COLE_AQUI_A_URL_DO_APP_DA_WEB"
Public Const TOKEN_PLANILHA As String = "COLE_AQUI_O_TOKEN"
Public Const RG_ENVIO       As String = "V"
Private Const N_COLS        As Long = 21     ' A:U

'------------------------------------------------------------------------------
' ID padrao do acordo, usado no TERMO quando o operador nao informa outro:
' AC-<codigo do cliente>-<aaaammdd>
'------------------------------------------------------------------------------
Public Function IdAcordoPadrao(ByVal empresa As String, ByVal cnpj As String, _
                               ByVal dataAcordo As Date) As String
    Dim cod As String
    cod = Trim$(empresa)
    If InStr(cod, " - ") > 0 Then cod = Left$(cod, InStr(cod, " - ") - 1)
    If Len(cod) = 0 Then cod = ApenasDigitos(cnpj)
    IdAcordoPadrao = "AC-" & cod & "-" & Format$(dataAcordo, "yyyymmdd")
End Function

'------------------------------------------------------------------------------
' Envia as linhas rIni..rFim de REGISTRO_ACORDO. Marca a coluna V.
' Retorna True se a planilha confirmou o recebimento.
'------------------------------------------------------------------------------
Public Function EnviarLinhasRegistro(ByVal rIni As Long, ByVal rFim As Long, _
                                     ByRef msg As String) As Boolean
    Dim ws As Worksheet, r As Long, c As Long
    Dim corpo As String, linha As String

    Set ws = ThisWorkbook.Worksheets(ABA_REGISTRO)
    ws.Cells(REG_LIN_CAB, RG_ENVIO).Value = "ENVIO PLANILHA"

    If rFim < rIni Then
        msg = "nada a enviar"
        Exit Function
    End If
    If Left$(URL_PLANILHA, 4) <> "http" Or Left$(TOKEN_PLANILHA, 4) = "COLE" Then
        msg = "URL/token do envio nao configurados (Module9_EnvioPlanilha)"
        MarcarEnvio ws, rIni, rFim, "PENDENTE - " & msg
        Exit Function
    End If

    corpo = "{""token"":" & JsonTexto(TOKEN_PLANILHA) & ",""linhas"":["
    For r = rIni To rFim
        linha = "["
        For c = 1 To N_COLS
            If c > 1 Then linha = linha & ","
            linha = linha & JsonCelula(ws.Cells(r, c).Value)
        Next c
        corpo = corpo & IIf(r > rIni, ",", "") & linha & "]"
    Next r
    corpo = corpo & "]}"

    Dim http As Object, resposta As String
    On Error GoTo FalhaHttp
    Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
    http.Open "POST", URL_PLANILHA, False
    http.SetTimeouts 15000, 15000, 30000, 90000
    http.SetRequestHeader "Content-Type", "application/json; charset=utf-8"
    http.Send BytesUtf8(corpo)
    resposta = http.ResponseText
    On Error GoTo 0

    If http.Status = 200 And InStr(resposta, """ok"":true") > 0 Then
        EnviarLinhasRegistro = True
        msg = "enviado para a aba ACORDOS"
        MarcarEnvio ws, rIni, rFim, "ENVIADO " & Format$(Now, "dd/mm/yyyy hh:mm")
    Else
        msg = "a planilha respondeu: " & Left$(resposta, 200)
        MarcarEnvio ws, rIni, rFim, "PENDENTE - " & msg
    End If
    Exit Function

FalhaHttp:
    msg = "falha de conexao: " & Err.Description
    MarcarEnvio ws, rIni, rFim, "PENDENTE - " & msg
End Function

'------------------------------------------------------------------------------
' Reenvia todos os acordos marcados como PENDENTE em REGISTRO_ACORDO.
' Cada bloco continuo de linhas pendentes do mesmo CNPJ + TERMO e um envio.
'------------------------------------------------------------------------------
Public Sub EnviarPendentes()
    Dim ws As Worksheet, ult As Long, r As Long, ini As Long
    Dim chave As String, ok As Long, falha As Long, msg As String

    Set ws = ThisWorkbook.Worksheets(ABA_REGISTRO)
    ult = ws.Cells(ws.Rows.Count, RG_EMPRESA).End(xlUp).Row
    r = REG_LIN_INI
    Do While r <= ult
        If Left$(CStr(ws.Cells(r, RG_ENVIO).Value), 8) = "PENDENTE" Then
            ini = r
            chave = ChaveAcordo(ws, r)
            Do While r + 1 <= ult
                If Left$(CStr(ws.Cells(r + 1, RG_ENVIO).Value), 8) <> "PENDENTE" Then Exit Do
                If ChaveAcordo(ws, r + 1) <> chave Then Exit Do
                r = r + 1
            Loop
            If EnviarLinhasRegistro(ini, r, msg) Then ok = ok + 1 Else falha = falha + 1
        End If
        r = r + 1
    Loop

    MsgBox "Acordos enviados: " & ok & vbCrLf & "Ainda pendentes: " & falha & _
           IIf(falha > 0, vbCrLf & vbCrLf & "Ultimo erro: " & msg, ""), _
           IIf(falha > 0, vbExclamation, vbInformation), "CTA SMART"
End Sub

'==============================================================================
' Apoio
'==============================================================================
Private Function ChaveAcordo(ws As Worksheet, ByVal r As Long) As String
    ChaveAcordo = Trim$(CStr(ws.Cells(r, RG_CNPJ).Value)) & "|" & _
                  Trim$(CStr(ws.Cells(r, RG_TERMO).Value))
End Function

Private Sub MarcarEnvio(ws As Worksheet, ByVal rIni As Long, ByVal rFim As Long, _
                        ByVal texto As String)
    ws.Range(ws.Cells(rIni, RG_ENVIO), ws.Cells(rFim, RG_ENVIO)).Value = texto
    ws.Range(ws.Cells(rIni, RG_ENVIO), ws.Cells(rFim, RG_ENVIO)).Font.Color = _
        IIf(Left$(texto, 7) = "ENVIADO", RGB(0, 120, 60), RGB(200, 0, 0))
End Sub

Private Function JsonCelula(ByVal v As Variant) As String
    If IsEmpty(v) Or IsNull(v) Then
        JsonCelula = """"""
    ElseIf IsError(v) Then
        JsonCelula = """"""
    ElseIf VarType(v) = vbDate Then
        JsonCelula = """" & Format$(v, "dd/mm/yyyy") & """"
    ElseIf VarType(v) = vbBoolean Then
        JsonCelula = IIf(v, """SIM""", """NAO""")
    ElseIf IsNumeric(v) And VarType(v) <> vbString Then
        JsonCelula = Trim$(Str$(CDbl(v)))        ' Str$ usa ponto decimal
    Else
        JsonCelula = JsonTexto(CStr(v))
    End If
End Function

Private Function JsonTexto(ByVal s As String) As String
    s = Replace(s, "\", "\\")
    s = Replace(s, """", "\""")
    s = Replace(s, vbCrLf, " ")
    s = Replace(s, vbCr, " ")
    s = Replace(s, vbLf, " ")
    s = Replace(s, vbTab, " ")
    JsonTexto = """" & s & """"
End Function

Private Function BytesUtf8(ByVal s As String) As Variant
    Dim st As Object
    Set st = CreateObject("ADODB.Stream")
    st.Type = 2                 ' texto
    st.Charset = "utf-8"
    st.Open
    st.WriteText s
    st.Position = 0
    st.Type = 1                 ' binario
    st.Position = 3             ' pula o BOM
    BytesUtf8 = st.Read
    st.Close
End Function

Private Function ApenasDigitos(ByVal s As String) As String
    Dim i As Long, ch As String
    For i = 1 To Len(s)
        ch = Mid$(s, i, 1)
        If ch Like "#" Then ApenasDigitos = ApenasDigitos & ch
    Next i
End Function
