# Migracao one-off da aba ACORDOS (legado) para ACORDOS_RESUMO / ACORDOS_PARCELAS / ACORDOS_TITULOS.
# Entrada: diretorio com acordos.json (get_values de ACORDOS!A1:AM974). Saida: migracao.json.
# Regras descritas em docs/ACORDOS_NOVA_ESTRUTURA.md, secao "Migracao do historico".
import json,sys,re,collections,datetime as dt
D=sys.argv[1]
A=json.load(open(D+'/acordos.json'))['values']
HOJE=dt.date(2026,10,14)
EPOCH=dt.date(1899,12,30)

def num(s):
    s=(s or '').replace('R$','').replace('\t','').replace('\r','').replace('\n','').strip()
    if not s: return None
    if re.fullmatch(r'-?[\d.]+,\d+',s): s=s.replace('.','').replace(',','.')
    elif re.fullmatch(r'-?\d{1,3}(\.\d{3})+',s): s=s.replace('.','')
    try: return float(s)
    except: return None

def data(s):
    s=(s or '').strip()
    m=re.fullmatch(r'(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?',s)
    if not m: return None
    d,mo,y=int(m[1]),int(m[2]),m[3]
    y=2026 if y is None else (2000+int(y) if len(y)==2 else int(y))
    try: return dt.date(y,mo,d)
    except: return None

def serial(d): return (d-EPOCH).days if d else ''

def nf(s):
    s=(s or '').strip().replace('\n',' ')
    d=data(s)
    if d and d.year<2000: return str(serial(d)), True   # NF virou data no legado
    return s, False

def cnpj_root(c):
    c=re.sub(r'\D','',c or '')
    return c[:8] if len(c)==14 else c

rows=[(i,(r+['']*39)[:39]) for i,r in enumerate(A[2:],start=3)]
rows=[(i,r) for i,r in rows if any(x.strip() for x in r)]

# blocos contiguos por raiz de CNPJ e por formato (novo = macro com ENTRADA/PARCELA)
def isnew(r): return r[18]=='ENTRADA' or r[18].startswith('PARCELA ')
blocks=[]
for i,r in rows:
    key=(cnpj_root(r[3]) or r[2].strip(), isnew(r))
    if blocks and blocks[-1][0]==key: blocks[-1][1].append((i,r))
    else: blocks.append((key,[(i,r)]))

RES=[];PAR=[];TIT=[];avisos=[]
for n,(key,g) in enumerate(blocks,start=1):
    aid=f'L-{n:03d}'
    l0,l1=g[0][0],g[-1][0]
    resp=collections.Counter(r[1].strip() for _,r in g if r[1].strip()).most_common(1)
    empresa=g[0][1][2].strip().replace('\n',' ')
    stat=collections.Counter(r[0] or '(vazio)' for _,r in g)
    forma=next((r[16].strip().replace('\n',' ') for _,r in g if r[16].strip()),'')
    termo=next((r[17].strip().replace('\n',' ') for _,r in g if r[17].strip()),'')
    obs_leg=[f'Migrado da aba ACORDOS, linhas {l0} a {l1}.',
             'Status no legado: '+', '.join(f'{k} {v}' for k,v in stat.items())+'.']
    vp=[r[14].strip() for _,r in g if r[14].strip()]; vpar=[r[15].strip() for _,r in g if r[15].strip()]
    if vp: obs_leg.append('VALOR PAGO no legado: '+'; '.join(vp[:6]).replace('\n',' ')+('...' if len(vp)>6 else ''))
    if vpar: obs_leg.append('VALOR DE PARCELA no legado: '+'; '.join(vpar[:6]).replace('\n',' ')+('...' if len(vpar)>6 else ''))
    titulos=[]  # (nump, venc_parc, row, empresa, doc, nfse, venc, orig, juros, total, alocado, saldo, status)
    first={}
    corr=[]
    for i,r in g:
        doc=r[4].strip()
        if not doc: continue
        orig,jur,tot=num(r[8]),num(r[9]),num(r[10])
        if doc in first and orig is None and tot is None:
            orig,jur,tot=first[doc]
        if orig is None and tot is not None: orig,jur=tot,0.0
        if jur is None: jur=0.0
        if orig is not None and (tot is None or abs(tot-(orig+jur))>1):
            if tot is not None: corr.append(f'linha {i}: VALOR NF TOTAL {r[10]} corrigido para {orig+jur:.2f}')
            tot=round(orig+jur,2)
        first.setdefault(doc,(orig,jur,tot))
        dp=data(r[13]) or (data(r[11]) if data(r[11]) else None)
        nfs,conv=nf(r[5])
        if conv: corr.append(f'linha {i}: NFS-e {r[5]} (formatada como data) convertida para {nfs}')
        if isnew(r):
            nump=0 if r[18]=='ENTRADA' else int(re.search(r'PARCELA (\d+)',r[18])[1])
            aloc=num(r[19]); sal=num(r[20]) or 0.0
            if aloc is None: aloc=tot
        else:
            nump=None; aloc=tot; sal=0.0
        titulos.append(dict(lin=i,nump=nump,vp=dp,emp=r[2].strip().replace('\n',' '),doc=doc,nf=nfs,
            venc=data(r[7]),orig=orig,jur=jur,tot=tot,aloc=aloc,sal=sal,st=r[0]))
    # numeracao das parcelas do formato antigo: datas distintas em ordem
    if not key[1]:
        datas=sorted({t['vp'] for t in titulos if t['vp']})
        idx={d:k+1 for k,d in enumerate(datas)}
        for t in titulos:
            t['nump']=idx[t['vp']] if t['vp'] else len(datas)+1
    parcelas=collections.OrderedDict()
    for t in titulos:
        p=parcelas.setdefault(t['nump'],dict(venc=t['vp'],prev=0.0,quit=0.0,nq=0,n=0))
        if p['venc'] is None: p['venc']=t['vp']
        p['prev']+=t['aloc'] or 0; p['n']+=1
        if t['st']=='Quitado': p['quit']+=t['aloc'] or 0; p['nq']+=1
    # bloco sem titulos (ex.: linha 3): parcelas pelas datas S.., valor P
    if not titulos:
        r=g[0][1]; vparc=num(r[15]); tot=num(r[14])
        ds=[data(x) for x in r[18:] if data(x)]
        if vparc and tot: ds=ds[:round(tot/vparc)]
        for k,d in enumerate(ds,start=1):
            parcelas[k]=dict(venc=d,prev=vparc or 0,quit=0,nq=0,n=0)
        obs_leg.append('Acordo sem títulos individualizados no legado. NFs: '+r[5].replace('\n',' '))
    total=round(sum(p['prev'] for p in parcelas.values()),2)
    for k,p in sorted(parcelas.items()):
        if p['n'] and p['nq']==p['n']:
            rec=round(p['prev'],2); o='Legado: títulos marcados Quitado. Valor assumido igual ao previsto; data de recebimento não registrada.'
        elif p['nq']:
            rec=round(p['quit'],2); o=f'Legado: {p["nq"]} de {p["n"]} títulos marcados Quitado. Valor recebido = soma desses títulos.'
        else:
            rec=''; o=''
        PAR.append([aid,k,serial(p['venc']),round(p['prev'],2),'',rec,o])
    for t in sorted(titulos,key=lambda t:(t['nump'],t['venc'] or HOJE)):
        TIT.append([aid,t['nump'],t['emp'],"'"+t['doc'],("'"+t['nf']) if t['nf'] else '',serial(t['venc']),
                    t['orig'] if t['orig'] is not None else '',t['jur'],t['tot'] if t['tot'] is not None else '',
                    round(t['aloc'],2) if t['aloc'] is not None else '',round(t['sal'],2)])
    if corr: obs_leg.append('Correções na migração: '+'; '.join(corr[:5])+('...' if len(corr)>5 else ''))
    avisos+=corr
    RES.append([aid,'',resp[0][0] if resp else '',empresa,g[0][1][3].strip(),total,forma,termo,'',' '.join(obs_leg)])

json.dump(dict(res=RES,par=PAR,tit=TIT),open(D+'/migracao.json','w'),ensure_ascii=False)
print('acordos',len(RES),'parcelas',len(PAR),'titulos',len(TIT),'correcoes',len(avisos))
for a in avisos[:15]: print(' ',a)
print(RES[0]); print(RES[19]); print(PAR[:3]); print(TIT[:2])
# conferencias
import itertools
print('soma total',round(sum(r[5] for r in RES),2))
print('maiores',sorted(((r[5],r[0],r[3][:30]) for r in RES),reverse=True)[:5])
