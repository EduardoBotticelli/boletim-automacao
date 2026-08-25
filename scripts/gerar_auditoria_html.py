"""Gera auditoria consolidada com 12 blocos e cobertura por fonte."""
from html import escape
from pathlib import Path
from collections import Counter
import json
BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "output"
def e(v): return escape(str(v or ""), quote=True)
def load(p): return json.loads(p.read_text(encoding="utf-8"))
def table(headers, rows):
    if not rows: return '<p class="empty">Nenhum registro.</p>'
    return '<div class="tw"><table><thead><tr>' + ''.join(f'<th>{e(h)}</th>' for h in headers) + '</tr></thead><tbody>' + ''.join('<tr>'+''.join(f'<td>{c}</td>' for c in r)+'</tr>' for r in rows) + '</tbody></table></div>'
def sec(n,t,b,s=""): return f'<section id="s{n}"><header><b>{n:02d}</b><div><h2>{e(t)}</h2><small>{e(s)}</small></div></header><div class="body">{b}</div></section>'
def main():
    b, l = load(OUT/'boletim.json'), load(OUT/'log_execucao.json')
    cfg=b.get('boletins_config',{}); nomes=cfg.get('nomes_radares',{}); stats=b.get('estatisticas_por_boletim',{}); audit=b.get('auditoria',{})
    proc=l.get('fontes_processadas',[]); itens=b.get('itens',[]); por_fonte=Counter(i.get('fonte','') for i in itens); status={x.get('fonte'):x for x in b.get('validacao_fontes',[]) if isinstance(x,dict)}
    rows1=[]
    for x in proc:
        v=status.get(x.get('fonte'),{}); rows1.append([e(x.get('fonte')),e(x.get('status')),e(x.get('tamanho_chars','')),e(v.get('publicacoes_aprovadas',por_fonte.get(x.get('fonte'),0))),e(v.get('status_editorial',''))])
    def fm(ch): return [[e(x.get('fonte')),e(x.get('motivo'))] for x in b.get(ch,[]) if isinstance(x,dict)]
    susp=cfg.get('fontes_em_defeso',[]); rows5=[[e(x.get('fonte')),e(x.get('motivo')),e(x.get('reativar_em'))] for x in susp]
    rows6=[[e(nomes.get(s,s)),e(d.get('total',0) if isinstance(d,dict) else d)] for s,d in stats.items()]
    bloq=l.get('resultado',{}).get('filtro1_bloqueios',{}); rows7=[[e(nomes.get(s,s)),e(q)] for s,q in bloq.items()]
    det=l.get('filtro1_bloqueios_detalhe',{}); rows8=[[e(nomes.get(s,s)),e(t)] for s,ts in det.items() for t in ts]
    rows9=[[e(nomes.get(s,s)),e(q)] for s,q in audit.get('rejeicoes_por_boletim',{}).items()]
    rows10=[[e(x.get('palavra')),e(x.get('ocorrencias'))] for x in audit.get('top_palavras_chave_detectadas',[])]
    rows11=[[e(i.get('fonte')),e(i.get('titulo')),e(i.get('data_publicacao'))] for i in itens if not i.get('boletins')]
    links=''.join(f'<a href="validacao_{s}.html">{e(nomes.get(s,s))}</a>' for s in cfg.get('boletins_disponiveis',[]))
    sections=''.join([
      sec(1,'Fontes processadas',table(['Fonte','Coleta','Caracteres','Itens aprovados','Situação editorial'],rows1),f'{len(rows1)} fontes'),
      sec(2,'Fontes sem resultado',table(['Fonte','Motivo'],fm('fontes_sem_resultado'))),
      sec(3,'Fontes sem publicação',table(['Fonte','Motivo'],fm('fontes_sem_publicacao_hoje'))),
      sec(4,'Erros técnicos',table(['Fonte','Motivo'],fm('fontes_com_erro_tecnico'))),
      sec(5,'Fontes em defeso',table(['Fonte','Motivo','Retomada'],rows5)),sec(6,'Totais por Radar',table(['Radar','Total'],rows6)),
      sec(7,'Bloqueios do Filtro 1',table(['Radar','Quantidade'],rows7)),sec(8,'Itens bloqueados',table(['Radar','Item'],rows8)),
      sec(9,'Rejeições por Radar',table(['Radar','Rejeições'],rows9)),sec(10,'Principais palavras-chave',table(['Palavra-chave','Ocorrências'],rows10)),
      sec(11,'Itens sem classificação',table(['Fonte','Item','Data'],rows11)),sec(12,'Páginas de validação',f'<div class="links">{links}</div>')])
    doc=f'''<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width"><title>Auditoria dos Radares</title><style>body{{margin:0;background:#f0f2f1;color:#1f2937;font-family:Arial}}main{{max-width:1180px;margin:28px auto}}.top{{background:#0d3320;color:white;padding:30px;border-radius:10px}}section{{background:white;margin:16px 0;border:1px solid #e5e7eb;border-radius:9px;overflow:hidden}}section header{{display:flex;gap:14px;padding:16px 20px;background:#f8faf9}}section header>b{{background:#0d3320;color:white;padding:8px;border-radius:5px}}h2{{margin:0;color:#0d3320;font-size:18px}}small{{color:#6b7280}}.body{{padding:18px 20px}}.tw{{overflow:auto}}table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{text-align:left;padding:9px;border-bottom:1px solid #e5e7eb}}th{{color:#1a4d2e;background:#f5f8f6}}.links{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px}}.links a{{padding:12px;border-left:4px solid #22c55e;color:#0d3320;text-decoration:none;background:#f8faf9}}.empty{{color:#6b7280;text-align:center}}</style></head><body><main><div class="top"><h1>Auditoria dos Radares</h1><p>Painel técnico da execução e cobertura das fontes.</p></div>{sections}</main></body></html>'''
    (OUT/'auditoria.html').write_text(doc,encoding='utf-8'); print('Auditoria gerada.')
if __name__=='__main__': main()
