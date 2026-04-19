# create_dummy_db.py
import sqlite3

# Connect to the SQLite database (this will create the file if it doesn't exist)
conn = sqlite3.connect('portfolio.db')
cursor = conn.cursor()

# --- Create the holdings table ---
cursor.execute('''
CREATE TABLE IF NOT EXISTS holdings (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL UNIQUE,
    shares INTEGER NOT NULL,
    average_cost REAL NOT NULL
)
''')
print("Table 'holdings' created successfully.")

# --- Insert some sample data ---
# Using INSERT OR IGNORE to prevent errors if you run the script multiple times
holdings_data = [
    ('NVDA', 1500, 250.75),
    ('AAPL', 5000, 180.20),
    ('IBM', 2500, 155.45),
    ('TSLA', 1000, 220.90)
]

cursor.executemany('''
INSERT OR IGNORE INTO holdings (symbol, shares, average_cost) VALUES (?, ?, ?)
''', holdings_data)
print(f"{len(holdings_data)} sample holdings inserted.")

# --- Commit the changes and close the connection ---
conn.commit()
conn.close()
print("Database 'portfolio.db' is set up and ready.")