#!/usr/bin/env python3
"""
Pro Manager - AI Business Manager (with 30-Day Free Trial)
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
# 1. CONFIGURATION
# ------------------------------------------------------------
APP_NAME = "Pro Manager"  # <-- NEW NAME!
st.set_page_config(page_title=APP_NAME, layout="wide", page_icon="🧠")

# ---- STRIPE CONFIGURATION (Replace with your live keys later) ----
STRIPE_PUBLISHABLE_KEY = "pk_test_..."  # From Stripe Dashboard
STRIPE_SECRET_KEY = "sk_test_..."       # From Stripe Dashboard
stripe.api_key = STRIPE_SECRET_KEY

# Your Stripe Price ID (Create this in Stripe Dashboard)
MONTHLY_PRICE_ID = "price_123456789"    # Replace with your actual Price ID

# ------------------------------------------------------------
# 2. DATABASE SETUP (with Trial Support)
# ------------------------------------------------------------
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    # Added trial_end_date column
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (email TEXT PRIMARY KEY, 
                  password TEXT, 
                  stripe_customer_id TEXT,
                  subscription_status TEXT,  -- 'active', 'trialing', 'inactive'
                  created_at TIMESTAMP,
                  trial_end_date TIMESTAMP)''')
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
        trial_end = datetime.now() + timedelta(days=30)  # 30-day free trial
        c.execute("INSERT INTO users (email, password, subscription_status, created_at, trial_end_date) VALUES (?, ?, ?, ?, ?)",
                  (email, hashed, 'trialing', datetime.now(), trial_end))
        conn.commit()
        conn.close()
        return True, f"Account created! Your 30-day free trial starts now. Ends on {trial_end.strftime('%Y-%m-%d')}."
    except sqlite3.IntegrityError:
        conn.close()
        return False, "Email already registered."

def get_user(email):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT password, subscription_status, trial_end_date FROM users WHERE email=?", (email,))
    result = c.fetchone()
    conn.close()
    return result

def login_user(email, password):
    user = get_user(email)
    if user and verify_password(password, user[0]):
        status = user[1]
        trial_end = datetime.strptime(user[2], '%Y-%m-%d %H:%M:%S.%f') if user[2] else None
        
        # --- Check if trial has expired ---
        if status == 'trialing' and trial_end and datetime.now() > trial_end:
            # Automatically expire the trial
            conn = sqlite3.connect('users.db')
            c = conn.cursor()
            c.execute("UPDATE users SET subscription_status='inactive' WHERE email=?", (email,))
            conn.commit()
            conn.close()
            status = 'inactive'
            return True, 'inactive'
        
        return True, status
    return False, None

def update_subscription(email, status, customer_id=None):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    if customer_id:
        c.execute("UPDATE users SET subscription_status=?, stripe_customer_id=? WHERE email=?", (status, customer_id, email))
    else:
        c.execute("UPDATE users SET subscription_status=? WHERE email=?", (status, email))
    # Clear trial end date if they become active
    if status == 'active':
        c.execute("UPDATE users SET trial_end_date=NULL WHERE email=?", (email,))
    conn.commit()
    conn.close()

def get_user_status(email):
    user = get_user(email)
    if not user:
        return 'inactive'
    status = user[1]
    trial_end = datetime.strptime(user[2], '%Y-%m-%d %H:%M:%S.%f') if user[2] else None
    
    # Auto-expire if trial ended
    if status == 'trialing' and trial_end and datetime.now() > trial_end:
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute("UPDATE users SET subscription_status='inactive' WHERE email=?", (email,))
        conn.commit()
        conn.close()
        return 'inactive'
    
    return status

def get_trial_days_left(email):
    user = get_user(email)
    if not user:
        return 0
    trial_end = datetime.strptime(user[2], '%Y-%m-%d %H:%M:%S.%f') if user[2] else None
    if trial_end:
        remaining = (trial_end - datetime.now()).days
        return max(0, remaining)
    return 0

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
# 4. INVENTORY AI ENGINE (Same as before)
# ------------------------------------------------------------
def generate_demo_data():
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
    st.markdown("**Start your 30-day free trial today.** No credit card required.")
    
    choice = st.radio("", ["Login", "Sign Up"])
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    
    if choice == "Sign Up":
        if st.button("🚀 Start Free Trial"):
            if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
                st.error("Invalid email")
            elif len(password) < 6:
                st.error("Password must be at least 6 characters")
            else:
                ok, msg = signup_user(email, password)
                if ok:
                    st.success(msg)
                    st.info("✅ Account created! Please switch to 'Login' and sign in to access your dashboard.")
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
# 6. MAIN DASHBOARD (with Trial Banner)
# ------------------------------------------------------------
def main_dashboard():
    st.title(f"🧠 {APP_NAME}")
    st.caption("AI-powered inventory & money leak detection.")

    # --- Check User Status & Trial ---
    email = st.session_state['user_email']
    status = get_user_status(email)
    trial_days = get_trial_days_left(email)
    
    # --- Status Bar ---
    col_status, col_button = st.columns([3, 1])
    with col_status:
        if status == 'active':
            st.success(f"✅ Active Subscription | Logged in as {email}")
        elif status == 'trialing':
            st.warning(f"🔓 Free Trial: {trial_days} days remaining | Logged in as {email}")
        else:
            st.error(f"🚫 Subscription Inactive | Logged in as {email}")
    with col_button:
        if st.button("🚪 Logout"):
            st.session_state['logged_in'] = False
            st.rerun()

    # --- PAYWALL: If inactive, block access ---
    if status == 'inactive':
        st.divider()
        st.error("❌ Your free trial has expired or you have no active subscription.")
        st.markdown("Subscribe now to regain access to your AI business manager.")
        
        col_price, col_action = st.columns([1, 1])
        with col_price:
            st.markdown("**📦 Monthly Plan**  \nR499 / month  \n*Full access + priority support*")
        with col_action:
            if st.button("🔗 Subscribe Now (Stripe)"):
                url = create_checkout_session(email)
                if url:
                    st.markdown(f"Redirecting... [Click here if not redirected]({url})")
                    st.info(f"Click the link to subscribe: {url}")
                else:
                    st.error("Failed to create checkout session. Check your Stripe keys.")
        st.stop()  # Stop rendering the dashboard
    
    # --- If Active or Trialing: Show Full Dashboard ---
    if status == 'trialing':
        st.info(f"🎉 You are on a {trial_days}-day free trial. No charges yet. Subscribe anytime to keep access after {trial_days} days.")
    
    # --- Data & Analysis ---
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

    # --- Stock Chart ---
    st.subheader("📊 Stock Overview")
    fig, ax = plt.subplots(figsize=(10, 4))
    products = df_processed['product_name']
    x = np.arange(len(products))
    ax.bar(x-0.2, df_processed['current_stock'], 0.4, label='Current Stock', color='skyblue')
    ax.bar(x+0.2, df_processed['reorder_point'], 0.4, label='Reorder Point', color='salmon')
    ax.set_xticks(x); ax.set_xticklabels(products, rotation=20)
    ax.legend(); ax.grid(axis='y', linestyle='--', alpha=0.7)
    st.pyplot(fig)

    # ------------------------------------------------------------
    # NEW: PITCH MODE - Upload Purchase Orders vs Sales
    # ------------------------------------------------------------
    st.divider()
    st.subheader("📊 Pitch Mode: Audit Your Orders (Compare AI vs Reality)")
    st.caption("Upload your actual purchase orders. The AI will tell you exactly how much money you wasted on over-ordering or lost on under-ordering.")
    
    col_pitch1, col_pitch2 = st.columns(2)
    
    with col_pitch1:
        sales_file = st.file_uploader("1. Upload Sales History (CSV)", type=["csv"], key="sales_audit")
        st.caption("Columns: product_name, quantity_sold, date")
        
    with col_pitch2:
        orders_file = st.file_uploader("2. Upload Purchase Orders (CSV)", type=["csv"], key="orders_audit")
        st.caption("Columns: product_name, quantity_ordered, cost_per_unit, date")
    
    if sales_file and orders_file:
        try:
            sales_df = pd.read_csv(sales_file)
            orders_df = pd.read_csv(orders_file)
            
            total_sold = sales_df.groupby('product_name')['quantity_sold'].sum().reset_index()
            total_ordered = orders_df.groupby('product_name')['quantity_ordered'].sum().reset_index()
            costs = orders_df.groupby('product_name')['cost_per_unit'].first().reset_index()
            
            comparison = pd.merge(total_sold, total_ordered, on='product_name', how='outer').fillna(0)
            comparison = pd.merge(comparison, costs, on='product_name', how='left').fillna(0)
            
            comparison['ai_suggested_order'] = comparison['quantity_sold'] * 1.15
            comparison['over_ordered'] = comparison['quantity_ordered'] - comparison['ai_suggested_order']
            comparison['under_ordered'] = comparison['ai_suggested_order'] - comparison['quantity_ordered']
            comparison['waste_units'] = comparison['over_ordered'].apply(lambda x: max(0, x))
            comparison['lost_units'] = comparison['under_ordered'].apply(lambda x: max(0, x))
            comparison['waste_cost'] = comparison['waste_units'] * comparison['cost_per_unit']
            comparison['lost_revenue'] = comparison['lost_units'] * (comparison['cost_per_unit'] * 1.5)
            
            total_waste = comparison['waste_cost'].sum()
            total_lost_sales = comparison['lost_revenue'].sum()
            total_impact = total_waste + total_lost_sales
            
            st.success(f"✅ Audit Complete! AI found a total potential leak of **R{total_impact:,.2f}** in this period.")
            
            st.dataframe(
                comparison[['product_name', 'quantity_sold', 'quantity_ordered', 'ai_suggested_order', 
                            'waste_units', 'lost_units', 'waste_cost', 'lost_revenue']],
                column_config={
                    "product_name": "Product",
                    "quantity_sold": "Actual Sales",
                    "quantity_ordered": "You Bought",
                    "ai_suggested_order": "AI Suggested",
                    "waste_units": "Over-Ordered (Waste)",
                    "lost_units": "Under-Ordered (Lost Sales)",
                    "waste_cost": st.column_config.NumberColumn("Wasted Money", format="R%.2f"),
                    "lost_revenue": st.column_config.NumberColumn("Lost Revenue", format="R%.2f"),
                }
            )
            
            biggest_leak = comparison.loc[comparison['waste_cost'].idxmax()] if comparison['waste_cost'].max() > 0 else None
            if biggest_leak is not None and biggest_leak['waste_cost'] > 0:
                st.error(f"🔴 **Biggest Waste:** {biggest_leak['product_name']} | You wasted R{biggest_leak['waste_cost']:.2f} by over-ordering {int(biggest_leak['waste_units'])} units.")
            
            st.markdown("---")
            st.success("**Pitch Script:** *'This is exactly what my AI does automatically every day. It stops you from throwing away money on products you don't need and makes sure you never run out of what sells. I can set this up for you permanently for R499/month.'*")
            
        except Exception as e:
            st.error(f"Error processing files: {e}. Make sure the CSV columns are named correctly.")
    else:
        st.info("Upload both files to see how much money you are currently leaking.")

    # ---- STRIPE SUBSCRIPTION BUTTON (for users who want to upgrade from trial) ----
    st.divider()
    st.subheader("💳 Upgrade to Paid Plan")
    
    if status == 'active':
        st.success("✅ You are subscribed! Thank you for supporting Pro Manager.")
        if st.button("Manage Subscription (Cancel/Update)"):
            url = create_portal_session(email)
            if url:
                st.markdown(f"[Click here to manage your subscription]({url})")
            else:
                st.error("Could not load billing portal.")
    else:
        st.info("Your free trial is active. Upgrade now to support the platform and get priority support.")
        col_price, col_action = st.columns([1, 1])
        with col_price:
            st.markdown("**📦 Monthly Plan**  \nR499 / month  \n*Full access + priority support*")
        with col_action:
            if st.button("🔗 Subscribe with Stripe"):
                url = create_checkout_session(email)
                if url:
                    st.markdown(f"Redirecting to checkout... [Click here if not redirected]({url})")
                    st.info(f"Click the link to subscribe: {url}")
                else:
                    st.error("Failed to create checkout session. Check your Stripe keys.")

# ------------------------------------------------------------
# 7. APP ROUTER
# ------------------------------------------------------------
def main():
    init_db()
    
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
    
    if not st.session_state['logged_in']:
        auth_page()
        st.markdown("---")
        st.caption("By continuing, you agree to our Terms of Service. 30-day free trial, cancel anytime.")
    else:
        main_dashboard()

if __name__ == "__main__":
    main()
