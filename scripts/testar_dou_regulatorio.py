"""Prova de conceito isolada para extração textual do DOU, Seção 1."""
import json, os, sys, time
from pathlib import Path
from firecrawl import Firecrawl
from google import genai
from google.genai import types
BASE=Path(__file__).resolve().parent.parent; OUT=BASE/'output'; OUT.mkdir(exist_ok=True)
DATA=os.getenv('DOU_DATA','24-08-2026'); URL=f'https://www.in.gov.br/leiturajornal?data={DATA}&secao=do1'
MODELOS=['gemini-3.7-flash','gemini-3.6-flash','gemini-3.5-flash','gemini-3.5-flash-lite','gemini-2.5-flash']
def main():
    if not os.getenv('FIRECRAWL_API_KEY') or not os.getenv('GEMINI_API_KEY'): raise SystemExit('Secrets ausentes.')
    r=Firecrawl(api_key=os.environ['FIRECRAWL_API_KEY']).scrape(URL,formats=['markdown'],only_main_content=True)
    texto=(r.markdown or '')[:60000]
    prompt='''Analise somente esta edição do DOU Seção 1. Retorne JSON com publicacoes, cada uma com titulo, orgao, tipo_ato, data_publicacao, resumo, justificativa_regulatorio, url_publicacao e palavras_chave. Inclua apenas atos com aderência real ao cluster Regulatório e exclua pessoal, organização interna e atos meramente administrativos. Não invente dados.'''+'\n'+texto
    client=genai.Client(api_key=os.environ['GEMINI_API_KEY']); logs=[]; dados=None; vencedor=''
    try:
      for modelo in MODELOS:
       for tentativa in (1,2):
        try:
         resp=client.models.generate_content(model=modelo,contents=prompt,config=types.GenerateContentConfig(temperature=.1,response_mime_type='application/json')); dados=json.loads(resp.text); vencedor=modelo; logs.append({'modelo':modelo,'tentativa':tentativa,'status':'sucesso'}); break
        except Exception as erro:
         logs.append({'modelo':modelo,'tentativa':tentativa,'status':'erro','erro':' '.join(str(erro).split())[:500]}); time.sleep(10)
       if dados is not None: break
    finally: client.close()
    if dados is None: raise SystemExit('Toda a cascata falhou.')
    pubs=dados.get('publicacoes',[]) if isinstance(dados,dict) else []
    saida={'publicacoes':pubs,'observacoes_tecnicas':dados.get('observacoes_tecnicas',[]),'data_dou':DATA,'secao':'Seção 1','url_edicao':URL,'modelo_gemini_utilizado':vencedor,'tentativas_gemini':logs,'total_publicacoes_regulatorias':len(pubs)}
    (OUT/'teste_dou_regulatorio.json').write_text(json.dumps(saida,ensure_ascii=False,indent=2),encoding='utf-8')
    artigos=''.join(f"<article><small>{p.get('orgao','')} · {p.get('tipo_ato','')}</small><h2>{p.get('titulo','')}</h2><p>{p.get('resumo','')}</p><p><b>Aderência:</b> {p.get('justificativa_regulatorio','')}</p></article>" for p in pubs)
    (OUT/'teste_dou_regulatorio.html').write_text(f'<!doctype html><html lang="pt-BR"><meta charset="utf-8"><style>body{{background:#f0f2f1;font-family:Arial}}main{{max-width:900px;margin:24px auto}}header{{background:#0d3320;color:#fff;padding:28px}}article{{background:#fff;padding:20px;margin-top:14px}}</style><main><header><h1>DOU · Cluster Regulatório</h1><p>{DATA} · {len(pubs)} publicações</p></header>{artigos}</main></html>',encoding='utf-8')
if __name__=='__main__': main()
