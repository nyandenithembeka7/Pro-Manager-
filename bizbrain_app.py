#!/usr/bin/env python3
"""
Pro Manager - AI Business Manager
---------------------------------
Inventory intelligence + money leak detection + business insights.

Run locally:
    streamlit run bizbrain_app.py

This version includes:
- 30-day free trial
- Password login
- Secure password hashing
- Magic email login links
- Demo business data
- CSV upload
- Excel upload
- Inventory analysis
- Demand forecasting
- Low-stock detection
- Overstock detection
- Dead-stock detection
- Supplier cost increase detection
- Profit margin analysis
- Money-leak detection
- Business insights
- Pitch/Audit Mode
- Stripe Checkout
- Stripe customer portal
- Safer configuration through Streamlit secrets
- Better error handling
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
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

try:
    import bcrypt
except ImportError:
    bcrypt = None

try:
    import stripe
except ImportError:
    stripe = None


# ============================================================
# 2. APP CONFIGURATION
# ============================================================

APP_NAME = "Pro Manager"

# Change this after deployment.
APP_URL = "https://pro-manager.streamlit.app"

TRIAL_DAYS = 30
MAGIC_LINK_HOURS = 24
MONTHLY_PRICE_DISPLAY = "R499 / month"

st.set_page_config(
    page_title=APP_NAME,
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# 3. OPTIONAL LOGO
# ============================================================

try:
    st.logo("logo.png", icon_image="logo.png")
except Exception:
    pass


# ============================================================
# 4. SECRETS / CONFIGURATION
# ============================================================

def get_secret(name, default=""):
    """
    Safely read a value from Streamlit secrets first,
    then environment variables.

    This prevents passwords/API keys from being hard-coded
    into the application.
    """

    try:
        value = st.secrets.get(name, None)
        if value is not None:
            return value
    except Exception:
        pass

    return os.getenv(name, default)


EMAIL_SENDER = get_secret("EMAIL_SENDER")
EMAIL_PASSWORD = get_secret("EMAIL_PASSWORD")

STRIPE_PUBLISHABLE_KEY = get_secret("STRIPE_PUBLISHABLE_KEY")
STRIPE_SECRET_KEY = get_secret("STRIPE_SECRET_KEY")
MONTHLY_PRICE_ID = get_secret("MONTHLY_PRICE_ID")

if stripe is not None and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY


# ============================================================
# 5. DATABASE
# ============================================================

DB_FILE = "users.db"


def get_connection():
    """
    Creates a SQLite connection.

    SQLite is suitable for our prototype.
    We should replace it with a hosted database before
    scaling to many paying customers.
    """
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    Create the users table if it does not exist.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            email TEXT PRIMARY KEY,
            password TEXT,
            stripe_customer_id TEXT,
            subscription_status TEXT DEFAULT 'trialing',
            created_at TEXT,
            trial_end_date TEXT,
            login_token TEXT,
            token_expiry TEXT
        )
        """
    )

    conn.commit()
    conn.close()


# ============================================================
# 6. PASSWORD SECURITY
# ============================================================

def hash_password(password):
    """
    Hash a password using bcrypt.
    """

    if bcrypt is None:
        raise RuntimeError(
            "bcrypt is not installed. Run: pip install bcrypt"
        )

    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")


def verify_password(password, hashed):
    """
    Verify a password against its bcrypt hash.
    """

    if bcrypt is None:
        return False

    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            hashed.encode("utf-8")
        )
    except Exception:
        return False


# ============================================================
# 7. DATE HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def datetime_to_string(dt):
    return dt.isoformat()


def string_to_datetime(value):
    """
    Safely convert stored datetime text back to datetime.
    """

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
# 8. USER ACCOUNT FUNCTIONS
# ============================================================

def valid_email(email):
    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    return bool(re.match(pattern, email.strip()))


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

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            INSERT INTO users
            (
                email,
                password,
                subscription_status,
                created_at,
                trial_end_date
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                email,
                hashed,
                "trialing",
                datetime_to_string(created_at),
                datetime_to_string(trial_end),
            ),
        )

        conn.commit()

        return (
            True,
            f"Account created! Your {TRIAL_DAYS}-day free trial starts now."
        )

    except sqlite3.IntegrityError:

        return False, "An account with this email already exists."

    finally:

        conn.close()


def get_user(email):

    email = email.strip().lower()

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            email,
            password,
            subscription_status,
            trial_end_date,
            stripe_customer_id
        FROM users
        WHERE email = ?
        """,
        (email,),
    )

    result = cursor.fetchone()

    conn.close()

    return result


def set_user_status(email, status):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE users
        SET subscription_status = ?
        WHERE email = ?
        """,
        (status, email),
    )

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

    user = get_user(email)

    if not user:
        return "inactive"

    status = user["subscription_status"]

    trial_end = string_to_datetime(
        user["trial_end_date"]
    )

    if (
        status == "trialing"
        and trial_end is not None
        and utc_now() > trial_end
    ):

        set_user_status(email, "inactive")

        return "inactive"

    return status


def get_trial_days_left(email):

    user = get_user(email)

    if not user:
        return 0

    trial_end = string_to_datetime(
        user["trial_end_date"]
    )

    if not trial_end:
        return 0

    remaining_seconds = (
        trial_end - utc_now()
    ).total_seconds()

    if remaining_seconds <= 0:
        return 0

    return int(np.ceil(remaining_seconds / 86400))


# ============================================================
# 9. MAGIC LOGIN
# ============================================================

def generate_login_token():

    return secrets.token_urlsafe(32)


def save_login_token(email):

    token = generate_login_token()

    expiry = utc_now() + timedelta(
        hours=MAGIC_LINK_HOURS
    )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE users
        SET login_token = ?,
            token_expiry = ?
        WHERE email = ?
        """,
        (
            token,
            datetime_to_string(expiry),
            email,
        ),
    )

    conn.commit()
    conn.close()

    return token


def verify_login_token(token):

    if not token:
        return None

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT email, token_expiry
        FROM users
        WHERE login_token = ?
        """,
        (token,),
    )

    result = cursor.fetchone()

    if not result:
        conn.close()
        return None

    email = result["email"]

    expiry = string_to_datetime(
        result["token_expiry"]
    )

    if expiry and utc_now() < expiry:

        # IMPORTANT:
        # Make the magic link single-use.
        cursor.execute(
            """
            UPDATE users
            SET login_token = NULL,
                token_expiry = NULL
            WHERE email = ?
            """,
            (email,),
        )

        conn.commit()
        conn.close()

        return email

    conn.close()

    return None


def send_login_email(email, token):

    if not EMAIL_SENDER or not EMAIL_PASSWORD:

        return False, (
            "Email settings are not configured. "
            "Add EMAIL_SENDER and EMAIL_PASSWORD to Streamlit secrets."
        )

    magic_link = (
        f"{APP_URL}/?login_token={token}"
    )

    subject = f"🔐 Login to {APP_NAME}"

    body = f"""
<html>
<body>

<h2>Welcome to {APP_NAME}</h2>

<p>
You requested a secure login link.
</p>

<p>
<a href="{magic_link}">
<strong>Log in to {APP_NAME}</strong>
</a>
</p>

<p>
This link expires in {MAGIC_LINK_HOURS} hours and can only be used once.
</p>

<hr>

<p>
If you did not request this login link, you can safely ignore this email.
</p>

</body>
</html>
"""

    try:

        message = MIMEMultipart("alternative")

        message["From"] = EMAIL_SENDER
        message["To"] = email
        message["Subject"] = subject

        message.attach(
            MIMEText(body, "html")
        )

        server = smtplib.SMTP(
            "smtp.gmail.com",
            587,
            timeout=20,
        )

        server.starttls()

        server.login(
            EMAIL_SENDER,
            EMAIL_PASSWORD,
        )

        server.sendmail(
            EMAIL_SENDER,
            email,
            message.as_string(),
        )

        server.quit()

        return True, "Login link sent."

    except Exception as exc:

        return False, f"Email error: {exc}"


# ============================================================
# 10. STRIPE
# ============================================================

def stripe_is_configured():

    return bool(
        stripe
        and STRIPE_SECRET_KEY
        and MONTHLY_PRICE_ID
    )


def create_checkout_session(email):

    if not stripe_is_configured():

        st.error(
            "Stripe is not configured yet. "
            "Add STRIPE_SECRET_KEY and MONTHLY_PRICE_ID "
            "to Streamlit secrets."
        )

        return None

    try:

        session = stripe.checkout.Session.create(

            mode="subscription",

            line_items=[
                {
                    "price": MONTHLY_PRICE_ID,
                    "quantity": 1,
                }
            ],

            customer_email=email,

            success_url=(
                APP_URL
                + "/?payment=success"
            ),

            cancel_url=(
                APP_URL
                + "/?payment=cancelled"
            ),
        )

        return session.url

    except Exception as exc:

        st.error(
            f"Stripe error: {exc}"
        )

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

        session = stripe.billing_portal.Session.create(

            customer=customer_id,

            return_url=APP_URL,
        )

        return session.url

    except Exception:

        return None


def update_subscription(
    email,
    status,
    customer_id=None
):

    conn = get_connection()
    cursor = conn.cursor()

    if customer_id:

        cursor.execute(
            """
            UPDATE users
            SET subscription_status = ?,
                stripe_customer_id = ?
            WHERE email = ?
            """,
            (
                status,
                customer_id,
                email,
            ),
        )

    else:

        cursor.execute(
            """
            UPDATE users
            SET subscription_status = ?
            WHERE email = ?
            """,
            (
                status,
                email,
            ),
        )

    if status == "active":

        cursor.execute(
            """
            UPDATE users
            SET trial_end_date = NULL
            WHERE email = ?
            """,
            (email,),
        )

    conn.commit()
    conn.close()


# ============================================================
# 11. DEMO DATA
# ============================================================

def generate_demo_data():

    rng = np.random.default_rng(42)

    products = [

        {
            "name": "Coffee Beans",
            "price": 12.50,
            "cost": 6.00,
            "lead_time": 5,
        },

        {
            "name": "Green Tea",
            "price": 8.00,
            "cost": 3.50,
            "lead_time": 4,
        },

        {
            "name": "Bottled Water",
            "price": 1.20,
            "cost": 0.60,
            "lead_time": 3,
        },

        {
            "name": "Protein Bars",
            "price": 4.50,
            "cost": 2.00,
            "lead_time": 6,
        },

        {
            "name": "Hand Sanitiser",
            "price": 5.00,
            "cost": 2.50,
            "lead_time": 7,
        },
    ]

    rows = []

    dates = pd.date_range(
        end=pd.Timestamp.today().normalize(),
        periods=60,
        freq="D",
    )

    for product in products:

        base_sales = rng.integers(
            5,
            35,
        )

        trend = rng.uniform(
            -0.20,
            0.35,
        )

        starting_stock = rng.integers(
            50,
            300,
        )

        current_stock = float(
            starting_stock
        )

        previous_cost = (
            product["cost"]
            * rng.uniform(0.90, 1.05)
        )

        for i, date in enumerate(dates):

            demand = (
                base_sales
                + trend * i
                + rng.normal(
                    0,
                    max(base_sales * 0.15, 1),
                )
            )

            sales = max(
                0,
                int(round(demand)),
            )

            current_stock = max(
                0,
                current_stock - sales,
            )

            # Replenishment events create a more realistic
            # inventory history.
            if current_stock < 20:

                current_stock += rng.integers(
                    50,
                    150,
                )

            rows.append(
                {
                    "date": date,
                    "product_name": product["name"],
                    "current_stock": int(
                        round(current_stock)
                    ),
                    "selling_price": round(
                        product["price"],
                        2,
                    ),
                    "cost_per_unit": round(
                        product["cost"],
                        2,
                    ),
                    "previous_cost_per_unit": round(
                        previous_cost,
                        2,
                    ),
                    "supplier_lead_time_days": product[
                        "lead_time"
                    ],
                    "sales": sales,
                }
            )

    return pd.DataFrame(rows)


# ============================================================
# 12. DATA CLEANING
# ============================================================

COLUMN_ALIASES = {

    "product_name": [
        "product_name",
        "product",
        "product name",
        "item",
        "item_name",
        "sku",
    ],

    "current_stock": [
        "current_stock",
        "stock",
        "inventory",
        "inventory_level",
        "on_hand",
        "stock_level",
    ],

    "selling_price": [
        "selling_price",
        "selling price",
        "sale_price",
        "sale price",
        "unit_price",
        "price",
    ],

    "cost_per_unit": [
        "cost_per_unit",
        "cost per unit",
        "unit_cost",
        "unit cost",
        "cost",
        "purchase_price",
    ],

    "previous_cost_per_unit": [
        "previous_cost_per_unit",
        "previous cost per unit",
        "previous_cost",
        "old_cost",
    ],

    "supplier_lead_time_days": [
        "supplier_lead_time_days",
        "supplier lead time days",
        "lead_time_days",
        "lead_time",
        "delivery_days",
        "supplier_lead_time",
    ],

    "date": [
        "date",
        "order_date",
        "transaction_date",
        "sales_date",
        "day",
        "timestamp",
    ],

    "sales": [
        "sales",
        "quantity_sold",
        "quantity sold",
        "units_sold",
        "units sold",
        "qty",
        "quantity",
        "demand",
    ],

    "daily_sales": [
        "daily_sales",
        "daily sales",
        "sales_history",
        "sales history",
        "daily_demand",
        "daily demand",
    ],
}


def clean_column_name(column):

    return (
        str(column)
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
    )


def normalize_columns(df):

    if df is None or df.empty:

        raise ValueError(
            "The uploaded file is empty."
        )

    work = df.copy()

    work.columns = [
        clean_column_name(column)
        for column in work.columns
    ]

    rename_map = {}

    for target, aliases in COLUMN_ALIASES.items():

        aliases_cleaned = {
            clean_column_name(alias)
            for alias in aliases
        }

        for column in work.columns:

            if column in aliases_cleaned:

                if column != target:

                    if target not in work.columns:

                        rename_map[column] = target

                break

    work = work.rename(
        columns=rename_map
    )

    required = [
        "product_name",
        "current_stock",
    ]

    missing = [
        column
        for column in required
        if column not in work.columns
    ]

    if missing:

        raise ValueError(
            "Missing required columns: "
            + ", ".join(missing)
            + ".\n\n"
            "Required fields:\n"
            "- product_name\n"
            "- current_stock\n"
            "- sales OR daily_sales"
        )

    if (
        "sales" not in work.columns
        and "daily_sales" not in work.columns
    ):

        raise ValueError(
            "Missing sales data.\n\n"
            "Your file must contain either:\n"
            "- sales\n"
            "or\n"
            "- daily_sales"
        )

    return work


def expand_daily_sales_history(df):

    """
    Converts a file containing one row per product and
    a comma-separated daily_sales history into one row
    per day.

    Example:

    product_name = Coffee Beans
    daily_sales = 10,12,9,11

    becomes:

    Coffee Beans | day 1 | 10
    Coffee Beans | day 2 | 12
    Coffee Beans | day 3 | 9
    Coffee Beans | day 4 | 11
    """

    if (
        "daily_sales" not in df.columns
        or "sales" in df.columns
    ):

        return df

    expanded_rows = []

    for _, row in df.iterrows():

        raw_sales = row["daily_sales"]

        if pd.isna(raw_sales):

            sales_values = []

        else:

            sales_values = [
                value.strip()
                for value in str(
                    raw_sales
                ).split(",")
                if value.strip() != ""
            ]

        if not sales_values:

            sales_values = ["0"]

        for index, value in enumerate(
            sales_values
        ):

            try:

                sales_value = float(
                    value
                )

            except Exception:

                sales_value = 0.0

            new_row = row.copy()

            new_row["sales"] = max(
                0.0,
                sales_value,
            )

            # Create a date for each historical
            # sales observation.
            new_row["date"] = (
                pd.Timestamp.today().normalize()
                - pd.Timedelta(
                    days=(
                        len(sales_values)
                        - 1
                        - index
                    )
                )
            )

            expanded_rows.append(
                new_row
            )

    if not expanded_rows:

        raise ValueError(
            "No daily sales data could be read "
            "from the uploaded file."
        )

    expanded = pd.DataFrame(
        expanded_rows
    )

    expanded = expanded.drop(
        columns=["daily_sales"],
        errors="ignore",
    )

    return expanded


def prepare_data(df):

    # --------------------------------------------------------
    # Step 1: Normalise column names
    # --------------------------------------------------------

    work = normalize_columns(
        df
    )

    # --------------------------------------------------------
    # Step 2: Convert daily_sales history
    # --------------------------------------------------------

    work = expand_daily_sales_history(
        work
    )

    # --------------------------------------------------------
    # Step 3: Clean product names
    # --------------------------------------------------------

    work["product_name"] = (
        work["product_name"]
        .astype(str)
        .str.strip()
    )

    work = work[
        work["product_name"].ne("")
    ].copy()

    # --------------------------------------------------------
    # Step 4: Convert numeric columns
    # --------------------------------------------------------

    numeric_columns = [

        "current_stock",

        "selling_price",

        "cost_per_unit",

        "previous_cost_per_unit",

        "supplier_lead_time_days",

        "sales",
    ]

    for column in numeric_columns:

        if column in work.columns:

            work[column] = pd.to_numeric(
                work[column],
                errors="coerce",
            )

    # --------------------------------------------------------
    # Step 5: Clean stock
    # --------------------------------------------------------

    work["current_stock"] = (
        work["current_stock"]
        .fillna(0)
        .clip(lower=0)
    )

    # --------------------------------------------------------
    # Step 6: Clean sales
    # --------------------------------------------------------

    work["sales"] = (
        work["sales"]
        .fillna(0)
        .clip(lower=0)
    )

    # --------------------------------------------------------
    # Step 7: Selling price
    # --------------------------------------------------------

    if (
        "selling_price"
        not in work.columns
    ):

        work["selling_price"] = 0.0

    work["selling_price"] = (
        work["selling_price"]
        .fillna(0)
        .clip(lower=0)
    )

    # --------------------------------------------------------
    # Step 8: Cost per unit
    # --------------------------------------------------------

    if (
        "cost_per_unit"
        not in work.columns
    ):

        work["cost_per_unit"] = 0.0

    work["cost_per_unit"] = (
        work["cost_per_unit"]
        .fillna(0)
        .clip(lower=0)
    )

    # --------------------------------------------------------
    # Step 9: Previous cost
    # --------------------------------------------------------

    if (
        "previous_cost_per_unit"
        not in work.columns
    ):

        work[
            "previous_cost_per_unit"
        ] = work[
            "cost_per_unit"
        ]

    work[
        "previous_cost_per_unit"
    ] = (
        work[
            "previous_cost_per_unit"
        ]
        .fillna(
            work[
                "cost_per_unit"
            ]
        )
        .clip(lower=0)
    )

    # --------------------------------------------------------
    # Step 10: Supplier lead time
    # --------------------------------------------------------

    if (
        "supplier_lead_time_days"
        not in work.columns
    ):

        work[
            "supplier_lead_time_days"
        ] = 5

    work[
        "supplier_lead_time_days"
    ] = (
        pd.to_numeric(
            work[
                "supplier_lead_time_days"
            ],
            errors="coerce",
        )
        .fillna(5)
        .clip(0, 365)
    )

    # --------------------------------------------------------
    # Step 11: Dates
    # --------------------------------------------------------

    if "date" in work.columns:

        work["date"] = pd.to_datetime(
            work["date"],
            errors="coerce",
        )

    else:

        work["date"] = pd.NaT

    # --------------------------------------------------------
    # Step 12: Sort historical records
    # --------------------------------------------------------

    work = work.sort_values(
        [
            "product_name",
            "date",
        ],
        na_position="last",
    )

    return work.reset_index(
        drop=True
    )

# ============================================================
# 13. MONTHLY DATA SUPPORT
# ============================================================

MONTH_NAMES = [
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
]


def detect_monthly_columns(df):

    cleaned = {
        clean_column_name(c): c
        for c in df.columns
    }

    found = []

    for month in MONTH_NAMES:

        if month in cleaned:

            found.append(
                cleaned[month]
            )

    return found


def convert_monthly_data(df):

    month_columns = detect_monthly_columns(
        df
    )

    if not month_columns:

        return df

    work = df.copy()

    daily_sales = []

    for _, row in work.iterrows():

        values = []

        for month in month_columns:

            try:

                monthly_value = float(
                    row[month]
                )

            except Exception:

                monthly_value = 0

            daily_average = max(
                0,
                monthly_value / 30,
            )

            values.extend(
                [daily_average] * 30
            )

        daily_sales.append(
            sum(values)
        )

    work["sales"] = daily_sales

    return work


# ============================================================
# 14. DEMAND FORECASTING
# ============================================================

def calculate_forecast(
    sales_history,
    forecast_days=14,
):

    values = np.asarray(
        sales_history,
        dtype=float,
    )

    values = np.nan_to_num(
        values,
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )

    values = np.clip(
        values,
        0,
        None,
    )

    if len(values) == 0:

        return 0.0

    window = min(
        len(values),
        30,
    )

    recent = values[-window:]

    recent_mean = float(
        np.mean(recent)
    )

    if len(recent) < 3:

        return recent_mean

    x = np.arange(
        len(recent),
        dtype=float,
    )

    try:

        slope, intercept = np.polyfit(
            x,
            recent,
            1,
        )

        future_x = np.arange(
            len(recent),
            len(recent)
            + max(forecast_days, 1),
        )

        predictions = (
            intercept
            + slope * future_x
        )

        predictions = np.clip(
            predictions,
            0,
            None,
        )

        trend_forecast = float(
            np.mean(predictions)
        )

        # Blend the trend with the recent
        # average to avoid overreacting to
        # one unusual period.
        forecast = (
            0.60 * trend_forecast
            + 0.40 * recent_mean
        )

        return max(
            0.0,
            float(forecast),
        )

    except Exception:

        return recent_mean


# ============================================================
# 15. INVENTORY ANALYSIS
# ============================================================

def process_data(df):

    work = df.copy()

    results = []

    grouped = work.groupby(
        "product_name",
        sort=True,
    )

    for product, group in grouped:

        group = group.copy()

        group = group.sort_values(
            "date"
        )

        sales_history = (
            group["sales"]
            .astype(float)
            .tolist()
        )

        current_stock = float(
            group["current_stock"].iloc[-1]
        )

        selling_price = float(
            group["selling_price"].iloc[-1]
        )

        cost_per_unit = float(
            group["cost_per_unit"].iloc[-1]
        )

        previous_cost = float(
            group[
                "previous_cost_per_unit"
            ].iloc[-1]
        )

        lead_time = float(
            group[
                "supplier_lead_time_days"
            ].iloc[-1]
        )

        avg_daily_demand = (
            calculate_forecast(
                sales_history,
                14,
            )
        )

        recent_sales = np.asarray(
            sales_history[-30:],
            dtype=float,
        )

        if len(recent_sales) > 1:

            demand_std = float(
                np.std(
                    recent_sales,
                    ddof=1,
                )
            )

        else:

            demand_std = 0.0

        days_of_stock = (

            current_stock
            / avg_daily_demand

            if avg_daily_demand > 0

            else np.inf
        )

        # Safety buffer.
        safety_stock = (
            1.65
            * demand_std
            * np.sqrt(
                max(lead_time, 1)
            )
        )

        reorder_point = (
            avg_daily_demand
            * lead_time
            + safety_stock
        )

        target_stock = (
            avg_daily_demand
            * (
                lead_time
                + 14
            )
            + safety_stock
        )

        recommended_order = max(
            0,
            int(
                np.ceil(
                    target_stock
                    - current_stock
                )
            ),
        )

        stock_value = (
            current_stock
            * cost_per_unit
        )

        if selling_price > 0:

            profit_margin = (
                (
                    selling_price
                    - cost_per_unit
                )
                / selling_price
                * 100
            )

        else:

            profit_margin = 0.0

        if previous_cost > 0:

            price_hike_pct = (
                (
                    cost_per_unit
                    - previous_cost
                )
                / previous_cost
                * 100
            )

        else:

            price_hike_pct = 0.0

        recent_10 = sales_history[-10:]

        is_dead = (
            len(recent_10) >= 10
            and all(
                value == 0
                for value in recent_10
            )
        )

        if len(sales_history) >= 3:

            x = np.arange(
                len(sales_history)
            )

            try:

                demand_trend = float(
                    np.polyfit(
                        x,
                        sales_history,
                        1,
                    )[0]
                )

            except Exception:

                demand_trend = 0.0

        else:

            demand_trend = 0.0

        if current_stock <= reorder_point:

            priority = "HIGH"

            reason = (
                "Stock is at or below "
                "the estimated reorder point."
            )

        elif (
            np.isfinite(days_of_stock)
            and days_of_stock <= lead_time
        ):

            priority = "HIGH"

            reason = (
                "Current stock may not "
                "cover supplier lead time."
            )

        elif (
            np.isfinite(days_of_stock)
            and days_of_stock
            <= lead_time + 3
        ):

            priority = "MEDIUM"

            reason = (
                "Inventory cover is "
                "getting low."
            )

        elif (
            np.isfinite(days_of_stock)
            and days_of_stock > 90
        ):

            priority = "MEDIUM"

            reason = (
                "Large amount of inventory "
                "may be tied up."
            )

        else:

            priority = "LOW"

            reason = (
                "No immediate inventory "
                "risk detected."
            )

        results.append(
            {
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
            }
        )

    return pd.DataFrame(
        results
    )


# ============================================================
# 16. ALERT GENERATION
# ============================================================

def generate_alerts(df):

    alerts = []

    for _, row in df.iterrows():

        product = row["product_name"]

        if row["current_stock"] <= row[
            "reorder_point"
        ]:

            alerts.append(
                {
                    "priority": "🔴 HIGH",
                    "title": (
                        f"{product} - Low Stock"
                    ),
                    "description": (
                        f"Approximately "
                        f"{row['days_of_stock']:.1f} "
                        "days of stock remain."
                    ),
                    "impact": (
                        f"Recommended order: "
                        f"{int(row['recommended_order'])} units."
                    ),
                }
            )

        if (
            row["days_of_stock"]
            != np.inf
            and row["days_of_stock"] > 90
        ):

            alerts.append(
                {
                    "priority": "🟡 MEDIUM",
                    "title": (
                        f"{product} - Overstocked"
                    ),
                    "description": (
                        f"Approximately "
                        f"{row['days_of_stock']:.0f} "
                        "days of stock."
                    ),
                    "impact": (
                        f"R{row['stock_value']:,.2f} "
                        "may be tied up."
                    ),
                }
            )

        if row["demand_trend"] < -0.5:

            alerts.append(
                {
                    "priority": "🟡 MEDIUM",
                    "title": (
                        f"{product} - Demand Declining"
                    ),
                    "description": (
                        f"Estimated trend: "
                        f"{row['demand_trend']:.2f} "
                        "units/day."
                    ),
                    "impact": (
                        "Future revenue may be at risk."
                    ),
                }
            )

        if row["price_hike"]:

            alerts.append(
                {
                    "priority": "🔴 HIGH",
                    "title": (
                        f"{product} - Supplier Cost Increase"
                    ),
                    "description": (
                        f"Unit cost increased "
                        f"{row['price_hike_pct']:.1f}%."
                    ),
                    "impact": (
                        "Review supplier pricing "
                        "and product margins."
                    ),
                }
            )

        if row["is_dead"]:

            alerts.append(
                {
                    "priority": "🔴 HIGH",
                    "title": (
                        f"{product} - Dead Stock"
                    ),
                    "description": (
                        "No sales detected in "
                        "the recent history."
                    ),
                    "impact": (
                        f"R{row['stock_value']:,.2f} "
                        "may be tied up."
                    ),
                }
            )

    return alerts


# ============================================================
# 17. BUSINESS INSIGHTS
# ============================================================

def generate_business_insights(df):

    insights = []

    if df.empty:
        return insights

    total_stock_value = (
        df["stock_value"].sum()
    )

    dead_stock_value = (
        df.loc[
            df["is_dead"],
            "stock_value",
        ].sum()
    )

    high_priority = (
        df["priority"] == "HIGH"
    ).sum()

    price_hikes = (
        df["price_hike"]
    ).sum()

    declining = (
        df["demand_trend"] < -0.5
    ).sum()

    if high_priority > 0:

        insights.append(
            {
                "type": "risk",
                "title": "Immediate inventory risk",
                "text": (
                    f"{high_priority} product(s) "
                    "need urgent inventory attention."
                ),
            }
        )

    if dead_stock_value > 0:

        percentage = (
            dead_stock_value
            / total_stock_value
            * 100
            if total_stock_value > 0
            else 0
        )

        insights.append(
            {
                "type": "money",
                "title": "Capital tied up in dead stock",
                "text": (
                    f"Approximately "
                    f"R{dead_stock_value:,.2f} "
                    f"({percentage:.1f}% of inventory value) "
                    "is associated with non-moving products."
                ),
            }
        )

    if price_hikes > 0:

        insights.append(
            {
                "type": "supplier",
                "title": "Supplier costs changed",
                "text": (
                    f"{price_hikes} product(s) "
                    "show a supplier cost increase "
                    "greater than 3%."
                ),
            }
        )

    if declining > 0:

        insights.append(
            {
                "type": "sales",
                "title": "Demand is declining",
                "text": (
                    f"{declining} product(s) "
                    "show a negative demand trend."
                ),
            }
        )

    best_margin = df.loc[
        df["profit_margin"].idxmax()
    ]

    insights.append(
        {
            "type": "opportunity",
            "title": "Highest-margin product",
            "text": (
                f"{best_margin['product_name']} "
                f"currently has the highest estimated "
                f"gross margin at "
                f"{best_margin['profit_margin']:.1f}%."
            ),
        }
    )

    return insights


# ============================================================
# 18. PITCH / ORDER AUDIT
# ============================================================

def run_order_audit(
    sales_df,
    orders_df,
):

    required_sales = {
        "product_name",
        "quantity_sold",
        "date",
    }

    required_orders = {
        "product_name",
        "quantity_ordered",
        "cost_per_unit",
        "date",
    }

    missing_sales = (
        required_sales
        - set(sales_df.columns)
    )

    missing_orders = (
        required_orders
        - set(orders_df.columns)
    )

    if missing_sales:

        raise ValueError(
            "Sales file is missing: "
            + ", ".join(missing_sales)
        )

    if missing_orders:

        raise ValueError(
            "Orders file is missing: "
            + ", ".join(missing_orders)
        )

    sales_df = sales_df.copy()
    orders_df = orders_df.copy()

    sales_df[
        "quantity_sold"
    ] = pd.to_numeric(
        sales_df[
            "quantity_sold"
        ],
        errors="coerce",
    ).fillna(0)

    orders_df[
        "quantity_ordered"
    ] = pd.to_numeric(
        orders_df[
            "quantity_ordered"
        ],
        errors="coerce",
    ).fillna(0)

    orders_df[
        "cost_per_unit"
    ] = pd.to_numeric(
        orders_df[
            "cost_per_unit"
        ],
        errors="coerce",
    ).fillna(0)

    total_sold = (
        sales_df
        .groupby("product_name")[
            "quantity_sold"
        ]
        .sum()
        .reset_index()
    )

    total_ordered = (
        orders_df
        .groupby("product_name")[
            "quantity_ordered"
        ]
        .sum()
        .reset_index()
    )

    costs = (
        orders_df
        .groupby("product_name")[
            "cost_per_unit"
        ]
        .mean()
        .reset_index()
    )

    comparison = pd.merge(
        total_sold,
        total_ordered,
        on="product_name",
        how="outer",
    )

    comparison = pd.merge(
        comparison,
        costs,
        on="product_name",
        how="left",
    )

    comparison = comparison.fillna(0)

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # We no longer call "sales × 1.15" AI.
    #
    # This audit uses a transparent planning buffer:
    # historical sales + 15% buffer.
    #
    # Later we can replace this with the same forecasting
    # engine used by the main product.
    # --------------------------------------------------------

    comparison[
        "planning_quantity"
    ] = (
        comparison["quantity_sold"]
        * 1.15
    )

    comparison[
        "over_ordered"
    ] = (
        comparison[
            "quantity_ordered"
        ]
        - comparison[
            "planning_quantity"
        ]
    ).clip(lower=0)

    comparison[
        "under_ordered"
    ] = (
        comparison[
            "planning_quantity"
        ]
        - comparison[
            "quantity_ordered"
        ]
    ).clip(lower=0)

    comparison[
        "waste_cost"
    ] = (
        comparison["over_ordered"]
        * comparison["cost_per_unit"]
    )

    comparison[
        "estimated_lost_sales_value"
    ] = (
        comparison["under_ordered"]
        * comparison["cost_per_unit"]
    )

    return comparison


# ============================================================
# 19. AUTHENTICATION PAGE
# ============================================================

def auth_page():

    st.title(
        f"🧠 {APP_NAME}"
    )

    st.caption(
        "AI-powered business intelligence."
    )

    st.markdown(
        """
        ### Turn your business data into decisions.

        Pro Manager helps identify:

        - 📦 Inventory risks
        - 💰 Money leaks
        - 📈 Demand changes
        - 🧊 Dead stock
        - 🏭 Supplier cost increases
        - 🚨 Business problems that need attention
        """
    )

    st.divider()

    choice = st.radio(
        "Account",
        [
            "Login",
            "Sign Up",
        ],
        horizontal=True,
    )

    email = st.text_input(
        "Email address",
        placeholder="you@example.com",
    )

    password = st.text_input(
        "Password",
        type="password",
    )

    if choice == "Sign Up":

        if st.button(
            "🚀 Start 30-Day Free Trial",
            use_container_width=True,
        ):

            if not valid_email(email):

                st.error(
                    "Please enter a valid email."
                )

            elif len(password) < 8:

                st.error(
                    "Password must be at least 8 characters."
                )

            else:

                success, message = signup_user(
                    email,
                    password,
                )

                if success:

                    st.success(message)

                    st.info(
                        "Your account has been created. "
                        "You can now log in."
                    )

                else:

                    st.error(message)

    else:

        if st.button(
            "🔐 Log In",
            use_container_width=True,
        ):

            success, status = login_user(
                email,
                password,
            )

            if success:

                st.session_state[
                    "logged_in"
                ] = True

                st.session_state[
                    "user_email"
                ] = email.strip().lower()

                st.session_state[
                    "user_status"
                ] = status

                st.rerun()

            else:

                st.error(
                    "Invalid email or password."
                )

        st.divider()

        st.caption(
            "Forgot your password? "
            "Use a secure login link instead."
        )

        if st.button(
            "📧 Email Me a Login Link",
            use_container_width=True,
        ):

            clean_email = (
                email.strip().lower()
            )

            if not valid_email(clean_email):

                st.error(
                    "Please enter a valid email address."
                )

            else:

                user = get_user(
                    clean_email
                )

                if not user:

                    # Do not reveal too much account
                    # information in production.
                    st.info(
                        "If an account exists for that "
                        "email, a login link will be sent."
                    )

                else:

                    token = save_login_token(
                        clean_email
                    )

                    success, message = (
                        send_login_email(
                            clean_email,
                            token,
                        )
                    )

                    if success:

                        st.success(
                            "Login link sent. "
                            "Check your inbox."
                        )

                    else:

                        st.error(message)

    st.divider()

    st.caption(
        "30-day free trial. "
        "No credit card required."
    )


# ============================================================
# 20. DATA SOURCE LOADER
# ============================================================

def load_uploaded_file(uploaded_file):

    if uploaded_file is None:
        return None

    filename = (
        uploaded_file.name.lower()
    )

    if filename.endswith(".csv"):

        return pd.read_csv(
            uploaded_file
        )

    if (
        filename.endswith(".xlsx")
        or filename.endswith(".xls")
    ):

        return pd.read_excel(
            uploaded_file,
            engine="openpyxl",
        )

    raise ValueError(
        "Unsupported file type."
    )


# ============================================================
# 21. SIDEBAR DATA SOURCE
# ============================================================

def data_source_sidebar():

    with st.sidebar:

        st.header(
            "🔌 Data Source"
        )

        source = st.radio(
            "Choose your data source:",
            [
                "📊 Demo Business",
                "📂 Upload CSV / Excel",
            ],
        )

        st.divider()

        if source == "📊 Demo Business":

            st.success(
                "Demo data is active."
            )

            return (
                generate_demo_data(),
                "Demo Business",
            )

        uploaded = st.file_uploader(
            "Upload your business data",
            type=[
                "csv",
                "xlsx",
                "xls",
            ],
        )

        if uploaded is None:

            st.info(
                "Upload a CSV or Excel file "
                "to analyse your business."
            )

            return (
                generate_demo_data(),
                "Demo Business - Waiting for Upload",
            )

        try:

            raw = load_uploaded_file(
                uploaded
            )

            monthly_columns = (
                detect_monthly_columns(
                    raw
                )
            )

            if monthly_columns:

                st.info(
                    "Monthly sales columns detected. "
                    "They will be converted into a "
                    "sales estimate for analysis."
                )

                raw = convert_monthly_data(
                    raw
                )

            cleaned = prepare_data(
                raw
            )

            st.success(
                f"Loaded {uploaded.name}"
            )

            return (
                cleaned,
                uploaded.name,
            )

        except Exception as exc:

            st.error(
                f"Could not process file: {exc}"
            )

            st.info(
                "Using demo data so the dashboard "
                "can continue running."
            )

            return (
                generate_demo_data(),
                "Demo Business - Upload Error",
            )


# ============================================================
# 22. DASHBOARD
# ============================================================

def main_dashboard():

    email = st.session_state[
        "user_email"
    ]

    status = get_user_status(
        email
    )

    trial_days = get_trial_days_left(
        email
    )

    # --------------------------------------------------------
    # Header
    # --------------------------------------------------------

    st.title(
        f"🧠 {APP_NAME}"
    )

    st.caption(
        "Your AI-powered business manager."
    )

    # --------------------------------------------------------
    # Sidebar
    # --------------------------------------------------------

    df, source_label = (
        data_source_sidebar()
    )

    with st.sidebar:

        st.divider()

        st.caption(
            f"📊 Data source: {source_label}"
        )

    # --------------------------------------------------------
    # Account status
    # --------------------------------------------------------

    col_status, col_logout = st.columns(
        [4, 1]
    )

    with col_status:

        if status == "active":

            st.success(
                f"✅ Active subscription · {email}"
            )

        elif status == "trialing":

            st.warning(
                f"🔓 Free trial · "
                f"{trial_days} day(s) remaining · "
                f"{email}"
            )

        else:

            st.error(
                f"🚫 Subscription inactive · {email}"
            )

    with col_logout:

        if st.button(
            "🚪 Logout"
        ):

            st.session_state[
                "logged_in"
            ] = False

            st.session_state.pop(
                "user_email",
                None,
            )

            st.session_state.pop(
                "user_status",
                None,
            )

            st.rerun()

    # --------------------------------------------------------
    # Paywall
    # --------------------------------------------------------

    if status == "inactive":

        st.divider()

        st.error(
            "Your free trial has expired "
            "or your subscription is inactive."
        )

        st.markdown(
            f"""
            ### Continue using {APP_NAME}

            **Monthly plan:** {MONTHLY_PRICE_DISPLAY}

            ✓ Inventory intelligence  
            ✓ Money leak detection  
            ✓ Business insights  
            ✓ Demand analysis  
            ✓ Priority support
            """
        )

        if st.button(
            "💳 Subscribe with Stripe",
            use_container_width=True,
        ):

            checkout_url = (
                create_checkout_session(
                    email
                )
            )

            if checkout_url:

                st.markdown(
                    f"[Continue to secure Stripe checkout]({checkout_url})"
                )

        st.stop()

    # --------------------------------------------------------
    # Trial message
    # --------------------------------------------------------

    if status == "trialing":

        st.info(
            f"🎉 You're using your free trial. "
            f"{trial_days} day(s) remaining."
        )

    # --------------------------------------------------------
    # Process inventory
    # --------------------------------------------------------

    try:

        processed = process_data(
            df
        )

    except Exception as exc:

        st.error(
            f"Could not analyse the data: {exc}"
        )

        st.stop()

    alerts = generate_alerts(
        processed
    )

    insights = generate_business_insights(
        processed
    )

    # ========================================================
    # KEY METRICS
    # ========================================================

    st.divider()

    total_inventory_value = (
        processed["stock_value"].sum()
    )

    dead_stock_value = (
        processed.loc[
            processed["is_dead"],
            "stock_value",
        ].sum()
    )

    high_alerts = len(
        [
            alert
            for alert in alerts
            if "HIGH" in alert["priority"]
        ]
    )

    avg_margin = (
        processed["profit_margin"].mean()
        if not processed.empty
        else 0
    )

    col1, col2, col3, col4 = st.columns(
        4
    )

    col1.metric(
        "💰 Inventory Value",
        f"R{total_inventory_value:,.2f}",
    )

    col2.metric(
        "🚨 High-Priority Alerts",
        high_alerts,
    )

    col3.metric(
        "🧊 Dead Stock",
        f"R{dead_stock_value:,.2f}",
    )

    col4.metric(
        "📈 Average Margin",
        f"{avg_margin:.1f}%",
    )

    # ========================================================
    # TABS
    # ========================================================

    (
        overview_tab,
        alerts_tab,
        inventory_tab,
        forecast_tab,
        pitch_tab,
    ) = st.tabs(
        [
            "🧠 Business Overview",
            "🚨 Alerts",
            "📦 Inventory",
            "📈 Forecast",
            "💡 Pitch Mode",
        ]
    )

    # ========================================================
    # BUSINESS OVERVIEW
    # ========================================================

    with overview_tab:

        st.subheader(
            "🧠 What should you know today?"
        )

        if not insights:

            st.success(
                "No major business insights detected."
            )

        else:

            for insight in insights:

                if insight["type"] == "risk":

                    st.error(
                        f"🔴 **{insight['title']}**\n\n"
                        f"{insight['text']}"
                    )

                elif insight["type"] == "money":

                    st.warning(
                        f"💰 **{insight['title']}**\n\n"
                        f"{insight['text']}"
                    )

                elif insight["type"] == "supplier":

                    st.warning(
                        f"🏭 **{insight['title']}**\n\n"
                        f"{insight['text']}"
                    )

                elif insight["type"] == "sales":

                    st.warning(
                        f"📉 **{insight['title']}**\n\n"
                        f"{insight['text']}"
                    )

                else:

                    st.success(
                        f"🟢 **{insight['title']}**\n\n"
                        f"{insight['text']}"
                    )

        st.divider()

        st.subheader(
            "🎯 Recommended actions"
        )

        high_priority_rows = processed[
            processed["priority"] == "HIGH"
        ]

        if high_priority_rows.empty:

            st.success(
                "No urgent inventory action is required."
            )

        else:

            for _, row in (
                high_priority_rows
                .head(5)
                .iterrows()
            ):

                st.markdown(
                    f"""
                    **{row['product_name']}**

                    Current stock: **{int(row['current_stock'])}**

                    Estimated daily demand:
                    **{row['avg_daily_demand']:.1f}**

                    Recommended order:
                    **{int(row['recommended_order'])} units**

                    Reason: {row['reason']}
                    """
                )

                st.divider()

    # ========================================================
    # ALERTS
    # ========================================================

    with alerts_tab:

        st.subheader(
            "🚨 Business Alerts"
        )

        if not alerts:

            st.success(
                "Everything looks healthy."
            )

        else:

            for alert in alerts:

                if "HIGH" in alert["priority"]:

                    st.error(
                        f"**{alert['priority']} · "
                        f"{alert['title']}**\n\n"
                        f"{alert['description']}\n\n"
                        f"💸 {alert['impact']}"
                    )

                else:

                    st.warning(
                        f"**{alert['priority']} · "
                        f"{alert['title']}**\n\n"
                        f"{alert['description']}\n\n"
                        f"💸 {alert['impact']}"
                    )

    # ========================================================
    # INVENTORY
    # ========================================================

    with inventory_tab:

        st.subheader(
            "📦 Inventory Intelligence"
        )

        display_columns = [
            "product_name",
            "current_stock",
            "avg_daily_demand",
            "days_of_stock",
            "reorder_point",
            "recommended_order",
            "stock_value",
            "profit_margin",
            "price_hike_pct",
            "priority",
        ]

        display_df = (
            processed[
                display_columns
            ]
            .copy()
        )

        display_df = display_df.rename(
            columns={
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
            }
        )

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
        )

        csv_data = (
            processed
            .to_csv(index=False)
            .encode("utf-8")
        )

        st.download_button(
            "⬇️ Download Inventory Analysis",
            data=csv_data,
            file_name=(
                "pro_manager_inventory_analysis.csv"
            ),
            mime="text/csv",
        )

        st.divider()

        st.subheader(
            "📊 Stock vs Reorder Point"
        )

        fig, ax = plt.subplots(
            figsize=(12, 5)
        )

        x = np.arange(
            len(processed)
        )

        width = 0.35

        ax.bar(
            x - width / 2,
            processed[
                "current_stock"
            ],
            width,
            label="Current Stock",
        )

        ax.bar(
            x + width / 2,
            processed[
                "reorder_point"
            ],
            width,
            label="Reorder Point",
        )

        ax.set_xticks(x)

        ax.set_xticklabels(
            processed[
                "product_name"
            ],
            rotation=25,
            ha="right",
        )

        ax.set_ylabel(
            "Units"
        )

        ax.set_title(
            "Current Stock vs Estimated Reorder Point"
        )

        ax.legend()

        ax.grid(
            axis="y",
            linestyle="--",
            alpha=0.4,
        )

        st.pyplot(
            fig,
            clear_figure=True,
        )

    # ========================================================
    # FORECAST
    # ========================================================

    with forecast_tab:

        st.subheader(
            "📈 Demand Forecast"
        )

        st.caption(
            "The current MVP uses historical demand "
            "and trend analysis. Later versions can "
            "use more advanced forecasting models."
        )

        forecast_rows = []

        for product, group in (
            df.groupby("product_name")
        ):

            history = (
                group
                .sort_values("date")
                ["sales"]
                .tolist()
            )

            forecast = calculate_forecast(
                history,
                14,
            )

            forecast_rows.append(
                {
                    "Product": product,
                    "Estimated Daily Demand": round(
                        forecast,
                        2,
                    ),
                    "Estimated 14-Day Demand": round(
                        forecast * 14,
                        0,
                    ),
                }
            )

        forecast_df = pd.DataFrame(
            forecast_rows
        )

        st.dataframe(
            forecast_df,
            use_container_width=True,
            hide_index=True,
        )

    # ========================================================
    # PITCH MODE
    # ========================================================

    with pitch_tab:

        st.subheader(
            "💡 Pitch Mode"
        )

        st.markdown(
            """
            ### Show a business owner what Pro Manager could find.

            Upload:

            **1. Sales history**

            **2. Purchase orders**

            The system compares actual purchasing against a
            transparent planning benchmark.
            """
        )

        col_a, col_b = st.columns(
            2
        )

        with col_a:

            sales_file = st.file_uploader(
                "1️⃣ Sales History",
                type=["csv"],
                key="sales_audit",
            )

            st.caption(
                "Required columns: "
                "product_name, quantity_sold, date"
            )

        with col_b:

            orders_file = st.file_uploader(
                "2️⃣ Purchase Orders",
                type=["csv"],
                key="orders_audit",
            )

            st.caption(
                "Required columns: "
                "product_name, quantity_ordered, "
                "cost_per_unit, date"
            )

        if sales_file and orders_file:

            try:

                sales_df = pd.read_csv(
                    sales_file
                )

                orders_df = pd.read_csv(
                    orders_file
                )

                comparison = run_order_audit(
                    sales_df,
                    orders_df,
                )

                total_waste = (
                    comparison[
                        "waste_cost"
                    ].sum()
                )

                estimated_lost_sales = (
                    comparison[
                        "estimated_lost_sales_value"
                    ].sum()
                )

                total_impact = (
                    total_waste
                    + estimated_lost_sales
                )

                st.success(
                    "✅ Audit completed."
                )

                col1, col2, col3 = st.columns(
                    3
                )

                col1.metric(
                    "Potential Excess Cost",
                    f"R{total_waste:,.2f}",
                )

                col2.metric(
                    "Estimated Missed Sales Value",
                    f"R{estimated_lost_sales:,.2f}",
                )

                col3.metric(
                    "Estimated Combined Impact",
                    f"R{total_impact:,.2f}",
                )

                st.caption(
                    "These figures are estimates based on "
                    "the uploaded historical data and the "
                    "transparent 15% planning buffer. "
                    "They are not proof of actual financial loss."
                )

                audit_display = comparison[
                    [
                        "product_name",
                        "quantity_sold",
                        "quantity_ordered",
                        "planning_quantity",
                        "over_ordered",
                        "under_ordered",
                        "waste_cost",
                        "estimated_lost_sales_value",
                    ]
                ]

                st.dataframe(
                    audit_display,
                    use_container_width=True,
                    hide_index=True,
                )

                if total_waste > 0:

                    biggest = comparison.loc[
                        comparison[
                            "waste_cost"
                        ].idxmax()
                    ]

                    if (
                        biggest["waste_cost"]
                        > 0
                    ):

                        st.error(
                            f"🔴 Biggest potential "
                            f"excess cost: "
                            f"{biggest['product_name']} — "
                            f"approximately "
                            f"R{biggest['waste_cost']:,.2f}."
                        )

                st.divider()

                st.subheader(
                    "🎤 Example Pitch"
                )

                st.info(
                    """
                    “Pro Manager analyses your business data,
                    identifies inventory risks and potential
                    money leaks, and gives you specific actions
                    instead of making you search through
                    spreadsheets manually.”
                    """
                )

            except Exception as exc:

                st.error(
                    f"Could not complete the audit: {exc}"
                )

        else:

            st.info(
                "Upload both files to run the audit."
            )

    # ========================================================
    # BILLING
    # ========================================================

    st.divider()

    st.subheader(
        "💳 Subscription"
    )

    if status == "active":

        st.success(
            "✅ Your Pro Manager subscription is active."
        )

        portal_url = create_portal_session(
            email
        )

        if portal_url:

            st.markdown(
                f"[Manage your subscription]({portal_url})"
            )

    else:

        st.info(
            f"Your free trial is active. "
            f"Continue with the paid plan for "
            f"{MONTHLY_PRICE_DISPLAY}."
        )

        if st.button(
            "💳 Subscribe with Stripe",
            use_container_width=True,
        ):

            checkout_url = (
                create_checkout_session(
                    email
                )
            )

            if checkout_url:

                st.markdown(
                    f"[Continue to secure checkout]({checkout_url})"
                )


# ============================================================
# 23. APP ROUTER
# ============================================================

def main():

    init_db()

    # --------------------------------------------------------
    # Magic login token
    # --------------------------------------------------------

    query_params = st.query_params

    login_token = query_params.get(
        "login_token"
    )

    if login_token:

        email = verify_login_token(
            login_token
        )

        if email:

            st.session_state[
                "logged_in"
            ] = True

            st.session_state[
                "user_email"
            ] = email

            st.session_state[
                "user_status"
            ] = get_user_status(
                email
            )

            st.query_params.clear()

            st.rerun()

        else:

            st.error(
                "❌ Invalid or expired login link."
            )

    # --------------------------------------------------------
    # Payment status
    # --------------------------------------------------------

    payment_status = (
        query_params.get(
            "payment"
        )
    )

    if payment_status == "success":

        st.success(
            "Payment process completed. "
            "Your subscription status will update "
            "once Stripe confirms the subscription."
        )

    elif payment_status == "cancelled":

        st.info(
            "Payment was cancelled. "
            "Your account has not been changed."
        )

    # --------------------------------------------------------
    # Session state
    # --------------------------------------------------------

    if "logged_in" not in st.session_state:

        st.session_state[
            "logged_in"
        ] = False

    # --------------------------------------------------------
    # Routing
    # --------------------------------------------------------

    if not st.session_state[
        "logged_in"
    ]:

        auth_page()

    else:

        main_dashboard()


# ============================================================
# 24. RUN APPLICATION
# ============================================================

if __name__ == "__main__":

    main()
