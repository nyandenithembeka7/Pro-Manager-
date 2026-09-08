#!/usr/bin/env python3
"""
Pro Manager - AI Business Manager
Run with: streamlit run bizbrain_app.py
"""

# ============================================================
# 1. IMPORTS
# ============================================================

import os
import re
import secrets
import sqlite3
import hashlib
import smtplib
import time
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import requests

try:
    import bcrypt
except ImportError:
    bcrypt = None

try:
    import stripe
except ImportError:
    stripe = None

try:
    import extra_streamlit_components as stx
except ImportError:
    stx = None

try:
    from supabase import create_client
except ImportError:
    create_client = None


# ============================================================
# 2. APP CONFIGURATION
# ============================================================

APP_NAME = "Pro Manager"
APP_URL = "https://pro-manager.streamlit.app"
TRIAL_DAYS = 30
MAGIC_LINK_HOURS = 24
MONTHLY_PRICE_DISPLAY = "R499 / month"
# SUPER ADMIN - Free forever access
SUPER_ADMINS = ["nyandenithembeka7@gmail.com", "your-other-email@example.com"]  # <-- ADD YOUR EMAIL HERE

st.set_page_config(
    page_title=APP_NAME,
    page_icon="logo.png",        # <-- custom favicon
    layout="wide",
    initial_sidebar_state="expanded",
)

# Show logo in the sidebar/header (optional)
st.logo("logo.png", icon_image="logo.png")


# ============================================================
# 3. SAFE SECRETS (No hardcoded keys!)
# ============================================================

def get_secret(name, default=None):
    try:
        value = st.secrets.get(name, None)
        if value is not None:
            return value
    except Exception:
        pass

    env_val = os.getenv(name)
    if env_val:
        return env_val

    return default


# Clean Supabase URL – remove www. and /rest/v1/ if present
def clean_supabase_url(raw_url):
    if not raw_url:
        return raw_url
    # Remove leading www.
    url = re.sub(r'^https?://(?:www\.)', 'https://', raw_url)
    # Remove trailing /rest/v1/ or /rest/v1
    url = re.sub(r'/rest/v1/?$', '', url)
    return url


SUPABASE_URL = clean_supabase_url(get_secret("SUPABASE_URL"))
SUPABASE_SECRET_KEY = get_secret("SUPABASE_SECRET_KEY")
EMAIL_SENDER = get_secret("EMAIL_SENDER")
EMAIL_PASSWORD = get_secret("EMAIL_PASSWORD")
STRIPE_PUBLISHABLE_KEY = get_secret("STRIPE_PUBLISHABLE_KEY")
STRIPE_SECRET_KEY = get_secret("STRIPE_SECRET_KEY")
MONTHLY_PRICE_ID = get_secret("MONTHLY_PRICE_ID")

if stripe is not None and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# Check if Supabase is enabled
SUPABASE_ENABLED = bool(
    create_client
    and SUPABASE_URL
    and SUPABASE_SECRET_KEY
    and "YOUR_PROJECT_ID" not in SUPABASE_URL
)

# ============================================================
# 4. DATABASE
# ============================================================

DB_FILE = "users.db"
SESSION_COOKIE_NAME = "pro_manager_session"
SESSION_DAYS = 30


@st.cache_resource
def get_supabase_client():
    if not SUPABASE_ENABLED:
        return None
    try:
        return create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
    except Exception as e:
        st.error(f"Supabase connection error: {e}")
        return None


SUPABASE = get_supabase_client()


def get_cookie_manager():
    """Return a CookieManager instance, stored in session_state to avoid widget caching."""
    if "cookie_manager" not in st.session_state:
        if stx is None:
            st.session_state.cookie_manager = None
        else:
            try:
                st.session_state.cookie_manager = stx.CookieManager()
            except Exception:
                st.session_state.cookie_manager = None
    return st.session_state.cookie_manager


COOKIE_MANAGER = get_cookie_manager()


def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def hash_session_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def init_local_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            email TEXT PRIMARY KEY,
            password TEXT,
            stripe_customer_id TEXT,
            subscription_status TEXT DEFAULT 'trialing',
            created_at TEXT,
            trial_end_date TEXT,
            login_token TEXT,
            token_expiry TEXT,
            pos_connection TEXT,
            pos_config TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS login_sessions (
            token_hash TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def init_db():
    init_local_db()


def database_mode_label():
    if SUPABASE_ENABLED:
        return "☁️ Persistent cloud memory"
    return "💻 Local prototype storage"


# ============================================================
# SUPABASE / SQLITE USER HELPERS
# ============================================================

def signup_user(email, password):
    email = email.strip().lower()
    if not valid_email(email):
        return False, "Please enter a valid email address."
    if len(password) < 8:
        return False, "Password must be at least 8 characters."
    try:
        hashed = hash_password(password)
    except Exception as exc:
        return False, str(exc)
    created_at = utc_now()
    trial_end = created_at + timedelta(days=TRIAL_DAYS)

    if SUPABASE_ENABLED:
        try:
            existing = SUPABASE.table("users").select("email").eq("email", email).limit(1).execute()
            if existing.data:
                return False, "An account with this email already exists."
            SUPABASE.table("users").insert({
                "email": email,
                "password": hashed,
                "subscription_status": "trialing",
                "created_at": datetime_to_string(created_at),
                "trial_end_date": datetime_to_string(trial_end),
            }).execute()
            return True, f"Account created! Your {TRIAL_DAYS}-day free trial starts now."
        except Exception as exc:
            return False, f"Could not create account: {exc}"

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (email, password, subscription_status, created_at, trial_end_date) VALUES (?, ?, ?, ?, ?)",
            (email, hashed, "trialing", datetime_to_string(created_at), datetime_to_string(trial_end))
        )
        conn.commit()
        return True, f"Account created! Your {TRIAL_DAYS}-day free trial starts now."
    except sqlite3.IntegrityError:
        return False, "An account with this email already exists."
    finally:
        conn.close()


def get_user(email):
    email = email.strip().lower()
    if SUPABASE_ENABLED:
        try:
            response = SUPABASE.table("users").select(
                "email,password,subscription_status,trial_end_date,stripe_customer_id,pos_connection,pos_config"
            ).eq("email", email).limit(1).execute()
            if response.data:
                return response.data[0]
            return None
        except Exception:
            return None
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT email, password, subscription_status, trial_end_date, stripe_customer_id, pos_connection, pos_config FROM users WHERE email = ?",
        (email,)
    )
    result = cursor.fetchone()
    conn.close()
    return result


def set_user_status(email, status):
    if SUPABASE_ENABLED:
        try:
            SUPABASE.table("users").update({"subscription_status": status}).eq("email", email.strip().lower()).execute()
            return
        except Exception:
            return
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET subscription_status = ? WHERE email = ?", (status, email.strip().lower()))
    conn.commit()
    conn.close()


def login_user(email, password):
    email = email.strip().lower()
    user = get_user(email)
    if not user:
        return False, None
    stored_hash = user["password"]
    if not stored_hash:
        return False, None
    if not verify_password(password, stored_hash):
        return False, None
    status = get_user_status(email)
    return True, status


def get_user_status(email):
    # SUPER ADMIN: Always active, never expires
    if email in SUPER_ADMINS:
        return "active"
    
    user = get_user(email)
    if not user:
        return "inactive"
    status = user["subscription_status"]
    trial_end = string_to_datetime(user["trial_end_date"])
    if status == "trialing" and trial_end is not None and utc_now() > trial_end:
        set_user_status(email, "inactive")
        return "inactive"
    return status

def get_trial_days_left(email):
    # SUPER ADMIN: No trial, unlimited access
    if email in SUPER_ADMINS:
        return 9999  # Big number = "never expires"
    
    user = get_user(email)
    if not user:
        return 0
    trial_end = string_to_datetime(user["trial_end_date"])
    if not trial_end:
        return 0
    remaining_seconds = (trial_end - utc_now()).total_seconds()
    if remaining_seconds <= 0:
        return 0
    return int(np.ceil(remaining_seconds / 86400))


def save_pos_connection(email, pos_type, config):
    email = email.strip().lower()
    if SUPABASE_ENABLED:
        try:
            SUPABASE.table("users").update({"pos_connection": pos_type, "pos_config": config}).eq("email", email).execute()
            return True
        except Exception:
            return False
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET pos_connection = ?, pos_config = ? WHERE email = ?", (pos_type, config, email))
    conn.commit()
    conn.close()
    return True


def get_pos_connection(email):
    user = get_user(email)
    if not user:
        return None, None
    return user.get("pos_connection"), user.get("pos_config")


def valid_email(email):
    return re.match(r"[^@]+@[^@]+\.[^@]+", email) is not None


# ============================================================
# PERSISTENT LOGIN SESSIONS
# ============================================================

def create_persistent_login(email):
    token = secrets.token_urlsafe(48)
    token_hash = hash_session_token(token)
    created_at = utc_now()
    expires_at = created_at + timedelta(days=SESSION_DAYS)
    if SUPABASE_ENABLED:
        try:
            SUPABASE.table("login_sessions").upsert({
                "token_hash": token_hash,
                "email": email.strip().lower(),
                "expires_at": datetime_to_string(expires_at),
                "created_at": datetime_to_string(created_at),
            }, on_conflict="token_hash").execute()
        except Exception:
            return False
    else:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO login_sessions (token_hash, email, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (token_hash, email.strip().lower(), datetime_to_string(expires_at), datetime_to_string(created_at))
        )
        conn.commit()
        conn.close()
    if COOKIE_MANAGER is None:
        return False
    try:
        COOKIE_MANAGER.set(SESSION_COOKIE_NAME, token, expires_at=expires_at, key="set_" + SESSION_COOKIE_NAME)
        return True
    except Exception:
        return False


def get_persistent_login():
    if COOKIE_MANAGER is None:
        return None
    try:
        token = COOKIE_MANAGER.get(SESSION_COOKIE_NAME)
    except Exception:
        return None
    if not token:
        return None
    token_hash = hash_session_token(token)
    if SUPABASE_ENABLED:
        try:
            response = SUPABASE.table("login_sessions").select("email,expires_at").eq("token_hash", token_hash).limit(1).execute()
            if not response.data:
                return None
            row = response.data[0]
            expiry = string_to_datetime(row["expires_at"])
            if not expiry or utc_now() >= expiry:
                delete_persistent_login()
                return None
            email = row["email"]
            if not get_user(email):
                delete_persistent_login()
                return None
            return email
        except Exception:
            return None
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT email, expires_at FROM login_sessions WHERE token_hash = ?", (token_hash,))
    result = cursor.fetchone()
    conn.close()
    if not result:
        return None
    expiry = string_to_datetime(result["expires_at"])
    if not expiry or utc_now() >= expiry:
        delete_persistent_login()
        return None
    return result["email"]


def delete_persistent_login():
    token = None
    if COOKIE_MANAGER is not None:
        try:
            token = COOKIE_MANAGER.get(SESSION_COOKIE_NAME)
        except Exception:
            token = None
    if token:
        token_hash = hash_session_token(token)
        if SUPABASE_ENABLED:
            try:
                SUPABASE.table("login_sessions").delete().eq("token_hash", token_hash).execute()
            except Exception:
                pass
        else:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM login_sessions WHERE token_hash = ?", (token_hash,))
            conn.commit()
            conn.close()
    if COOKIE_MANAGER is not None:
        try:
            COOKIE_MANAGER.delete(SESSION_COOKIE_NAME, key="set_" + SESSION_COOKIE_NAME)
        except Exception:
            pass


def migrate_local_users_if_available():
    if not SUPABASE_ENABLED:
        return
    if not os.path.exists(DB_FILE):
        return
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT email, password, stripe_customer_id, subscription_status, created_at, trial_end_date FROM users"
        )
        rows = cursor.fetchall()
        conn.close()
        for row in rows:
            email = row["email"]
            existing = SUPABASE.table("users").select("email").eq("email", email).limit(1).execute()
            if existing.data:
                continue
            SUPABASE.table("users").insert({
                "email": email,
                "password": row["password"],
                "stripe_customer_id": row["stripe_customer_id"],
                "subscription_status": row["subscription_status"],
                "created_at": row["created_at"],
                "trial_end_date": row["trial_end_date"],
            }).execute()
    except Exception:
        pass


# ============================================================
# BUSINESS MEMORY
# ============================================================

BUSINESS_HISTORY_COLUMNS = [
    "email", "product_name", "date", "sales", "current_stock",
    "selling_price", "cost_per_unit", "previous_cost_per_unit",
    "supplier_lead_time_days", "uploaded_at"
]


def _history_rows_from_dataframe(email, df):
    if df is None or df.empty:
        return []
    work = df.copy()
    if "date" not in work.columns:
        work["date"] = pd.Timestamp.today().normalize()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work["date"] = work["date"].fillna(pd.Timestamp.today().normalize())
    numeric_columns = ["sales", "current_stock", "selling_price", "cost_per_unit", "previous_cost_per_unit",
                       "supplier_lead_time_days"]
    for column in numeric_columns:
        if column not in work.columns:
            work[column] = 0.0
        work[column] = pd.to_numeric(work[column], errors="coerce").fillna(0.0)
    uploaded_at = datetime_to_string(utc_now())
    rows = []
    for _, row in work.iterrows():
        product = str(row["product_name"]).strip()
        if not product:
            continue
        rows.append({
            "email": email.strip().lower(),
            "product_name": product,
            "date": row["date"].date().isoformat(),
            "sales": float(row["sales"]),
            "current_stock": float(row["current_stock"]),
            "selling_price": float(row["selling_price"]),
            "cost_per_unit": float(row["cost_per_unit"]),
            "previous_cost_per_unit": float(row["previous_cost_per_unit"]),
            "supplier_lead_time_days": float(row["supplier_lead_time_days"]),
            "uploaded_at": uploaded_at,
        })
    return rows


def save_business_history(email, df):
    rows = _history_rows_from_dataframe(email, df)
    if not rows:
        return False, "There was no business history to save."
    if SUPABASE_ENABLED:
        try:
            SUPABASE.table("business_history").upsert(rows, on_conflict="email,product_name,date").execute()
            return True, f"Saved {len(rows)} business observation(s) to Business Memory."
        except Exception as exc:
            return False, f"Business Memory could not be saved: {exc}"
    return False, "Persistent Business Memory requires Supabase."


def save_single_sales_record(email, product_name, date, quantity_sold, cost_per_unit=None, selling_price=None,
                             current_stock=None):
    if not SUPABASE_ENABLED:
        return False, "Business Memory requires Supabase."
    row = {
        "email": email.strip().lower(),
        "product_name": product_name,
        "date": date,
        "sales": float(quantity_sold),
        "current_stock": float(current_stock) if current_stock is not None else 0,
        "selling_price": float(selling_price) if selling_price else 0,
        "cost_per_unit": float(cost_per_unit) if cost_per_unit else 0,
        "previous_cost_per_unit": float(cost_per_unit) if cost_per_unit else 0,
        "supplier_lead_time_days": 5,
        "uploaded_at": datetime_to_string(utc_now()),
    }
    try:
        SUPABASE.table("business_history").upsert(row, on_conflict="email,product_name,date").execute()
        return True, f"Saved sales for {product_name} on {date}."
    except Exception as e:
        return False, f"Error saving daily sales: {e}"


def load_business_history(email):
    if not SUPABASE_ENABLED:
        return pd.DataFrame()
    try:
        response = SUPABASE.table("business_history").select(
            "product_name,date,sales,current_stock,selling_price,cost_per_unit,previous_cost_per_unit,supplier_lead_time_days"
        ).eq("email", email.strip().lower()).order("date").execute()
        rows = response.data or []
        if not rows:
            return pd.DataFrame()
        history = pd.DataFrame(rows)
        history["date"] = pd.to_datetime(history["date"], errors="coerce")
        numeric_columns = ["sales", "current_stock", "selling_price", "cost_per_unit", "previous_cost_per_unit",
                           "supplier_lead_time_days"]
        for column in numeric_columns:
            history[column] = pd.to_numeric(history[column], errors="coerce").fillna(0.0)
        return prepare_data(
            history[["product_name", "current_stock", "selling_price", "cost_per_unit", "previous_cost_per_unit",
                     "supplier_lead_time_days", "date", "sales"]])
    except Exception:
        return pd.DataFrame()


def get_business_memory(email):
    return load_business_history(email)


def business_memory_count(email):
    if not SUPABASE_ENABLED:
        return 0
    try:
        response = SUPABASE.table("business_history").select("id", count="exact").eq("email", email.strip().lower()).execute()
        return int(response.count or 0)
    except Exception:
        return 0


def trend_summary(sales_history):
    values = np.asarray(sales_history, dtype=float)
    values = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
    values = np.clip(values, 0, None)
    if len(values) < 6:
        return {"label": "Building baseline", "change_pct": 0.0,
                "message": "Pro Manager needs more historical observations before it can confidently classify the trend."}
    window = min(30, len(values) // 2)
    previous = values[-2 * window:-window]
    recent = values[-window:]
    previous_mean = float(np.mean(previous))
    recent_mean = float(np.mean(recent))
    if previous_mean <= 0:
        change_pct = 100.0 if recent_mean > 0 else 0.0
    else:
        change_pct = (recent_mean - previous_mean) / previous_mean * 100
    if change_pct >= 25:
        label = "Rapidly increasing"
        message = f"Recent demand is about {change_pct:.1f}% higher than the previous comparison period."
    elif change_pct >= 8:
        label = "Increasing"
        message = f"Recent demand is about {change_pct:.1f}% higher than the previous comparison period."
    elif change_pct <= -25:
        label = "Rapidly decreasing"
        message = f"Recent demand is about {abs(change_pct):.1f}% lower than the previous comparison period."
    elif change_pct <= -8:
        label = "Decreasing"
        message = f"Recent demand is about {abs(change_pct):.1f}% lower than the previous comparison period."
    else:
        label = "Stable"
        message = f"Recent demand changed by {change_pct:+.1f}% versus the previous comparison period."
    return {"label": label, "change_pct": change_pct, "message": message}


def calculate_forecast(sales_history, forecast_days=14):
    values = np.asarray(sales_history, dtype=float)
    values = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
    values = np.clip(values, 0, None)
    if len(values) == 0:
        return 0.0
    window = min(len(values), 30)
    recent = values[-window:]
    recent_mean = float(np.mean(recent))
    if len(recent) < 3:
        return recent_mean
    x = np.arange(len(recent), dtype=float)
    try:
        slope, intercept = np.polyfit(x, recent, 1)
        future_x = np.arange(len(recent), len(recent) + max(forecast_days, 1))
        predictions = intercept + slope * future_x
        predictions = np.clip(predictions, 0, None)
        trend_forecast = float(np.mean(predictions))
        forecast = 0.60 * trend_forecast + 0.40 * recent_mean
        return max(0.0, float(forecast))
    except Exception:
        return recent_mean


def generate_memory_insights(df):
    insights = []
    if df is None or df.empty:
        return insights
    for product, group in df.groupby("product_name"):
        group = group.sort_values("date")
        history = group["sales"].astype(float).tolist()
        summary = trend_summary(history)
        forecast = calculate_forecast(history, 30)
        if summary["label"] in ("Rapidly increasing", "Increasing"):
            icon = "📈"
        elif summary["label"] in ("Rapidly decreasing", "Decreasing"):
            icon = "📉"
        else:
            icon = "➡️"
        insights.append({
            "product_name": product,
            "label": summary["label"],
            "change_pct": summary["change_pct"],
            "message": summary["message"],
            "forecast": forecast,
            "observations": len(history),
            "start_date": group["date"].min(),
            "end_date": group["date"].max(),
            "icon": icon,
        })
    return insights


def render_business_memory(email):
    history = get_business_memory(email)
    if history.empty:
        st.info(
            "🧠 Business Memory is ready, but it has no saved history yet. Upload your first business file and Pro Manager will save it.")
        return
    st.subheader("🧠 Business Memory")
    min_date = history["date"].min()
    max_date = history["date"].max()
    products = history["product_name"].nunique()
    col1, col2, col3 = st.columns(3)
    col1.metric("Historical observations", f"{len(history):,}")
    col2.metric("Products remembered", products)
    col3.metric("Memory period", f"{min_date:%d %b %Y} → {max_date:%d %b %Y}")
    st.caption(
        "Older uploaded periods remain in Business Memory. When you upload a new month, Pro Manager combines it with the history already saved for your business.")
    memory_insights = generate_memory_insights(history)
    if not memory_insights:
        return
    rows = []
    for item in memory_insights:
        rows.append({
            "Product": item["product_name"],
            "Trend": f"{item['icon']} {item['label']}",
            "Change vs previous period": f"{item['change_pct']:+.1f}%",
            "Next 30-day daily demand": round(item["forecast"], 2),
            "Observations": item["observations"],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.divider()
    for item in memory_insights:
        label = item["label"]
        if label in ("Rapidly decreasing", "Decreasing"):
            st.warning(
                f"📉 **{item['product_name']}: {label}** — {item['message']} Estimated next-30-day daily demand is {item['forecast']:.1f} units.")
        elif label in ("Rapidly increasing", "Increasing"):
            st.success(
                f"📈 **{item['product_name']}: {label}** — {item['message']} Estimated next-30-day daily demand is {item['forecast']:.1f} units.")
        else:
            st.info(
                f"➡️ **{item['product_name']}: Stable** — {item['message']} Estimated next-30-day daily demand is {item['forecast']:.1f} units.")


# ============================================================
# PASSWORD SECURITY
# ============================================================

def hash_password(password):
    if bcrypt is None:
        raise RuntimeError("bcrypt is not installed. Run: pip install bcrypt")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password, hashed):
    if bcrypt is None:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ============================================================
# DATE HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def datetime_to_string(dt):
    return dt.isoformat()


def string_to_datetime(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


# ============================================================
# MAGIC LOGIN
# ============================================================

def generate_login_token():
    return secrets.token_urlsafe(32)


def save_login_token(email):
    token = generate_login_token()
    expiry = utc_now() + timedelta(hours=MAGIC_LINK_HOURS)
    if SUPABASE_ENABLED:
        try:
            SUPABASE.table("users").update({"login_token": token, "token_expiry": datetime_to_string(expiry)}).eq("email",
                                                                                                                email.strip().lower()).execute()
            return token
        except Exception:
            return None
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET login_token = ?, token_expiry = ? WHERE email = ?",
                   (token, datetime_to_string(expiry), email.strip().lower()))
    conn.commit()
    conn.close()
    return token


def verify_login_token(token):
    if not token:
        return None
    if SUPABASE_ENABLED:
        try:
            response = SUPABASE.table("users").select("email,token_expiry").eq("login_token", token).limit(1).execute()
            if not response.data:
                return None
            row = response.data[0]
            email = row["email"]
            expiry = string_to_datetime(row["token_expiry"])
            if expiry and utc_now() < expiry:
                SUPABASE.table("users").update({"login_token": None, "token_expiry": None}).eq("email", email).execute()
                create_persistent_login(email)
                return email
            return None
        except Exception:
            return None
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT email, token_expiry FROM users WHERE login_token = ?", (token,))
    result = cursor.fetchone()
    if not result:
        conn.close()
        return None
    email = result["email"]
    expiry = string_to_datetime(result["token_expiry"])
    if expiry and utc_now() < expiry:
        cursor.execute("UPDATE users SET login_token = NULL, token_expiry = NULL WHERE email = ?", (email,))
        conn.commit()
        conn.close()
        create_persistent_login(email)
        return email
    conn.close()
    return None


def send_login_email(email, token):
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        return False, "Email settings are not configured. Add EMAIL_SENDER and EMAIL_PASSWORD to Streamlit secrets."
    magic_link = f"{APP_URL}/?login_token={token}"
    subject = f"🔐 Login to {APP_NAME}"
    body = f"""
    <html><body>
    <h2>Welcome to {APP_NAME}</h2>
    <p>You requested a secure login link.</p>
    <p><a href="{magic_link}"><strong>Log in to {APP_NAME}</strong></a></p>
    <p>This link expires in {MAGIC_LINK_HOURS} hours and can only be used once.</p>
    <hr><p>If you did not request this login link, you can safely ignore this email.</p>
    </body></html>
    """
    try:
        message = MIMEMultipart("alternative")
        message["From"] = EMAIL_SENDER
        message["To"] = email
        message["Subject"] = subject
        message.attach(MIMEText(body, "html"))
        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=20)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, email, message.as_string())
        server.quit()
        return True, "Login link sent."
    except Exception as exc:
        return False, f"Email error: {exc}"


# ============================================================
# STRIPE
# ============================================================

def stripe_is_configured():
    return bool(stripe and STRIPE_SECRET_KEY and MONTHLY_PRICE_ID)


def create_checkout_session(email):
    if not stripe_is_configured():
        st.error("Stripe is not configured yet. Add STRIPE_SECRET_KEY and MONTHLY_PRICE_ID to Streamlit secrets.")
        return None
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": MONTHLY_PRICE_ID, "quantity": 1}],
            customer_email=email,
            success_url=APP_URL + "/?payment=success",
            cancel_url=APP_URL + "/?payment=cancelled",
        )
        return session.url
    except Exception as exc:
        st.error(f"Stripe error: {exc}")
        return None


def create_portal_session(email):
    if not stripe_is_configured():
        return None
    user = get_user(email)
    if not user:
        return None
    customer_id = user["stripe_customer_id"]
    if not customer_id:
        return None
    try:
        session = stripe.billing_portal.Session.create(customer=customer_id, return_url=APP_URL)
        return session.url
    except Exception:
        return None


def update_subscription(email, status, customer_id=None):
    email = email.strip().lower()
    values = {"subscription_status": status}
    if customer_id:
        values["stripe_customer_id"] = customer_id
    if status == "active":
        values["trial_end_date"] = None
    if SUPABASE_ENABLED:
        try:
            SUPABASE.table("users").update(values).eq("email", email).execute()
        except Exception:
            pass
        return
    conn = get_connection()
    cursor = conn.cursor()
    if customer_id:
        cursor.execute("UPDATE users SET subscription_status = ?, stripe_customer_id = ? WHERE email = ?",
                       (status, customer_id, email))
    else:
        cursor.execute("UPDATE users SET subscription_status = ? WHERE email = ?", (status, email))
    if status == "active":
        cursor.execute("UPDATE users SET trial_end_date = NULL WHERE email = ?", (email,))
    conn.commit()
    conn.close()


# ============================================================
# DEMO DATA
# ============================================================

def generate_demo_data():
    rng = np.random.default_rng(42)
    products = [
        {"name": "Coffee Beans", "price": 12.50, "cost": 6.00, "lead_time": 5},
        {"name": "Green Tea", "price": 8.00, "cost": 3.50, "lead_time": 4},
        {"name": "Bottled Water", "price": 1.20, "cost": 0.60, "lead_time": 3},
        {"name": "Protein Bars", "price": 4.50, "cost": 2.00, "lead_time": 6},
        {"name": "Hand Sanitiser", "price": 5.00, "cost": 2.50, "lead_time": 7},
    ]
    rows = []
    dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=60, freq="D")
    for product in products:
        base_sales = rng.integers(5, 35)
        trend = rng.uniform(-0.20, 0.35)
        starting_stock = rng.integers(50, 300)
        current_stock = float(starting_stock)
        previous_cost = product["cost"] * rng.uniform(0.90, 1.05)
        for i, date in enumerate(dates):
            demand = base_sales + trend * i + rng.normal(0, max(base_sales * 0.15, 1))
            sales = max(0, int(round(demand)))
            current_stock = max(0, current_stock - sales)
            if current_stock < 20:
                current_stock += rng.integers(50, 150)
            rows.append({
                "date": date,
                "product_name": product["name"],
                "current_stock": int(round(current_stock)),
                "selling_price": round(product["price"], 2),
                "cost_per_unit": round(product["cost"], 2),
                "previous_cost_per_unit": round(previous_cost, 2),
                "supplier_lead_time_days": product["lead_time"],
                "sales": sales,
            })
    return pd.DataFrame(rows)


# ============================================================
# DATA CLEANING
# ============================================================

COLUMN_ALIASES = {
    "product_name": ["product_name", "product", "product name", "item", "item_name", "sku"],
    "current_stock": ["current_stock", "stock", "inventory", "inventory_level", "on_hand", "stock_level"],
    "selling_price": ["selling_price", "selling price", "sale_price", "sale price", "unit_price", "price"],
    "cost_per_unit": ["cost_per_unit", "cost per unit", "unit_cost", "unit cost", "cost", "purchase_price"],
    "previous_cost_per_unit": ["previous_cost_per_unit", "previous cost per unit", "previous_cost", "old_cost"],
    "supplier_lead_time_days": ["supplier_lead_time_days", "supplier lead time days", "lead_time_days", "lead_time",
                                "delivery_days", "supplier_lead_time"],
    "date": ["date", "order_date", "transaction_date", "sales_date", "day", "timestamp"],
    "sales": ["sales", "quantity_sold", "quantity sold", "units_sold", "units sold", "qty", "quantity", "demand"],
    "daily_sales": ["daily_sales", "daily sales", "sales_history", "sales history", "daily_demand", "daily demand"],
}


def clean_column_name(column):
    return str(column).strip().lower().replace(" ", "_").replace("-", "_").replace("/", "_")


def normalize_columns(df):
    if df is None or df.empty:
        raise ValueError("The uploaded file is empty.")
    work = df.copy()
    work.columns = [clean_column_name(c) for c in work.columns]
    rename_map = {}
    for target, aliases in COLUMN_ALIASES.items():
        aliases_cleaned = {clean_column_name(alias) for alias in aliases}
        for column in work.columns:
            if column in aliases_cleaned:
                if column != target:
                    if target not in work.columns:
                        rename_map[column] = target
                break
    work = work.rename(columns=rename_map)
    required = ["product_name", "current_stock"]
    missing = [c for c in required if c not in work.columns]
    if missing:
        raise ValueError(
            "Missing required columns: " + ", ".join(missing) + ".\n\nRequired fields:\n- product_name\n- current_stock\n- sales OR daily_sales")
    if "sales" not in work.columns and "daily_sales" not in work.columns:
        raise ValueError(
            "Missing sales data.\n\nYour file must contain either:\n- sales\nor\n- daily_sales")
    return work


def expand_daily_sales_history(df):
    if "daily_sales" not in df.columns or "sales" in df.columns:
        return df
    expanded_rows = []
    for _, row in df.iterrows():
        raw_sales = row["daily_sales"]
        if pd.isna(raw_sales):
            sales_values = []
        else:
            sales_values = [v.strip() for v in str(raw_sales).split(",") if v.strip() != ""]
        if not sales_values:
            sales_values = ["0"]
        for index, value in enumerate(sales_values):
            try:
                sales_value = float(value)
            except Exception:
                sales_value = 0.0
            new_row = row.copy()
            new_row["sales"] = max(0.0, sales_value)
            new_row["date"] = pd.Timestamp.today().normalize() - pd.Timedelta(days=(len(sales_values) - 1 - index))
            expanded_rows.append(new_row)
    if not expanded_rows:
        raise ValueError("No daily sales data could be read from the uploaded file.")
    expanded = pd.DataFrame(expanded_rows)
    expanded = expanded.drop(columns=["daily_sales"], errors="ignore")
    return expanded


MONTH_NAMES = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def detect_monthly_columns(df):
    cleaned = {clean_column_name(c): c for c in df.columns}
    found = []
    for month in MONTH_NAMES:
        if month in cleaned:
            found.append(cleaned[month])
    return found


def convert_monthly_data(df):
    month_columns = detect_monthly_columns(df)
    if not month_columns:
        return df
    work = df.copy()
    daily_sales = []
    for _, row in work.iterrows():
        values = []
        for month in month_columns:
            try:
                monthly_value = float(row[month])
            except Exception:
                monthly_value = 0
            daily_average = max(0, monthly_value / 30)
            values.extend([daily_average] * 30)
        daily_sales.append(sum(values))
    work["sales"] = daily_sales
    return work


def prepare_data(df):
    work = normalize_columns(df)
    work = expand_daily_sales_history(work)
    work["product_name"] = work["product_name"].astype(str).str.strip()
    work = work[work["product_name"].ne("")].copy()
    numeric_columns = ["current_stock", "selling_price", "cost_per_unit", "previous_cost_per_unit",
                       "supplier_lead_time_days", "sales"]
    for column in numeric_columns:
        if column in work.columns:
            work[column] = pd.to_numeric(work[column], errors="coerce")
    work["current_stock"] = work["current_stock"].fillna(0).clip(lower=0)
    work["sales"] = work["sales"].fillna(0).clip(lower=0)
    if "selling_price" not in work.columns:
        work["selling_price"] = 0.0
    work["selling_price"] = work["selling_price"].fillna(0).clip(lower=0)
    if "cost_per_unit" not in work.columns:
        work["cost_per_unit"] = 0.0
    work["cost_per_unit"] = work["cost_per_unit"].fillna(0).clip(lower=0)
    if "previous_cost_per_unit" not in work.columns:
        work["previous_cost_per_unit"] = work["cost_per_unit"]
    work["previous_cost_per_unit"] = work["previous_cost_per_unit"].fillna(work["cost_per_unit"]).clip(lower=0)
    if "supplier_lead_time_days" not in work.columns:
        work["supplier_lead_time_days"] = 5
    work["supplier_lead_time_days"] = pd.to_numeric(work["supplier_lead_time_days"], errors="coerce").fillna(5).clip(0, 365)
    if "date" in work.columns:
        work["date"] = pd.to_datetime(work["date"], errors="coerce")
    else:
        work["date"] = pd.NaT
    work = work.sort_values(["product_name", "date"], na_position="last")
    return work.reset_index(drop=True)


# ============================================================
# INVENTORY ANALYSIS
# ============================================================

def process_data(df):
    work = df.copy()
    results = []
    grouped = work.groupby("product_name", sort=True)
    for product, group in grouped:
        group = group.copy().sort_values("date")
        sales_history = group["sales"].astype(float).tolist()
        current_stock = float(group["current_stock"].iloc[-1])
        selling_price = float(group["selling_price"].iloc[-1])
        cost_per_unit = float(group["cost_per_unit"].iloc[-1])
        previous_cost = float(group["previous_cost_per_unit"].iloc[-1])
        lead_time = float(group["supplier_lead_time_days"].iloc[-1])
        avg_daily_demand = calculate_forecast(sales_history, 14)
        recent_sales = np.asarray(sales_history[-30:], dtype=float)
        if len(recent_sales) > 1:
            demand_std = float(np.std(recent_sales, ddof=1))
        else:
            demand_std = 0.0
        days_of_stock = current_stock / avg_daily_demand if avg_daily_demand > 0 else np.inf
        safety_stock = 1.65 * demand_std * np.sqrt(max(lead_time, 1))
        reorder_point = avg_daily_demand * lead_time + safety_stock
        target_stock = avg_daily_demand * (lead_time + 14) + safety_stock
        recommended_order = max(0, int(np.ceil(target_stock - current_stock)))
        stock_value = current_stock * cost_per_unit
        profit_margin = ((selling_price - cost_per_unit) / selling_price * 100) if selling_price > 0 else 0.0
        price_hike_pct = ((cost_per_unit - previous_cost) / previous_cost * 100) if previous_cost > 0 else 0.0
        recent_10 = sales_history[-10:]
        is_dead = len(recent_10) >= 10 and all(v == 0 for v in recent_10)
        if len(sales_history) >= 3:
            try:
                demand_trend = float(np.polyfit(np.arange(len(sales_history)), sales_history, 1)[0])
            except Exception:
                demand_trend = 0.0
        else:
            demand_trend = 0.0
        if current_stock <= reorder_point:
            priority = "HIGH"
            reason = "Stock is at or below the estimated reorder point."
        elif np.isfinite(days_of_stock) and days_of_stock <= lead_time:
            priority = "HIGH"
            reason = "Current stock may not cover supplier lead time."
        elif np.isfinite(days_of_stock) and days_of_stock <= lead_time + 3:
            priority = "MEDIUM"
            reason = "Inventory cover is getting low."
        elif np.isfinite(days_of_stock) and days_of_stock > 90:
            priority = "MEDIUM"
            reason = "Large amount of inventory may be tied up."
        else:
            priority = "LOW"
            reason = "No immediate inventory risk detected."
        results.append({
            "product_name": product,
            "current_stock": current_stock,
            "avg_daily_demand": avg_daily_demand,
            "demand_trend": demand_trend,
            "days_of_stock": days_of_stock,
            "supplier_lead_time_days": lead_time,
            "reorder_point": reorder_point,
            "recommended_order": recommended_order,
            "stock_value": stock_value,
            "selling_price": selling_price,
            "cost_per_unit": cost_per_unit,
            "previous_cost_per_unit": previous_cost,
            "profit_margin": profit_margin,
            "price_hike_pct": price_hike_pct,
            "price_hike": price_hike_pct > 3,
            "is_dead": is_dead,
            "priority": priority,
            "reason": reason,
        })
    return pd.DataFrame(results)


def generate_alerts(df):
    alerts = []
    for _, row in df.iterrows():
        product = row["product_name"]
        if row["current_stock"] <= row["reorder_point"]:
            alerts.append(
                {"priority": "🔴 HIGH", "title": f"{product} - Low Stock",
                 "description": f"Approximately {row['days_of_stock']:.1f} days of stock remain.",
                 "impact": f"Recommended order: {int(row['recommended_order'])} units."})
        if row["days_of_stock"] != np.inf and row["days_of_stock"] > 90:
            alerts.append({"priority": "🟡 MEDIUM", "title": f"{product} - Overstocked",
                           "description": f"Approximately {row['days_of_stock']:.0f} days of stock.",
                           "impact": f"R{row['stock_value']:,.2f} may be tied up."})
        if row["demand_trend"] < -0.5:
            alerts.append({"priority": "🟡 MEDIUM", "title": f"{product} - Demand Declining",
                           "description": f"Estimated trend: {row['demand_trend']:.2f} units/day.",
                           "impact": "Future revenue may be at risk."})
        if row["price_hike"]:
            alerts.append({"priority": "🔴 HIGH", "title": f"{product} - Supplier Cost Increase",
                           "description": f"Unit cost increased {row['price_hike_pct']:.1f}%.",
                           "impact": "Review supplier pricing and product margins."})
        if row["is_dead"]:
            alerts.append({"priority": "🔴 HIGH", "title": f"{product} - Dead Stock",
                           "description": "No sales detected in the recent history.",
                           "impact": f"R{row['stock_value']:,.2f} may be tied up."})
    return alerts


def generate_business_insights(df):
    insights = []
    if df.empty:
        return insights
    total_stock_value = df["stock_value"].sum()
    dead_stock_value = df.loc[df["is_dead"], "stock_value"].sum()
    high_priority = (df["priority"] == "HIGH").sum()
    price_hikes = (df["price_hike"]).sum()
    declining = (df["demand_trend"] < -0.5).sum()
    if high_priority > 0:
        insights.append(
            {"type": "risk", "title": "Immediate inventory risk", "text": f"{high_priority} product(s) need urgent inventory attention."})
    if dead_stock_value > 0:
        percentage = (dead_stock_value / total_stock_value * 100) if total_stock_value > 0 else 0
        insights.append({"type": "money", "title": "Capital tied up in dead stock",
                         "text": f"Approximately R{dead_stock_value:,.2f} ({percentage:.1f}% of inventory value) is associated with non-moving products."})
    if price_hikes > 0:
        insights.append({"type": "supplier", "title": "Supplier costs changed",
                         "text": f"{price_hikes} product(s) show a supplier cost increase greater than 3%."})
    if declining > 0:
        insights.append(
            {"type": "sales", "title": "Demand is declining", "text": f"{declining} product(s) show a negative demand trend."})
    best_margin = df.loc[df["profit_margin"].idxmax()]
    insights.append({"type": "opportunity", "title": "Highest-margin product",
                     "text": f"{best_margin['product_name']} currently has the highest estimated gross margin at {best_margin['profit_margin']:.1f}%."})
    return insights


def run_order_audit(sales_df, orders_df):
    required_sales = {"product_name", "quantity_sold", "date"}
    required_orders = {"product_name", "quantity_ordered", "cost_per_unit", "date"}
    missing_sales = required_sales - set(sales_df.columns)
    missing_orders = required_orders - set(orders_df.columns)
    if missing_sales:
        raise ValueError("Sales file is missing: " + ", ".join(missing_sales))
    if missing_orders:
        raise ValueError("Orders file is missing: " + ", ".join(missing_orders))
    sales_df = sales_df.copy()
    orders_df = orders_df.copy()
    sales_df["quantity_sold"] = pd.to_numeric(sales_df["quantity_sold"], errors="coerce").fillna(0)
    orders_df["quantity_ordered"] = pd.to_numeric(orders_df["quantity_ordered"], errors="coerce").fillna(0)
    orders_df["cost_per_unit"] = pd.to_numeric(orders_df["cost_per_unit"], errors="coerce").fillna(0)
    total_sold = sales_df.groupby("product_name")["quantity_sold"].sum().reset_index()
    total_ordered = orders_df.groupby("product_name")["quantity_ordered"].sum().reset_index()
    costs = orders_df.groupby("product_name")["cost_per_unit"].mean().reset_index()
    comparison = pd.merge(total_sold, total_ordered, on="product_name", how="outer")
    comparison = pd.merge(comparison, costs, on="product_name", how="left")
    comparison = comparison.fillna(0)
    comparison["planning_quantity"] = comparison["quantity_sold"] * 1.15
    comparison["over_ordered"] = (comparison["quantity_ordered"] - comparison["planning_quantity"]).clip(lower=0)
    comparison["under_ordered"] = (comparison["planning_quantity"] - comparison["quantity_ordered"]).clip(lower=0)
    comparison["waste_cost"] = comparison["over_ordered"] * comparison["cost_per_unit"]
    comparison["estimated_lost_sales_value"] = comparison["under_ordered"] * comparison["cost_per_unit"]
    return comparison


# ============================================================
# POS / CASH REGISTER INTEGRATIONS
# ============================================================

def fetch_yoco_sales(secret_key, date_from=None, date_to=None):
    if not secret_key:
        return None, "Yoco secret key is required."

    if date_from is None:
        date_from = (datetime.now() - timedelta(days=1)).date().isoformat()
    if date_to is None:
        date_to = datetime.now().date().isoformat()

    url = "https://api.yoco.com/v1/payments"

    headers = {
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": "application/json",
    }

    from_ts = int(datetime.fromisoformat(date_from).timestamp() * 1000)
    to_ts = int(datetime.fromisoformat(date_to).timestamp() * 1000)

    params = {
        "created_after": from_ts,
        "created_before": to_ts,
        "limit": 100,
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        payments = data.get("data", []) or data.get("payments", []) or data

        if not payments:
            return [], "No payments found in the selected date range."

        sales_by_product = {}

        for payment in payments:
            if payment.get("status") not in ["successful", "completed", "paid"]:
                continue

            items = payment.get("items", [])

            if not items:
                metadata = payment.get("metadata", {})
                product_name = metadata.get("product_name") or metadata.get("item_name") or "General Sale"
                quantity = int(metadata.get("quantity", 1))
                sales_by_product[product_name] = sales_by_product.get(product_name, 0) + quantity
                continue

            for item in items:
                product_name = item.get("name") or item.get("description") or "Unnamed Product"
                quantity = int(item.get("quantity", 1))
                sales_by_product[product_name] = sales_by_product.get(product_name, 0) + quantity

        result = []
        for product, qty in sales_by_product.items():
            if qty > 0:
                result.append({"product_name": product, "quantity_sold": qty, "date": date_to})

        return result, f"Fetched {len(result)} product sales from Yoco."

    except requests.exceptions.RequestException as e:
        return None, f"Yoco API error: {e}"
    except Exception as e:
        return None, f"Unexpected error: {e}"


def render_yoco_connection():
    st.subheader("🇿🇦 Yoco POS Connection")
    st.markdown("""
    **Connect your Yoco account** to automatically fetch daily sales.
    1. Go to the [Yoco Developer Dashboard](https://developer.yoco.com/)
    2. Create a new app to get your **Secret Key**
    3. Paste the Secret Key below
    """)
    secret_key = st.text_input("Yoco Secret Key", type="password", placeholder="sk_live_... or sk_test_...")
    col1, col2 = st.columns(2)
    with col1:
        date_from = st.date_input("From Date", value=datetime.now().date() - timedelta(days=1))
    with col2:
        date_to = st.date_input("To Date", value=datetime.now().date())
    if st.button("🔗 Pull Sales from Yoco", use_container_width=True):
        if not secret_key:
            st.error("Please enter your Yoco Secret Key.")
        else:
            with st.spinner("Fetching sales from Yoco..."):
                result, message = fetch_yoco_sales(secret_key, date_from.isoformat(), date_to.isoformat())
                if result is None:
                    st.error(f"❌ {message}")
                elif not result:
                    st.info("✅ No sales found for the selected period.")
                else:
                    email = st.session_state['user_email']
                    success_count = 0
                    for sale in result:
                        product = sale["product_name"]
                        qty = sale["quantity_sold"]
                        date = sale["date"]
                        success, msg = save_single_sales_record(email, product, date, qty)
                        if success:
                            success_count += 1
                    st.success(f"✅ Pulled {len(result)} product sales from Yoco. Saved {success_count} to Business Memory.")
                    st.dataframe(pd.DataFrame(result), use_container_width=True, hide_index=True)
                    save_pos_connection(email, "yoco", {"secret_key": "********"})
                    st.info("Yoco connection saved. Future pulls will use this key.")


def pos_connection_ui():
    st.subheader("🔌 Cash Register / POS Connection")
    st.caption(
        "Connect your cash register or POS system to automatically import daily sales. This keeps your Business Memory always up to date without manual uploads.")
    email = st.session_state['user_email']
    pos_connection, pos_config = get_pos_connection(email)
    if pos_connection:
        st.success(f"✅ Currently connected to: **{pos_connection.upper()}**")
    pos_type = st.radio(
        "Select your POS system:",
        [
            "🇿🇦 Yoco (South Africa)",
            "📝 Manual Daily Entry (type it in)",
            "📁 Auto-Import CSV from folder",
            "🛍️ Shopify POS",
            "🏪 Custom API (enter URL)"
        ],
        index=0,
        key="pos_selector"
    )
    if "Yoco" in pos_type:
        render_yoco_connection()
    elif "Manual Daily Entry" in pos_type:
        render_manual_sales_entry()
    elif "Auto-Import CSV" in pos_type:
        render_csv_auto_import()
    elif "Shopify POS" in pos_type:
        render_shopify_connection()
    elif "Custom API" in pos_type:
        render_custom_api_connection()
    st.divider()
    if SUPABASE_ENABLED:
        try:
            response = SUPABASE.table("business_history").select("date,product_name,sales,uploaded_at").eq("email",
                                                                                                           email).order(
                "uploaded_at", desc=True).limit(10).execute()
            if response.data:
                st.subheader("📋 Recent Auto-Imported Sales")
                recent_df = pd.DataFrame(response.data)
                recent_df["date"] = pd.to_datetime(recent_df["date"])
                st.dataframe(recent_df, use_container_width=True, hide_index=True)
            else:
                st.info("No sales have been auto-imported yet. Connect your POS system above.")
        except Exception:
            pass


def render_manual_sales_entry():
    st.caption("Enter today's sales manually if your cash register doesn't have an API.")
    col1, col2 = st.columns(2)
    with col1:
        product_name = st.text_input("Product Name", placeholder="e.g., Coffee Beans")
        quantity_sold = st.number_input("Quantity Sold Today", min_value=0, step=1)
    with col2:
        date = st.date_input("Date", value=datetime.now().date())
        selling_price = st.number_input("Selling Price (per unit)", min_value=0.0, step=0.50, format="%.2f")
        cost_per_unit = st.number_input("Cost Per Unit (optional)", min_value=0.0, step=0.50, format="%.2f")
    if st.button("✅ Save Today's Sales to Memory", use_container_width=True):
        if not product_name or quantity_sold <= 0:
            st.error("Please enter a product name and quantity sold.")
        else:
            email = st.session_state['user_email']
            success, message = save_single_sales_record(email, product_name, date.isoformat(), quantity_sold,
                                                        cost_per_unit, selling_price)
            if success:
                st.success(f"✅ {message}")
            else:
                st.error(f"❌ {message}")


def render_csv_auto_import():
    st.caption("Drop a CSV file in your Google Drive or local folder, and Pro Manager will import it automatically.")
    uploaded = st.file_uploader("Upload today's sales CSV (or drop it here)", type=["csv"], key="pos_csv_upload")
    if uploaded:
        try:
            df = pd.read_csv(uploaded)
            if 'product_name' not in df.columns or 'quantity_sold' not in df.columns:
                st.error("CSV must have 'product_name' and 'quantity_sold' columns.")
            else:
                email = st.session_state['user_email']
                success_count = 0
                for _, row in df.iterrows():
                    product = row['product_name']
                    qty = row['quantity_sold']
                    date_str = row.get('date', datetime.now().date().isoformat())
                    success, msg = save_single_sales_record(email, product, date_str, qty)
                    if success:
                        success_count += 1
                st.success(f"✅ Imported {success_count} sales records to Business Memory!")
        except Exception as e:
            st.error(f"Error reading CSV: {e}")


def render_shopify_connection():
    st.caption("Connect your Shopify store to automatically import daily sales.")
    store_name = st.text_input("Shopify Store Name", placeholder="my-store")
    access_token = st.text_input("Access Token", type="password", placeholder="shpat_...")
    if st.button("🔗 Connect Shopify POS"):
        if store_name and access_token:
            email = st.session_state['user_email']
            if save_pos_connection(email, "shopify", {"store_name": store_name}):
                st.success("✅ Shopify connection saved! Daily sales will auto-import.")
            else:
                st.error("❌ Could not save connection.")
        else:
            st.warning("Please enter both your store name and access token.")


def render_custom_api_connection():
    st.caption("Enter a custom API endpoint that returns daily sales in JSON format.")
    api_url = st.text_input("API URL", placeholder="https://your-pos.com/api/daily-sales")
    api_key = st.text_input("API Key", type="password")
    if st.button("🔗 Connect Custom API"):
        if api_url:
            try:
                headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                response = requests.get(api_url, headers=headers, timeout=5)
                if response.status_code == 200:
                    st.success("✅ API connection successful!")
                    st.info("Daily sales will now be automatically imported.")
                else:
                    st.error(f"API returned status code: {response.status_code}")
            except Exception as e:
                st.error(f"Error connecting to API: {e}")
        else:
            st.warning("Please enter the API URL.")


# ============================================================
# AUTHENTICATION PAGE
# ============================================================

def auth_page():
    st.title(APP_NAME)
    st.caption("AI-powered business intelligence.")
    st.markdown("""
        ### Turn your business data into decisions.
        Pro Manager helps identify:
        - 📦 Inventory risks
        - 💰 Money leaks
        - 📈 Demand changes
        - 🧊 Dead stock
        - 🏭 Supplier cost increases
        - 🚨 Business problems that need attention
    """)
    st.divider()
    choice = st.radio("Account", ["Login", "Sign Up"], horizontal=True)
    email = st.text_input("Email address", placeholder="you@example.com")
    password = st.text_input("Password", type="password")
    if choice == "Sign Up":
        if st.button("🚀 Start 30-Day Free Trial", use_container_width=True):
            if not valid_email(email):
                st.error("Please enter a valid email.")
            elif len(password) < 8:
                st.error("Password must be at least 8 characters.")
            else:
                success, message = signup_user(email, password)
                if success:
                    st.success(message)
                    st.info("Your account has been created. You can now log in.")
                else:
                    st.error(message)
    else:
        if st.button("🔐 Log In", use_container_width=True):
            success, status = login_user(email, password)
            if success:
                st.session_state["logged_in"] = True
                st.session_state["user_email"] = email.strip().lower()
                st.session_state["user_status"] = status
                create_persistent_login(email.strip().lower())
                st.rerun()
            else:
                st.error("Invalid email or password.")
        st.divider()
        st.caption("Forgot your password? Use a secure login link instead.")
        if st.button("📧 Email Me a Login Link", use_container_width=True):
            clean_email = email.strip().lower()
            if not valid_email(clean_email):
                st.error("Please enter a valid email address.")
            else:
                user = get_user(clean_email)
                if not user:
                    st.info("If an account exists for that email, a login link will be sent.")
                else:
                    token = save_login_token(clean_email)
                    success, message = send_login_email(clean_email, token)
                    if success:
                        st.success("Login link sent. Check your inbox.")
                    else:
                        st.error(message)
    st.divider()
    st.caption("30-day free trial. No credit card required.")


# ============================================================
# DATA SOURCE LOADER
# ============================================================

def load_uploaded_file(uploaded_file):
    if uploaded_file is None:
        return None
    filename = uploaded_file.name.lower()
    if filename.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        return pd.read_excel(uploaded_file, engine="openpyxl")
    raise ValueError("Unsupported file type.")


def data_source_sidebar(email):
    with st.sidebar:
        st.header("🔌 Data Source")
        memory_count = business_memory_count(email)
        if memory_count > 0:
            default_index = 0
        else:
            default_index = 1
        source = st.radio(
            "Choose your data source:",
            ["🧠 My Business Memory", "📊 Demo Business", "📂 Upload / Update Data"],
            index=default_index,
        )
        st.caption(database_mode_label())
        st.divider()
        if source == "🧠 My Business Memory":
            memory = get_business_memory(email)
            if memory.empty:
                st.info("No saved business history yet. Use Upload / Update Data to add your first period.")
                return generate_demo_data(), "Demo Business - No Saved History"
            st.success(f"🧠 {len(memory):,} saved observation(s)")
            return memory, "Business Memory"
        if source == "📊 Demo Business":
            st.success("Demo data is active.")
            return generate_demo_data(), "Demo Business"
        uploaded = st.file_uploader("Upload your business data", type=["csv", "xlsx", "xls"])
        st.caption(
            "Tip: upload each new month/period. Older periods already saved in Business Memory do not need to be uploaded again.")
        if uploaded is None:
            if memory_count > 0:
                memory = get_business_memory(email)
                st.info("Your saved Business Memory will remain available. Upload a new file when you have new data.")
                return memory, "Business Memory"
            st.info("Upload a CSV or Excel file to analyse and remember your business.")
            return generate_demo_data(), "Demo Business - Waiting for Upload"
        try:
            raw = load_uploaded_file(uploaded)
            monthly_columns = detect_monthly_columns(raw)
            if monthly_columns:
                st.info("Monthly sales columns detected. They will be converted into a sales estimate for analysis.")
                raw = convert_monthly_data(raw)
            cleaned = prepare_data(raw)
            saved, save_message = save_business_history(email, cleaned)
            if saved:
                st.success(f"Loaded {uploaded.name} and saved it to Business Memory.")
                st.caption(save_message)
                memory = get_business_memory(email)
                if not memory.empty:
                    return memory, "Business Memory + New Upload"
            else:
                st.warning(f"Loaded {uploaded.name}, but it was not saved to persistent memory. {save_message}")
            return cleaned, uploaded.name
        except Exception as exc:
            st.error(f"Could not process file: {exc}")
            st.info("Using demo data so the dashboard can continue running.")
            return generate_demo_data(), "Demo Business - Upload Error"


# ============================================================
# MAIN DASHBOARD
# ============================================================

def main_dashboard():
    email = st.session_state["user_email"]
    status = get_user_status(email)
    trial_days = get_trial_days_left(email)

    st.title(APP_NAME)
    st.caption("Your AI-powered business manager.")

    df, source_label = data_source_sidebar(email)

    with st.sidebar:
        st.divider()
        st.caption(f"📊 Data source: {source_label}")

    col_status, col_logout = st.columns([4, 1])
    with col_status:
        if status == "active":
            st.success(f"✅ Active subscription · {email}")
        elif status == "trialing":
            st.warning(f"🔓 Free trial · {trial_days} day(s) remaining · {email}")
        else:
            st.error(f"🚫 Subscription inactive · {email}")
    with col_logout:
        if st.button("🚪 Logout"):
            delete_persistent_login()
            st.session_state["logged_in"] = False
            st.session_state.pop("user_email", None)
            st.session_state.pop("user_status", None)
            st.rerun()

    if status == "inactive":
        st.divider()
        st.error("Your free trial has expired or your subscription is inactive.")
        st.markdown(f"""
            ### Continue using {APP_NAME}
            **Monthly plan:** {MONTHLY_PRICE_DISPLAY}
            ✓ Inventory intelligence  
            ✓ Money leak detection  
            ✓ Business insights  
            ✓ Demand analysis  
            ✓ Priority support
        """)
        if st.button("💳 Subscribe with Stripe", use_container_width=True):
            checkout_url = create_checkout_session(email)
            if checkout_url:
                st.markdown(f"[Continue to secure Stripe checkout]({checkout_url})")
        st.stop()

    if status == "trialing":
        st.info(f"🎉 You're using your free trial. {trial_days} day(s) remaining.")

    try:
        processed = process_data(df)
    except Exception as exc:
        st.error(f"Could not analyse the data: {exc}")
        st.stop()

    alerts = generate_alerts(processed)
    insights = generate_business_insights(processed)

    st.divider()
    total_inventory_value = processed["stock_value"].sum()
    dead_stock_value = processed.loc[processed["is_dead"], "stock_value"].sum()
    high_alerts = len([a for a in alerts if "HIGH" in a["priority"]])
    avg_margin = processed["profit_margin"].mean() if not processed.empty else 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("💰 Inventory Value", f"R{total_inventory_value:,.2f}")
    col2.metric("🚨 High-Priority Alerts", high_alerts)
    col3.metric("🧊 Dead Stock", f"R{dead_stock_value:,.2f}")
    col4.metric("📈 Average Margin", f"{avg_margin:.1f}%")

    (overview_tab, memory_tab, alerts_tab, inventory_tab, forecast_tab, pos_tab, pitch_tab) = st.tabs(
        ["🧠 Business Overview", "🧠 Business Memory", "🚨 Alerts", "📦 Inventory", "📈 Forecast", "🔌 POS / Cash Register",
         "💡 Pitch Mode"]
    )

    with overview_tab:
        st.subheader("🧠 What should you know today?")
        if not insights:
            st.success("No major business insights detected.")
        else:
            for insight in insights:
                if insight["type"] == "risk":
                    st.error(f"🔴 **{insight['title']}**\n\n{insight['text']}")
                elif insight["type"] == "money":
                    st.warning(f"💰 **{insight['title']}**\n\n{insight['text']}")
                elif insight["type"] == "supplier":
                    st.warning(f"🏭 **{insight['title']}**\n\n{insight['text']}")
                elif insight["type"] == "sales":
                    st.warning(f"📉 **{insight['title']}**\n\n{insight['text']}")
                else:
                    st.success(f"🟢 **{insight['title']}**\n\n{insight['text']}")
        st.divider()
        st.subheader("🎯 Recommended actions")
        high_priority_rows = processed[processed["priority"] == "HIGH"]
        if high_priority_rows.empty:
            st.success("No urgent inventory action is required.")
        else:
            for _, row in high_priority_rows.head(5).iterrows():
                st.markdown(f"""
                    **{row['product_name']}**
                    Current stock: **{int(row['current_stock'])}**
                    Estimated daily demand: **{row['avg_daily_demand']:.1f}**
                    Recommended order: **{int(row['recommended_order'])} units**
                    Reason: {row['reason']}
                """)
                st.divider()

    with memory_tab:
        render_business_memory(email)

    with alerts_tab:
        st.subheader("🚨 Business Alerts")
        if not alerts:
            st.success("Everything looks healthy.")
        else:
            for alert in alerts:
                if "HIGH" in alert["priority"]:
                    st.error(f"**{alert['priority']} · {alert['title']}**\n\n{alert['description']}\n\n💸 {alert['impact']}")
                else:
                    st.warning(f"**{alert['priority']} · {alert['title']}**\n\n{alert['description']}\n\n💸 {alert['impact']}")

    with inventory_tab:
        st.subheader("📦 Inventory Intelligence")
        display_columns = ["product_name", "current_stock", "avg_daily_demand", "days_of_stock", "reorder_point",
                           "recommended_order", "stock_value", "profit_margin", "price_hike_pct", "priority"]
        display_df = processed[display_columns].copy()
        display_df = display_df.rename(columns={
            "product_name": "Product",
            "current_stock": "Current Stock",
            "avg_daily_demand": "Daily Demand",
            "days_of_stock": "Days of Stock",
            "reorder_point": "Reorder Point",
            "recommended_order": "Recommended Order",
            "stock_value": "Stock Value",
            "profit_margin": "Profit Margin %",
            "price_hike_pct": "Cost Change %",
            "priority": "Priority",
        })
        st.dataframe(display_df, use_container_width=True, hide_index=True)
        csv_data = processed.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download Inventory Analysis", data=csv_data,
                           file_name="pro_manager_inventory_analysis.csv", mime="text/csv")
        st.divider()
        st.subheader("📊 Stock vs Reorder Point")
        fig, ax = plt.subplots(figsize=(12, 5))
        x = np.arange(len(processed))
        width = 0.35
        ax.bar(x - width / 2, processed["current_stock"], width, label="Current Stock")
        ax.bar(x + width / 2, processed["reorder_point"], width, label="Reorder Point")
        ax.set_xticks(x)
        ax.set_xticklabels(processed["product_name"], rotation=25, ha="right")
        ax.set_ylabel("Units")
        ax.set_title("Current Stock vs Estimated Reorder Point")
        ax.legend()
        ax.grid(axis="y", linestyle="--", alpha=0.4)
        st.pyplot(fig, clear_figure=True)

    with forecast_tab:
        st.subheader("📈 Demand Forecast")
        st.caption("The current MVP uses historical demand and trend analysis. Later versions can use more advanced forecasting models.")
        forecast_rows = []
        for product, group in df.groupby("product_name"):
            history = group.sort_values("date")["sales"].tolist()
            forecast = calculate_forecast(history, 14)
            forecast_rows.append({
                "Product": product,
                "Estimated Daily Demand": round(forecast, 2),
                "Estimated 14-Day Demand": round(forecast * 14, 0),
            })
        forecast_df = pd.DataFrame(forecast_rows)
        st.dataframe(forecast_df, use_container_width=True, hide_index=True)

    with pos_tab:
        pos_connection_ui()

    with pitch_tab:
        st.subheader("💡 Pitch Mode")
        st.markdown("""
            ### Show a business owner what Pro Manager could find.
            Upload:
            **1. Sales history**
            **2. Purchase orders**
            The system compares actual purchasing against a transparent planning benchmark.
        """)
        col_a, col_b = st.columns(2)
        with col_a:
            sales_file = st.file_uploader("1️⃣ Sales History", type=["csv"], key="sales_audit")
            st.caption("Required columns: product_name, quantity_sold, date")
        with col_b:
            orders_file = st.file_uploader("2️⃣ Purchase Orders", type=["csv"], key="orders_audit")
            st.caption("Required columns: product_name, quantity_ordered, cost_per_unit, date")
        if sales_file and orders_file:
            try:
                sales_df = pd.read_csv(sales_file)
                orders_df = pd.read_csv(orders_file)
                comparison = run_order_audit(sales_df, orders_df)
                total_waste = comparison["waste_cost"].sum()
                estimated_lost_sales = comparison["estimated_lost_sales_value"].sum()
                total_impact = total_waste + estimated_lost_sales
                st.success("✅ Audit completed.")
                col1, col2, col3 = st.columns(3)
                col1.metric("Potential Excess Cost", f"R{total_waste:,.2f}")
                col2.metric("Estimated Missed Sales Value", f"R{estimated_lost_sales:,.2f}")
                col3.metric("Estimated Combined Impact", f"R{total_impact:,.2f}")
                st.caption(
                    "These figures are estimates based on the uploaded historical data and the transparent 15% planning buffer. They are not proof of actual financial loss.")
                audit_display = comparison[
                    ["product_name", "quantity_sold", "quantity_ordered", "planning_quantity", "over_ordered",
                     "under_ordered", "waste_cost", "estimated_lost_sales_value"]]
                st.dataframe(audit_display, use_container_width=True, hide_index=True)
                if total_waste > 0:
                    biggest = comparison.loc[comparison["waste_cost"].idxmax()]
                    if biggest["waste_cost"] > 0:
                        st.error(
                            f"🔴 Biggest potential excess cost: {biggest['product_name']} — approximately R{biggest['waste_cost']:,.2f}.")
                st.divider()
                st.subheader("🎤 Example Pitch")
                st.info("""
                    “Pro Manager analyses your business data,
                    identifies inventory risks and potential
                    money leaks, and gives you specific actions
                    instead of making you search through
                    spreadsheets manually.”
                """)
            except Exception as exc:
                st.error(f"Could not complete the audit: {exc}")
        else:
            st.info("Upload both files to run the audit.")

    st.divider()
    st.subheader("💳 Subscription")
    if status == "active":
        st.success("✅ Your Pro Manager subscription is active.")
        portal_url = create_portal_session(email)
        if portal_url:
            st.markdown(f"[Manage your subscription]({portal_url})")
    else:
        st.info(f"Your free trial is active. Continue with the paid plan for {MONTHLY_PRICE_DISPLAY}.")
        if st.button("💳 Subscribe with Stripe", use_container_width=True):
            checkout_url = create_checkout_session(email)
            if checkout_url:
                st.markdown(f"[Continue to secure checkout]({checkout_url})")


# ============================================================
# APP ROUTER
# ============================================================

def main():
    init_db()
    migrate_local_users_if_available()

    query_params = st.query_params

    login_token = query_params.get("login_token")
    if login_token:
        email = verify_login_token(login_token)
        if email:
            st.session_state["logged_in"] = True
            st.session_state["user_email"] = email
            st.session_state["user_status"] = get_user_status(email)
            st.query_params.clear()
            st.rerun()
        else:
            st.error("❌ Invalid or expired login link.")

    payment_status = query_params.get("payment")
    if payment_status == "success":
        st.success("Payment process completed. Your subscription status will update once Stripe confirms the subscription.")
    elif payment_status == "cancelled":
        st.info("Payment was cancelled. Your account has not been changed.")

    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False

    if not st.session_state["logged_in"]:
        remembered_email = get_persistent_login()
        if remembered_email:
            st.session_state["logged_in"] = True
            st.session_state["user_email"] = remembered_email
            st.session_state["user_status"] = get_user_status(remembered_email)

    if not st.session_state["logged_in"]:
        auth_page()
    else:
        main_dashboard()


if __name__ == "__main__":
    main()
