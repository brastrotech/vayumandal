import kivy
from kivy.app import App
from kivy.lang import Builder
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.properties import StringProperty
import sqlite3
import datetime
import requests

# Simulated GPS coordinates for Windows (replace with plyer for Android)
def get_current_gps():
    return 28.6139, 77.2090  # Delhi coordinates

# Fetch AQI from AQICN API using API key
def get_aqi_by_location(lat, lon, api_key):
    url = f"https://api.waqi.info/feed/geo:{lat};{lon}/?token={api_key}"
    try:
        r = requests.get(url, timeout=10)
        resp = r.json()
        if resp.get("status") == "ok":
            return resp["data"]["aqi"]
        return None
    except Exception as e:
        print(f"AQI API error: {e}")
        return None

# Database setup and helpers
def init_db():
    con = sqlite3.connect("db.sqlite3")
    cur = con.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS aqi_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        latitude REAL, longitude REAL,
        aqi INTEGER, timestamp TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS junkfood_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        food TEXT, calories INTEGER, timestamp TEXT)''')
    cur.execute('SELECT * FROM users WHERE username=?', ('admin',))
    if cur.fetchone() is None:
        cur.execute('INSERT INTO users (username, password) VALUES (?, ?)', ('admin', '1234')) # DEMO ONLY
    con.commit()
    con.close()

def verify_user(username, password):
    con = sqlite3.connect("db.sqlite3")
    cur = con.cursor()
    cur.execute('SELECT * FROM users WHERE username=? AND password=?', (username, password))
    res = cur.fetchone()
    con.close()
    return res is not None

def add_aqi(username, lat, lon, aqi):
    con = sqlite3.connect("db.sqlite3")
    cur = con.cursor()
    cur.execute('INSERT INTO aqi_data (username, latitude, longitude, aqi, timestamp) VALUES (?, ?, ?, ?, ?)',
                (username, lat, lon, aqi, datetime.datetime.now().isoformat()))
    con.commit()
    con.close()

def get_aqi_history(username):
    con = sqlite3.connect("db.sqlite3")
    cur = con.cursor()
    cur.execute('SELECT aqi, timestamp FROM aqi_data WHERE username=? ORDER BY timestamp DESC', (username,))
    results = cur.fetchall()
    con.close()
    return results

def log_junk_food(username, food, calories):
    con = sqlite3.connect("db.sqlite3")
    cur = con.cursor()
    cur.execute('INSERT INTO junkfood_log (username, food, calories, timestamp) VALUES (?, ?, ?, ?)',
                (username, food, calories, datetime.datetime.now().isoformat()))
    con.commit()
    con.close()

def get_junkfood_history(username):
    con = sqlite3.connect("db.sqlite3")
    cur = con.cursor()
    cur.execute('SELECT food, calories, timestamp FROM junkfood_log WHERE username=? ORDER BY timestamp DESC', (username,))
    data = cur.fetchall()
    con.close()
    return data

# Kivy Screens
class LoginScreen(Screen):
    error_message = StringProperty("")
    def do_login(self):
        user = self.ids.username.text.strip()
        pwd = self.ids.password.text.strip()
        if verify_user(user, pwd):
            self.manager.current = 'main'
            self.manager.get_screen('main').username = user
            self.ids.username.text = ""
            self.ids.password.text = ""
            self.error_message = ""
        else:
            self.error_message = "Invalid login. Try again."
    def register(self):
        user = self.ids.username.text.strip()
        pwd = self.ids.password.text.strip()
        if not user or not pwd:
            self.error_message = "Enter username and password."
            return
        con = sqlite3.connect("db.sqlite3")
        cur = con.cursor()
        try:
            cur.execute('INSERT INTO users (username, password) VALUES (?, ?)', (user, pwd))
            con.commit()
            self.error_message = "Registration successful!"
        except sqlite3.IntegrityError:
            self.error_message = "User already exists."
        finally:
            con.close()

class MainScreen(Screen):
    username = StringProperty("")
    aqi_info = StringProperty("Awaiting data...")
    def on_enter(self):
        self.get_aqi()
    def get_aqi(self):
        lat, lon = get_current_gps()
        api_key = "579b464db66ec23bdd000001a03f90232e63420a6069ee95fff7c19e"
        aqi = get_aqi_by_location(lat, lon, api_key)
        if aqi is not None:
            add_aqi(self.username, lat, lon, aqi)
            self.aqi_info = f"Your GPS: ({lat:.4f}, {lon:.4f})\nLatest AQI: {aqi}"
        else:
            self.aqi_info = "Failed to fetch AQI data."

class HealthScreen(Screen):
    username = StringProperty("")
    history_info = StringProperty("")
    def on_pre_enter(self):
        history = get_aqi_history(self.username)
        if not history:
            self.history_info = "No data yet."
        else:
            report = ""
            unsafe_days = sum(1 for a, t in history if a and int(a) > 100)
            report += f"Entries: {len(history)}. Unsafe AQI occasions: {unsafe_days}\nRecent readings:\n"
            for a, t in history[:10]:
                report += f"AQI: {a} at {t[:19]}\n"
            self.history_info = report

class CarbonScreen(Screen):
    def on_enter(self):
        info = ("What are Carbon Credits?\n\nA carbon credit is a permit allowing emission of a set amount of carbon dioxide or greenhouse gases. "
                "Credits can be traded, incentivizing emission reductions.\n\n"
                "Learn more:\n- UN Carbon Credits Program\n- India's PAT/Perform-Achieve-Trade Scheme")
        self.ids.carbon_info.text = info

class JunkFoodScreen(Screen):
    username = StringProperty("")
    result = StringProperty("")
    def calc_junkfood(self):
        food = self.ids.food_item.text
        try:
            cal = int(self.ids.calories.text)
        except:
            cal = 0
        if not food or not cal:
            self.result = "Please enter valid food and calories."
            return
        log_junk_food(self.username, food, cal)
        self.result = f"{food} ({cal} kcal) added!"
    def on_pre_enter(self):
        data = get_junkfood_history(self.username)
        log = "Recent Entries:\n"
        for food, cal, t in data[:5]:
            log += f"{food}: {cal} kcal at {t[:19]}\n"
        self.result = log

class WindowManager(ScreenManager):
    pass

init_db()
kv = Builder.load_file("main.kv")

class PollutionApp(App):
    def build(self):
        return kv

if __name__ == "__main__":
    PollutionApp().run()
