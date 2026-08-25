"""Gera os Radares com coleta Firecrawl, cascata Gemini, Filtros 1/2 e auditoria."""
import datetime,json,os,time,unicodedata
from collections import Counter
from zoneinfo import ZoneInfo
from firecrawl import Firecrawl
from google import genai
from google.genai import types

BASE_DIR=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTES_PATH=os.path.join(BASE_DIR,"fontes.json"); PROMPT_PATH=os.path.join(BASE_DIR,"prompt.md")
OUTPUT_DIR=os.path.join(BASE_DIR,"output"); OUTPUT_PATH=os.path.join(OUTPUT_DIR,"boletim.json"); LOG_PATH=os.path.join(OUTPUT_DIR,"log_execucao.json")
FIRECRAWL_API_KEY=os.environ.get("FIRECRAWL_API_KEY"); GEMINI_API_KEY=os.environ.get("GEMINI_API_KEY")
CASCATA_MODELOS=["gemini-3.7-flash","gemini-3.6-flash","gemini-3.5-flash","gemini-3.5-flash-lite","gemini-2.5-flash"]
TENTATIVAS_POR_MODELO=2; ESPERAS_GEMINI_SEGUNDOS=[10,30]; MIN_CONTEUDO_CHARS=500; MAX_CONTEUDO_CHARS=10000
INTERVALO_ENTRE_SCRAPES_SEGUNDOS=6.5; MAX_TENTATIVAS_SCRAPE=3; ESPERA_RATE_LIMIT_SEGUNDOS=65
DESCRICAO_RADARES="Informativo com atualizações legislativas, regulamentações, consultas públicas e publicações de órgãos reguladores."
BOLETINS_DISPONIVEIS=["trabalhista-empresarial","direito-tributario","societario-ma","mercado-capitais-fundos","regulatorio-oleo-gas","imobiliario-infraestrutura","ambiental-esg","propriedade-intelectual","contencioso-civel"]
NOMES_RADARES={"trabalhista-empresarial":"Radar Trabalhista Empresarial","direito-tributario":"Radar Tributário","societario-ma":"Radar Societário, Fusões e Aquisições","mercado-capitais-fundos":"Radar Mercado de Capitais e Fundos de Investimento","regulatorio-oleo-gas":"Radar Regulatório e Óleo e Gás","imobiliario-infraestrutura":"Radar Negócios Imobiliários e Infraestrutura","ambiental-esg":"Radar Ambiental e ESG","propriedade-intelectual":"Radar Propriedade Intelectual, Tecnologia e Privacidade","contencioso-civel":"Radar Solução de Conflitos"}
CLUSTERS_POR_BOLETIM={"trabalhista-empresarial":["Amber","Pink"],"direito-tributario":["Tributário Consultivo","Tributário Contencioso"],"societario-ma":["White","Purple","Due Diligence"],"mercado-capitais-fundos":["Financeiro Green","Fundos"],"regulatorio-oleo-gas":["Regulatório","Óleo & Gás Blue"],"imobiliario-infraestrutura":["Imobiliário","Infraestrutura"],"ambiental-esg":["Ambiental"],"propriedade-intelectual":["Propriedade Intelectual"],"contencioso-civel":["Contencioso Carbon","Contencioso Gold"]}
FONTES_EMAIL_PENDENTES={"trabalhista-empresarial":[],"direito-tributario":["Tributário.com"],"societario-ma":["Latin Lawyer"],"mercado-capitais-fundos":["Latin Lawyer"],"regulatorio-oleo-gas":["Agência iNFRA","iNFRA Energia","Agência Eixos"],"imobiliario-infraestrutura":["Agência iNFRA","iNFRA Energia","IRIB","Latin Lawyer"],"ambiental-esg":["RC Ambiental"],"propriedade-intelectual":[],"contencioso-civel":[]}
FONTES_PENDENTES_INTEGRACAO={"regulatorio-oleo-gas":["CADE - Diário Oficial da União (Seções 1 e 3)","MEC - Diário Oficial da União (Seções 1 e 3)","MDIC - Diário Oficial da União (Seção 1)","Portal da Legislação","Portal da Câmara dos Deputados","Portal do Senado Federal","Agência Eixos"]}

def sem_acento(s): return ''.join(c for c in unicodedata.normalize('NFD',str(s)) if unicodedata.category(c)!='Mn')
def chave_fonte(s): return sem_acento(s).replace("Últimas","Ultimas").replace("Prévias","Previas")
FONTE_PARA_BOLETINS={
"Planalto | Resenha Diaria":BOLETINS_DISPONIVEIS.copy(),"Destaques do D.O.U.":["trabalhista-empresarial","direito-tributario","regulatorio-oleo-gas","contencioso-civel"],"Ministerio da Fazenda | Noticias":BOLETINS_DISPONIVEIS.copy(),"CGU | Noticias":["trabalhista-empresarial","regulatorio-oleo-gas"],"Receita Federal | Normas":["direito-tributario"],"Banco Central | Normas":["direito-tributario","societario-ma","mercado-capitais-fundos"],"COAF | Noticias":["direito-tributario","mercado-capitais-fundos"],"CVM | Noticias":["mercado-capitais-fundos","regulatorio-oleo-gas","imobiliario-infraestrutura"],"B3 | Oficios e Comunicados":["mercado-capitais-fundos"],"ANP | Noticias":["regulatorio-oleo-gas","imobiliario-infraestrutura","ambiental-esg"],"ANP | Consultas e Audiencias Publicas":["regulatorio-oleo-gas","imobiliario-infraestrutura","ambiental-esg"],"ANP | Consultas Previas":["regulatorio-oleo-gas"],"ANP | Pautas e Atas da Diretoria Colegiada":["regulatorio-oleo-gas"],"ANEEL | Ultimas Noticias":["societario-ma","regulatorio-oleo-gas","imobiliario-infraestrutura","ambiental-esg"],"ANM | Noticias":["regulatorio-oleo-gas","imobiliario-infraestrutura","ambiental-esg"],"ANVISA | Noticias":["regulatorio-oleo-gas"],"SENACON | Noticias":["regulatorio-oleo-gas","propriedade-intelectual","contencioso-civel"],"Secretaria de Premios e Apostas | Noticias":[],"ONS | Noticias":["imobiliario-infraestrutura","ambiental-esg"],"CCEE | Noticias":["imobiliario-infraestrutura","ambiental-esg"],"EPE | Noticias":["regulatorio-oleo-gas","imobiliario-infraestrutura","ambiental-esg"],"MME | Noticias":["regulatorio-oleo-gas","imobiliario-infraestrutura","ambiental-esg"],"MME | Consultas Publicas":["regulatorio-oleo-gas","imobiliario-infraestrutura","ambiental-esg"],"Ministerio do Meio Ambiente | Noticias":["ambiental-esg"],"Ministerio da Agricultura | Noticias":["imobiliario-infraestrutura","ambiental-esg"],"INPI | Noticias":["propriedade-intelectual"],"ANPD | Noticias":["propriedade-intelectual"],"ANTAQ | Noticias":["regulatorio-oleo-gas","imobiliario-infraestrutura"],"CNPE | Comunicacoes":["regulatorio-oleo-gas"],"Kollemata | Decretos":["imobiliario-infraestrutura"],"ANATEL | Noticias":["regulatorio-oleo-gas","imobiliario-infraestrutura"],"SUSEP | Noticias":["mercado-capitais-fundos","regulatorio-oleo-gas","imobiliario-infraestrutura","ambiental-esg"],"ANTT | Noticias - Defeso Eleitoral":["regulatorio-oleo-gas","imobiliario-infraestrutura","ambiental-esg"]}

def exigir_secrets():
 if not FIRECRAWL_API_KEY: raise SystemExit("ERRO: FIRECRAWL_API_KEY não encontrada.")
 if not GEMINI_API_KEY: raise SystemExit("ERRO: GEMINI_API_KEY não encontrada.")
def normalizar_lista(valor,motivo):
 out=[]; vistos=set()
 for x in valor if isinstance(valor,list) else []:
  f=str(x.get('fonte','')).strip() if isinstance(x,dict) else str(x).strip(); m=str(x.get('motivo',motivo)).strip() if isinstance(x,dict) else motivo
  if f and f not in vistos: vistos.add(f); out.append({'fonte':f,'motivo':m})
 return out
def salvar(caminho,dados):
 tmp=caminho+'.tmp'
 with open(tmp,'w',encoding='utf-8') as a: json.dump(dados,a,ensure_ascii=False,indent=2); a.flush(); os.fsync(a.fileno())
 os.replace(tmp,caminho)
def recuperavel(e): return any(x in str(e).lower() for x in ['429','500','502','503','504','rate limit','unavailable','timeout','not found','not supported'])
def scrape(fc,url):
 for t in range(1,MAX_TENTATIVAS_SCRAPE+1):
  try:return fc.scrape(url,formats=['markdown'],only_main_content=True)
  except Exception as e:
   if not recuperavel(e) or t==MAX_TENTATIVAS_SCRAPE: raise
   time.sleep(ESPERA_RATE_LIMIT_SEGUNDOS)
def gemini(client,prompt):
 logs=[]
 for modelo in CASCATA_MODELOS:
  for t in range(1,TENTATIVAS_POR_MODELO+1):
   try:
    r=client.models.generate_content(model=modelo,contents=prompt,config=types.GenerateContentConfig(temperature=.2,response_mime_type='application/json')); texto=r.text or ''; d=json.loads(texto)
    if not isinstance(d,dict) or not isinstance(d.get('itens'),list): raise ValueError('JSON sem lista itens')
    logs.append({'modelo':modelo,'tentativa':t,'status':'sucesso'}); return d,modelo,logs
   except Exception as e:
    logs.append({'modelo':modelo,'tentativa':t,'status':'erro','erro':' '.join(str(e).split())[:500]})
    if not recuperavel(e) and not isinstance(e,(ValueError,json.JSONDecodeError)): return None,'',logs
    if t<TENTATIVAS_POR_MODELO: time.sleep(ESPERAS_GEMINI_SEGUNDOS[min(t-1,len(ESPERAS_GEMINI_SEGUNDOS)-1)])
 return None,'',logs

def carregar_fontes(inicio,agora,hoje):
 with open(FONTES_PATH,encoding='utf-8') as a: fontes=json.load(a)
 di=inicio.strftime('%d/%m/%Y').replace('/','%2F'); df=agora.strftime('%d/%m/%Y').replace('/','%2F'); meses=['janeiro','fevereiro','marco','abril','maio','junho','julho','agosto','setembro','outubro','novembro','dezembro']
 din=[{'fonte':'Planalto | Resenha Diaria','categoria':'Legislação Federal','url':'http://www4.planalto.gov.br/legislacao/portal-legis/resenha-diaria/'+meses[hoje.month-1]+'-resenha-diaria','ativo':True},{'fonte':'Banco Central | Normas','categoria':'Financeiro e Mercado de Capitais','url':'https://www.bcb.gov.br/estabilidadefinanceira/buscanormas?dataInicioBusca='+di+'&dataFimBusca='+df+'&tipoDocumento=Todos','ativo':True},{'fonte':'CCEE | Noticias','categoria':'Energia e Recursos','url':'https://www.ccee.org.br/busca-ccee?q=&dtIni='+di+'&dtFim='+df+'&structure=ccee-noticias&ordenacao=Mais%20recentes','ativo':True}]
 return din+fontes

def main():
 exigir_secrets(); os.makedirs(OUTPUT_DIR,exist_ok=True); brt=ZoneInfo('America/Sao_Paulo'); agora=datetime.datetime.now(brt); hoje=agora.date(); inicio=datetime.datetime.combine(hoje-datetime.timedelta(days=3 if hoje.weekday()==0 else 1),datetime.time(),tzinfo=brt)
 fontes=carregar_fontes(inicio,agora,hoje); ativas=[]; suspensas=[]; inativas=[]
 for f in fontes:
  if not f.get('ativo',True): inativas.append(f); continue
  reativar=f.get('reativar_em'); suspenso=bool(f.get('suspenso')) and (not reativar or hoje<datetime.date.fromisoformat(reativar))
  if suspenso: suspensas.append({'fonte':f['fonte'],'motivo':f.get('motivo_suspensao','Suspensão temporária'),'reativar_em':reativar or ''})
  else: ativas.append(f)
 print(f'{len(ativas)} fontes a processar; {len(suspensas)} suspensas; {len(inativas)} inativas')
 with open(PROMPT_PATH,encoding='utf-8') as a: prompt=a.read()
 dossier=[]; log={'data_execucao':hoje.isoformat(),'executado_em':agora.isoformat(),'janela':{'inicio':inicio.strftime('%Y-%m-%dT%H:%M'),'fim':agora.strftime('%Y-%m-%dT%H:%M')},'fontes_processadas':[],'fontes_suspensas':suspensas,'fontes_inativas':[f['fonte'] for f in inativas]}; fc=Firecrawl(api_key=FIRECRAWL_API_KEY)
 for i,f in enumerate(ativas,1):
  try:
   r=scrape(fc,f['url']); c=(r.markdown or '')[:MAX_CONTEUDO_CHARS]; erro='' if len(c)>=MIN_CONTEUDO_CHARS else f'Conteúdo muito curto ({len(c)} chars)'; dossier.append({'fonte':f['fonte'],'categoria':f['categoria'],'url':f['url'],'tipo_coleta':f.get('tipo_coleta','pagina'),'conteudo':c if not erro else '',**({'erro_tecnico':erro} if erro else {})}); log['fontes_processadas'].append({'fonte':f['fonte'],'status':'ok' if not erro else 'erro_tecnico','tamanho_chars':len(c),**({'detalhe':erro} if erro else {})})
  except Exception as e:
   m=' '.join(str(e).split())[:300]; dossier.append({'fonte':f['fonte'],'categoria':f['categoria'],'url':f['url'],'conteudo':'','erro_tecnico':m}); log['fontes_processadas'].append({'fonte':f['fonte'],'status':'erro','erro':m})
  if i<len(ativas): time.sleep(INTERVALO_ENTRE_SCRAPES_SEGUNDOS)
 cliente=genai.Client(api_key=GEMINI_API_KEY)
 try: boletim,modelo,tentativas=gemini(cliente,prompt+'\n\n## Contexto\n'+json.dumps({'inicio':log['janela']['inicio'],'fim':log['janela']['fim']},ensure_ascii=False)+'\n\n## Dossier\n'+json.dumps(dossier,ensure_ascii=False))
 finally: cliente.close()
 log['tentativas_gemini']=tentativas
 if not boletim: log['resultado']={'status':'falha_gemini','boletim_anterior_preservado':os.path.exists(OUTPUT_PATH)}; salvar(LOG_PATH,log); raise SystemExit('ERRO: cascata Gemini falhou; boletim anterior preservado.')
 boletim['data_execucao']=hoje.isoformat(); boletim['janela_aplicada']=log['janela']; boletim['modelo_gemini_utilizado']=modelo
 for k,m in [('fontes_sem_resultado','Página acessada sem conteúdo utilizável.'),('fontes_sem_publicacao_hoje','Nenhuma publicação identificada na janela.'),('fontes_com_erro_tecnico','Erro técnico na coleta.')]: boletim[k]=normalizar_lista(boletim.get(k,[]),m)
 erros=[{'fonte':x['fonte'],'motivo':x['erro_tecnico']} for x in dossier if x.get('erro_tecnico')]; nomes={x['fonte'] for x in erros}; boletim['fontes_sem_resultado']=[x for x in boletim['fontes_sem_resultado'] if x['fonte'] not in nomes]; boletim['fontes_sem_publicacao_hoje']=[x for x in boletim['fontes_sem_publicacao_hoje'] if x['fonte'] not in nomes]; existentes={x['fonte'] for x in boletim['fontes_com_erro_tecnico']}; boletim['fontes_com_erro_tecnico'] += [x for x in erros if x['fonte'] not in existentes]
 itens=[]; descartados=[]
 for x in boletim['itens']:
  if not isinstance(x,dict): continue
  ds=str(x.get('data_publicacao','')).strip()
  try: ok=not ds or inicio.date()<=datetime.date.fromisoformat(ds[:10])<=hoje
  except ValueError: x['data_publicacao']=''; ok=True
  (itens if ok else descartados).append(x)
 bloqueios={}; rejeicoes=Counter(); palavras=Counter(); com_bloqueio=0; com_rejeicao=0
 for x in itens:
  fonte=str(x.get('fonte','')); permitidos=set(FONTE_PARA_BOLETINS.get(chave_fonte(fonte),[])); conf=x.get('boletins_confirmados',[]); conf=conf if isinstance(conf,list) else []; sugeridos={s for s in conf if s in BOLETINS_DISPONIVEIS}; finais=[s for s in BOLETINS_DISPONIVEIS if s in permitidos&sugeridos]; bloqueados=sugeridos-permitidos
  if bloqueados: com_bloqueio+=1
  for s in bloqueados: bloqueios.setdefault(s,[]).append(x.get('titulo',''))
  rej=[r for r in x.get('boletins_rejeitados',[]) if isinstance(r,dict)] if isinstance(x.get('boletins_rejeitados',[]),list) else []; existentes={r.get('boletim') for r in rej}
  for s in bloqueados:
   if s not in existentes: rej.append({'boletim':s,'motivo':f"Filtro 1: fonte '{fonte}' não está mapeada para este Radar"})
  x['boletins_rejeitados']=rej; x['boletins']=finais; pcs=x.get('palavras_chave_detectadas',[]); x['palavras_chave_detectadas']=pcs if isinstance(pcs,list) else []
  if rej: com_rejeicao+=1
  for r in rej:
   if r.get('boletim'): rejeicoes[r['boletim']]+=1
  for p in x['palavras_chave_detectadas']:
   if isinstance(p,str) and p.strip(): palavras[p.lower().strip()]+=1
 boletim['itens']=itens; boletim['boletins_config']={'descricao':DESCRICAO_RADARES,'boletins_disponiveis':BOLETINS_DISPONIVEIS,'nomes_radares':NOMES_RADARES,'clusters_por_boletim':CLUSTERS_POR_BOLETIM,'fontes_email_pendentes':FONTES_EMAIL_PENDENTES,'fontes_pendentes_integracao':FONTES_PENDENTES_INTEGRACAO,'mapeamento_fonte_boletim':FONTE_PARA_BOLETINS,'fontes_em_defeso':suspensas}
 stats={s:{'nome':NOMES_RADARES[s],'clusters':CLUSTERS_POR_BOLETIM[s],'total':sum(s in x.get('boletins',[]) for x in itens)} for s in BOLETINS_DISPONIVEIS}; boletim['estatisticas_por_boletim']=stats; boletim['auditoria']={'total_itens':len(itens),'itens_com_alguma_rejeicao':com_rejeicao,'itens_com_bloqueio_f1':com_bloqueio,'rejeicoes_por_boletim':dict(rejeicoes),'top_palavras_chave_detectadas':[{'palavra':p,'ocorrencias':c} for p,c in palavras.most_common(20)]}
 log['resultado']={'status':'sucesso','modelo_gemini_utilizado':modelo,'itens_aceitos':len(itens),'itens_descartados_pos_validacao':len(descartados),'fontes_ativas':len(ativas),'fontes_suspensas':len(suspensas),'fontes_inativas':len(inativas),'fontes_sem_resultado':len(boletim['fontes_sem_resultado']),'fontes_sem_publicacao_hoje':len(boletim['fontes_sem_publicacao_hoje']),'fontes_com_erro_tecnico':len(boletim['fontes_com_erro_tecnico']),'itens_por_boletim':stats,'filtro1_bloqueios':{s:len(v) for s,v in bloqueios.items()},'auditoria':boletim['auditoria']}; log['filtro1_bloqueios_detalhe']=bloqueios
 salvar(OUTPUT_PATH,boletim); salvar(LOG_PATH,log); print('Concluído:',len(itens),'itens; modelo',modelo)
if __name__=='__main__': main()
