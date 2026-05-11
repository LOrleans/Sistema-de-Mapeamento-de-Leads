# 🚀 Automated B2B Lead Mapping & Enrichment System

A robust and fully automated Python script designed to search, enrich, and organize B2B leads directly into a Google Sheets spreadsheet. This system leverages multiple APIs and intelligent scraping fallback strategies to build highly qualified prospecting lists with minimal manual effort.

## ✨ Features

- **Google Maps Integration**: Searches for businesses by sector and city, extracting essential data like Name, Phone, and Website.
- **Smart Instagram Discovery**: Scrapes the company's website to automatically find and extract their official Instagram profile.
- **Advanced CNPJ (Tax ID) Discovery**: Utilizes a dual-strategy approach (Direct Lookup + AOL Web Search fallback) to reliably find the company's Brazilian CNPJ without being blocked by search engine rate limits.
- **Decision-Maker Identification**: Queries the `Brasil API` to extract the *QSA (Quadro de Sócios e Administradores)*, intelligently identifying the names of Directors, Presidents, or Administrators so your sales team can contact the right person.
- **Google Sheets Sync**: Connects directly to your Google Workspace to append enriched leads into a specific spreadsheet in real-time.
- **Anti-Duplication System**: Cross-references the `Google Place ID` with the existing rows in the spreadsheet to guarantee that no lead is ever saved twice.
- **Resilient & Anti-Block**: Built-in network resilience with auto-retries for 502/503 API server errors and anti-scraping delays.

## 🛠️ Tech Stack & Dependencies

- **Language**: Python 3.x
- **APIs**: 
  - Google Maps Places API
  - Google Sheets API v4 / Google Drive API
  - Brasil API (for CNPJ data)
- **Libraries**:
  - `googlemaps`
  - `gspread`
  - `oauth2client`
  - `requests`, `urllib3`
  - `beautifulsoup4` (bs4)
  - `python-dotenv`

## ⚙️ Setup & Configuration

1. **Clone the repository:**
   ```bash
   git clone https://github.com/LOrleans/Sistema-de-Mapeamento-de-Leads.git
   cd Sistema-de-Mapeamento-de-Leads
   ```

2. **Install dependencies:**
   ```bash
   pip install googlemaps gspread oauth2client requests beautifulsoup4 python-dotenv
   ```

3. **Environment Variables:**
   Create a `.env` file in the root directory and add the following keys:
   ```env
   MAPS_API_KEY=your_google_maps_api_key_here
   NOME_PLANILHA=Your_Google_Sheets_Document_Name
   ```

4. **Service Account Credentials:**
   You must create a Google Cloud Service Account with access to the Google Sheets and Drive APIs. 
   - Download the JSON key file.
   - Rename it to `credentials.json` and place it in the root directory.
   - **Important**: Remember to share your target Google Sheet with the email address of the service account!

## 📊 Google Sheets Structure

The script is configured to append data expecting the following column order in your Google Sheet (Starting from Column B if A is blank):

1. **Nome / Estabelecimento** (Lead Name)
2. **Status** (Pipeline Status - Default: "Disponível")
3. **Telefone** (Phone)
4. **Site** (Website)
5. **Instagram** (Instagram Profile)
6. **Cidade** (City)
7. **Área / Setor** (Sector)
8. **Link CNPJ** (Direct link to financial info)
9. **Decisor** (Decision Maker Name)
10. **Google_ID** (Place ID used for duplication checks)

*(Note: The script currently targets the 11th index internally to check for the Google_ID due to a specific layout offset. Adjust `planilha.col_values(11)` in the code if your layout differs).*

## 🚀 Usage

Simply run the script in your terminal:
```bash
python automacao.py
```

The system will prompt you for the parameters:
1. **Setor (Sector)**: e.g., `Advocacia`, `Padaria`, `Automóveis`
2. **Cidade (City)**: e.g., `Natal`, `São Paulo` *(You can input multiple cities separated by commas)*
3. **Quantidade de Leads (Amount)**: The number of *new* leads you want to extract per city.

The script will handle the rest, showing real-time logs in the terminal as it hunts for data and populates your sheet!

## ⚠️ Disclaimer

This tool is designed to automate the public data retrieval process for legitimate B2B prospecting. Please ensure you comply with all local data privacy regulations (such as LGPD in Brazil) when handling corporate and personal data.
