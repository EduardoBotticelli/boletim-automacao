"""Radares Lobo de Rizzo: coleta, curadoria, filtros e auditoria de cobertura."""
import datetime
import json
import os
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

from firecrawl import Firecrawl
from google import genai
from google.genai import types

BASE = Path(__file__).resolve().parent.parent
FONTES_PATH = BASE / "fontes.json"
PROMPT_PATH = BASE / "prompt.md"
OUT = BASE / "output"
BOLETIM_PATH = OUT / "boletim.json"
LOG_PATH = OUT / "log_execucao.json"
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

MODELOS = ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"]
TENTATIVAS_GEMINI = 2
ESPERAS_GEMINI = [10, 30]
MIN_CHARS = 500
MAX_CHARS = 30000
INTERVALO_SCRAPE = 6.5
TENTATIVAS_SCRAPE = 3
ESPERA_429 = 65

SLUGS = [
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
CLUSTERS = {
    "trabalhista-empresarial": ["Amber", "Pink"],
    "direito-tributario": ["Tributário Consultivo", "Tributário Contencioso"],
    "societario-ma": ["White", "Purple", "Due Diligence"],
    "mercado-capitais-fundos": ["Financeiro Green", "Fundos"],
    "regulatorio-oleo-gas": ["Regulatório", "Óleo & Gás Blue"],
    "imobiliario-infraestrutura": ["Imobiliário", "Infraestrutura"],
    "ambiental-esg": ["Ambiental"],
    "propriedade-intelectual": ["Propriedade Intelectual"],
    "contencioso-civel": ["Contencioso Carbon", "Contencioso Gold"],
}
EMAIL_PENDENTES = {
    "trabalhista-empresarial": [], "direito-tributario": ["Tributário.com"],
    "societario-ma": ["Latin Lawyer"], "mercado-capitais-fundos": ["Latin Lawyer"],
    "regulatorio-oleo-gas": ["Agência iNFRA", "iNFRA Energia", "Agência Eixos"],
    "imobiliario-infraestrutura": ["Agência iNFRA", "iNFRA Energia", "IRIB", "Latin Lawyer"],
    "ambiental-esg": ["RC Ambiental"], "propriedade-intelectual": [], "contencioso-civel": [],
}
PENDENTES = {"regulatorio-oleo-gas": [
    "CADE - Diário Oficial da União (Seções 1 e 3)", "MEC - Diário Oficial da União (Seções 1 e 3)",
    "MDIC - Diário Oficial da União (Seção 1)", "Portal da Legislação",
    "Portal da Câmara dos Deputados", "Portal do Senado Federal", "Agência Eixos",
]}
MAPA = {
    "Planalto | Resenha Diaria": SLUGS.copy(),
    "Destaques do D.O.U.": ["trabalhista-empresarial", "direito-tributario", "regulatorio-oleo-gas", "contencioso-civel"],
    "Ministerio da Fazenda | Noticias": SLUGS.copy(),
    "CGU | Noticias": ["trabalhista-empresarial", "regulatorio-oleo-gas"],
    "Receita Federal | Normas": ["direito-tributario"],
    "Banco Central | Normas": ["direito-tributario", "societario-ma", "mercado-capitais-fundos"],
    "COAF | Noticias": ["direito-tributario", "mercado-capitais-fundos"],
    "CVM | Noticias": ["mercado-capitais-fundos", "regulatorio-oleo-gas", "imobiliario-infraestrutura"],
    "B3 | Oficios e Comunicados": ["mercado-capitais-fundos"],
    "ANP | Noticias": ["regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"],
    "ANP | Consultas e Audiencias Publicas": ["regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"],
    "ANP | Consultas Previas": ["regulatorio-oleo-gas"],
    "ANP | Pautas e Atas da Diretoria Colegiada": ["regulatorio-oleo-gas"],
    "ANEEL | Ultimas Noticias": ["societario-ma", "regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"],
    "ANM | Noticias": ["regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"],
    "ANVISA | Noticias": ["regulatorio-oleo-gas"],
    "SENACON | Noticias": ["regulatorio-oleo-gas", "propriedade-intelectual", "contencioso-civel"],
    "Secretaria de Premios e Apostas | Noticias": [],
    "ONS | Noticias": ["imobiliario-infraestrutura", "ambiental-esg"],
    "CCEE | Noticias": ["imobiliario-infraestrutura", "ambiental-esg"],
    "EPE | Noticias": ["regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"],
    "MME | Noticias": ["regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"],
    "MME | Consultas Publicas": ["regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"],
    "Ministerio do Meio Ambiente | Noticias": ["ambiental-esg"],
    "Ministerio da Agricultura | Noticias": ["imobiliario-infraestrutura", "ambiental-esg"],
    "INPI | Noticias": ["propriedade-intelectual"], "ANPD | Noticias": ["propriedade-intelectual"],
    "ANTAQ | Noticias": ["regulatorio-oleo-gas", "imobiliario-infraestrutura"],
    "CNPE | Comunicacoes": ["regulatorio-oleo-gas"], "Kollemata | Decretos": ["imobiliario-infraestrutura"],
    "ANATEL | Noticias": ["regulatorio-oleo-gas", "imobiliario-infraestrutura"],
    "SUSEP | Noticias": ["mercado-capitais-fundos", "regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"],
    "ANTT | Noticias - Defeso Eleitoral": ["regulatorio-oleo-gas", "imobiliario-infraestrutura", "ambiental-esg"],
}

def sem_acento(texto):
    return "".join(c for c in unicodedata.normalize("NFD", str(texto)) if unicodedata.category(c) != "Mn")

def normalizar_fonte(nome):
    alvo = sem_acento(nome)
    for chave in MAPA:
        if sem_acento(chave) == alvo:
            return chave
    return nome

def salvar_atomico(path, dados):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)

def resumo_erro(erro, n=500):
    return " ".join(str(erro).split())[:n]

def erro_429(erro):
    t = str(erro).lower()
    return "429" in t or "rate limit" in t or "too many requests" in t

def erro_recuperavel(erro):
    t = str(erro).lower()
    return any(x in t for x in ["429", "500", "502", "503", "504", "unavailable", "high demand", "timeout", "not found", "not supported"])

def pagina_de_erro(conteudo):
    t = conteudo.lower()
    marcadores = ["estamos em manutenção", "estamos em manutencao", "conteúdo restrito", "conteudo restrito", "access denied", "internal server error"]
    return next((m for m in marcadores if m in t), "")

def variantes_fontes(fontes, inicio, agora, hoje):
    di = inicio.strftime("%d/%m/%Y").replace("/", "%2F")
    df = agora.strftime("%d/%m/%Y").replace("/", "%2F")
    meses = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
    dinamicas = [
        {"fonte":"Planalto | Resenha Diaria","categoria":"Legislação Federal","url":f"http://www4.planalto.gov.br/legislacao/portal-legis/resenha-diaria/{meses[hoje.month-1]}-resenha-diaria","ativo":True},
        {"fonte":"Banco Central | Normas","categoria":"Financeiro e Mercado de Capitais","url":f"https://www.bcb.gov.br/estabilidadefinanceira/buscanormas?dataInicioBusca={di}&dataFimBusca={df}&tipoDocumento=Todos","ativo":True},
        {"fonte":"CCEE | Noticias","categoria":"Energia e Recursos","url":f"https://www.ccee.org.br/busca-ccee?q=&dtIni={di}&dtFim={df}&structure=ccee-noticias&ordenacao=Mais%20recentes","ativo":True},
    ]
    return dinamicas + fontes

def estado_fonte(fonte, hoje):
    if not fonte.get("ativo", True):
        return "inativa"
    if fonte.get("suspenso"):
        try:
            if hoje < datetime.date.fromisoformat(fonte.get("reativar_em", "9999-12-31")):
                return "suspensa"
        except ValueError:
            return "suspensa"
    return "ativa"

def scrape_retry(cliente, url):
    for tentativa in range(1, TENTATIVAS_SCRAPE + 1):
        try:
            return cliente.scrape(url, formats=["markdown"], only_main_content=True)
        except Exception as erro:
            if not erro_429(erro) or tentativa == TENTATIVAS_SCRAPE:
                raise
            print(f"      Rate limit. Tentativa {tentativa + 1}/{TENTATIVAS_SCRAPE}")
            time.sleep(ESPERA_429)

def gemini_cascata(cliente, prompt):
    registros = []
    for modelo in MODELOS:
        for tentativa in range(1, TENTATIVAS_GEMINI + 1):
            print(f"Gemini: {modelo}, tentativa {tentativa}/{TENTATIVAS_GEMINI}")
            try:
                r = cliente.models.generate_content(model=modelo, contents=prompt, config=types.GenerateContentConfig(temperature=0.2, response_mime_type="application/json"))
                dados = json.loads(r.text or "")
                if not isinstance(dados, dict) or not isinstance(dados.get("itens"), list):
                    raise ValueError("Resposta sem a estrutura mínima")
                registros.append({"modelo":modelo,"tentativa":tentativa,"status":"sucesso"})
                return dados, modelo, registros
            except Exception as erro:
                registros.append({"modelo":modelo,"tentativa":tentativa,"status":"erro","erro":resumo_erro(erro)})
                print("  " + resumo_erro(erro))
                if not erro_recuperavel(erro) and not isinstance(erro, json.JSONDecodeError):
                    return None, "", registros
                if tentativa < TENTATIVAS_GEMINI:
                    time.sleep(ESPERAS_GEMINI[min(tentativa-1, len(ESPERAS_GEMINI)-1)])
    return None, "", registros

def lista_objetos(valor, motivo):
    out=[]
    for x in valor if isinstance(valor,list) else []:
        if isinstance(x,dict): f=str(x.get("fonte","")).strip(); m=str(x.get("motivo",motivo)).strip() or motivo
        elif isinstance(x,str): f=x.strip(); m=motivo
        else: continue
        if f and f not in {y["fonte"] for y in out}: out.append({"fonte":f,"motivo":m})
    return out

def main():
    if not FIRECRAWL_API_KEY or not GEMINI_API_KEY:
        raise SystemExit("ERRO: secrets FIRECRAWL_API_KEY e GEMINI_API_KEY são obrigatórios.")
    OUT.mkdir(exist_ok=True)
    brt=ZoneInfo("America/Sao_Paulo"); agora=datetime.datetime.now(brt); hoje=agora.date()
    inicio=datetime.datetime.combine(hoje-datetime.timedelta(days=3 if hoje.weekday()==0 else 1),datetime.time(),tzinfo=brt)
    janela_inicio=inicio.strftime("%Y-%m-%dT%H:%M"); janela_fim=agora.strftime("%Y-%m-%dT%H:%M")
    fontes=variantes_fontes(json.loads(FONTES_PATH.read_text(encoding="utf-8")),inicio,agora,hoje)
    ativas=[f for f in fontes if estado_fonte(f,hoje)=="ativa"]
    suspensas=[f for f in fontes if estado_fonte(f,hoje)=="suspensa"]
    inativas=[f for f in fontes if estado_fonte(f,hoje)=="inativa"]
    print(f"Radares: {len(ativas)} fontes ativas, {len(suspensas)} suspensas, {len(inativas)} inativas")
    dossier=[]; log={"data_execucao":hoje.isoformat(),"executado_em":agora.isoformat(),"janela":{"inicio":janela_inicio,"fim":janela_fim},"fontes_processadas":[],"fontes_suspensas":[],"fontes_inativas":[]}
    fc=Firecrawl(api_key=FIRECRAWL_API_KEY)
    for n,fonte in enumerate(ativas,1):
        nome=fonte["fonte"]; print(f"  [{n}/{len(ativas)}] {nome}")
        try:
            r=scrape_retry(fc,fonte["url"]); conteudo=(r.markdown or "")[:MAX_CHARS]
            erro_pagina=pagina_de_erro(conteudo)
            if erro_pagina:
                detalhe=f"A origem retornou uma página de erro/manutenção ({erro_pagina})."
                dossier.append({"fonte":nome,"categoria":fonte["categoria"],"url":fonte["url"],"conteudo":"","erro_tecnico":detalhe})
                log["fontes_processadas"].append({"fonte":nome,"status":"erro_conteudo_origem","tamanho_chars":len(conteudo),"erro":detalhe})
            elif len(conteudo)<MIN_CHARS:
                detalhe=f"Conteúdo insuficiente ({len(conteudo)} caracteres)."
                dossier.append({"fonte":nome,"categoria":fonte["categoria"],"url":fonte["url"],"conteudo":"","erro_tecnico":detalhe})
                log["fontes_processadas"].append({"fonte":nome,"status":"erro_tecnico","tamanho_chars":len(conteudo),"erro":detalhe})
            else:
                dossier.append({"fonte":nome,"categoria":fonte["categoria"],"url":fonte["url"],"tipo_coleta":fonte.get("tipo_coleta","pagina"),"conteudo":conteudo})
                log["fontes_processadas"].append({"fonte":nome,"status":"ok","tamanho_chars":len(conteudo),"conteudo_truncado":len(r.markdown or "")>MAX_CHARS})
        except Exception as erro:
            msg=resumo_erro(erro,300); dossier.append({"fonte":nome,"categoria":fonte["categoria"],"url":fonte["url"],"conteudo":"","erro_tecnico":msg}); log["fontes_processadas"].append({"fonte":nome,"status":"erro","erro":msg})
        if n<len(ativas): time.sleep(INTERVALO_SCRAPE)
    for f in suspensas: log["fontes_suspensas"].append({"fonte":f["fonte"],"motivo":f.get("motivo_suspensao","Suspensão temporária"),"reativar_em":f.get("reativar_em","")})
    for f in inativas: log["fontes_inativas"].append({"fonte":f["fonte"]})
    prompt=PROMPT_PATH.read_text(encoding="utf-8")+f"\n\n## Contexto desta execução\ndata_execucao: {hoje.isoformat()}\njanela_inicio: {janela_inicio}\njanela_fim: {janela_fim}\n\n## Dossier\n"+json.dumps(dossier,ensure_ascii=False)
    cliente=genai.Client(api_key=GEMINI_API_KEY)
    try: boletim,modelo,tentativas=gemini_cascata(cliente,prompt)
    finally: cliente.close()
    log["tentativas_gemini"]=tentativas
    if boletim is None:
        log["resultado"]={"status":"falha_gemini","boletim_anterior_preservado":BOLETIM_PATH.exists()}; salvar_atomico(LOG_PATH,log); raise SystemExit("Todos os modelos Gemini falharam; boletim anterior preservado.")
    boletim["data_execucao"]=hoje.isoformat(); boletim["janela_aplicada"]={"inicio":janela_inicio,"fim":janela_fim}; boletim["modelo_gemini_utilizado"]=modelo
    itens=[]; descartados=[]
    for item in boletim.get("itens",[]):
        if not isinstance(item,dict): continue
        ds=str(item.get("data_publicacao","")).strip()
        if ds:
            try:
                d=datetime.date.fromisoformat(ds[:10])
                if not inicio.date()<=d<=hoje: descartados.append({"titulo":item.get("titulo",""),"data":ds}); continue
            except ValueError: item["data_publicacao"]=""
        itens.append(item)
    bloqueios={}; palavras=Counter(); rejeicoes=Counter(); com_bloqueio=0; com_rejeicao=0
    for item in itens:
        fonte=str(item.get("fonte","")); permitidos=set(MAPA.get(normalizar_fonte(fonte),[])); conf=item.get("boletins_confirmados",[]); sugeridos={x for x in conf if x in SLUGS} if isinstance(conf,list) else set(); finais=[x for x in SLUGS if x in permitidos&sugeridos]; bloqueados=sugeridos-permitidos
        if bloqueados:
            com_bloqueio+=1
            for s in bloqueados: bloqueios.setdefault(s,[]).append(item.get("titulo",""))
        rejs=[x for x in item.get("boletins_rejeitados",[]) if isinstance(x,dict)] if isinstance(item.get("boletins_rejeitados",[]),list) else []
        existentes={x.get("boletim") for x in rejs}
        for s in bloqueados:
            if s not in existentes: rejs.append({"boletim":s,"motivo":f"Filtro 1: fonte '{fonte}' não está mapeada para este Radar"})
        item["boletins_rejeitados"]=rejs; item["boletins"]=finais
        pcs=item.get("palavras_chave_detectadas",[]); item["palavras_chave_detectadas"]=pcs if isinstance(pcs,list) else []
        if rejs: com_rejeicao+=1
        for p in item["palavras_chave_detectadas"]:
            if isinstance(p,str) and p.strip(): palavras[p.lower().strip()]+=1
        for r in rejs:
            if r.get("boletim"): rejeicoes[r["boletim"]]+=1
    boletim["itens"]=itens
    # A verdade técnica vem exclusivamente do log, nunca do Gemini.
    erros=[]
    for x in log["fontes_processadas"]:
        if x.get("status") not in {"ok"}: erros.append({"fonte":x.get("fonte"),"motivo":x.get("erro","Erro técnico na coleta.")})
    nomes_erro={x["fonte"] for x in erros}
    sem_resultado=lista_objetos(boletim.get("fontes_sem_resultado",[]),"A página foi coletada, mas nenhuma publicação individual utilizável foi extraída.")
    sem_publicacao=lista_objetos(boletim.get("fontes_sem_publicacao_hoje",[]),"Nenhuma publicação foi identificada dentro da janela.")
    sem_resultado=[x for x in sem_resultado if x["fonte"] not in nomes_erro]
    sem_publicacao=[x for x in sem_publicacao if x["fonte"] not in nomes_erro]
    boletim["fontes_com_erro_tecnico"]=erros; boletim["fontes_sem_resultado"]=sem_resultado; boletim["fontes_sem_publicacao_hoje"]=sem_publicacao
    por_fonte=Counter(i.get("fonte","") for i in itens)
    sem_res={x["fonte"] for x in sem_resultado}; sem_pub={x["fonte"] for x in sem_publicacao}
    validacao=[]
    for x in log["fontes_processadas"]:
        f=x.get("fonte"); aprov=por_fonte.get(f,0)
        if x.get("status")!="ok": editorial="erro_tecnico"
        elif aprov: editorial="itens_incluidos"
        elif f in sem_res: editorial="sem_publicacao_individual_extraida"
        elif f in sem_pub: editorial="sem_publicacao_na_janela"
        else: editorial="publicacoes_sem_aderencia_editorial"
        validacao.append({"fonte":f,"status_coleta":x.get("status"),"publicacoes_aprovadas":aprov,"status_editorial":editorial,"conteudo_truncado":x.get("conteudo_truncado",False)})
    boletim["validacao_fontes"]=validacao
    susp_config=[{"fonte":x["fonte"],"motivo":x["motivo"],"reativar_em":x["reativar_em"]} for x in log["fontes_suspensas"]]
    boletim["boletins_config"]={"descricao":"Informativo com atualizações legislativas, regulamentações, consultas públicas e publicações de órgãos reguladores.","boletins_disponiveis":SLUGS,"nomes_radares":NOMES,"clusters_por_boletim":CLUSTERS,"fontes_email_pendentes":EMAIL_PENDENTES,"fontes_pendentes_integracao":PENDENTES,"mapeamento_fonte_boletim":MAPA,"fontes_em_defeso":susp_config}
    stats={s:{"nome":NOMES[s],"clusters":CLUSTERS[s],"total":sum(s in i.get("boletins",[]) for i in itens)} for s in SLUGS}; boletim["estatisticas_por_boletim"]=stats
    boletim["auditoria"]={"total_itens":len(itens),"itens_com_alguma_rejeicao":com_rejeicao,"itens_com_bloqueio_f1":com_bloqueio,"rejeicoes_por_boletim":dict(rejeicoes),"top_palavras_chave_detectadas":[{"palavra":p,"ocorrencias":c} for p,c in palavras.most_common(20)]}
    log["resultado"]={"status":"sucesso","modelo_gemini_utilizado":modelo,"itens_aceitos":len(itens),"itens_descartados_pos_validacao":len(descartados),"fontes_ativas":len(ativas),"fontes_suspensas":len(suspensas),"fontes_inativas":len(inativas),"fontes_sem_resultado":len(sem_resultado),"fontes_sem_publicacao_hoje":len(sem_publicacao),"fontes_com_erro_tecnico":len(erros),"itens_por_boletim":stats,"filtro1_bloqueios":{s:len(t) for s,t in bloqueios.items()},"auditoria":boletim["auditoria"]}
    if bloqueios: log["filtro1_bloqueios_detalhe"]=bloqueios
    if descartados: log["itens_descartados"]=descartados
    salvar_atomico(BOLETIM_PATH,boletim); salvar_atomico(LOG_PATH,log)
    print(f"Concluído: {len(itens)} itens, modelo {modelo}.")

if __name__=="__main__": main()
