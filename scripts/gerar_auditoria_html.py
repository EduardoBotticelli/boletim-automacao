"""Gera auditoria de cobertura e classificação."""
from collections import Counter
from html import escape
from pathlib import Path
import json
BASE=Path(__file__).resolve().parent.parent; OUT=BASE/"output"
def e(v): return escape(str(v or ""),quote=True)
def load(n): return json.loads((OUT/n).read_text(encoding="utf-8"))
def table(h,rows):
    if not rows:return '<p class="empty">Nenhum registro.</p>'
    return '<div class="tw"><table><thead><tr>'+''.join(f'<th>{e(x)}</th>' for x in h)+'</tr></thead><tbody>'+''.join('<tr>'+''.join(f'<td>{c}</td>' for c in r)+'</tr>' for r in rows)+'</tbody></table></div>'
def sec(n,t,b):return f'<section><header><b>{n:02d}</b><h2>{e(t)}</h2></header><div class="body">{b}</div></section>'
def main():
    b,l=load("boletim.json"),load("log_execucao.json"); cfg=b.get("boletins_config",{}); nomes=cfg.get("nomes_radares",{}); val={x.get("fonte"):x for x in b.get("validacao_fontes",[])}; itens=b.get("itens",[]); por=Counter(i.get("fonte","") for i in itens)
    rows=[]
    for x in l.get("fontes_processadas",[]):
        v=val.get(x.get("fonte"),{}); rows.append([e(x.get("fonte")),e(x.get("status")),e(x.get("tamanho_chars")),e(v.get("publicacoes_localizadas",0)),e(v.get("publicacoes_aprovadas",por.get(x.get("fonte"),0))),e(v.get("status_editorial")),e(v.get("conteudo_truncado"))])
    def fm(k):return [[e(x.get("fonte")),e(x.get("motivo"))] for x in b.get(k,[]) if isinstance(x,dict)]
    stats=[[e(nomes.get(s,s)),e(v.get("total",0))] for s,v in b.get("estatisticas_por_boletim",{}).items()]
    det=l.get("filtro1_bloqueios_detalhe",{}); bloqueados=[[e(nomes.get(s,s)),e(t)] for s,ts in det.items() for t in ts]
    susp=[[e(x.get("fonte")),e(x.get("motivo")),e(x.get("reativar_em"))] for x in cfg.get("fontes_em_defeso",[])]
    sem=[[e(i.get("fonte")),e(i.get("titulo")),e(i.get("exclusao_editorial_automatica",""))] for i in itens if not i.get("boletins")]
    links=''.join(f'<a href="validacao_{s}.html">{e(nomes.get(s,s))}</a>' for s in cfg.get("boletins_disponiveis",[]))
    sections=''.join([sec(1,"Cobertura por fonte",table(["Fonte","Coleta","Caracteres","Localizadas","Aprovadas","Situação","Truncada"],rows)),sec(2,"Fontes sem resultado",table(["Fonte","Motivo"],fm("fontes_sem_resultado"))),sec(3,"Fontes sem publicação",table(["Fonte","Motivo"],fm("fontes_sem_publicacao_hoje"))),sec(4,"Erros técnicos",table(["Fonte","Motivo"],fm("fontes_com_erro_tecnico"))),sec(5,"Fontes em defeso",table(["Fonte","Motivo","Retomada"],susp)),sec(6,"Totais por Radar",table(["Radar","Total"],stats)),sec(7,"Bloqueios por Radar",table(["Radar","Quantidade"],[[e(nomes.get(s,s)),e(q)] for s,q in l.get("resultado",{}).get("filtro1_bloqueios",{}).items()])),sec(8,"Itens bloqueados",table(["Radar","Item"],bloqueados)),sec(9,"Rejeições por Radar",table(["Radar","Quantidade"],[[e(nomes.get(s,s)),e(q)] for s,q in b.get("auditoria",{}).get("rejeicoes_por_boletim",{}).items()])),sec(10,"Palavras-chave",table(["Palavra","Ocorrências"],[[e(x.get("palavra")),e(x.get("ocorrencias"))] for x in b.get("auditoria",{}).get("top_palavras_chave_detectadas",[])])),sec(11,"Itens sem classificação",table(["Fonte","Item","Exclusão automática"],sem)),sec(12,"Páginas de validação",f'<div class="links">{links}</div>')])
    css='body{margin:0;background:#f0f2f1;color:#1f2937;font-family:Arial}main{max-width:1180px;margin:28px auto}.top{background:#0d3320;color:#fff;padding:30px;border-radius:10px}section{background:#fff;margin:16px 0;border:1px solid #ddd;border-radius:9px;overflow:hidden}section header{display:flex;gap:12px;align-items:center;padding:14px 20px;background:#f8faf9}section header b{background:#0d3320;color:#fff;padding:8px;border-radius:5px}h2{margin:0;font-size:18px}.body{padding:18px}.tw{overflow:auto}table{width:100%;border-collapse:collapse;font-size:12px}th,td{text-align:left;padding:9px;border-bottom:1px solid #e5e7eb}th{color:#1a4d2e;background:#f5f8f6}.links{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px}.links a{padding:12px;border-left:4px solid #22c55e;color:#0d3320;text-decoration:none;background:#f8faf9}'
    (OUT/"auditoria.html").write_text(f'<!doctype html><html lang="pt-BR"><meta charset="utf-8"><style>{css}</style><main><div class="top"><h1>Auditoria dos Radares</h1><p>Cobertura, coleta e classificação editorial.</p></div>{sections}</main></html>',encoding="utf-8")
if __name__=="__main__":main()
