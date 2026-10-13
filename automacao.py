import gspread
import requests
import time
import os
import re
import urllib3
import urllib.parse
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
import sys

sys.stdout.reconfigure(encoding='utf-8')

# Desativa avisos de certificado SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv(override=True)

API_KEY_MAPS = os.getenv("MAPS_API_KEY")
NOME_PLANILHA = os.getenv("NOME_PLANILHA")

# --- Places API (New) ---
PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.nationalPhoneNumber",
    "places.websiteUri",
    "places.businessStatus",
    "nextPageToken",
])
MAX_FALHAS_SEGUIDAS = 3


class ErroPermanenteMaps(Exception):
    """Erro que não adianta tentar de novo (chave inválida, API desativada, sem faturamento...)."""


def buscar_places(texto, page_token=None):
    body = {
        "textQuery": texto,
        "languageCode": "pt-BR",
        "regionCode": "BR",
        "pageSize": 20,
    }
    if page_token:
        body["pageToken"] = page_token

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": API_KEY_MAPS,
        "X-Goog-FieldMask": PLACES_FIELD_MASK,
    }
    res = requests.post(PLACES_URL, json=body, headers=headers, timeout=20)

    if res.status_code in (400, 401, 403):
        try:
            msg = res.json().get("error", {}).get("message", res.text)
        except ValueError:
            msg = res.text
        raise ErroPermanenteMaps(f"HTTP {res.status_code} - {msg[:400]}")

    res.raise_for_status()
    return res.json()

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

if not API_KEY_MAPS:
    print("❌ ERRO CRÍTICO: MAPS_API_KEY não encontrada no arquivo .env")
    exit()

planilha = iniciar_planilha()

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
        
        fallback_cnpj = None
        fallback_link = "N/A"
        
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
                    
                    # Prioridade: Se o link for do cnpj.biz, retorna ele na hora
                    if 'cnpj.biz' in link_cnpj:
                        return cnpj, link_cnpj
                    
                    # Guarda o primeiro resultado válido de outros sites como plano B
                    if not fallback_cnpj:
                        fallback_cnpj = cnpj
                        fallback_link = link_cnpj
                        
        if fallback_cnpj:
            return fallback_cnpj, fallback_link
            
    except Exception:
        pass

    return None, "N/A"

def buscar_dados_completos_cnpj(cnpj_limpo):
    resultado = {
        "cnpj": cnpj_limpo,
        "decisor": "N/A",
        "tipo_empresa": "Empresa Sênior",
        "tamanho_empresa": "Sem classificação",
        # Estrutura pronta para requisitar mais informações no futuro
        "razao_social": "N/A",
        "capital_social": "N/A",
        "situacao_cadastral": "N/A"
    }
    
    if not cnpj_limpo or not validar_cnpj(cnpj_limpo):
        return resultado
    
    try:
        time.sleep(1) # Rate limit safety
        url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}"
        res = requests.get(url, timeout=15)
        
        if res.status_code == 200:
            dados = res.json()
            
            # 1. Decisor
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
            resultado["decisor"] = str(nome_decisor).title() if nome_decisor != "Não informado" else "N/A"
            
            # 2. Tipo de Empresa (Mapeamento para o Pipefy)
            natureza = str(dados.get('natureza_juridica', '')).upper()
            if dados.get('opcao_pelo_mei'):
                resultado["tipo_empresa"] = "MEI"
            elif "EMPRESÁRIO INDIVIDUAL" in natureza or "EMPRESARIO INDIVIDUAL" in natureza:
                resultado["tipo_empresa"] = "Empresário Individual"
            elif any(x in natureza for x in ["ASSOCIAÇÃO PRIVADA", "ASSOCIACAO PRIVADA", "FUNDAÇÃO PRIVADA", "ORGANIZAÇÃO RELIGIOSA"]):
                resultado["tipo_empresa"] = "ONG"
            else:
                # Assumimos 'Empresa Sênior' para LTDA, S/A, EIRELI, etc.
                resultado["tipo_empresa"] = "Empresa Sênior"
                
            # 3. Tamanho da Empresa (Mapeamento para o Pipefy)
            porte = str(dados.get('porte', '')).upper()
            map_porte = {
                "MICRO EMPRESA": "Microempresa (ME)",
                "EMPRESA DE PEQUENO PORTE": "Empresa de pequeno porte (EPP)",
                "MEDIA EMPRESA": "Média empresa",
                "GRANDE EMPRESA": "Grande empresa"
            }
            resultado["tamanho_empresa"] = map_porte.get(porte, "Sem classificação") if porte else "Sem classificação"
                
            # 4. Mais informações prontas para uso futuro
            resultado["razao_social"] = dados.get('razao_social', 'N/A')
            resultado["capital_social"] = dados.get('capital_social', 'N/A')
            resultado["situacao_cadastral"] = dados.get('descricao_situacao_cadastral', 'N/A')
            
    except Exception:
        pass
        
    return resultado

def cadastrar_lead_pipefy(dados):
    token = os.getenv("PIPEFY_TOKEN")
    pipe_id = os.getenv("PIPEFY_PIPE_ID")
    
    if not token or not pipe_id:
        return
        
    url = "https://api.pipefy.com/graphql"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # 1. Criar Record na Tabela Banco de dados de Leads
    query_record = '''
    mutation CreateRecord($input: CreateTableRecordInput!) {
      createTableRecord(input: $input) {
        table_record { id }
      }
    }
    '''
    variables_record = {
        "input": {
            "table_id": "OSsaOrTh",
            "fields_attributes": [
                {"field_id": "nome", "field_value": dados.get('nome', 'N/A')},
                {"field_id": "tipo_de_empresa", "field_value": dados.get('tipo_empresa', 'Empresa Sênior')},
                {"field_id": "tamanho_da_empresa", "field_value": dados.get('tamanho_empresa', 'Sem classificação')},
                {"field_id": "servi_os_de_interesse", "field_value": ["Sistema Web"]},
                {"field_id": "rea_de_atua_o", "field_value": "Prestação de Serviços"},
                {"field_id": "nome_do_contato", "field_value": dados.get('decisor', 'N/A')},
                {"field_id": "criado_por", "field_value": ["306852816"]}, # 306852816 é o ID do Lucas Orleans
                {"field_id": "telefone_de_contato", "field_value": dados.get('telefone', 'N/A')},
                {"field_id": "p_gina_do_instagram", "field_value": dados.get('instagram', 'N/A')},
                {"field_id": "link_dos_dados_do_cnpj", "field_value": dados.get('link_cnpj', 'N/A')},
                {"field_id": "endere_o_comercial", "field_value": dados.get('cidade', 'N/A')}
            ]
        }
    }
    
    try:
        res_record = requests.post(url, headers=headers, json={'query': query_record, 'variables': variables_record})
        record_data = res_record.json()
        
        if 'errors' in record_data:
            print(f"⚠️ Erro ao criar registro na tabela do Pipefy: {record_data['errors']}")
            return

        data_obj = record_data.get('data')
        if not data_obj:
            return
            
        record_id = data_obj.get('createTableRecord', {}).get('table_record', {}).get('id')
        
        # 2. Criar Card no Pipe conectando ao Record criado
        if record_id:
            query_card = '''
            mutation CreateCard($input: CreateCardInput!) {
              createCard(input: $input) {
                card { id }
              }
            }
            '''
            variables_card = {
                "input": {
                    "pipe_id": int(pipe_id),
                    "fields_attributes": [
                        {"field_id": "lead", "field_value": [record_id]},
                        {"field_id": "quantidade_de_vezes_que_j_entramos_em_contato", "field_value": 0}
                    ]
                }
            }
            res_card = requests.post(url, headers=headers, json={'query': query_card, 'variables': variables_card})
            card_data = res_card.json()
            if 'errors' in card_data:
                print(f"⚠️ Erro ao criar card no Pipefy: {card_data['errors']}")
                
    except Exception as e:
        print(f"⚠️ Erro de conexão ao cadastrar no Pipefy: {e}")

def buscar_leads(setor, cidade, meta_leads):
    print(f"\n🚀 INICIANDO MAPEAMENTO: {setor} em {cidade} (Meta: {meta_leads} leads)")
    
    leads_salvos = 0
    token = None
    falhas_seguidas = 0

    while leads_salvos < meta_leads:
        try:
            coluna_ids = planilha.col_values(11) # A ID está na coluna 11 (K) pois a coluna A da planilha é usada para outra coisa / vazia.
            res_maps = buscar_places(f"{setor} em {cidade}", page_token=token)

            results = res_maps.get('places', [])
            if not results: break

            for lead in results:
                if leads_salvos >= meta_leads: break

                pid = lead.get('id')
                nome = lead.get('displayName', {}).get('text', 'N/A')

                if not pid or pid in coluna_ids:
                    continue

                # Pula empresas que o Google marca como fechadas de vez
                if lead.get('businessStatus') == 'CLOSED_PERMANENTLY':
                    print(f"⏭️  {nome} -> fechada permanentemente, ignorada.")
                    continue

                tel = lead.get('nationalPhoneNumber', 'N/A')
                site = lead.get('websiteUri', 'N/A')

                insta = buscar_instagram_no_site(site)
                cnpj_num, link_cnpj = capturar_cnpj_no_google(nome, cidade)
                
                dados_cnpj = buscar_dados_completos_cnpj(cnpj_num)
                decisor = dados_cnpj["decisor"]
                tipo_empresa = dados_cnpj["tipo_empresa"]
                tamanho_empresa = dados_cnpj["tamanho_empresa"]
                razao_social = dados_cnpj["razao_social"]
                capital_social = dados_cnpj["capital_social"]
                situacao_cadastral = dados_cnpj["situacao_cadastral"]

                # Condicional de Descarte: Só descarta se TODOS estiverem ausentes.
                if decisor == "N/A" and tel == "N/A" and insta == "N/A" and link_cnpj == "N/A":
                    print(f"❌ [{leads_salvos}/{meta_leads}] {nome} -> Descartado (Sem dados suficientes).")
                    continue

                status_inicial = "Disponível"
                
                # Encontra a primeira linha vazia na Coluna B (Nome do Lead)
                col_b = planilha.col_values(2)
                proxima_linha = len(col_b) + 1
                
                # Insere os dados exatamente das colunas B até O
                planilha.update(
                    range_name=f"B{proxima_linha}:O{proxima_linha}", 
                    values=[[nome, status_inicial, tel, site, insta, cidade, setor, link_cnpj, decisor, pid, tipo_empresa, razao_social, capital_social, situacao_cadastral]]
                )
                
                # Cadastro no Pipefy
                dados_lead = {
                    "nome": nome,
                    "telefone": tel,
                    "site": site,
                    "instagram": insta,
                    "cidade": cidade,
                    "setor": setor,
                    "link_cnpj": link_cnpj,
                    "decisor": decisor,
                    "tipo_empresa": tipo_empresa,
                    "tamanho_empresa": tamanho_empresa
                }
                cadastrar_lead_pipefy(dados_lead)
                
                leads_salvos += 1
                print(f"📍 [{leads_salvos}/{meta_leads}] {nome} -> Mapeado com sucesso!")
                
                time.sleep(2)

            falhas_seguidas = 0
            token = res_maps.get('nextPageToken')
            if not token: break
            time.sleep(2)

        except ErroPermanenteMaps as e:
            print(f"❌ O Google recusou a busca: {e}")
            print("   Confira se a 'Places API (New)' está ativada no projeto e liberada nas restrições da chave.")
            return

        except Exception as e:
            falhas_seguidas += 1
            if falhas_seguidas >= MAX_FALHAS_SEGUIDAS:
                print(f"❌ {falhas_seguidas} falhas seguidas ({e}). Encerrando {cidade} para não ficar em loop.")
                return
            print(f"❌ Erro de conexão com o Google ou timeout: {e}")
            print(f"⏳ Aguardando 10 segundos antes de tentar novamente... ({falhas_seguidas}/{MAX_FALHAS_SEGUIDAS})")
            time.sleep(10)
            continue

    if leads_salvos < meta_leads:
        print(f"ℹ️  O Google devolve no máximo 60 resultados por busca. Para mais leads, busque por bairro (ex.: 'Ponta Negra, Natal').")
    print(f"✨ Mapeamento finalizado em {cidade}! Total de {leads_salvos} leads mapeados.")

if __name__ == '__main__':
    print("--- SISTEMA DE MAPEAMENTO PROFISSIONAL V2 ---")
    s_in = input("Setor: ")
    c_in = input("Cidade: ").split(',')
    q_in = int(input("Quantidade de Leads desejados: "))

    for cid in c_in:
        buscar_leads(s_in, cid.strip(), q_in)

    print("\n🏆 Processo completo! Todos os leads foram processados com sucesso.")