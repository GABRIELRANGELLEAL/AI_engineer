import os
from dotenv import load_dotenv

load_dotenv()

# eProc Configuration
EPROC_BASE_URL = os.getenv("EPROC_BASE_URL", "https://eproc.tjsp.jus.br")
EPROC_TIMEOUT_MS = int(os.getenv("EPROC_TIMEOUT_MS", "30000"))
EPROC_RETRY_ATTEMPTS = int(os.getenv("EPROC_RETRY_ATTEMPTS", "3"))

# Authentication
AUTH_METHOD = os.getenv("AUTH_METHOD", "username")  # "username" or "certificate"
EPROC_USERNAME = os.getenv("EPROC_USERNAME")
EPROC_PASSWORD = os.getenv("EPROC_PASSWORD")
CERTIFICATE_PATH = os.getenv("CERTIFICATE_PATH")
CERTIFICATE_PASSWORD = os.getenv("CERTIFICATE_PASSWORD")

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/legal_assistant_db")

# Scraper
HEADLESS_MODE = os.getenv("HEADLESS_MODE", "true").lower() == "true"
SAVE_SESSION_PATH = os.getenv("SAVE_SESSION_PATH", "./.playwright_session")
SESSION_COOKIE_DURATION_DAYS = int(os.getenv("SESSION_COOKIE_DURATION_DAYS", "30"))

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "scraper.log")
