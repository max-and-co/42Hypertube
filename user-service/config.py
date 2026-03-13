import os

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8080")

FT_CLIENT_ID     = os.getenv("FT_CLIENT_ID", "")
FT_CLIENT_SECRET = os.getenv("FT_CLIENT_SECRET", "")
FT_REDIRECT_URI  = os.getenv("FT_REDIRECT_URI", "http://localhost:8080/api/oauth/42/callback")

GITHUB_CLIENT_ID     = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
GITHUB_REDIRECT_URI  = os.getenv("GITHUB_REDIRECT_URI", "http://localhost:8080/api/oauth/github/callback")

SMTP_HOST     = os.getenv("SMTP_HOST", "")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM     = os.getenv("SMTP_FROM", "noreply@hypertube.com")
