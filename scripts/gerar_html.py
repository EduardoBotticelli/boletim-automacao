"""Gera páginas de validação em formato de newsletter."""
from collections import defaultdict
from datetime import date
from html import escape
from pathlib import Path
import json

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "output"
SLUGS = ["trabalhista-empresarial", "direito-tributario", "societario-ma", "mercado-capitais-fundos", "regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg", "propriedade-intelectual", "contencioso-civel"]
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]

def e(v): return escape(str(v or ""), quote=True)
def data_curta(v):
    try: return date.fromisoformat(str(v)[:10]).strftime("%d/%m/%Y")
    except ValueError: return str(v or "")
def data_longa(v):
    try:
        d=date.fromisoformat(str(v)[:10]); return f"{d.day} de {MESES[d.month-1]} de {d.year}"
    except ValueError: return str(v or "")
def suspensas(config, slug):
    mapa=config.get("mapeamento_fonte_boletim",{}); saida=[]
    for x in config.get("fontes_em_defeso",[]):
        base=x.get("fonte","").split(" | ")[0]
        if any(slug in radares and nome.split(" | ")[0]==base for nome,radares in mapa.items()): saida.append(x)
    return saida
def card(i):
    link=f'<a href="{e(i.get("url"))}" style="color:#1a4d2e;text-decoration:none;font-weight:600">Acessar matéria &raquo;</a>' if i.get("url") else ""
    return f'<div style="background:#fff;border-left:4px solid #1a4d2e;padding:14px 18px;margin:10px 0;border-radius:4px;box-shadow:0 1px 2px #0001"><h3 style="margin:0 0 6px;font-size:14.5px;color:#1a1a1a">{e(i.get("titulo"))}</h3><p style="font-size:13px;color:#4a4a4a;line-height:1.55">{e(i.get("resumo"))}</p><div style="font-size:12px;color:#777;border-top:1px solid #eee;padding-top:7px"><strong>Publicado:</strong> {e(data_curta(i.get("data_publicacao")))} &nbsp; {link}</div></div>'
def main():
    b=json.loads((OUT/"boletim.json").read_text(encoding="utf-8")); cfg=b.get("boletins_config",{}); OUT.mkdir(exist_ok=True)
    for slug in SLUGS:
        nome=cfg.get("nomes_radares",{}).get(slug,slug); grupos=defaultdict(list)
        for i in b.get("itens",[]):
            if slug in i.get("boletins",[]): grupos[i.get("fonte","Fonte")].append(i)
        corpo=[]
        for fonte,itens in grupos.items():
            corpo.append(f'<h2 style="font-size:12.5px;color:#1a4d2e;text-transform:uppercase;border-bottom:2px solid #1a4d2e;padding-bottom:4px;margin-top:20px">{e(fonte)} ({len(itens)})</h2>'); corpo.extend(card(i) for i in itens)
        if not corpo: corpo=['<div style="padding:45px;text-align:center;color:#777">Nenhum item selecionado para este Radar nesta edição.</div>']
        avisos=[]; pend=cfg.get("fontes_email_pendentes",{}).get(slug,[])
        if pend: avisos.append(f'<div style="background:#fff3cd;border-left:4px solid #d68910;padding:12px 20px;font-size:12.5px"><strong>Aviso:</strong> fontes por e-mail ainda não integradas: {e(", ".join(pend))}.</div>')
        sus=suspensas(cfg,slug)
        if sus: avisos.append(f'<div style="background:#fef2f2;border-left:4px solid #b91c1c;padding:12px 20px;font-size:12.5px"><strong>Fonte temporariamente suspensa:</strong> {e(", ".join(x.get("fonte","") for x in sus))}.</div>')
        html=f'<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><body style="margin:0;background:#f0f2f5;font-family:Segoe UI,Arial;color:#2c3e50"><div style="max-width:780px;margin:auto;background:#fafafa"><header style="background:linear-gradient(135deg,#0d3320,#2d8659);padding:32px;color:white"><small style="letter-spacing:2px;color:#a8d8b9">VERSÃO DE VALIDAÇÃO</small><h1 style="font-weight:300;margin:8px 0">{e(nome)}</h1><p style="color:#a8d8b9">{e(data_longa(b.get("data_execucao")))}</p></header><div style="background:#fef5e7;border-left:4px solid #d68910;padding:16px 24px;font-size:13.5px">Versão de validação da curadoria automatizada para revisão editorial.</div>{"".join(avisos)}<main style="background:white;padding:1px 24px 20px">{"".join(corpo)}</main><footer style="background:#0d3320;padding:18px;color:#a8d8b9;text-align:center;font-size:11px">RADARES LOBO DE RIZZO · VALIDAÇÃO INTERNA</footer></div></body></html>'
        (OUT/f"validacao_{slug}.html").write_text(html,encoding="utf-8")
if __name__=="__main__": main()
