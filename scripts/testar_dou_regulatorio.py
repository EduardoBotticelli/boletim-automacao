"""Prova de conceito separada: extrai publicações do DOU para o cluster Regulatório."""
import datetime,html,json,os,time
from pathlib import Path
from zoneinfo import ZoneInfo
from firecrawl import Firecrawl
from google import genai
from google.genai import types
BASE=Path(__file__).resolve().parent.parent; OUT=BASE/'output'; OJ=OUT/'teste_dou_regulatorio.json'; OH=OUT/'teste_dou_regulatorio.html'
FK=os.environ.get('FIRECRAWL_API_KEY'); GK=os.environ.get('GEMINI_API_KEY'); MODELOS=['gemini-3.7-flash','gemini-3.6-flash','gemini-3.5-flash','gemini-3.5-flash-lite','gemini-2.5-flash']
ORGAOS=['ANATEL','SUSEP','ANTT','CADE','MDIC','MME','ANP','ANEEL','ANTAQ','CNPE','SENACON','ANVISA','ANM']
def err(e):return any(x in str(e).lower() for x in ['429','500','502','503','504','rate limit','unavailable','timeout','not found'])
def salvar(p,d):
 t=p.with_suffix(p.suffix+'.tmp'); t.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8'); os.replace(t,p)
def main():
 if not FK or not GK: raise SystemExit('ERRO: secrets ausentes.')
 OUT.mkdir(exist_ok=True); data=os.environ.get('DOU_DATA') or datetime.datetime.now(ZoneInfo('America/Sao_Paulo')).strftime('%d-%m-%Y'); datetime.datetime.strptime(data,'%d-%m-%Y'); secao=os.environ.get('DOU_SECAO','do1'); url=os.environ.get('DOU_URL') or f'https://www.in.gov.br/leiturajornal?data={data}&secao={secao}'
 fc=Firecrawl(api_key=FK); conteudo=''
 for t in range(1,4):
  try:conteudo=(fc.scrape(url,formats=['markdown'],only_main_content=True).markdown or '')[:120000]; break
  except Exception as e:
   if not err(e) or t==3: raise
   time.sleep(65)
 if not conteudo: raise SystemExit('ERRO: DOU sem conteúdo.')
 prompt=f'''Extraia SOMENTE publicações individuais da Seção 1 do DOU com aderência material ao cluster Regulatório. Não reproduza a edição inteira. Priorize, sem exclusividade, estes órgãos: {json.dumps(ORGAOS,ensure_ascii=False)}. Exclua atos de pessoal, agenda e atos internos sem impacto externo. Não invente dados. Retorne JSON válido: {{"publicacoes":[{{"titulo":"","orgao":"","tipo_ato":"","data_publicacao":"AAAA-MM-DD ou vazio","resumo":"até 500 caracteres","justificativa_regulatorio":"até 300 caracteres","palavras_chave":[],"url_publicacao":""}}],"observacoes_tecnicas":[]}}. Conteúdo:\n{conteudo}'''
 c=genai.Client(api_key=GK); tent=[]; dados=None; modelo=''
 try:
  for m in MODELOS:
   for t in range(1,3):
    try:
     r=c.models.generate_content(model=m,contents=prompt,config=types.GenerateContentConfig(temperature=.1,response_mime_type='application/json')); d=json.loads(r.text or '')
     if not isinstance(d.get('publicacoes'),list): raise ValueError('publicacoes ausente')
     dados=d; modelo=m; tent.append({'modelo':m,'tentativa':t,'status':'sucesso'}); break
    except Exception as e:
     tent.append({'modelo':m,'tentativa':t,'status':'erro','erro':' '.join(str(e).split())[:500]})
     if t<2:time.sleep([10,30][t-1])
   if dados:break
 finally:c.close()
 if not dados: salvar(OJ,{'status':'falha','data_dou':data,'url_edicao':url,'tentativas_gemini':tent}); raise SystemExit('ERRO: Gemini falhou.')
 pubs=[]
 for x in dados['publicacoes']:
  if not isinstance(x,dict):continue
  y={k:str(x.get(k,'')).strip() for k in ['titulo','orgao','tipo_ato','data_publicacao','resumo','justificativa_regulatorio','url_publicacao']}; y['palavras_chave']=[str(p).strip() for p in x.get('palavras_chave',[]) if isinstance(p,str) and p.strip()]
  if y['titulo'] and y['resumo']:pubs.append(y)
 dados.update({'publicacoes':pubs,'data_dou':data,'secao':'Seção 1' if secao=='do1' else secao,'url_edicao':url,'modelo_gemini_utilizado':modelo,'tentativas_gemini':tent,'total_publicacoes_regulatorias':len(pubs)}); salvar(OJ,dados)
 cards=''.join(f'<article><small>{html.escape(x["orgao"])} · {html.escape(x["tipo_ato"])}</small><h2>{html.escape(x["titulo"])}</h2><p>{html.escape(x["resumo"])}</p><p><b>Aderência:</b> {html.escape(x["justificativa_regulatorio"])}</p></article>' for x in pubs) or '<p>Nenhuma publicação aderente identificada.</p>'; doc=f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Teste DOU Regulatório</title><style>body{{background:#f0f2f1;font-family:Arial}}main{{max-width:900px;margin:24px auto}}header{{background:#0d3320;color:white;padding:28px}}article{{background:white;padding:20px;margin-top:14px}}h2{{color:#0d3320}}</style></head><body><main><header><h1>DOU · Cluster Regulatório</h1><p>{html.escape(data)} · {len(pubs)} publicações</p></header>{cards}</main></body></html>'; tmp=OH.with_suffix('.html.tmp'); tmp.write_text(doc,encoding='utf-8'); os.replace(tmp,OH); print('Teste DOU:',len(pubs),'publicações')
if __name__=='__main__':main()
