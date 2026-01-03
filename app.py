import sqlite3
import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime
import os
import psycopg2
from flask import Flask, render_template

app = Flask(__name__)

# ID stanice (5457076 = Plzeň hl.n.). Pokud chceš jinou, změň to tady.
STATION_URL = "https://provoz.spravazeleznic.cz/Tabule/Zobrazeni?stanice_id=5457076&typ=Odjezdy"

def get_db_connection():
    """Připojí se buď k Postgres (Render) nebo SQLite (lokálně)"""
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        conn = psycopg2.connect(db_url)
    else:
        conn = sqlite3.connect('zpozdeni.sqlite3')
    return conn

def init_db():
    """Vytvoří tabulku, pokud neexistuje"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS zpozdeni
                 (cas TEXT, cislo_vlaku TEXT, dopravce TEXT, cilova_stanice TEXT, 
                  planovany_odjezd TEXT, aktualni_odjezd TEXT, meskani TEXT)''')
    conn.commit()
    conn.close()

def get_delay_color(meskani):
    """Určí barvu podle zpoždění"""
    try:
        m = int(meskani)
        if m < 5: return "green"
        elif m < 15: return "orange"
        else: return "red"
    except:
        return "black"

@app.route('/')
def index():
    """Hlavní stránka - zobrazí data z databáze"""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Načtení posledních 50 záznamů
    c.execute("SELECT * FROM zpozdeni ORDER BY cas DESC LIMIT 50")
    rows = c.fetchall()
    conn.close()
    
    data = []
    for row in rows:
        data.append({
            'cas': row[0],
            'cislo': row[1],
            'dopravce': row[2],
            'cil': row[3],
            'plan': row[4],
            'aktual': row[5],
            'meskani': row[6],
            'barva': get_delay_color(row[6])
        })
    return render_template('index.html', data=data)

@app.route('/update')
def update_data():
    """Tuto adresu volej přes Cron-job každých 5 minut"""
    try:
        response = requests.get(STATION_URL)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        table = soup.find('table', {'id': 'TabuleGrid'})
        if not table:
            return "Chyba: Tabulka na webu SŽ nenalezena", 500

        conn = get_db_connection()
        c = conn.cursor()
        
        # Aktuální čas pro záznam
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        is_postgres = os.environ.get('DATABASE_URL') is not None

        count = 0
        # Projdeme tabulku řádek po řádku (přeskakujeme hlavičku)
        for row in table.find_all('tr')[1:]:
            cols = row.find_all('td')
            if len(cols) > 0:
                vals = (
                    now,
                    cols[1].text.strip(), # Číslo vlaku
                    cols[0].text.strip(), # Dopravce
                    cols[2].text.strip(), # Cíl
                    cols[3].text.strip(), # Plánovaný
                    cols[4].text.strip(), # Aktuální
                    cols[5].text.strip().replace(' min', '') or "0" # Zpoždění
                )

                if is_postgres:
                    c.execute("INSERT INTO zpozdeni VALUES (%s, %s, %s, %s, %s, %s, %s)", vals)
                else:
                    c.execute("INSERT INTO zpozdeni VALUES (?, ?, ?, ?, ?, ?, ?)", vals)
                count += 1

        conn.commit()
        conn.close()
        return f"Úspěch! Staženo {count} vlaků v čase {now}", 200
        
    except Exception as e:
        return f"Chyba: {str(e)}", 500

# Spuštění
init_db()

if __name__ == "__main__":
    app.run(debug=True)
