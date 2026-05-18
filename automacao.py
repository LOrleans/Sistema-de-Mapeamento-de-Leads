import googlemaps
import gspread
import requests
import time
import os
import re
import urllib3
import urllib.parse
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from googlesearch import search
from oauth2client.service_account import ServiceAccountCredentials

# Desativa avisos de certificado SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv(override=True)

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
        planilha = client.open(NOME_PLANILHA)
        return planilha.sheet1
    except Exception as e:
        print(f"❌ ERRO CRÍTICO (Planilha): {e}")
        exit()

planilha = iniciar_planilha()
gmaps = googlemaps.Client(key=API_KEY_MAPS)

def buscar_instagram_no_site(url):
    if not url or url == 'N/A': return 'N/A'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'}
    try:
        res = requests.get(url, timeout=10, headers=headers, verify=False)
        soup = BeautifulSoup(res.text, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if 'instagram.com/' in href and all(x not in href for x in ['sharer', 'whatsapp', 'facebook', 'twitter']):
                return a['href']
    except Exception:
        pass
    return 'N/A'

def capturar_cnpj_no_google(nome_empresa, cidade):
    # Limpeza Semântica: Remove descrições geográficas que confundem o buscador
    nome_limpo = re.split(r'[-|/]| na Praia| em Natal| Parnamirim', nome_empresa)[0].strip()
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8'
    }
    
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
                return cnpj, f"https://cnpj.biz/{cnpj}"
    except Exception:
        pass

    # ESTRATÉGIA 2: Fallback via Web Search (AOL)
    try:
        time.sleep(1) # Delay anti-bloqueio
        url_search = "https://search.aol.com/aol/search"
        res_search = requests.get(url_search, params={'q': f'{nome_limpo} {cidade} cnpj'}, headers=headers, timeout=12)
        soup = BeautifulSoup(res_search.text, 'html.parser')
        
        for result in soup.find_all('div', class_='algo'):
            text = result.get_text()
            match_search = re.search(r'\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}', text)
            if match_search:
                cnpj = re.sub(r'\D', '', match_search.group(0))
                if validar_cnpj(cnpj) and cnpj != "34013481030122":
                    a_tag = result.find('a', href=True)
                    link_cnpj = "N/A"
                    if a_tag:
                        href = a_tag['href']
                        if 'RU=' in href:
                            ru_encoded = href.split('RU=')[1].split('/RK=')[0]
                            link_cnpj = urllib.parse.unquote(ru_encoded)
                        else:
                            link_cnpj = href
                    return cnpj, link_cnpj
    except Exception:
        pass

    return None, "N/A"

def buscar_decisor_brasil_api(cnpj_limpo):
    if not cnpj_limpo or not validar_cnpj(cnpj_limpo):
        return "N/A", "N/A"
    
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
            
            return dados.get('cnpj'), str(nome_decisor).title()
    except Exception:
        pass
        
    return cnpj_limpo, "N/A"

def buscar_leads(setor, cidade, meta_leads):
    print(f"\n🚀 INICIANDO MAPEAMENTO: {setor} em {cidade} (Meta: {meta_leads} leads)")
    
    leads_salvos = 0
    token = None
    
    while leads_salvos < meta_leads:
        try:
            coluna_ids = planilha.col_values(11) # A ID está na coluna 11 (K) pois a coluna A da planilha é usada para outra coisa / vazia.
            res_maps = gmaps.places(query=f"{setor} em {cidade}", page_token=token) if token else gmaps.places(query=f"{setor} em {cidade}")

            results = res_maps.get('results', [])
            if not results: break

            for lead in results:
                if leads_salvos >= meta_leads: break
                
                pid = lead['place_id']
                nome = lead.get('name')

                if pid in coluna_ids:
                    continue

                det = gmaps.place(place_id=pid, fields=['formatted_phone_number', 'website'])['result']

                tel = det.get('formatted_phone_number', 'N/A')
                site = det.get('website', 'N/A')

                insta = buscar_instagram_no_site(site)
                cnpj_num, link_cnpj = capturar_cnpj_no_google(nome, cidade)
                _, decisor = buscar_decisor_brasil_api(cnpj_num)

                status_inicial = "Disponível"
                
                # Encontra a primeira linha vazia na Coluna B (Nome do Lead)
                col_b = planilha.col_values(2)
                proxima_linha = len(col_b) + 1
                
                # Insere os dados exatamente das colunas B até K
                planilha.update(
                    range_name=f"B{proxima_linha}:K{proxima_linha}", 
                    values=[[nome, status_inicial, tel, site, insta, cidade, setor, link_cnpj, decisor, pid]]
                )
                
                leads_salvos += 1
                print(f"📍 [{leads_salvos}/{meta_leads}] {nome} -> Mapeado com sucesso!")
                
                time.sleep(2)

            token = res_maps.get('next_page_token')
            if not token: break
            time.sleep(2) 
            
        except Exception as e:
            print(f"❌ Erro de conexão com o Google ou timeout: {e}")
            print("⏳ Aguardando 10 segundos antes de tentar novamente...")
            time.sleep(10)
            continue

    print(f"✨ Mapeamento finalizado em {cidade}! Total de {leads_salvos} leads mapeados.")

print("--- SISTEMA DE MAPEAMENTO PROFISSIONAL V2 ---")
s_in = input("Setor: ")
c_in = input("Cidade: ").split(',')
q_in = int(input("Quantidade de Leads desejados: "))

for cid in c_in:
    buscar_leads(s_in, cid.strip(), q_in)

print("\n🏆 Processo completo! Todos os leads foram processados com sucesso.")