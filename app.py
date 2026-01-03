import os
import sqlite3
import requests
from datetime import datetime
import psycopg2
from flask import Flask, render_template, jsonify

app = Flask(__name__)

# ID stanice pro ČD (Plzeň hl.n. = 5473275)
STATION_ID = "5473275"
API_URL = f"https://www.cd.cz/stanice/{STATION_ID}/getopt"

def get_db_connection():
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        return psycopg2.connect(db_url)
    return sqlite3.connect('zpozdeni.sqlite3')

def get_placeholder():
    return '%s' if os.environ.get('DATABASE_URL') else '?'

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS zpozdeni
                 (cas TEXT, cislo_vlaku TEXT, dopravce TEXT, cilova_stanice TEXT, 
                  planovany_odjezd TEXT, aktualni_odjezd TEXT, meskani TEXT)''')
    conn.commit()
    conn.close()

@app.route('/update')
def update_data():
    try:
        # Nastavení požadavku pro ČD (tváříme se jako prohlížeč)
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        data = 'language=cs&isDeep=false&toHistory=false'
        
        response = requests.post(API_URL, headers=headers, data=data)
        
        if response.status_code != 200:
            return f"Chyba ČD API: {response.status_code}", 500

        json_data = response.json()
        trains = json_data.get('Trains', [])
        
        if not trains:
            return "Žádné vlaky nenalezeny (nebo chyba API)", 500

        conn = get_db_connection()
        c = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ph = get_placeholder()
        
        count = 0
        for train in trains:
            # Vytáhneme data z JSONu ČD
            # ČD posílá čas jako "12:34", musíme k tomu přidat datum, pokud chybí,
            # ale pro jednoduchost ukládáme, co pošlou.
            
            cislo = train.get('TrainNumber', '??')
            # ČD často spojuje název vlaku a číslo, zkusíme to vyčistit
            dopravce = "ČD" # API ČD většinou ukazuje své vlaky, nebo partnery
            cil = train.get('TargetStation', '?')
            plan = train.get('Time', '?')
            meskani = str(train.get('Delay', 0))
            
            # Výpočet aktuálního odjezdu (jen orientačně, textově)
            aktual = f"{plan} (+{meskani} min)" if meskani != "0" else plan

            vals = (now, cislo, dopravce, cil, plan, aktual, meskani)
            
            c.execute(f"INSERT INTO zpozdeni VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})", vals)
            count += 1

        conn.commit()
        conn.close()
        return f"ÚSPĚCH! Uloženo {count} vlaků z ČD API.", 200
        
    except Exception as e:
        return f"CHYBA: {str(e)}", 500

@app.route('/')
def index():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM zpozdeni ORDER BY cas DESC LIMIT 50")
        rows = c.fetchall()
        conn.close()
        
        data = []
        for row in rows:
            # Barvy
            try:
                m = int(row[6])
                color = "red" if m >= 15 else "orange" if m >= 5 else "green"
            except:
                color = "black"

            data.append({
                'cas': row[0], 'cislo': row[1], 'dopravce': row[2],
                'cil': row[3], 'plan': row[4], 'aktual': row[5], 
                'meskani': row[6], 'barva': color
            })
        return render_template('index.html', data=data)
    except Exception as e:
        return str(e)

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
