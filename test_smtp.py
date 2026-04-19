import smtplib
import os
from dotenv import load_dotenv

load_dotenv(override=True)
user = os.getenv("SMTP_USER")
pwd = os.getenv("SMTP_PASSWORD")

print(f"Testing login for: {user}")
try:
    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(user, pwd)
    print("Login SUCCESSFUL!")
    server.quit()
except Exception as e:
    print(f"Login FAILED: {e}")
