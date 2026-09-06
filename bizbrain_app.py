import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime

# Page config
st.set_page_config(page_title="BizBrain AI", layout="wide")

# Title
st.title("🤖 BizBrain AI")
st.write(f"Welcome to BizBrain AI! Today is {datetime.now().strftime('%B %d, %Y')}")

# Sidebar
with st.sidebar:
    st.header("⚙️ Settings")
    user_input = st.text_input("Ask BizBrain a question:")
    if st.button("🚀 Ask BizBrain"):
        st.session_state['last_question'] = user_input

# Main content - 3 columns
col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("📊 Data Analytics")
    st.write("Upload your data and get insights instantly.")
    
with col2:
    st.subheader("🤖 AI Assistant")
    st.write("Ask questions and get AI-powered answers.")
    
with col3:
    st.subheader("📈 Visualizations")
    st.write("Create beautiful charts with one click.")

# Show last question if exists
if 'last_question' in st.session_state and st.session_state['last_question']:
    st.info(f"💡 You asked: '{st.session_state['last_question']}'")

# Sample chart
st.subheader("📊 Sample Data Visualization")
data = pd.DataFrame({
    'Category': ['A', 'B', 'C', 'D', 'E'],
    'Value': np.random.randint(10, 100, 5)
})

fig, ax = plt.subplots()
ax.bar(data['Category'], data['Value'], color='skyblue')
ax.set_title('Sample Business Data')
ax.set_xlabel('Category')
ax.set_ylabel('Value')
st.pyplot(fig)

# Sample data table
st.subheader("📋 Sample Data")
st.dataframe(pd.DataFrame(
    np.random.randn(10, 4),
    columns=['Revenue', 'Cost', 'Profit', 'Growth']
))

# Footer
st.caption("🚀 BizBrain AI is running successfully on Streamlit Cloud!")
