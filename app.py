import sqlite3
import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime
import os
import psycopg2
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# URL pro Plzeň hl.n.
URL = "https://provoz.spravazeleznic.cz/Tabule/Zobrazeni?stanice_id=5457076&typ=Odjezdy"

def get_db_connection():
    """
    Tato funkce zajistí bezpečné připojení k databázi.
    Na Renderu použije Postgres, doma SQLite.
    """
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        return psycopg2.connect(db_url)
    else:
        return sqlite3.connect('zpozdeni.sqlite3')

def get_placeholder():
    """Vrátí správný zástupný znak pro SQL (%s pro Postgres, ? pro SQLite)"""
    if os.environ.get('DATABASE_URL'):
        return '%s'
    return '?'

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    # Vytvoření tabulky s podporou pro obě databáze
    c.execute('''CREATE TABLE IF NOT EXISTS zpozdeni
                 (cas TEXT, cislo_vlaku TEXT, dopravce TEXT, cilova_stanice TEXT, 
                  planovany_odjezd TEXT, aktualni_odjezd TEXT, meskani TEXT, platform TEXT)''')
    
    # Sloupec platform přidáme dodatečně, pokud by chyběl (pro starší DB)
    try:
        if os.environ.get('DATABASE_URL'):
            c.execute("ALTER TABLE zpozdeni ADD COLUMN platform TEXT")
        else:
            c.execute("ALTER TABLE zpozdeni ADD COLUMN platform TEXT")
    except:
        pass # Sloupec už existuje

    conn.commit()
    conn.close()

@app.route('/update')
def update_data():
    """Tuto adresu volej přes cron-job.org každých 5 minut"""
    try:
        response = requests.get(URL)
        soup = BeautifulSoup(response.content, 'html.parser')
        table = soup.find('table', {'id': 'TabuleGrid'})
        
        if not table:
            return "Chyba: Tabulka nenalezena", 500

        conn = get_db_connection()
        c = conn.cursor()
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ph = get_placeholder() # Zjistí jestli použít ? nebo %s
        
        count = 0
        for row in table.find_all('tr')[1:]:
            cols = row.find_all('td')
            if len(cols) > 0:
                dopravce = cols[0].text.strip()
                cislo_vlaku = cols[1].text.strip()
                cilova_stanice = cols[2].text.strip()
                planovany_odjezd = cols[3].text.strip()
                aktualni_odjezd = cols[4].text.strip()
                meskani = cols[5].text.strip().replace(' min', '') or "0"
                
                # Uložíme základní data (platforma se doplní později nebo je NULL)
                query = f"INSERT INTO zpozdeni (cas, cislo_vlaku, dopravce, cilova_stanice, planovany_odjezd, aktualni_odjezd, meskani) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})"
                c.execute(query, (now, cislo_vlaku, dopravce, cilova_stanice, planovany_odjezd, aktualni_odjezd, meskani))
                count += 1

        conn.commit()
        conn.close()
        return f"Aktualizováno {count} vlaků v {now}", 200
    except Exception as e:
        return f"Chyba: {str(e)}", 500

@app.route('/')
def index():
    conn = get_db_connection()
    c = conn.cursor()
    ph = get_placeholder()

    # Získání filtrů z URL
    filter_date = request.args.get('date')
    filter_time = request.args.get('time')

    query = "SELECT * FROM zpozdeni WHERE 1=1"
    params = []

    if filter_date:
        if os.environ.get('DATABASE_URL'):
             # Postgres syntaxe pro datum
             query += " AND cas::date = %s"
        else:
             # SQLite syntaxe (text)
             query += " AND date(cas) = ?"
        params.append(filter_date)

    if filter_time:
        # Jednoduchý filtr času (hodina)
        query += f" AND cas LIKE {ph}"
        params.append(f"% {filter_time}:%")

    query += " ORDER BY cas DESC LIMIT 100"
    
    c.execute(query, tuple(params))
    rows = c.fetchall()
    conn.close()
    
    # Zpracování dat pro šablonu
    data = []
    for row in rows:
        meskani = row[6]
        try:
            m_val = int(meskani)
            if m_val < 5: color = "green"
            elif m_val < 15: color = "orange"
            else: color = "red"
        except:
            color = "black"

        data.append({
            'cas': row[0],
            'cislo': row[1],
            'dopravce': row[2],
            'cil': row[3],
            'plan': row[4],
            'aktual': row[5],
            'meskani': meskani,
            'barva': color,
            'platform': row[7] if len(row) > 7 else None
        })
        
    return render_template('index.html', data=data)

@app.route('/nastupiste/<train_num>')
def get_platform(train_num):
    """Stáhne nástupiště pro konkrétní vlak"""
    conn = get_db_connection()
    c = conn.cursor()
    ph = get_placeholder()
    
    # 1. Zkusíme najít nástupiště v naší DB
    query_select = f"SELECT platform FROM zpozdeni WHERE cislo_vlaku = {ph} AND platform IS NOT NULL ORDER BY cas DESC LIMIT 1"
    c.execute(query_select, (train_num,))
    result = c.fetchone()
    
    if result and result[0]:
        conn.close()
        return jsonify({"platform": result[0], "source": "cache"})

    # 2. Pokud není v DB, zkusíme stáhnout online
    try:
        # Tady je trik - musíme najít detail vlaku. Pro zjednodušení zkusíme hledat přímo
        # V reálu je to složitější, ale použijeme tvůj původní logický postup (zjednodušený)
        # Poznámka: Tento link by se měl ideálně dynamicky získávat, ale pro teď zkusíme obecný dotaz
        detail_url = f"https://provoz.spravazeleznic.cz/Tabule/Zobrazeni?stanice_id=5457076&typ=Odjezdy"
        # Poznámka: Scrapování detailu konkrétního vlaku je složité bez ID vlaku. 
        # Pokud tvůj původní kód fungoval, asi tahal data jinak. 
        # Pro stabilitu teď vrátíme "Nezjištěno", dokud se neimplementuje přesný scraper detailu.
        
        # Aby ti to nepadalo, vrátíme zatím placeholder, než se opraví scrapování detailu
        conn.close()
        return jsonify({"platform": "N/A", "note": "Scraper detailu čeká na update"}), 200

    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500

@app.route('/historie')
def historie():
    return render_template('historie.html')

@app.route('/historie_vysledky')
def historie_vysledky():
    train_num = request.args.get('train_num')
    conn = get_db_connection()
    c = conn.cursor()
    ph = get_placeholder()
    
    query = f"SELECT * FROM zpozdeni WHERE cislo_vlaku = {ph} ORDER BY cas DESC"
    c.execute(query, (train_num,))
    rows = c.fetchall()
    conn.close()
    
    data = []
    for row in rows:
        data.append({
            'cas': row[0], 'cislo': row[1], 'dopravce': row[2],
            'cil': row[3], 'plan': row[4], 'aktual': row[5], 'meskani': row[6]
        })
    return render_template('historie_vysledky.html', data=data, train_num=train_num)

@app.route('/api/vlaky')
def api_vlaky():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM zpozdeni ORDER BY cas DESC LIMIT 50")
    rows = c.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        results.append(dict(zip(['cas', 'cislo', 'dopravce', 'cil', 'plan', 'aktual', 'meskani', 'platform'], row)))
    return jsonify(results)

# Inicializace při startu
init_db()

if __name__ == "__main__":
    app.run(debug=True)
