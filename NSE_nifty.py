import datetime
# ... baki imports

# Helper function to find the nearest future expiry date
def get_nearest_expiry(data):
    """
    NSE data mein se future ki sabse pehli expiry date nikalta hai.
    """
    expiry_dates_list = data.get('records', {}).get('expiryDates', [])
    today = datetime.date.today()
    future_dates = []

    for date_str in expiry_dates_list:
        try:
            # Date format 'dd-MMM-yyyy' hota hai (e.g., '30-Oct-2025')
            date_obj = datetime.datetime.strptime(date_str, '%d-%b-%Y').date()
            if date_obj >= today:
                future_dates.append(date_obj)
        except ValueError as e:
            # Agar date format galat ho to ignore karein
            print(f"Skipping invalid date format: {date_str}. Error: {e}")
            continue

    if future_dates:
        # Sort karke sabse choti (nearest) date nikalna
        future_dates.sort()
        return future_dates[0].strftime('%d-%b-%Y') # Wapas string format mein return karein
    
    return None # Agar koi future date na mile

# Mukhya (Main) Data Processing function update
def fetch_and_process_data(strike_count):
    global last_oi_data
    global LAST_FUT_OI
    
    # --- 1. Data Fetch karna ---
    # ... (Aapka API fetch code yahan hai)
    # ... response = requests.get(NSE_API_URL, headers=headers)
    # ... data = response.json()

    # --- 2. Last Expiry Date Find Karna ---
    nearest_expiry_date_str = get_nearest_expiry(data)
    
    if not nearest_expiry_date_str:
        print("Nearest expiry date nahi mil saki. Skipping this cycle.")
        return

    print(f"Nearest Expiry Found: {nearest_expiry_date_str}")

    # --- 3. Data Filter Karna ---
    # Ab Option Chain data ko sirf us 'nearest_expiry_date_str' ke liye filter karein.
    
    records = data.get('records', {}).get('data', [])
    filtered_records = []
    
    for record in records:
        # Check karein ki current record, humari nearest expiry date ka hai ya nahi.
        if record.get('expiryDate') == nearest_expiry_date_str:
            filtered_records.append(record)
    
    if not filtered_records:
        print(f"Nearest Expiry ({nearest_expiry_date_str}) ke liye koi records nahi mile.")
        return

    # Ab aapka saara aage ka COI aur strike filtering logic is 'filtered_records' list par chalega.
    # ... (Baki logic jahan aap ATM nikalenge aur 6 CE/6 PE filter karenge)
    
    # ...
