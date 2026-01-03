import logging
from logging.handlers import RotatingFileHandler
from urllib.parse import urlencode
from flask import Flask, render_template, request, make_response, jsonify
import logging
from logging.handlers import RotatingFileHandler
import sqlite3
from datetime import datetime, timedelta
import requests
from apscheduler.schedulers.background import BackgroundScheduler


# Function to connect to DB and properly handle exceptions
def create_connection(db_file):
    conn = None
    try:
        conn = sqlite3.connect(db_file, check_same_thread=False)
        print(sqlite3.version)
    except sqlite3.Error as e:
        print(e)
    finally:
        if conn:
            return conn
        else:
            return None


# Function to fetch data from the CzechRail database and put the relevant info in the db
def data_fetcher():
    # Set API URL and set request details for past and future arrivals
    API_URL = 'https://www.cd.cz/stanice/5473275/getopt'
    API_REQ = 'language=cs&isDeep=false&toHistory=false'
    API_REQ_PAST = 'language=cs&isDeep=false&toHistory=true'


    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    data = API_REQ
    data_past = API_REQ_PAST

    # Fetches data from CzechRail API and puts it into one concise list
    train_data_cur = requests.post(API_URL, headers=headers, data=data).json()['Trains'][:10]
    train_data_past = requests.post(API_URL, headers=headers, data=data_past).json()['Trains'][-3:]
    train_data = train_data_past + train_data_cur
    # Sets current time at the time the request got back
    cur_time = datetime.now().strftime('%H:%M')

    # Check whether the first 13 arrivals have arrived, if so, save them into database, incl. delays and platform info
    for train in train_data:
        # Parse expected arrival time into a datetime object
        if train['DTDelay'] == '':
            train_time = datetime.strptime(train['DT'], '%H:%M')
        else:
            train_time = datetime.strptime(train['DTDelay'], '%H:%M')

        train_cur_time = datetime.strptime(cur_time, '%H:%M')

        # Calculate a time difference in minutes between the current time and the expected arrival
        time_diff = train_time - train_cur_time
        time_diff = int(time_diff.total_seconds() / 60)

        # If time difference between the present and the expected arrival is +- 2 minutes, we can safely write the data
        if -5 <= time_diff <= 2:
            # Build a planned departure string for DB, which requires datetime to adhere to ISO 8601
            planned_dep = f"{datetime.today().strftime('%Y-%m-%d')} {train['DT']}:00"
            # Check whether train hasn't already been inserted into DB
            c.execute('SELECT id FROM zpozdeni WHERE train_num = ? AND planned = ?',
                      [train['TrainNumber'], planned_dep])
            train_exists = c.fetchone()
            # If train has arrived and isn't yet present in the DB, insert it
            if train_exists is None:
                print(f"logging train {train['Name']} with an expected arrival of {train['DT']} and a "
                      f"{train['Delay']}m delay")
                c.execute('INSERT INTO zpozdeni (train_num, train_type, train_name, from_direction, delay, planned, '
                          'cd_url, platform) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', 
                          [train['TrainNumber'], train['Type'], train['Name'], train['Destination'] + ', ' + train['Direction'], 
                           train['Delay'], planned_dep, train['URL'], train.get('StandAndTrackBox', 'N/A')])
                con.commit()


# Connect to DB and create table if it hasn't yet been created
# Connect to DB and create table if it hasn't yet been created
con = create_connection("zpozdeni.sqlite3")
c = con.cursor()

# Updated table structure with platform information
c.execute("CREATE TABLE IF NOT EXISTS zpozdeni (id INTEGER PRIMARY KEY NOT NULL, train_num INTEGER, train_type TEXT, "
          "train_name TEXT, from_direction TEXT, delay INTEGER, planned TEXT, cd_url TEXT, platform TEXT, "
          "inserted TEXT DEFAULT (datetime('now', 'localtime')))")
con.commit()


# Calls data fetcher manually on startup, since it would otherwise wait a minute before first scan
data_fetcher()

# Add scheduled task to scrape CzechRail API every minute
scrape_task = BackgroundScheduler(daemon=True)
scrape_task.add_job(data_fetcher, 'interval', minutes=1)
scrape_task.start()

app = Flask(__name__)
# Strip whitespaces from Jinja generated HTML
app.jinja_env.lstrip_blocks = True
app.jinja_env.trim_blocks = True


# Add a function to calculate real arrival time based on planned arrival and delay
def calculate_arrival(query_res):
    real_arrivals = list()
    for arrival in query_res:
        planned_arrival = datetime.strptime(arrival[6], '%Y-%m-%d %H:%M:%S')
        real_arrival = planned_arrival + timedelta(minutes=arrival[5])
        real_arrivals.append(datetime.strftime(real_arrival, '%H:%M'))
    return real_arrivals

@app.before_request
def log_ip():
    if request.headers.get('X-Forwarded-For'):
        actual_ip = request.headers.getlist('X-Forwarded-For')[0]
    else:
        actual_ip = request.remote_addr

    query_string = request.query_string.decode('utf-8')
    if query_string:
        log_entry = f'{actual_ip} - - [{datetime.now().strftime("%d/%b/%Y %H:%M:%S")}] "{request.method} {request.path}?{query_string} HTTP/1.1" (Proxy: {PROXY_IP})'
    else:
        log_entry = f'{actual_ip} - - [{datetime.now().strftime("%d/%b/%Y %H:%M:%S")}] "{request.method} {request.path} HTTP/1.1" (Proxy: {PROXY_IP})'

    app.logger.info(log_entry)
    print(log_entry)


@app.route('/')
def view_delays():
    con = create_connection("zpozdeni.sqlite3")
    c = con.cursor()
    
    date = request.args.get('date')
    time = request.args.get('time')

    if any(val is None or val == "" for val in [date, time]):
        c.execute('SELECT * FROM zpozdeni ORDER BY id DESC LIMIT 5')
    else:
        datetime_db = f"{date} {time}:00"
        c.execute('SELECT * FROM zpozdeni WHERE inserted > ? ORDER BY id LIMIT 5', [datetime_db])
    
    last_delays = c.fetchall()
    real_arrivals = calculate_arrival(last_delays)
    
    con.close()  # nezapomeň zavřít spojení
    return make_response(render_template('maina.html', trains=last_delays, datetime=[date, time], real_arrivals=real_arrivals))


# Proxy IP address
PROXY_IP = '38.242.156.120'

# New route for getting platform information based on train_num
@app.route('/nastupiste/<train_num>')
def get_platform(train_num):
    c.execute('SELECT platform FROM zpozdeni WHERE train_num = ? ORDER BY id DESC LIMIT 1', [train_num])
    platform_info = c.fetchone()
    if platform_info:
        return jsonify({"platform": platform_info[0]})
    else:
        return jsonify({"platform": "N/A"})  # Return "N/A" if no platform information is found


@app.route('/isthisworking')
def is_this_working():
    if request.headers.get('X-Forwarded-For'):
        actual_ip = request.headers.getlist('X-Forwarded-For')[0]
    else:
        actual_ip = request.remote_addr

    query_string = request.query_string.decode('utf-8')
    if query_string:
        log_entry2 = f'{actual_ip} - - [{datetime.now().strftime("%d/%b/%Y %H:%M:%S")}] "{request.method} {request.path}?{query_string} HTTP/1.1" (Proxy: {PROXY_IP})'
    else:
        log_entry2 = f'{actual_ip} - - [{datetime.now().strftime("%d/%b/%Y %H:%M:%S")}] "{request.method} {request.path} HTTP/1.1" (Proxy: {PROXY_IP})'
    print(log_entry2)
    return f'This is working!\n\n\n' + log_entry2




@app.route('/historie')
def view_history():
    # Get data from form on history site (or referral from main)
    train_num = request.args.get('train_num')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    if any(val is None or val == "" for val in [date_from, date_to]):
        # Preset last 2 weeks as default
        cur_date = datetime.now()
        date_to = cur_date.strftime('%Y-%m-%d')
        date_from = (cur_date - timedelta(days=14)).strftime('%Y-%m-%d')

    if train_num is None or train_num == "":
        # Return an empty form with prefilled dates
        return render_template('historie.html', error='', form_data=['', date_from, date_to])
    # If train number is not numeric, call a popup to tell the user
    elif train_num.isnumeric() is False:
        error = "Zadané číslo vlaku není číslo, zkontrolujte zda Vámi zadaná hodnota neobsahuje písmena!"
        return render_template('historie.html', error=error, form_data=[train_num, date_from, date_to])
    # User input is valid, fetch data from db and send it to Jinja
    else:
        c.execute('SELECT * FROM zpozdeni WHERE train_num = ? AND inserted BETWEEN ? AND ? ORDER BY id DESC',
                  [train_num, date_from, f"{date_to} 23:59:59"])
        train_info = c.fetchall()

        # Calculate actual arrival based on planned arrival and delay
        real_arrivals = calculate_arrival(train_info)

        # Convert strings into datetime objects for later formatting
        train_datetimes = list()
        for train in train_info:
            train_datetime = datetime.strptime(train[6], '%Y-%m-%d %H:%M:%S')
            train_datetimes.append(train_datetime)

        # Send data to Jinja
        return render_template('historie_vysledky.html', error='', form_data=[train_num, date_from, date_to],
                               train_info=train_info, real_arrivals=real_arrivals, train_datetimes=train_datetimes)


if __name__ == '__main__':
    handler = RotatingFileHandler('app.log', maxBytes=10000, backupCount=1)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(message)s')
    handler.setFormatter(formatter)
    app.logger.addHandler(handler)

    app.run(host='0.0.0.0', port='5010')
