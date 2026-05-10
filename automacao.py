import googlemaps
import gspread
import requests
import time
import os
import re
import urllib3
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from googlesearch import search
from oauth2client.service_account import ServiceAccountCredentials

# Desativa avisos de certificado SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

API_KEY_MAPS = os.getenv("MAPS_API_KEY")
NOME_PLANILHA = os.getenv("NOME_PLANILHA")

def validar_cnpj(cnpj):
    """Verifica se o CNPJ tem 14 dígitos e não é uma sequência repetida óbvia."""
    cnpj = re.sub(r'\D', '', str(cnpj))
    if len(cnpj) != 14 or len(set(cnpj)) == 1:
        return False
    return True

def iniciar_planilha():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
        client = gspread.authorize(creds)
        return client.open(NOME_PLANILHA).sheet1
    except Exception as e:
        print(f"❌ ERRO CRÍTICO (Planilha): {e}")
        exit()

planilha = iniciar_planilha()
gmaps = googlemaps.Client(key=API_KEY_MAPS)

def buscar_instagram_no_site(url):
    if not url or url == 'N/A': return 'N/A'
    print(f"   🌐 Acessando site: {url}")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'}
    try:
        res = requests.get(url, timeout=10, headers=headers, verify=False)
        soup = BeautifulSoup(res.text, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if 'instagram.com/' in href and all(x not in href for x in ['sharer', 'whatsapp', 'facebook', 'twitter']):
                print(f"   📸 Instagram encontrado: {a['href']}")
                return a['href']
    except Exception as e:
        print(f"   ⚠️ Erro ao varrer site: {e}")
    return 'N/A'

def capturar_cnpj_no_google(nome_empresa, cidade):
    # Limpeza Semântica: Remove descrições geográficas que confundem o buscador
    nome_limpo = re.split(r'[-|/]| na Praia| em Natal| Parnamirim', nome_empresa)[0].strip()
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8'
    }
    
    print(f"   🔍 [ENRIQUECIMENTO] Buscando dados de: {nome_limpo}")

    # ESTRATÉGIA 1: Busca Direta (CNPJ.biz) - Evita o filtro dos buscadores
    try:
        url_procura = f"https://cnpj.biz/procura/{nome_limpo.replace(' ', '+')}+{cidade.replace(' ', '+')}"
        res = requests.get(url_procura, headers=headers, timeout=12)
        
        # Procura padrão formatado ou link de 14 dígitos
        match = re.search(r'\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}', res.text)
        if not match:
            match = re.search(r'/\d{14}', res.text)
            
        if match:
            cnpj = re.sub(r'\D', '', match.group(0))
            if validar_cnpj(cnpj):
                print(f"      🎯 CNPJ ENCONTRADO (Estratégia Direta): {cnpj}")
                return cnpj
    except Exception as e:
        print(f"      ⚠️ Falha na Estratégia 1: {e}")

    # ESTRATÉGIA 2: Fallback via DuckDuckGo (HTML bruto)
    try:
        url_ddg = "https://html.duckduckgo.com/html/"
        res_ddg = requests.get(url_ddg, params={'q': f'{nome_limpo} {cidade} cnpj'}, headers=headers, timeout=12)
        match_ddg = re.search(r'\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}', res_ddg.text)
        if match_ddg:
            cnpj = re.sub(r'\D', '', match_ddg.group(0))
            if validar_cnpj(cnpj) and cnpj != "34013481030122":
                print(f"      🎯 CNPJ ENCONTRADO (Estratégia 2): {cnpj}")
                return cnpj
    except:
        pass

    print(f"      ℹ️ CNPJ não localizado para {nome_limpo}")
    return None

def buscar_decisor_brasil_api(cnpj_limpo):
    if not cnpj_limpo or not validar_cnpj(cnpj_limpo):
        return "N/A", "N/A"
    
    print(f"   🏢 Validando na Brasil API: {cnpj_limpo}")
    try:
        time.sleep(1) # Rate limit safety
        url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}"
        res = requests.get(url, timeout=15)
        
        if res.status_code == 200:
            dados = res.json()
            socios = dados.get('qsa', [])
            nome_decisor = "Não informado"
            
            if socios:
                for s in socios:
                    qualif = str(s.get('qualificacao_socio', '')).upper()
                    if any(x in qualif for x in ['ADMINISTRADOR', 'SOCIO-ADMINISTRADOR', 'TITULAR', 'DIRETOR']):
                        nome_decisor = s.get('nome_socio')
                        break
                if nome_decisor == "Não informado":
                    nome_decisor = socios[0].get('nome_socio')
            
            print(f"      👤 DECISOR: {nome_decisor}")
            return dados.get('cnpj'), str(nome_decisor).title()
        else:
            print(f"      ⚠️ Erro API: {res.status_code}")
    except Exception as e:
        print(f"      ⚠️ Erro conexão API: {e}")
        
    return cnpj_limpo, "N/A"

def buscar_leads(setor, cidade, meta_leads):
    print(f"\n" + "="*50 + f"\n🚀 INICIANDO: {setor} @ {cidade}\n" + "="*50)
    
    leads_salvos = 0
    token = None
    
    while leads_salvos < meta_leads:
        try:
            coluna_ids = planilha.col_values(10)
            res_maps = gmaps.places(query=f"{setor} em {cidade}", page_token=token) if token else gmaps.places(query=f"{setor} em {cidade}")

            results = res_maps.get('results', [])
            if not results: break

            for lead in results:
                if leads_salvos >= meta_leads: break
                
                pid = lead['place_id']
                nome = lead.get('name')

                if pid in coluna_ids:
                    print(f"⚠️ Pular: {nome}")
                    continue

                print(f"\n💎 LEAD {leads_salvos + 1}: {nome}")
                det = gmaps.place(place_id=pid, fields=['formatted_phone_number', 'website', 'formatted_address'])['result']

                tel = det.get('formatted_phone_number', 'N/A')
                site = det.get('website', 'N/A')
                end = det.get('formatted_address', 'N/A')

                insta = buscar_instagram_no_site(site)
                cnpj_num = capturar_cnpj_no_google(nome, cidade)
                cnpj_format, decisor = buscar_decisor_brasil_api(cnpj_num)

                planilha.append_row([nome, tel, site, insta, end, cidade, setor, cnpj_format, decisor, pid])
                leads_salvos += 1
                print(f"✅ Salvo com sucesso!")
                
                time.sleep(2)

            token = res_maps.get('next_page_token')
            if not token: break
            time.sleep(2) 
            
        except Exception as e:
            print(f"❌ Erro no ciclo: {e}")
            break

print("--- SISTEMA DE MAPEAMENTO PROFISSIONAL V2 ---")
s_in = input("Setor: ")
c_in = input("Cidade: ").split(',')
q_in = int(input("Quantidade de Leads desejados: "))

for cid in c_in:
    buscar_leads(s_in, cid.strip(), q_in)