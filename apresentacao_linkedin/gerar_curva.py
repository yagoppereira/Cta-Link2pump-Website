# Gera curva_reserva_vs_2682.html (SVG) — renderizado em PNG via Playwright
W, H = 1080, 1350
L, R, T, B = 130, 980, 380, 1080       # área do gráfico
xmax, ymax = 240, 100
sx = lambda d: L + (R - L) * d / xmax
sy = lambda p: B - (B - T) * p / ymax

curva = lambda d: (min(max(d, 0), 210) / 210) ** 2 * 100
pts = " ".join(f"{sx(d):.1f},{sy(curva(d)):.1f}" for d in range(0, xmax + 1))

# Res. CMN 2.682 — provisão mínima por faixa de atraso
faixas = [(0, 14, 0), (14, 30, 1), (30, 60, 3), (60, 90, 10), (90, 120, 30),
          (120, 150, 50), (150, 180, 70), (180, 240, 100)]
step = []
for a, b, p in faixas:
    step += [f"{sx(a):.1f},{sy(p):.1f}", f"{sx(b):.1f},{sy(p):.1f}"]
step = " ".join(step)

grid = ""
for p in range(0, 101, 25):
    grid += f'<line x1="{L}" x2="{R}" y1="{sy(p)}" y2="{sy(p)}" class="grid"/>'
    grid += f'<text x="{L-16}" y="{sy(p)+7}" class="tick" text-anchor="end">{p}%</text>'
for d in [0, 30, 60, 90, 120, 150, 180, 210, 240]:
    grid += f'<text x="{sx(d)}" y="{B+38}" class="tick" text-anchor="middle">{d}</text>'

def marca(d, p, cor):
    return f'<circle cx="{sx(d)}" cy="{sy(p)}" r="7" fill="{cor}" stroke="#fcfcfb" stroke-width="2"/>'

anot = ""
for d, txt_dx, anchor in [(90, -14, "end"), (150, -14, "end"), (180, -14, "end")]:
    c = curva(d); r = dict((b, p) for a, b, p in faixas)[d]
    anot += marca(d, c, "#4a3aa7") + marca(d, r, "#eb6834")
    anot += (f'<text x="{sx(d)+txt_dx}" y="{sy(max(c, r))-18}" class="anot" text-anchor="{anchor}">'
             f'{d} dias: <tspan class="v1">{c:.0f}%</tspan> vs <tspan class="v2">{r}%</tspan></text>')

html = f"""<!doctype html><html><head><meta charset="utf-8"><style>
@font-face {{ font-family: Poppins; font-weight: 600; src: url(../fonts/Poppins-600.ttf); }}
@font-face {{ font-family: Poppins; font-weight: 700; src: url(../fonts/Poppins-700.ttf); }}
@font-face {{ font-family: DM Sans; font-weight: 400; src: url(../fonts/DMSans-400.ttf); }}
@font-face {{ font-family: DM Sans; font-weight: 500; src: url(../fonts/DMSans-500.ttf); }}
body {{ margin: 0; }}
.slide {{ width: {W}px; height: {H}px; background: #fcfcfb; font-family: 'DM Sans'; color: #0b0b0b; position: relative; }}
h1 {{ font-family: Poppins; font-weight: 700; font-size: 54px; line-height: 1.12; margin: 0; position: absolute; left: 80px; top: 80px; width: 920px; }}
.sub {{ position: absolute; left: 80px; top: 228px; font-size: 27px; color: #52514e; width: 920px; line-height: 1.35; }}
.grid {{ stroke: #e4e3df; stroke-width: 1; }}
.tick {{ font-size: 22px; fill: #52514e; }}
.eixo {{ font-size: 22px; fill: #52514e; font-weight: 500; }}
.anot {{ font-size: 23px; fill: #0b0b0b; font-weight: 500; }}
.v1 {{ fill: #4a3aa7; font-weight: 700; }} .v2 {{ fill: #c4501f; font-weight: 700; }}
.lbl {{ font-family: Poppins; font-weight: 600; font-size: 26px; }}
.rodape {{ position: absolute; left: 80px; bottom: 70px; width: 920px; font-size: 21px; color: #52514e; line-height: 1.45; }}
.rodape b {{ color: #0b0b0b; font-weight: 500; }}
</style></head><body><div class="slide">
<h1>Quanto provisionar para cada dia de atraso?</h1>
<div class="sub">Reserva estimada por título. Uma curva contínua que acompanha a tabela de provisão dos bancos a partir de 120 dias — e é mais conservadora antes disso.</div>
<svg width="{W}" height="{H}" style="position:absolute;left:0;top:0">
{grid}
<text x="{(L+R)/2}" y="{B+80}" class="eixo" text-anchor="middle">Dias de atraso do título</text>
<polyline points="{step}" fill="none" stroke="#eb6834" stroke-width="3" stroke-linejoin="round"/>
<polyline points="{pts}" fill="none" stroke="#4a3aa7" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>
{anot}
<text x="{sx(174)}" y="{sy(90)}" class="lbl" fill="#4a3aa7" text-anchor="end">Curva (dias ÷ 210)²</text>
<text x="{sx(128)}" y="{sy(10)}" class="lbl" fill="#c4501f" text-anchor="start">Res. CMN 2.682</text>
</svg>
<div class="rodape"><b>Reserva estimada</b> = (dias de atraso ÷ 210)² × saldo, com teto de 100% aos 210 dias.<br>
<b>Índice de risco</b> = reserva estimada ÷ saldo devedor da carteira.<br>
Referência: provisão mínima por faixa de atraso da Resolução CMN 2.682/99.</div>
</div></body></html>"""
open("curva_reserva_vs_2682.html", "w", encoding="utf8").write(html)
