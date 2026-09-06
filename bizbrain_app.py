#!/usr/bin/env python3
"""
BizBrain AI - SaaS Subscription Version
Renamed and monetized with Stripe subscriptions.
Run with: streamlit run bizbrain_app.py
"""

import streamlit as st
import pandas as pd
import numpy as np
from io import StringIO
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import sqlite3
import bcrypt
import stripe
import random
import re

# ------------------------------------------------------------
# 1. CONFIGURATION (RENAME YOUR APP HERE)
# ------------------------------------------------------------
APP_NAME = "BizBrain AI"  # <-- CHANGE THIS TO YOUR BRAND NAME!
st.set_page_config(page_title=APP_NAME, layout="wide", page_icon="🧠")

# ---- STRIPE CONFIGURATION ----
# Replace these with your real Stripe keys from dashboard.stripe.com
STRIPE_PUBLISHABLE_KEY = "pk_test_..."  # Get from Stripe Dashboard
STRIPE_SECRET_KEY = "sk_test_..."      # Get from Stripe Dashboard
stripe.api_key = STRIPE_SECRET_KEY

# Your Stripe Price ID (create this in Stripe Dashboard first)
MONTHLY_PRICE_ID = "price_123456789"    # Replace with your actual Price ID

# ------------------------------------------------------------
# 2. DATABASE SETUP (User Auth + Subscriptions)
# ------------------------------------------------------------
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (email TEXT PRIMARY KEY, 
                  password TEXT, 
                  stripe_customer_id TEXT,
                  subscription_status TEXT,
                  created_at TIMESTAMP)''')
    conn.commit()
    conn.close()

def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

def verify_password(password, hashed):
    return bcrypt.checkpw(password.encode('utf-8'), hashed)

def signup_user(email, password):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    try:
        hashed = hash_password(password)
        c.execute("INSERT INTO users (email, password, subscription_status, created_at) VALUES (?, ?, ?, ?)",
                  (email, hashed, 'inactive', datetime.now()))
        conn.commit()
        conn.close()
        return True, "Account created! Please log in."
    except sqlite3.IntegrityError:
        conn.close()
        return False, "Email already registered."

def login_user(email, password):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT password, subscription_status FROM users WHERE email=?", (email,))
    result = c.fetchone()
    conn.close()
    if result and verify_password(password, result[0]):
        return True, result[1]  # status
    return False, None

def update_subscription(email, status, customer_id=None):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    if customer_id:
        c.execute("UPDATE users SET subscription_status=?, stripe_customer_id=? WHERE email=?", (status, customer_id, email))
    else:
        c.execute("UPDATE users SET subscription_status=? WHERE email=?", (status, email))
    conn.commit()
    conn.close()

def get_user_status(email):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT subscription_status FROM users WHERE email=?", (email,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 'inactive'

# ------------------------------------------------------------
# 3. STRIPE PAYMENT FUNCTIONS
# ------------------------------------------------------------
def create_checkout_session(email):
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': MONTHLY_PRICE_ID,
                'quantity': 1,
            }],
            mode='subscription',
            success_url='http://localhost:8501/?success=true',
            cancel_url='http://localhost:8501/?canceled=true',
            customer_email=email,
        )
        return checkout_session.url
    except Exception as e:
        st.error(f"Stripe error: {e}")
        return None

def create_portal_session(email):
    # For managing subscription (cancel/upgrade)
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT stripe_customer_id FROM users WHERE email=?", (email,))
    result = c.fetchone()
    conn.close()
    if result and result[0]:
        try:
            session = stripe.billing_portal.Session.create(
                customer=result[0],
                return_url='http://localhost:8501/'
            )
            return session.url
        except:
            return None
    return None

# ------------------------------------------------------------
# 4. THE ACTUAL INVENTORY AI ENGINE (YOUR EXISTING LOGIC)
# ------------------------------------------------------------
def generate_demo_data():
    """Generates realistic demo data."""
    products = [
        {"name": "Coffee Beans", "base_price": 12.50, "cost": 6.00, "lead_time": 5},
        {"name": "Green Tea", "base_price": 8.00, "cost": 3.50, "lead_time": 4},
        {"name": "Bottled Water", "base_price": 1.20, "cost": 0.60, "lead_time": 3},
        {"name": "Protein Bars", "base_price": 4.50, "cost": 2.00, "lead_time": 6},
        {"name": "Hand Sanitiser", "base_price": 5.00, "cost": 2.50, "lead_time": 7},
    ]
    data = []
    for p in products:
        stock = random.randint(20, 300)
        prev_cost = p["cost"] * random.uniform(0.85, 1.10)
        base_sales = random.randint(5, 40)
        sales = [max(0, int(base_sales + np.random.normal(0, 5))) for _ in range(30)]
        trend = random.uniform(-1.5, 1.5)
        for i in range(30):
            sales[i] = max(0, sales[i] + int(trend * i * 0.5))
        daily_sales = ",".join(map(str, sales))
        data.append({
            "product_name": p["name"],
            "current_stock": stock,
            "selling_price": round(p["base_price"] * random.uniform(0.9, 1.1), 2),
            "cost_per_unit": round(p["cost"] * random.uniform(0.95, 1.05), 2),
            "previous_cost_per_unit": round(prev_cost, 2),
            "supplier_lead_time_days": p["lead_time"],
            "daily_sales": daily_sales
        })
    return pd.DataFrame(data)

def process_data(df):
    df = df.copy()
    df['sales_history'] = df['daily_sales'].apply(lambda x: [int(v) for v in x.split(',')] if isinstance(x, str) else [0])
    df['avg_daily_demand'] = df['sales_history'].apply(lambda h: np.mean(h[-7:]) if len(h)>=7 else np.mean(h) if len(h)>0 else 0)
    def calc_trend(h):
        if len(h)<3: return 0.0
        return np.polyfit(np.arange(len(h)), h, 1)[0]
    df['demand_trend'] = df['sales_history'].apply(calc_trend)
    df['days_of_stock'] = df.apply(lambda r: r['current_stock']/r['avg_daily_demand'] if r['avg_daily_demand']>0 else 999, axis=1)
    df['reorder_point'] = df.apply(lambda r: r['avg_daily_demand']*(r['supplier_lead_time_days']+2), axis=1)
    df['stock_value'] = df['current_stock']*df['cost_per_unit']
    df['profit_margin'] = (df['selling_price']-df['cost_per_unit'])/df['selling_price']*100
    df['is_dead'] = df['sales_history'].apply(lambda h: all(v==0 for v in h[-10:]) if len(h)>=10 else False)
    if 'previous_cost_per_unit' in df.columns:
        df['price_hike_pct'] = (df['cost_per_unit']-df['previous_cost_per_unit'])/df['previous_cost_per_unit']*100
        df['price_hike'] = df['price_hike_pct'] > 3
    else:
        df['price_hike'] = False
        df['price_hike_pct'] = 0
    return df

def generate_alerts(df):
    alerts = []
    for _, row in df.iterrows():
        if row['current_stock'] < row['reorder_point']:
            alerts.append({"priority":"🔴 HIGH","title":f"{row['product_name']} - Low Stock","desc":f"{row['days_of_stock']:.1f} days left.","impact":f"Order {int(row['reorder_point']*1.5)-row['current_stock']} units"})
        if row['days_of_stock'] > 90 and row['avg_daily_demand']>0:
            alerts.append({"priority":"🟡 MEDIUM","title":f"{row['product_name']} - Overstocked","desc":f"{row['days_of_stock']:.0f} days of stock.","impact":f"R{row['stock_value']:.2f} tied up"})
        if row['demand_trend'] < -0.5:
            alerts.append({"priority":"🟡 MEDIUM","title":f"{row['product_name']} - Demand Declining","desc":f"Trend: {row['demand_trend']:.2f} units/day.","impact":"Future revenue at risk"})
        if row['price_hike']:
            alerts.append({"priority":"🔴 HIGH","title":f"{row['product_name']} - Price Hike!","desc":f"Cost increased {row['price_hike_pct']:.1f}%","impact":f"R{row['cost_per_unit']*row['avg_daily_demand']*365*(row['price_hike_pct']/100):.2f} extra cost/year"})
    dead_total = df[df['is_dead']]['stock_value'].sum()
    if dead_total>0:
        alerts.append({"priority":"🔴 HIGH","title":"Dead Stock Detected","desc":f"R{dead_total:.2f} tied up in non-moving items.","impact":"Wasted capital"})
    return alerts

# ------------------------------------------------------------
# 5. AUTH UI (Login / Signup)
# ------------------------------------------------------------
def auth_page():
    st.subheader(f"🔐 Welcome to {APP_NAME}")
    st.markdown("Sign up to start your free trial or log in.")
    
    choice = st.radio("", ["Login", "Sign Up"])
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    
    if choice == "Sign Up":
        if st.button("Create Account"):
            if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
                st.error("Invalid email")
            elif len(password) < 6:
                st.error("Password must be at least 6 characters")
            else:
                ok, msg = signup_user(email, password)
                if ok:
                    st.success(msg)
                    st.info("Please switch to 'Login' tab and log in.")
                else:
                    st.error(msg)
    else:
        if st.button("Log In"):
            ok, status = login_user(email, password)
            if ok:
                st.session_state['logged_in'] = True
                st.session_state['user_email'] = email
                st.session_state['user_status'] = status
                st.rerun()
            else:
                st.error("Invalid credentials")

# ------------------------------------------------------------
# 6. MAIN DASHBOARD (Locked behind Paywall)
# ------------------------------------------------------------
def main_dashboard():
    st.title(f"🧠 {APP_NAME}")
    st.caption("Your AI-powered inventory & money leak detector.")

    # ---- Subscription Status ----
    status = get_user_status(st.session_state['user_email'])
    
    col_status, col_button = st.columns([3, 1])
    with col_status:
        if status == 'active':
            st.success(f"✅ Active Subscription | Logged in as {st.session_state['user_email']}")
        else:
            st.warning("🚫 Free Trial / Inactive. Subscribe to unlock full AI insights.")
    with col_button:
        if st.button("🚪 Logout"):
            st.session_state['logged_in'] = False
            st.rerun()

    # ---- Paywall Logic ----
    if status != 'active':
        st.info("You are viewing a preview. Your data is analyzed, but you need an active subscription to see detailed alerts and leaks.")
        # Show limited preview or full data? Let's show full data but nag them, OR just show everything to demo.
        # Since they are testing, we will show everything but put a subtle "Subscribe" watermark.
        st.caption("🔒 Subscribe below to support this AI and unlock unlimited usage.")
    else:
        st.success("🔓 Full access granted. Here is your detailed breakdown.")

    # --- Data Loading (currently demo only, but you can add CSV upload for paying users) ---
    df = generate_demo_data()
    df_processed = process_data(df)
    alerts = generate_alerts(df_processed)

    # --- Metrics ---
    col1, col2, col3, col4 = st.columns(4)
    with col1: st.metric("💰 Inventory Value", f"R{df_processed['stock_value'].sum():,.2f}")
    with col2: st.metric("⚠️ Alerts", len(alerts), delta="Urgent" if len([a for a in alerts if 'HIGH' in a['priority']])>0 else None)
    with col3: st.metric("🧊 Dead Stock", f"R{df_processed[df_processed['is_dead']]['stock_value'].sum():,.2f}")
    with col4: st.metric("📈 Avg Margin", f"{df_processed['profit_margin'].mean():.1f}%")

    st.divider()

    # --- Alerts ---
    st.subheader("🚨 Alerts")
    if alerts:
        for alert in alerts[:5]:
            if "🔴" in alert['priority']:
                st.error(f"**{alert['priority']} – {alert['title']}**  \n{alert['desc']}  \n💸 {alert.get('impact','')}")
            else:
                st.warning(f"**{alert['priority']} – {alert['title']}**  \n{alert['desc']}  \n💸 {alert.get('impact','')}")
    else:
        st.success("All clear!")

    # --- Charts (Same as before) ---
    st.subheader("📊 Stock Overview")
    fig, ax = plt.subplots(figsize=(10, 4))
    products = df_processed['product_name']
    x = np.arange(len(products))
    ax.bar(x-0.2, df_processed['current_stock'], 0.4, label='Current Stock', color='skyblue')
    ax.bar(x+0.2, df_processed['reorder_point'], 0.4, label='Reorder Point', color='salmon')
    ax.set_xticks(x); ax.set_xticklabels(products, rotation=20)
    ax.legend(); ax.grid(axis='y', linestyle='--', alpha=0.7)
    st.pyplot(fig)

    # ---- STRIPE SUBSCRIPTION BUTTON (Only if inactive or expired) ----
    st.divider()
    st.subheader("💳 Monetize & Subscribe")
    
    if status == 'active':
        st.success("You are subscribed! Thank you for supporting BizBrain.")
        if st.button("Manage Subscription (Cancel/Update)"):
            url = create_portal_session(st.session_state['user_email'])
            if url:
                st.markdown(f"[Click here to manage your subscription]({url})")
            else:
                st.error("Could not load billing portal.")
    else:
        st.warning("Subscribe now to get full access and support development.")
        col_price, col_action = st.columns([1, 1])
        with col_price:
            st.markdown("**📦 Monthly Plan**  \nR499 / month  \n*Full access + priority support*")
        with col_action:
            if st.button("🔗 Subscribe with Stripe"):
                url = create_checkout_session(st.session_state['user_email'])
                if url:
                    st.markdown(f"Redirecting to checkout... [Click here if not redirected]({url})")
                    # We can't auto-redirect in Streamlit easily, so we provide a link.
                    st.info(f"Click the link to subscribe: {url}")
                else:
                    st.error("Failed to create checkout session. Check your Stripe keys.")

# ------------------------------------------------------------
# 7. APP ROUTER
# ------------------------------------------------------------
def main():
    init_db()

    # BYPASS LOGIN FOR DEMO - Remove this when going live
    st.session_state['logged_in'] = True

    if not st.session_state['logged_in']:
        auth_page()
        st.markdown("---")
        st.caption("By continuing, you agree to our Terms of Service.")
    else:
        main_dashboard()

if __name__ == "__main__":
    main()
