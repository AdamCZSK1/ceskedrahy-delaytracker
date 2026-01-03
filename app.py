import sqlite3
import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime
import os
import psycopg2
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# URL stanice Plzeň hl.n.
URL = "https://provoz.spravazeleznic.cz/Tabule/Zobrazeni?stanice_id=5457076&typ=Odjezdy"

def get_db_connection():
    """Připojí se k Postgres (na Renderu) nebo SQLite (doma)"""
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
    # Vytvoření tabulky
    c.execute('''CREATE TABLE IF NOT EXISTS zpozdeni
                 (cas TEXT, cislo_vlaku TEXT, dopravce TEXT, cilova_stanice TEXT, 
                  planovany_odjezd TEXT, aktualni_odjezd TEXT, meskani TEXT)''')
    
    # Přidání sloupce platform, pokud chybí (pro zpětnou kompatibilitu)
    try:
        c.execute("ALTER TABLE zpozdeni ADD COLUMN platform TEXT")
    except:
        pass # Sloupec už tam asi je

    conn.commit()
    conn.close()

@app.route('/update')
def update_data():
    """Tuto adresu volej přes cron-job.org každých 5 minut"""
    try:
        # Debug info - kontrola databáze
        db_type = "Postgres (Bezpečné ✅)" if os.environ.get('DATABASE_URL') else "SQLite (Nebezpečné ⚠️)"
        
        response = requests.get(URL)
        if response.status_code != 200:
            return f"Chyba SŽ: {response.status_code}", 500
            
        soup = BeautifulSoup(response.content, 'html.parser')
        table = soup.find('table', {'id': 'TabuleGrid'})
        
        if not table:
            return "Chyba: Tabulka na webu SŽ nenalezena", 500

        conn = get_db_connection()
        c = conn.cursor()
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ph = get_placeholder()
        
        count = 0
        for row in table.find_all('tr')[1:]:
            cols = row.find_all('td')
            if len(cols) > 0:
                vals = (
                    now,
                    cols[1].text.strip(), # Číslo
                    cols[0].text.strip(), # Dopravce
                    cols[2].text.strip(), # Cíl
                    cols[3].text.strip(), # Plánovaný
                    cols[4].text.strip(), # Aktuální
                    cols[5].text.strip().replace(' min', '') or "0" # Zpoždění
                )
                
                # SQL dotaz
                query = f"INSERT INTO zpozdeni (cas, cislo_vlaku, dopravce, cilova_stanice, planovany_odjezd, aktualni_odjezd, meskani) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})"
                c.execute(query, vals)
                count += 1

        conn.commit()
        conn.close()
        return f"<h1>ÚSPĚCH!</h1><p>DB: {db_type}</p><p>Uloženo {count} vlaků v čase {now}</p>", 200
        
    except Exception as e:
        return f"CHYBA: {str(e)}", 500

@app.route('/')
def index():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM zpozdeni ORDER BY cas DESC LIMIT 100")
        rows = c.fetchall()
        conn.close()
        
        data = []
        for row in rows:
            # Bezpečné barvení
            try:
                m_val = int(row[6])
                color = "red" if m_val >= 15 else "orange" if m_val >= 5 else "green"
            except:
                color = "black"

            data.append({
                'cas': row[0],
                'cislo': row[1],
                'dopravce': row[2],
                'cil': row[3],
                'plan': row[4],
                'aktual': row[5],
                'meskani': row[6],
                'barva': color,
                'platform': row[7] if len(row) > 7 else None
            })
        return render_template('index.html', data=data)
    except Exception as e:
        return f"Chyba webu: {str(e)}<br>Zkus zavolat /update", 500

@app.route('/nastupiste/<train_num>')
def get_platform(train_num):
    """Získá nástupiště (z cache DB nebo placeholder)"""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        ph = get_placeholder()
        
        # Hledáme v DB, jestli už nástupiště neznáme
        query = f"SELECT platform FROM zpozdeni WHERE cislo_vlaku = {ph} AND platform IS NOT NULL LIMIT 1"
        c.execute(query, (train_num,))
        result = c.fetchone()
        conn.close()
        
        if result and result[0]:
            return jsonify({"platform": result[0], "source": "db"})
        
        return jsonify({"platform": "Zatím neznámé", "source": "none"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Spuštění
init_db()

if __name__ == "__main__":
    app.run(debug=True)
