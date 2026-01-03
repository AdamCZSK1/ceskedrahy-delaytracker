import os
import sqlite3
import requests
from datetime import datetime
import psycopg2
from flask import Flask, render_template, request

app = Flask(__name__)

# ID stanice ČD (Plzeň hl.n. = 5473275)
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
    # Tabulka se všemi sloupci
    c.execute('''CREATE TABLE IF NOT EXISTS zpozdeni
                 (cas TEXT, cislo_vlaku TEXT, dopravce TEXT, cilova_stanice TEXT, 
                  planovany_odjezd TEXT, aktualni_odjezd TEXT, meskani TEXT)''')
    conn.commit()
    conn.close()

@app.route('/update')
def update_data():
    try:
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        data = 'language=cs&isDeep=false&toHistory=false'
        response = requests.post(API_URL, headers=headers, data=data)
        
        if response.status_code != 200: return f"Chyba API: {response.status_code}", 500

        json_data = response.json()
        trains = json_data.get('Trains', [])
        
        conn = get_db_connection()
        c = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ph = get_placeholder()
        
        count = 0
        for train in trains:
            # Získání všech detailů
            cislo = train.get('TrainNumber', '??')
            # ČD posílá v TypeInfo např "R 1234 ...", zkusíme vzít jen typ
            dopravce = train.get('TrainType', 'Vlak') 
            cil = train.get('TargetStation', '?')
            plan = train.get('Time', '?')
            meskani = str(train.get('Delay', 0))
            
            # Pokud zpoždění > 0, vypočítáme "reálný čas" jen textově pro zobrazení
            aktual = f"{plan} (+{meskani} min)" if meskani != "0" else plan

            vals = (now, cislo, dopravce, cil, plan, aktual, meskani)
            
            c.execute(f"INSERT INTO zpozdeni VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})", vals)
            count += 1

        conn.commit()
        conn.close()
        return f"✅ ÚSPĚCH! Uloženo {count} vlaků (včetně detailů).", 200
    except Exception as e:
        return f"CHYBA: {str(e)}", 500

@app.route('/')
def index():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        ph = get_placeholder()
        
        # --- FILTROVÁNÍ ---
        filter_date = request.args.get('date')
        filter_train = request.args.get('train')
        
        query = "SELECT * FROM zpozdeni WHERE 1=1"
        params = []

        if filter_date:
            # Postgres vs SQLite syntaxe pro datum
            if os.environ.get('DATABASE_URL'):
                query += " AND cas::text LIKE %s"
            else:
                query += " AND cas LIKE ?"
            params.append(f"{filter_date}%")
            
        if filter_train:
            query += f" AND cislo_vlaku = {ph}"
            params.append(filter_train)
            
        query += " ORDER BY cas DESC LIMIT 100"
        
        c.execute(query, tuple(params))
        rows = c.fetchall()
        conn.close()
        
        data = []
        for row in rows:
            # Nastavení barev podle zpoždění
            try:
                m = int(row[6])
                if m < 5: color = "text-green-600"
                elif m < 15: color = "text-orange-500"
                else: color = "text-red-600 font-bold"
            except:
                color = "text-gray-600"

            data.append({
                'cas': row[0],        # Čas záznamu
                'cislo': row[1],      # Číslo vlaku
                'dopravce': row[2],   # Typ/Dopravce
                'cil': row[3],        # Cílová stanice
                'plan': row[4],       # Plánovaný odjezd
                'aktual': row[5],     # Aktuální odjezd
                'meskani': row[6],    # Minuty zpoždění
                'color': color        # Barva pro CSS
            })
            
        return render_template('index.html', data=data)
    except Exception as e:
        return f"Chyba webu: {str(e)}"

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
