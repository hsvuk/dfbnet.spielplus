import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

LOGIN_URL = "https://www.dfbnet.org/spielplus/login.do"

USERNAME = os.environ["DFBNET_USERNAME"]
PASSWORD = os.environ["DFBNET_PASSWORD"]
SPORTSTAETTE_NR = os.environ.get("DFBNET_SPORTSTAETTE_NR", "2100290091")

DB_PATH = ROOT_DIR / "data" / "spielplus.sqlite3"
LOG_PATH = ROOT_DIR / "logs" / "run.log"

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
NOTIFY_EMAIL_TO = os.environ.get("NOTIFY_EMAIL_TO", "")
