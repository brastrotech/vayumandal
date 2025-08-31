import kivy
from kivy.app import App
from kivy.lang import Builder
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.properties import StringProperty
import sqlite3
import datetime
import requests

from plyer import gps
from math import radians, cos, sin, asin, sqrt


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
# Haversine formula to calculate distance between two GPS points (in km)
def haversine(lon1, lat1, lon2, lat2):
    # convert decimal degrees to radians
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    # haversine formula
    dlon = lon2 - lon1 
    dlat = lat2 - lat1 
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a)) 
    km = 6371 * c
    return km

class CarbonScreen(Screen):
    electricity_bill = StringProperty("")
    transport_mode = StringProperty("walking")
    distance_travelled = 0.0
    carbon_footprint = StringProperty("")
    carbon_credits = StringProperty("")
    prev_lat = None
    prev_lon = None

    def on_enter(self):
        self.distance_travelled = 0.0
        self.prev_lat = None
        self.prev_lon = None
        self.transport_mode = "walking"
        self.ids.carbon_footprint_label.text = ""
        self.ids.carbon_credits_label.text = ""
        try:
            gps.configure(on_location=self.on_gps_location, on_status=self.on_gps_status)
            gps.start(minTime=1000, minDistance=1)  # Update every 1s or 1m movement
        except:
            self.ids.carbon_footprint_label.text = "GPS not available or permission denied."

    def on_leave(self):
        try:
            gps.stop()
        except:
            pass

    def on_gps_location(self, **kwargs):
        lat = kwargs.get('lat')
        lon = kwargs.get('lon')
        speed = kwargs.get('speed', 0) or 0  # m/s

        # Update transport mode based on speed thresholds
        if speed < 2:
            mode = "walking"
        elif speed < 15:
            mode = "two-wheeler"
        else:
            mode = "four-wheeler"
        self.transport_mode = mode
        self.ids.transport_spinner.text = mode

        # Calculate distance from previous point
        if self.prev_lat is not None and self.prev_lon is not None:
            dist = haversine(self.prev_lon, self.prev_lat, lon, lat)
            self.distance_travelled += dist
        self.prev_lat = lat
        self.prev_lon = lon

    def on_gps_status(self, stype, status):
        pass  # Can show GPS status messages if needed

    def calculate_credits(self):
        try:
            bill = float(self.ids.electricity_bill.text)
        except:
            self.ids.carbon_footprint_label.text = "Invalid electricity bill amount."
            self.ids.carbon_credits_label.text = ""
            return

        transport = self.transport_mode
        
        # Electricity CO2 estimation
        electricity_co2 = bill * 0.82  # kg CO2 approx

        # Petrol consumption estimation based on distance and mode
        mileage_map = {"walking": 0, "two-wheeler": 40, "four-wheeler": 15}  # km/l
        co2_per_liter_petrol = 2.3  # kg CO2 per liter petrol approx

        mileage = mileage_map.get(transport, 0)
        petrol_used = self.distance_travelled / mileage if mileage else 0
        transport_co2 = petrol_used * co2_per_liter_petrol

        total_co2 = electricity_co2 + transport_co2

        credits = total_co2 / 1000  # 1 credit per 1000 kg

        self.ids.carbon_footprint_label.text = (
            f"Electricity CO₂: {electricity_co2:.2f} kg\n"
            f"Transport CO₂: {transport_co2:.2f} kg (Distance: {self.distance_travelled:.2f} km)\n"
            f"Total CO₂ emissions: {total_co2:.2f} kg"
        )
        self.ids.carbon_credits_label.text = f"Estimated carbon credits: {credits:.3f}"


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
