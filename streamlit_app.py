import os
import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta, timezone

API_BASE = os.getenv("API_BASE", "").rstrip("/")  # e.g. https://labinventoryv20-production.up.railway.app
if not API_BASE:
    # When deployed as a separate Railway service, set API_BASE in Variables.
    st.warning("Missing API_BASE. Set it in Railway Variables to your FastAPI URL.")
    st.stop()

st.set_page_config(page_title="Lab Inventory v3.0", layout="wide")

@st.cache_data(ttl=30)
def fetch_inventory(token: str):
    r = requests.get(f"{API_BASE}/inventory", headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    return r.json()

def login(username: str, password: str):
    r = requests.post(f"{API_BASE}/auth/login", json={"username": username, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]

def parse_date_safe(x):
    if x is None or x == "":
        return None
    try:
        return pd.to_datetime(x).date()
    except Exception:
        return None

st.title("Lab Reagent Inventory v3.0")

with st.sidebar:
    st.header("Login")
    u = st.text_input("Username")
    p = st.text_input("Password", type="password")
    if st.button("Sign in"):
        try:
            token = login(u, p)
            st.session_state["token"] = token
            st.success("Logged in")
        except Exception as e:
            st.error(f"Login failed: {e}")

token = st.session_state.get("token")
if not token:
    st.info("Please login in the sidebar.")
    st.stop()

try:
    data = fetch_inventory(token)
except Exception as e:
    st.error(f"Failed to load inventory: {e}")
    st.stop()

df = pd.DataFrame(data)

# ---- Metrics (adjust column names to match your schema) ----
# Common fields in lab inventory: Quantity, MinStock/SafetyStock, ExpirationDate
qty_col_candidates = ["quantity", "Quantity", "qty", "Qty"]
exp_col_candidates = ["expiration", "Expiration", "expiry", "Expiry", "expiration_date", "ExpirationDate"]
min_col_candidates = ["min_stock", "MinStock", "safety_stock", "SafetyStock", "min", "Min"]

def pick_col(cands):
    for c in cands:
        if c in df.columns:
            return c
    return None

qty_col = pick_col(qty_col_candidates)
exp_col = pick_col(exp_col_candidates)
min_col = pick_col(min_col_candidates)

total = len(df)

low_stock = 0
if qty_col and min_col:
    low_stock = (pd.to_numeric(df[qty_col], errors="coerce").fillna(0) < pd.to_numeric(df[min_col], errors="coerce").fillna(0)).sum()

expiring_30 = 0
if exp_col:
    today = datetime.now().date()
    cutoff = today + timedelta(days=30)
    exp_dates = df[exp_col].apply(parse_date_safe)
    expiring_30 = exp_dates.apply(lambda d: d is not None and today <= d <= cutoff).sum()

c1, c2, c3 = st.columns(3)
c1.metric("Total Reagents", total)
c2.metric("Low Stock", int(low_stock))
c3.metric("Expiring ≤30d", int(expiring_30))

st.divider()

# ---- Search / filters ----
search = st.text_input("Search (name/vendor/catalog/etc.)").strip().lower()
filtered = df.copy()
if search:
    mask = filtered.astype(str).apply(lambda row: row.str.lower().str.contains(search, na=False)).any(axis=1)
    filtered = filtered[mask]

st.subheader("Inventory (editable)")
edited = st.data_editor(
    filtered,
    use_container_width=True,
    num_rows="dynamic",
    hide_index=True
)

st.caption("Edits are local until you click Save.")

if st.button("Save changes (v3.0 beta)"):
    st.warning("Next step: wire this to your FastAPI update endpoints (PUT/PATCH). Tell me your update endpoint and schema and I’ll plug it in cleanly.")