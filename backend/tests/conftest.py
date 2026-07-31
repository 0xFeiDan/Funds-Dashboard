import base64, os
os.environ.setdefault("DATABASE_URL","sqlite+aiosqlite:///./test-dashboard.db")
os.environ.setdefault("BOOTSTRAP_PASSWORD","test-password")
os.environ.setdefault("SESSION_SECRET","test-secret")
os.environ.setdefault("APP_ENCRYPTION_KEY",base64.urlsafe_b64encode(b"x"*32).decode())
