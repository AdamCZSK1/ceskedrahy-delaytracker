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
    c.execute('''CREATE TABLE IF NOT EXISTS zpozdeni
                 (cas TEXT, cislo_vlaku TEXT, dopravce TEXT, cilova_stanice TEXT, 
                  planovany_odjezd TEXT, aktualni_odjezd TEXT, meskani TEXT)''')
    conn.commit()
    conn.close()

def zjisti_dopravce(typ_info, cislo_vlaku):
    info = str(typ_info).lower()
    if "gw train" in info or "gwtr" in info: return "GW Train"
    if "arriva" in info or "arr" in info: return "Arriva"
    if "regiojet" in info or "rj" in info: return "RegioJet"
    if "alex" in info: return "Alex"
    if "laenderbahn" in info or "dlb" in info: return "Die Länderbahn"
    if "ažd" in info: return "AŽD Praha"
    return "ČD"

@app.route('/update')
def update_data():
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
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
            cislo = train.get('TrainNumber', '??')
            cil = train.get('TargetStation') or train.get('Station', 'Neznámá')
            plan = train.get('Time', '--:--')
            
            # Získání zpoždění (může být i záporné = náskok)
            try:
                meskani_int = int(train.get('Delay', 0))
            except:
                meskani_int = 0
            
            meskani_str = str(meskani_int)
            
            # Logika pro text "Aktuální odjezd"
            if meskani_int > 0:
                aktual = f"{plan} (+{meskani_int} min)"
            elif meskani_int < 0:
                aktual = f"{plan} (Náskok {abs(meskani_int)} min)"
            else:
                aktual = plan # Jede načas

            type_info = train.get('TypeInfo', '')
            dopravce = zjisti_dopravce(type_info, cislo)

            vals = (now, cislo, dopravce, cil, plan, aktual, meskani_str)
            c.execute(f"INSERT INTO zpozdeni VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})", vals)
            count += 1

        conn.commit()
        conn.close()
        return f"✅ ÚSPĚCH! Staženo {count} vlaků.", 200
        
    except Exception as e:
        return f"CHYBA: {str(e)}", 500

@app.route('/')
def index():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        ph = get_placeholder()
        
        filter_date = request.args.get('date')
        filter_train = request.args.get('train')
        
        query = "SELECT * FROM zpozdeni WHERE 1=1"
        params = []

        if filter_date:
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
            meskani_text = "načas"
            try:
                m = int(row[6])
                # BARVY A TEXTY
                if m < 0: # Náskok
                    color = "text-green-600 font-bold"
                    meskani_text = f"Náskok {abs(m)} min"
                elif m == 0: # Načas
                    color = "text-green-600"
                    meskani_text = "načas"
                elif m < 5: # Malé zpoždění
                    color = "text-green-600"
                    meskani_text = f"{m} min"
                elif m < 15: # Střední
                    color = "text-orange-500 font-bold"
                    meskani_text = f"{m} min"
                else: # Velké
                    color = "text-red-600 font-black"
                    meskani_text = f"{m} min"
            except:
                color = "text-gray-600"
                meskani_text = "?"

            data.append({
                'cas': row[0], 'cislo': row[1], 'dopravce': row[2],
                'cil': row[3], 'plan': row[4], 'aktual': row[5],
                'meskani_display': meskani_text, # Tohle pošleme do HTML
                'color': color
            })
            
        return render_template('index.html', data=data)
    except Exception as e:
        return f"Chyba webu: {str(e)}"

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
