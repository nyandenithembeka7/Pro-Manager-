#!/usr/bin/env python3
"""
BizBrain AI - Complete Working Version
Run with: streamlit run bizbrain_app.py
"""

import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import random
import sqlite3
import hashlib
import os

# ============================================================
# 1. PAGE CONFIGURATION
# ============================================================
st.set_page_config(
    page_title="BizBrain AI",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================
# 2. DATABASE SETUP (Auto-creates tables)
# ============================================================
def init_db():
    """Initialize SQLite database with tables"""
    conn = sqlite3.connect('bizbrain.db')
    c = conn.cursor()
    
    # Users table
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            subscription_status TEXT DEFAULT 'free',
            subscription_end DATE
        )
    ''')
    
    # Business data table
    c.execute('''
        CREATE TABLE IF NOT EXISTS business_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            revenue REAL,
            costs REAL,
            profit REAL,
            customers INTEGER,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # AI queries log
    c.execute('''
        CREATE TABLE IF NOT EXISTS ai_queries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            query TEXT,
            response TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.commit()
    conn.close()

# ============================================================
# 3. USER MANAGEMENT (Simplified)
# ============================================================
def hash_password(password):
    """Hash password for storage"""
    return hashlib.sha256(password.encode()).hexdigest()

def create_user(username, email, password):
    """Create a new user"""
    conn = sqlite3.connect('bizbrain.db')
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
            (username, email, hash_password(password))
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def login_user(email, password):
    """Authenticate user"""
    conn = sqlite3.connect('bizbrain.db')
    c = conn.cursor()
    c.execute(
        "SELECT id, username, email, subscription_status FROM users WHERE email = ? AND password = ?",
        (email, hash_password(password))
    )
    user = c.fetchone()
    conn.close()
    return user

def get_user_status(email):
    """Get user's subscription status"""
    conn = sqlite3.connect('bizbrain.db')
    c = conn.cursor()
    c.execute(
        "SELECT subscription_status, subscription_end FROM users WHERE email = ?",
        (email,)
    )
    result = c.fetchone()
    conn.close()
    if result:
        return {"status": result[0], "end_date": result[1]}
    return {"status": "free", "end_date": None}

# ============================================================
# 4. AUTHENTICATION PAGE
# ============================================================
def auth_page():
    """Login/Signup page"""
    st.title("🤖 BizBrain AI")
    st.write("Welcome! Please login or sign up to continue.")
    
    tab1, tab2 = st.tabs(["🔐 Login", "📝 Sign Up"])
    
    with tab1:
        st.subheader("Login")
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")
        
        if st.button("Login", key="login_btn"):
            if email and password:
                user = login_user(email, password)
                if user:
                    st.session_state['logged_in'] = True
                    st.session_state['user_id'] = user[0]
                    st.session_state['username'] = user[1]
                    st.session_state['user_email'] = user[2]
                    st.session_state['user_status'] = user[3]
                    st.rerun()
                else:
                    st.error("❌ Invalid email or password")
            else:
                st.warning("Please fill in all fields")
    
    with tab2:
        st.subheader("Create Account")
        new_username = st.text_input("Username", key="signup_username")
        new_email = st.text_input("Email", key="signup_email")
        new_password = st.text_input("Password", type="password", key="signup_password")
        confirm_password = st.text_input("Confirm Password", type="password", key="signup_confirm")
        
        if st.button("Sign Up", key="signup_btn"):
            if new_password != confirm_password:
                st.error("❌ Passwords don't match")
            elif len(new_password) < 6:
                st.warning("Password must be at least 6 characters")
            elif new_username and new_email and new_password:
                if create_user(new_username, new_email, new_password):
                    st.success("✅ Account created! Please login.")
                    st.info("Your default subscription is FREE - enjoy!")
                else:
                    st.error("❌ Username or email already exists")

# ============================================================
# 5. MAIN DASHBOARD
# ============================================================
def main_dashboard():
    """Main app dashboard"""
    
    # Header with user info
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.title("🤖 BizBrain AI")
    with col2:
        st.write(f"👤 {st.session_state.get('username', 'User')}")
    with col3:
        status = st.session_state.get('user_status', 'free')
        if status == 'premium':
            st.success("⭐ Premium")
        else:
            st.info("💠 Free")
        
        if st.button("🚪 Logout"):
            for key in ['logged_in', 'user_id', 'username', 'user_email', 'user_status']:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()
    
    st.divider()
    
    # ============================================================
    # FEATURE 1: AI Assistant
    # ============================================================
    st.subheader("🧠 AI Business Assistant")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        user_question = st.text_input("Ask BizBrain anything about your business:")
    with col2:
        st.write("")
        st.write("")
        if st.button("🚀 Ask AI", use_container_width=True):
            if user_question:
                # Simulated AI response (replace with real API later)
                responses = [
                    f"Based on your query '{user_question}', I recommend analyzing your customer retention metrics and focusing on high-value segments.",
                    f"Great question! For '{user_question}', consider using a SWOT analysis to identify opportunities in your market.",
                    f"BizBrain suggests: For '{user_question}', the optimal strategy would be to leverage data-driven decision making.",
                    f"Interesting! Regarding '{user_question}', I'd recommend A/B testing different approaches to find what works best."
                ]
                st.info(f"💡 {random.choice(responses)}")
                
                # Log query
                conn = sqlite3.connect('bizbrain.db')
                c = conn.cursor()
                c.execute(
                    "INSERT INTO ai_queries (user_id, query, response) VALUES (?, ?, ?)",
                    (st.session_state.get('user_id', 1), user_question, "Simulated response")
                )
                conn.commit()
                conn.close()
    
    # ============================================================
    # FEATURE 2: Business Analytics
    # ============================================================
    st.subheader("📊 Business Analytics")
    
    # Generate sample data
    dates = pd.date_range(start='2024-01-01', periods=12, freq='M')
    revenue = np.random.randint(10000, 50000, 12)
    costs = np.random.randint(5000, 25000, 12)
    profit = revenue - costs
    
    df = pd.DataFrame({
        'Month': dates.strftime('%b %Y'),
        'Revenue': revenue,
        'Costs': costs,
        'Profit': profit
    })
    
    # Metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("💰 Total Revenue", f"${df['Revenue'].sum():,}")
    with col2:
        st.metric("📉 Total Costs", f"${df['Costs'].sum():,}")
    with col3:
        st.metric("📈 Total Profit", f"${df['Profit'].sum():,}")
    with col4:
        profit_margin = (df['Profit'].sum() / df['Revenue'].sum()) * 100
        st.metric("📊 Profit Margin", f"{profit_margin:.1f}%")
    
    # Chart
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df['Month'], df['Revenue'], marker='o', label='Revenue', linewidth=2)
    ax.plot(df['Month'], df['Costs'], marker='s', label='Costs', linewidth=2)
    ax.plot(df['Month'], df['Profit'], marker='^', label='Profit', linewidth=2)
    ax.set_xlabel('Month')
    ax.set_ylabel('Amount ($)')
    ax.set_title('Business Performance Overview')
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    st.pyplot(fig)
    
    # Data table
    st.dataframe(df, use_container_width=True)
    
    # ============================================================
    # FEATURE 3: Data Upload & Processing
    # ============================================================
    st.subheader("📁 Upload & Analyze Data")
    
    uploaded_file = st.file_uploader("Upload CSV file for analysis", type=['csv'])
    if uploaded_file is not None:
        try:
            uploaded_df = pd.read_csv(uploaded_file)
            st.success(f"✅ File loaded! {len(uploaded_df)} rows, {len(uploaded_df.columns)} columns")
            st.dataframe(uploaded_df.head(10), use_container_width=True)
            
            # Quick stats
            if st.button("📊 Generate Statistics"):
                st.subheader("Quick Statistics")
                st.dataframe(uploaded_df.describe(), use_container_width=True)
                
                # Auto-visualize numeric columns
                numeric_cols = uploaded_df.select_dtypes(include=[np.number]).columns
                if len(numeric_cols) > 0:
                    col_to_plot = st.selectbox("Select column to visualize:", numeric_cols)
                    if col_to_plot:
                        fig2, ax2 = plt.subplots(figsize=(8, 4))
                        uploaded_df[col_to_plot].hist(bins=30, ax=ax2)
                        ax2.set_title(f'Distribution of {col_to_plot}')
                        st.pyplot(fig2)
        except Exception as e:
            st.error(f"Error reading file: {e}")
    
    # ============================================================
    # FEATURE 4: Reports & Export
    # ============================================================
    with st.expander("📄 Generate Report"):
        st.write("Generate a summary report of your business data")
        report_type = st.selectbox("Report Type:", ["Monthly Summary", "Revenue Analysis", "Customer Insights"])
        if st.button("📋 Generate Report"):
            st.info(f"📄 Generated {report_type} report successfully!")
            st.download_button(
                label="📥 Download Report (CSV)",
                data=df.to_csv(index=False).encode('utf-8'),
                file_name=f"bizbrain_report_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )

# ============================================================
# 6. APP ROUTER
# ============================================================
def main():
    # Initialize database
    init_db()
    
    # BYPASS LOGIN FOR DEMO - Remove these lines when going live
    st.session_state['logged_in'] = True
    st.session_state['user_id'] = 1
    st.session_state['username'] = "Demo User"
    st.session_state['user_email'] = "demo@bizbrain.ai"
    st.session_state['user_status'] = "free"
    
    # Check if user is logged in
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
    
    if not st.session_state['logged_in']:
        auth_page()
        st.markdown("---")
        st.caption("By continuing, you agree to our Terms of Service.")
    else:
        main_dashboard()

if __name__ == "__main__":
    main()
