import kivy
from kivy.app import App
from kivy.lang import Builder
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.properties import StringProperty, NumericProperty, ObjectProperty
from kivy.clock import Clock
import sqlite3
import datetime
import requests
import threading
from math import radians, cos, sin, asin, sqrt

# Using plyer for GPS requires buildozer permissions on Android/iOS
# For desktop testing, we will mock the location.
try:
    from plyer import gps
    PLYER_AVAILABLE = True
except ImportError:
    PLYER_AVAILABLE = False


# --- CPCB Data Integration ---
def get_cpcb_stations_data(api_key):
    """Fetches a list of all CPCB monitoring stations and their AQI data."""
    url = f"https://api.data.gov.in/resource/3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69?api-key={api_key}&format=json&limit=2000"
    print("CPCB: Fetching data from API...")
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status() # Raise an exception for bad status codes
        data = r.json()
        if "records" in data and data["records"]:
            return data["records"], "Success"
        else:
            return None, "Error: Unexpected API response format."
    except requests.exceptions.Timeout:
        return None, "Error: Connection timed out."
    except requests.exceptions.RequestException as e:
        return None, f"Error: Network connection failed: {e}"
    except Exception as e:
        return None, f"An unexpected error occurred: {e}"

def haversine(lon1, lat1, lon2, lat2):
    """Calculate the distance between two points on Earth."""
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon, dlat = lon2 - lon1, lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return 6371 * c # Radius of earth in kilometers.

def find_nearest_stations(user_lat, user_lon, stations):
    """Finds and returns the 5 nearest stations from a list."""
    if not stations: return []
    stations_with_dist = []
    for station in stations:
        try:
            st_lat, st_lon = float(station.get('latitude')), float(station.get('longitude'))
            distance = haversine(user_lon, user_lat, st_lon, st_lat)
            stations_with_dist.append((station, distance))
        except (ValueError, TypeError):
            continue
    stations_with_dist.sort(key=lambda x: x[1])
    return stations_with_dist[:5]

# --- Database Management ---
def init_db():
    """Initializes the SQLite database and tables."""
    with sqlite3.connect("health_tracker.db") as con:
        cur = con.cursor()
        cur.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)')
        cur.execute('''CREATE TABLE IF NOT EXISTS aqi_data (
            id INTEGER PRIMARY KEY, username TEXT, latitude REAL, longitude REAL,
            aqi INTEGER, timestamp TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS junkfood_log (
            id INTEGER PRIMARY KEY, username TEXT, food TEXT, calories INTEGER, timestamp TEXT)''')
        # Add a default user if one doesn't exist
        if cur.execute('SELECT * FROM users WHERE username=?', ('admin',)).fetchone() is None:
            cur.execute('INSERT INTO users (username, password) VALUES (?, ?)', ('admin', '1234'))
        con.commit()

# --- Screen Classes ---
class LoginScreen(Screen):
    error_message = StringProperty("")
    def do_login(self, username, password):
        if self._verify_user(username, password):
            self.manager.current = 'main'
            main_screen = self.manager.get_screen('main')
            main_screen.username = username
            main_screen.get_aqi() # Fetch data on login
            # Pass username to other screens
            self.manager.get_screen('health').username = username
            self.manager.get_screen('carbon').username = username
            self.manager.get_screen('junk_food').username = username
            self.ids.username.text = ""
            self.ids.password.text = ""
            self.error_message = ""
        else:
            self.error_message = "Invalid username or password."

    def register_user(self, username, password):
        if not username or not password:
            self.error_message = "Please enter a username and password."
            return
        try:
            with sqlite3.connect("health_tracker.db") as con:
                cur = con.cursor()
                cur.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, password))
                con.commit()
            self.error_message = "Registration successful! Please log in."
        except sqlite3.IntegrityError:
            self.error_message = "Username already exists."

    def _verify_user(self, username, password):
        with sqlite3.connect("health_tracker.db") as con:
            cur = con.cursor()
            cur.execute('SELECT * FROM users WHERE username=? AND password=?', (username, password))
            return cur.fetchone() is not None

class MainScreen(Screen):
    username = StringProperty("")
    aqi_info = StringProperty("Welcome! Fetching AQI data...")

    def on_enter(self, *args):
        self.get_aqi()

    def get_aqi(self):
        self.aqi_info = "Fetching your location..."
        if PLYER_AVAILABLE:
            try:
                gps.configure(on_location=self.on_gps_location)
                gps.start(1000, 0)
            except Exception as e:
                print(f"GPS Error: {e}")
                self.aqi_info = "Error: GPS not available. Using a default location."
                self.on_gps_location(lat=23.0225, lon=72.5714) # Default to Ahmedabad
        else:
            self.aqi_info = "Plyer not found. Using a default location."
            self.on_gps_location(lat=23.0225, lon=72.5714) # Default to Ahmedabad

    def on_gps_location(self, **kwargs):
        lat, lon = kwargs.get('lat'), kwargs.get('lon')
        if lat and lon:
            print(f"GPS: Location acquired: {lat}, {lon}")
            if PLYER_AVAILABLE:
                try: gps.stop()
                except Exception: pass
            self.aqi_info = "Location found. Fetching station data..."
            threading.Thread(target=self.fetch_station_data, args=(lat, lon)).start()

    def fetch_station_data(self, lat, lon):
        cpcb_api_key = "579b464db66ec23bdd000001a03f90232e63420a6069ee95fff7c19e"
        stations, status_message = get_cpcb_stations_data(cpcb_api_key)

        display_text = ""
        if stations:
            nearest = find_nearest_stations(lat, lon, stations)
            if nearest:
                # Log the AQI of the very closest station
                closest_station, _ = nearest[0]
                aqi_to_log = closest_station.get('aqi')
                if aqi_to_log and str(aqi_to_log).strip().lower() not in ['na', 'n/a', 'none', '']:
                    try:
                        with sqlite3.connect("health_tracker.db") as con:
                            cur = con.cursor()
                            cur.execute('INSERT INTO aqi_data (username, latitude, longitude, aqi, timestamp) VALUES (?, ?, ?, ?, ?)',
                                        (self.username, lat, lon, int(aqi_to_log), datetime.datetime.now().isoformat()))
                            con.commit()
                    except (ValueError, TypeError):
                        print(f"Could not log AQI: Invalid value '{aqi_to_log}'")

                display_text = "[b]Data from Nearest CPCB Stations:[/b]\n\n"
                for station, dist in nearest:
                    aqi = station.get('aqi', 'N/A')
                    name = station.get('station', 'Unknown')
                    city = station.get('city', 'Unknown')
                    last_update = station.get('last_update', 'N/A')
                    display_text += (f"[b]{name}, {city}[/b] ({dist:.2f} km)\n"
                                     f"  - AQI: {aqi}\n  - Updated: {last_update}\n\n")
            else:
                display_text = "Could not find a nearby CPCB station."
        else:
            display_text = f"Failed to fetch CPCB data.\n{status_message}"

        Clock.schedule_once(lambda dt: self.update_ui(display_text))

    def update_ui(self, text):
        self.aqi_info = text

class HealthScreen(Screen):
    username = StringProperty("")
    history_info = StringProperty("")

    def on_enter(self):
        with sqlite3.connect("health_tracker.db") as con:
            cur = con.cursor()
            cur.execute('SELECT aqi, timestamp FROM aqi_data WHERE username=? ORDER BY timestamp DESC', (self.username,))
            history = cur.fetchall()

        if not history:
            self.history_info = "No AQI data has been recorded yet."
        else:
            report = ""
            unsafe_days = sum(1 for aqi, ts in history if aqi and int(aqi) > 100)
            report += f"Total Entries: {len(history)}\nUnsafe AQI Days Recorded: {unsafe_days}\n\n[b]Recent Readings:[/b]\n"
            for aqi, ts in history[:10]:
                report += f"- AQI: {aqi} on {ts[:16]}\n"
            self.history_info = report

class CarbonScreen(Screen):
    username = StringProperty("")
    carbon_footprint = StringProperty("Enter details and calculate.")
    distance_travelled = NumericProperty(0.0)
    prev_lat = None
    prev_lon = None

    def on_enter(self):
        self.distance_travelled = 0.0
        self.prev_lat = None
        self.prev_lon = None
        # Start tracking location for distance
        if PLYER_AVAILABLE:
            try:
                gps.configure(on_location=self.on_gps_location)
                gps.start(1000, 1) # Update every 1s, 1m distance
            except Exception as e:
                self.carbon_footprint = "Could not start GPS for distance tracking."

    def on_leave(self):
        if PLYER_AVAILABLE:
            try: gps.stop()
            except Exception: pass

    def on_gps_location(self, **kwargs):
        lat, lon = kwargs.get('lat'), kwargs.get('lon')
        if lat is None or lon is None: return
        
        if self.prev_lat is not None and self.prev_lon is not None:
            self.distance_travelled += haversine(self.prev_lon, self.prev_lat, lon, lat)
        self.prev_lat, self.prev_lon = lat, lon
        
    def calculate_credits(self, bill_text, transport_mode):
        try:
            bill = float(bill_text)
        except ValueError:
            self.carbon_footprint = "Invalid electricity bill amount."
            return
            
        electricity_co2 = bill * 0.82 # kg CO2 per kWh in India (approx)

        mileage_map = {"Walking": 0, "Two-Wheeler": 40, "Four-Wheeler": 15}
        co2_per_liter_petrol = 2.3 # kg
        
        mileage = mileage_map.get(transport_mode, 0)
        petrol_used = self.distance_travelled / mileage if mileage else 0
        transport_co2 = petrol_used * co2_per_liter_petrol
        
        total_co2 = electricity_co2 + transport_co2
        self.carbon_footprint = (
            f"[b]Electricity CO₂:[/b] {electricity_co2:.2f} kg\n"
            f"[b]Transport CO₂:[/b] {transport_co2:.2f} kg (Dist: {self.distance_travelled:.2f} km)\n\n"
            f"[b]Total CO₂ Emissions:[/b] {total_co2:.2f} kg\n"
            f"[b]Estimated Carbon Credits:[/b] {total_co2 / 1000:.4f}"
        )


class JunkFoodScreen(Screen):
    username = StringProperty("")
    result = StringProperty("")

    def on_enter(self):
        self.update_log()

    def log_food(self, food_item, calories):
        if not food_item or not calories:
            self.result = "Please enter both food and calories."
            return
        try:
            cal = int(calories)
            with sqlite3.connect("health_tracker.db") as con:
                cur = con.cursor()
                cur.execute('INSERT INTO junkfood_log (username, food, calories, timestamp) VALUES (?, ?, ?, ?)',
                            (self.username, food_item, cal, datetime.datetime.now().isoformat()))
                con.commit()
            self.result = f"Logged: {food_item} ({cal} kcal)"
            self.ids.food_item.text = ""
            self.ids.calories.text = ""
            self.update_log()
        except ValueError:
            self.result = "Please enter a valid number for calories."

    def update_log(self):
        with sqlite3.connect("health_tracker.db") as con:
            cur = con.cursor()
            cur.execute('SELECT food, calories, timestamp FROM junkfood_log WHERE username=? ORDER BY timestamp DESC', (self.username,))
            data = cur.fetchall()

        if not data:
            self.ids.junk_food_log.text = "No junk food logged yet."
        else:
            log_text = "[b]Recent Entries:[/b]\n"
            for food, cal, ts in data[:7]:
                log_text += f"- {food}: {cal} kcal ({ts[:10]})\n"
            self.ids.junk_food_log.text = log_text

class WindowManager(ScreenManager):
    pass

class PollutionApp(App):
    def build(self):
        init_db()
        return Builder.load_file("main.kv")

if __name__ == "__main__":
    PollutionApp().run()
