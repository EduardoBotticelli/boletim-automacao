"""Gera páginas de validação com aparência próxima do e-mail final."""
from collections import defaultdict
from datetime import date
from html import escape
from pathlib import Path
import json

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "output"
BOLETIM = OUT / "boletim.json"

ORDEM = [
    "trabalhista-empresarial", "direito-tributario", "societario-ma",
    "mercado-capitais-fundos", "regulatorio-oleo-gas",
    "imobiliario-infraestrutura", "ambiental-esg",
    "propriedade-intelectual", "contencioso-civel",
]

NOMES = {
    "trabalhista-empresarial": "Radar Trabalhista Empresarial",
    "direito-tributario": "Radar Tributário",
    "societario-ma": "Radar Societário, Fusões e Aquisições",
    "mercado-capitais-fundos": "Radar Mercado de Capitais e Fundos de Investimento",
    "regulatorio-oleo-gas": "Radar Regulatório e Óleo e Gás",
    "imobiliario-infraestrutura": "Radar Negócios Imobiliários e Infraestrutura",
    "ambiental-esg": "Radar Ambiental e ESG",
    "propriedade-intelectual": "Radar Propriedade Intelectual, Tecnologia e Privacidade",
    "contencioso-civel": "Radar Solução de Conflitos",
}

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]

def e(v): return escape(str(v or ""), quote=True)

def data_extenso(valor):
    try:
        d = date.fromisoformat(str(valor)[:10])
        return f"{d.day} de {MESES[d.month - 1]} de {d.year}"
    except ValueError:
        return str(valor or "")

def data_curta(valor):
    try: return date.fromisoformat(str(valor)[:10]).strftime("%d/%m/%Y")
    except ValueError: return str(valor or "")

def fontes_suspensas_do_radar(config, slug):
    mapeamento = config.get("mapeamento_fonte_boletim", {})
    suspensas = config.get("fontes_em_defeso", [])
    aliases = {x.get("fonte", ""): x for x in suspensas if isinstance(x, dict)}
    resultado = []
    for nome_tecnico, radares in mapeamento.items():
        if slug not in radares:
            continue
        for nome_visivel, registro in aliases.items():
            base = nome_visivel.replace("í", "i").replace("é", "e").replace("ó", "o").replace("ã", "a").replace("ç", "c")
            if nome_tecnico.lower() == base.lower() or nome_tecnico.split(" | ")[0] == nome_visivel.split(" | ")[0]:
                resultado.append(registro)
    return resultado

def html_item(item):
    url = e(item.get("url"))
    link = f'<a href="{url}" style="color:#1a4d2e;text-decoration:none;font-weight:600;">Acessar matéria &raquo;</a>' if url else ""
    return f"""
    <div style="background:#fff;border-left:4px solid #1a4d2e;padding:14px 18px;margin:10px 0;border-radius:4px;box-shadow:0 1px 2px rgba(0,0,0,.06);">
      <h3 style="margin:0 0 6px;font-size:14.5px;color:#1a1a1a;font-weight:600;line-height:1.4;">{e(item.get('titulo'))}</h3>
      <p style="margin:4px 0 8px;font-size:13px;color:#4a4a4a;line-height:1.55;">{e(item.get('resumo'))}</p>
      <div style="font-size:12px;color:#7a7a7a;border-top:1px solid #eee;padding-top:7px;">
        <span style="margin-right:14px;"><strong>Publicado:</strong> {e(data_curta(item.get('data_publicacao')))}</span>{link}
      </div>
    </div>"""

def montar(dados, slug):
    config = dados.get("boletins_config", {})
    nome = config.get("nomes_radares", {}).get(slug, NOMES[slug])
    grupos = defaultdict(list)
    for item in dados.get("itens", []):
        if slug in item.get("boletins", []): grupos[item.get("fonte", "Fonte não informada")].append(item)
    pendentes = config.get("fontes_email_pendentes", {}).get(slug, [])
    suspensas = fontes_suspensas_do_radar(config, slug)
    corpo = []
    for fonte, itens in grupos.items():
        corpo.append(f'<div style="margin:20px 0 6px;font-size:12.5px;font-weight:700;color:#1a4d2e;letter-spacing:.5px;text-transform:uppercase;border-bottom:2px solid #1a4d2e;padding-bottom:4px;">{e(fonte)} ({len(itens)})</div>')
        corpo.extend(html_item(i) for i in itens)
    if not corpo:
        corpo.append('<div style="padding:46px 20px;text-align:center;color:#777;">Nenhum item selecionado para este Radar nesta edição.</div>')
    aviso_email = ""
    if pendentes:
        aviso_email = f'<div style="background:#fff3cd;border-left:4px solid #d68910;padding:12px 20px;color:#7d5a10;font-size:12.5px;"><strong>Aviso:</strong> fontes recebidas por e-mail ainda não integradas: {e(", ".join(pendentes))}.</div>'
    aviso_defeso = ""
    if suspensas:
        texto = ", ".join(f"{x.get('fonte')} (retomada em {data_curta(x.get('reativar_em'))})" for x in suspensas)
        aviso_defeso = f'<div style="background:#fef2f2;border-left:4px solid #b91c1c;padding:12px 20px;color:#7f1d1d;font-size:12.5px;"><strong>Fonte temporariamente suspensa:</strong> {e(texto)}.</div>'
    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width"><title>{e(nome)} - Validação</title></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:Segoe UI,Tahoma,Geneva,Verdana,sans-serif;color:#2c3e50;">
<div style="max-width:780px;margin:0 auto;background:#fafafa;">
  <div style="background:linear-gradient(135deg,#0d3320 0%,#1a4d2e 50%,#2d8659 100%);padding:32px;color:#fff;">
    <div style="font-size:11px;color:#a8d8b9;letter-spacing:2px;text-transform:uppercase;margin-bottom:6px;">Versão de validação</div>
    <h1 style="margin:0;font-size:30px;font-weight:300;color:#fff;">{e(nome)}</h1>
    <div style="height:2px;width:40px;background:#5cb88a;margin:12px 0;"></div>
    <p style="margin:0;font-size:13px;color:#a8d8b9;">{e(data_extenso(dados.get('data_execucao')))}</p>
  </div>
  <div style="background:#fef5e7;border-left:4px solid #d68910;padding:16px 24px;color:#5d4400;font-size:13.5px;line-height:1.6;">
    Esta é uma versão de validação da curadoria automatizada. Os itens abaixo foram selecionados para revisão editorial da área.
  </div>
  {aviso_email}{aviso_defeso}
  <div style="background:#fff;padding:0 24px 20px;">{''.join(corpo)}</div>
  <div style="background:#0d3320;padding:18px 24px;color:#a8d8b9;text-align:center;font-size:11px;letter-spacing:1px;">RADARES LOBO DE RIZZO · VALIDAÇÃO INTERNA</div>
</div></body></html>"""

def main():
    dados = json.loads(BOLETIM.read_text(encoding="utf-8"))
    OUT.mkdir(exist_ok=True)
    for slug in ORDEM:
        (OUT / f"validacao_{slug}.html").write_text(montar(dados, slug), encoding="utf-8")
        print(f"Gerado: validacao_{slug}.html")

if __name__ == "__main__": main()
