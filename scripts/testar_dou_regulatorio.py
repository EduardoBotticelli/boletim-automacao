"""Prova isolada do DOU com critério regulatório restrito."""
import json,os,time
from pathlib import Path
from firecrawl import Firecrawl
from google import genai
from google.genai import types
BASE=Path(__file__).resolve().parent.parent;OUT=BASE/"output";OUT.mkdir(exist_ok=True);DATA=os.getenv("DOU_DATA","24-08-2026");URL=f"https://www.in.gov.br/leiturajornal?data={DATA}&secao=do1";MODELOS=["gemini-3.7-flash","gemini-3.6-flash","gemini-3.5-flash","gemini-2.5-flash"]
def main():
    fc=Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"]); texto=(fc.scrape(URL,formats=["markdown"],only_main_content=True).markdown or "")[:60000]
    prompt="""Retorne JSON com publicacoes. Cada publicação: titulo, orgao, tipo_ato, data_publicacao, resumo, justificativa_regulatorio, url_publicacao e palavras_chave. Inclua somente atos com impacto jurídico externo concreto sobre setores regulados, agentes econômicos, concessionárias, autorizadas, fiscalização, sanções, consultas públicas, outorgas ou obrigações regulatórias. Exclua pessoal, organização interna, orçamento, planos genéricos, eventos, capacitação, prêmios e portarias locais sem impacto setorial nacional. Não invente dados."""+"\n"+texto
    client=genai.Client(api_key=os.environ["GEMINI_API_KEY"]);dados=None;logs=[];vencedor=""
    try:
        for m in MODELOS:
            for t in (1,2):
                try:r=client.models.generate_content(model=m,contents=prompt,config=types.GenerateContentConfig(temperature=.1,response_mime_type="application/json"));dados=json.loads(r.text);vencedor=m;logs.append({"modelo":m,"tentativa":t,"status":"sucesso"});break
                except Exception as ex:logs.append({"modelo":m,"tentativa":t,"status":"erro","erro":" ".join(str(ex).split())[:500]});time.sleep(10)
            if dados is not None:break
    finally:client.close()
    if dados is None:raise SystemExit("Cascata DOU falhou")
    pubs=dados.get("publicacoes",[]);saida={"publicacoes":pubs,"observacoes_tecnicas":dados.get("observacoes_tecnicas",[]),"data_dou":DATA,"secao":"Seção 1","url_edicao":URL,"modelo_gemini_utilizado":vencedor,"tentativas_gemini":logs,"total_publicacoes_regulatorias":len(pubs)};(OUT/"teste_dou_regulatorio.json").write_text(json.dumps(saida,ensure_ascii=False,indent=2),encoding="utf-8")
    cards=''.join(f'<article><small>{x.get("orgao","")} · {x.get("tipo_ato","")}</small><h2>{x.get("titulo","")}</h2><p>{x.get("resumo","")}</p></article>' for x in pubs);(OUT/"teste_dou_regulatorio.html").write_text(f'<!doctype html><meta charset="utf-8"><style>body{{font-family:Arial;background:#eee}}main{{max-width:900px;margin:auto}}article{{background:white;padding:20px;margin:12px}}</style><main><h1>DOU · Regulatório</h1>{cards}</main>',encoding="utf-8")
if __name__=="__main__":main()
