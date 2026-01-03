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

def zjisti_dopravce(typ_info, cislo_vlaku):
    """
    Pokusí se zjistit dopravce z textového popisu (TypeInfo)
    """
    info = str(typ_info).lower()
    if "gw train" in info or "gwtr" in info:
        return "GW Train"
    if "arriva" in info or "arr" in info:
        return "Arriva"
    if "regiojet" in info or "rj" in info:
        return "RegioJet"
    if "alex" in info:
        return "Alex"
    if "laenderbahn" in info or "dlb" in info:
        return "Die Länderbahn"
    if "ažd" in info:
        return "AŽD Praha"
    
    # Pokud jsme nic nenašli, jsou to pravděpodobně České dráhy
    return "ČD"

@app.route('/update')
def update_data():
    try:
        # Simulujeme prohlížeč
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        data = 'language=cs&isDeep=false&toHistory=false'
        
        response = requests.post(API_URL, headers=headers, data=data)
        
        if response.status_code != 200: 
            return f"Chyba API ČD: {response.status_code}", 500

        json_data = response.json()
        trains = json_data.get('Trains', [])
        
        if not trains:
            return "API vrátilo prázdný seznam vlaků (změna formátu?)", 500

        conn = get_db_connection()
        c = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ph = get_placeholder()
        
        count = 0
        for train in trains:
            # --- ZÍSKÁVÁNÍ DAT (Opravené klíče) ---
            
            # 1. Číslo vlaku
            cislo = train.get('TrainNumber', '??')
            
            # 2. Cílová stanice (ČD to má někdy jako 'Station', někdy 'TargetStation')
            # Zkusíme obojí
            cil = train.get('TargetStation')
            if not cil:
                cil = train.get('Station', 'Neznámá stanice')
            
            # 3. Čas odjezdu
            plan = train.get('Time', '--:--')
            
            # 4. Zpoždění
            meskani = str(train.get('Delay', 0))
            if meskani == "None": meskani = "0"
            
            # 5. Dopravce (Detektivní práce)
            # ČD posílá info např: "Os 7640 GW Train Regio a.s."
            type_info = train.get('TypeInfo', '')
            dopravce = zjisti_dopravce(type_info, cislo)

            # Výpočet zobrazení aktuálního času
            if meskani != "0":
                aktual = f"{plan} (+{meskani})"
            else:
                aktual = plan

            # Uložení
            vals = (now, cislo, dopravce, cil, plan, aktual, meskani)
            
            c.execute(f"INSERT INTO zpozdeni VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})", vals)
            count += 1

        conn.commit()
        conn.close()
        return f"✅ ÚSPĚCH! Staženo {count} vlaků.<br>Poslední vlak: {dopravce} {cislo} do {cil}", 200
        
    except Exception as e:
        return f"CHYBA v kódu: {str(e)}", 500

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
            try:
                m = int(row[6])
                if m < 5: color = "text-green-600"
                elif m < 15: color = "text-orange-500"
                else: color = "text-red-600 font-bold"
            except:
                color = "text-gray-600"

            data.append({
                'cas': row[0],
                'cislo': row[1],
                'dopravce': row[2],
                'cil': row[3],
                'plan': row[4],
                'aktual': row[5],
                'meskani': row[6],
                'color': color
            })
            
        return render_template('index.html', data=data)
    except Exception as e:
        return f"Chyba webu: {str(e)}"

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
