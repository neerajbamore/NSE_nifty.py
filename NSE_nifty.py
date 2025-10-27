import requests
import pandas as pd
import time
import datetime
import os
import json
import traceback # Detailed error logging ke liye

# --- 1. Global Variables aur Configuration Load Karna ---
# Environment Variables Render se load honge
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
NSE_API_URL = os.getenv('NSE_API_URL')

# Configuration Variables load karna aur error handling
try:
    STRIKE_COUNT = int(os.getenv('STRIKE_COUNT', 6))
    FETCH_INTERVAL_SECONDS = int(os.getenv('FETCH_INTERVAL_SECONDS', 180))
except (ValueError, TypeError):
    print("WARNING: STRIKE_COUNT ya FETCH_INTERVAL_SECONDS galat format mein hain. Default values use kar raha hoon.")
    STRIKE_COUNT = 6
    FETCH_INTERVAL_SECONDS = 180

# Pichle 3-minute cycle ka data store karne ke liye global variables
LAST_OI_DATA = {} # Key: Strike-Type (e.g., 20000CE), Value: OI
LAST_FUT_OI = 0

# --- 2. Helper Functions ---

def send_telegram_message(message):
    """Telegram par alert message bhejta hai."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Telegram credentials set nahi hain. Alert nahi bheja jaa sakta.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }
    
    try:
        requests.post(url, data=payload, timeout=5) # 5 seconds ka timeout
    except requests.exceptions.RequestException as e:
        print(f"Telegram Alert Error: {e}")

def is_market_open():
    """Check karta hai ki samay 9:15 AM se 3:30 PM (Mon to Sat) ke beech hai ya nahi."""
    now = datetime.datetime.now()
    day_of_week = now.weekday() # Monday is 0, Saturday is 5, Sunday is 6
    current_time = now.time()

    # Monday (0) to Saturday (5)
    if day_of_week >= 6: 
        return False

    start_time = datetime.time(9, 15)
    end_time = datetime.time(15, 30)

    return start_time <= current_time <= end_time

def get_nearest_expiry(data):
    """NSE data mein se future ki sabse pehli expiry date nikalta hai."""
    expiry_dates_list = data.get('records', {}).get('expiryDates', [])
    today = datetime.date.today()
    future_dates = []

    for date_str in expiry_dates_list:
        try:
            # Date format: 'dd-MMM-yyyy' (e.g., '30-Oct-2025')
            date_obj = datetime.datetime.strptime(date_str, '%d-%b-%Y').date()
            if date_obj >= today:
                future_dates.append(date_obj)
        except ValueError:
            continue

    if future_dates:
        future_dates.sort()
        return future_dates[0].strftime('%d-%b-%Y')
    
    return None

def find_atm_strike(filtered_records, current_nifty_spot):
    """Nifty Spot price ke sabse nazdeek ATM strike price nikalta hai."""
    
    all_strikes = sorted(list(set(r['strikePrice'] for r in filtered_records if 'strikePrice' in r)))
            
    if not all_strikes:
        return None
        
    atm_strike = min(all_strikes, key=lambda strike: abs(strike - current_nifty_spot))
    return atm_strike

# --- 3. Mukhya Logic ---

def fetch_and_process_data(strike_count):
    global LAST_OI_DATA
    global LAST_FUT_OI
    
    headers = {
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.149 Safari/537.36',
        'accept-language': 'en,gu;q=0.9,hi;q=0.8',
        'accept-encoding': 'gzip, deflate, br'
    }
    
    current_oi_data = {} # Current cycle ka OI store karne ke liye
    alert_message = f"**Nifty 50 Update ({datetime.datetime.now().strftime('%H:%M:%S')})**\n"
    
    try:
        # --- A. Data Fetch karna ---
        response = requests.get(NSE_API_URL, headers=headers, timeout=10)
        response.raise_for_status() 
        data = response.json()
        
        # Spot Price
        current_nifty_spot = data.get('records', {}).get('underlyingValue', 0.0)
        
        # --- B. Last Expiry Date Find Karna ---
        nearest_expiry_date_str = get_nearest_expiry(data)
        
        if not nearest_expiry_date_str:
            alert_message += "⚠️ Nearest expiry date nahi mil saki. Skipping."
            send_telegram_message(alert_message)
            return

        alert_message += f"Spot: **{current_nifty_spot}** | Expiry: {nearest_expiry_date_str}\n"

        # --- C. Data Filter Karna (Expiry ke Anusaar) ---
        records = data.get('records', {}).get('data', [])
        
        filtered_records = [
            record for record in records 
            if record.get('expiryDate') == nearest_expiry_date_str
        ]

        # --- D. ATM aur Strike Filtering ---
        atm_strike = find_atm_strike(filtered_records, current_nifty_spot)
        
        if not atm_strike:
            alert_message += "⚠️ ATM Strike nahi mila. Skipping."
            send_telegram_message(alert_message)
            return
            
        alert_message += f"ATM Strike: **{atm_strike}**\n"
        
        # Strikes ki list banana: ATM aur uske aas paas (6 upar, 6 neeche)
        all_strikes = sorted(list(set(r['strikePrice'] for r in filtered_records)))
        try:
            atm_index = all_strikes.index(atm_strike)
        except ValueError:
             # Should not happen if find_atm_strike worked, but safe check
             return
             
        # 6 strikes upar aur 6 strikes neeche (total 13-15 strikes)
        start_index = max(0, atm_index - strike_count)
        end_index = min(len(all_strikes), atm_index + strike_count + 1)
        near_strikes = all_strikes[start_index:end_index]
        
        # --- E. Calculation (OI, COI, IV, Volume) ---
        
        table_data = []

        for record in filtered_records:
            if record.get('strikePrice') in near_strikes:
                strike = record['strikePrice']
                
                # Call side data
                ce = record.get('CE', {})
                ce_oi_key = f"{strike}CE"
                ce_oi = ce.get('openInterest', 0)
                ce_coi = ce_oi - LAST_OI_DATA.get(ce_oi_key, 0)
                current_oi_data[ce_oi_key] = ce_oi
                
                # Put side data
                pe = record.get('PE', {})
                pe_oi_key = f"{strike}PE"
                pe_oi = pe.get('openInterest', 0)
                pe_coi = pe_oi - LAST_OI_DATA.get(pe_oi_key, 0)
                current_oi_data[pe_oi_key] = pe_oi

                table_data.append({
                    'STRIKE': strike,
                    'CE_OI': ce_oi,
                    'CE_COI': ce_coi,
                    'CE_IV': ce.get('impliedVolatility', '-'),
                    'PE_OI': pe_oi,
                    'PE_COI': pe_coi,
                    'PE_IV': pe.get('impliedVolatility', '-'),
                    'VOLUME': ce.get('totalTradedVolume', 0) + pe.get('totalTradedVolume', 0)
                })

        # --- F. Future Data Calculation ---
        
        # Nifty Future data (API structure ke anusaar badal sakta hai)
        future_data = data.get('filtered', {}).get('futures', [])
        
        current_fut_oi = 0
        fut_volume = 0
        if future_data:
            current_fut_oi = future_data[0].get('openInterest', 0)
            fut_volume = future_data[0].get('totalTradedVolume', 0)
            # Future COI calculation
            COI_Future = current_fut_oi - LAST_FUT_OI
        else:
            COI_Future = 0

        # --- G. Alert Message Formatting ---
        
        alert_message += "--- Options Data ---\n"
        
        # Table ko format karna thoda mushkil hai Telegram Markdown mein, 
        # isliye hum ise list mein bhejte hain
        
        for row in table_data:
            style = "**" if row['STRIKE'] == atm_strike else ""
            alert_message += f"\n{style}STRIKE {row['STRIKE']}{style}\n"
            alert_message += f"CE | OI: {row['CE_OI']} | COI: {row['CE_COI']:+,.0f} | IV: {row['CE_IV']}%\n"
            alert_message += f"PE | OI: {row['PE_OI']} | COI: {row['PE_COI']:+,.0f} | IV: {row['PE_IV']}%\n"
            alert_message += f"Total Volume: {row['VOLUME']}\n"
            
        alert_message += "\n--- Nifty Futures Data ---\n"
        alert_message += f"Fut OI: {current_fut_oi}\n"
        alert_message += f"Fut COI: {COI_Future:+,.0f}\n"
        alert_message += f"Fut Volume: {fut_volume}\n"
        
        # --- H. Alert Bhej na aur Data Store karna ---
        send_telegram_message(alert_message)
        
        # Agli cycle ke liye data store karein
        LAST_OI_DATA.update(current_oi_data)
        LAST_FUT_OI = current_fut_oi
        
        print(f"Data successfully fetched, processed, and alert sent.")

    except requests.exceptions.RequestException as e:
        print(f"API Ya Network Error: {e}")
        send_telegram_message(f"🚨 Network Error: Nifty API down ya network issue. {e}")
    except Exception as e:
        print(f"Unhandled Processing Error: {e}")
        print(traceback.format_exc())
        send_telegram_message(f"❌ Critical Script Error: Code processing mein galti. Check logs. {e}")
        
# --- Main Loop ---
def main_loop():
    print("Script started. Checking environment variables...")
    
    # Crucial pre-check
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not NSE_API_URL:
        print("FATAL ERROR: Essential Environment Variables (Telegram/NSE_API) missing. Exiting early.")
        return # Script turant exit ho jaayegi agar secrets nahi mile

    print(f"Configuration loaded: STRIKE_COUNT={STRIKE_COUNT}, INTERVAL={FETCH_INTERVAL_SECONDS}s")
    
    while True:
        try:
            if is_market_open():
                print(f"Market is open. Fetching data at: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                fetch_and_process_data(strike_count=STRIKE_COUNT) 
                
                print(f"Waiting for {FETCH_INTERVAL_SECONDS} seconds...")
                time.sleep(FETCH_INTERVAL_SECONDS) 
            else:
                print(f"Market closed or weekend. Sleeping for 1 minute. Current Time: {datetime.datetime.now().strftime('%H:%M:%S')}")
                time.sleep(60) 
                
        except Exception as e:
            # Agar while loop mein koi unhandled error aaye
            print(f"CRITICAL ERROR IN MAIN LOOP: {e}")
            print(traceback.format_exc())
            # Crash ke baad turant run hone se bachne ke liye thodi der wait karein
            time.sleep(600) # 10 minutes wait karein


if __name__ == "__main__":
    main_loop()

