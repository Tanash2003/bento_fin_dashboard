import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


# ---------- Helpers to clean your specific Excel structure ----------

def load_sheets(uploaded_file):
    return pd.read_excel(uploaded_file, sheet_name=None)


def parse_assumptions(df):
    """
    Uses your existing layout:
    - Market size is stored in the second column name (e.g. 250000)
    - Penetration year 1–3 and user base are in the first few rows
    - Monthly customer growth is in a later row
    """
    if df is None or df.empty:
        return {
            "market_size": None,
            "penetration": {},
            "user_base": {},
            "monthly_growth": None,
        }

    # Try to read market size from the second column header
    market_size = None
    if len(df.columns) > 1:
        try:
            market_size = float(df.columns[1])
        except Exception:
            market_size = None

    penetration = {}
    user_base = {}

    # Read first 3 rows for penetration + user base
    for i in range(3):
        try:
            row = df.iloc[i]
        except IndexError:
            continue

        # Use positional indexing on the Series, not label-based
        try:
            label = str(row.iloc[0])
        except Exception:
            label = ""

        try:
            pen = row.iloc[1]
        except Exception:
            pen = None

        # Try to pick user base from the last column if explicit "User base" col not found
        if "User base" in df.columns:
            users = row.get("User base", None)
        else:
            try:
                users = row.iloc[-1]
            except Exception:
                users = None

        if "Penetration year 1" in label:
            penetration[1] = pen
            user_base[1] = users
        elif "Penetration year 2" in label:
            penetration[2] = pen
            user_base[2] = users
        elif "Penetration year 3" in label:
            penetration[3] = pen
            user_base[3] = users

    # Monthly growth rate (keep try/except so it doesn't crash if row layout changes)
    monthly_growth = None
    try:
        monthly_growth = df.iloc[12, 1]
    except Exception:
        monthly_growth = None

    return {
        "market_size": market_size,
        "penetration": penetration,
        "user_base": user_base,
        "monthly_growth": monthly_growth,
    }



def parse_unit_economics(df):
    """
    Your sheet layout:

    Row 1: Monthly orders, order value, commission, Revenue per customer
    Row 3–6: per-order costs (gateway, support, refund, infra)
    Row 8–10: revenue per order, variable cost per order, contribution per order
    Row 12: contribution per customer (per month)
    """
    out = {}

    try:
        out["monthly_orders"] = df.iloc[1, 0]
        out["order_value"] = df.iloc[1, 1]
        out["commission_rate"] = df.iloc[1, 2]
        out["revenue_per_customer"] = df.iloc[1, 3]
    except Exception:
        pass

    # per-order costs (stored in col 3)
    label_map = {
        "Payment gateway cost": "payment_gateway_per_order",
        "Customer support load": "support_per_order",
        "Refund buffer": "refund_per_order",
        "Infra": "infra_per_order",
    }
    for i in range(3, 7):
        label = str(df.iloc[i, 0])
        value = df.iloc[i, 3]
        for key, field in label_map.items():
            if key in label:
                out[field] = value

    # order-level and customer-level contribution
    try:
        out["revenue_per_order"] = df.iloc[8, 2]
        out["variable_cost_per_order"] = df.iloc[9, 2]
        out["contribution_per_order"] = df.iloc[10, 2]
    except Exception:
        pass

    try:
        out["contribution_per_customer"] = df.iloc[12, 2]
    except Exception:
        pass

    return out


def parse_revenue_monthly(df):
    """
    Parse the 'Revenue' sheet into a clean monthly table with a Year column.

    Layout:
    - Header row with column names
    - Then Year 1 Jan–Dec
    - Then Year 2 Jan–Dec
    - Then Year 3 Jan–Dec
    """
    if df is None or df.empty:
        return pd.DataFrame()

    header_row = 2
    df2 = df.iloc[header_row:, :6].copy()
    df2.columns = [
        "Month",
        "No. of customers",
        "Growth rate",
        "No. of orders",
        "GMV",
        "Revenue",
    ]

    valid_months = ["Jan","Feb","Mar","Apr","May",
                    "Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

    df2 = df2.dropna(subset=["Month"])
    df2 = df2[df2["Month"].isin(valid_months)]

    # Reset index so we can assign years in 12-row blocks
    df2 = df2.reset_index(drop=True)
    df2["Year"] = df2.index // 12 + 1   # 0–11 -> 1, 12–23 -> 2, 24–35 -> 3

    # Numeric casts
    for col in ["No. of customers", "Growth rate", "No. of orders", "GMV", "Revenue"]:
        df2[col] = pd.to_numeric(df2[col], errors="coerce")

    # Month ordering + numeric month
    df2["Month"] = pd.Categorical(df2["Month"],
                                  categories=valid_months,
                                  ordered=True)

    month_to_num = {m: i+1 for i, m in enumerate(valid_months)}
    df2["Month_num"] = df2["Month"].map(month_to_num).astype(int)

    # Continuous index across all years: 1..36
    df2["Month_index"] = (df2["Year"] - 1) * 12 + df2["Month_num"]

    # Nice label for x-axis: Y1-Jan, Y1-Feb, ...
    df2["Period"] = "Y" + df2["Year"].astype(str) + "-" + df2["Month"].astype(str)

    return df2





def parse_break_even(df):
    """
    'Break even analysis' structure in your file:

    Columns:
      - col[0]: "Total upfront cost (month zero)"
      - col[1]: -32500 (the actual upfront cost, as column header)
      - col[2]: "Unnamed: 2"

    Rows:
      - row 0–3: meta (mostly NaN in row 0, then labels)
      - row 4: ["Month", "Net profit", "Net cash"]
      - row 5+: data
    """
    if df is None or df.empty:
        return pd.DataFrame(), {
            "upfront_cost": None,
            "contribution_per_customer": None,
            "fixed_cost_monthly": None,
            "break_even_month": None,
        }

    # --- META VALUES ---
    upfront_cost = None
    contribution_per_customer = None
    fixed_cost_monthly = None

    # ✅ Upfront cost is stored in the SECOND column header (df.columns[1])
    try:
        upfront_cost = float(df.columns[1])
    except Exception:
        upfront_cost = None

    # Contribution per customer: row 1, col 1
    try:
        contribution_per_customer = float(df.iloc[1, 1])
    except Exception:
        contribution_per_customer = None

    # Expected fixed cost: row 2, col 1
    try:
        fixed_cost_monthly = float(df.iloc[2, 1])
    except Exception:
        fixed_cost_monthly = None

    # --- DATA TABLE ---
    df2 = df.iloc[4:].copy()
    df2.columns = ["Month", "Net profit", "Net cash"]
    df2 = df2.dropna(subset=["Month"])

    df2["Month"] = pd.to_numeric(df2["Month"], errors="coerce")
    df2["Net profit"] = pd.to_numeric(df2["Net profit"], errors="coerce")
    df2["Net cash"] = pd.to_numeric(df2["Net cash"], errors="coerce")
    df2 = df2.dropna(subset=["Month"])

    # Break-even month (first month where Net cash >= 0)
    be_month = None
    try:
        positive = df2[df2["Net cash"] >= 0]
        if not positive.empty:
            be_month = int(positive["Month"].iloc[0])
    except Exception:
        be_month = None

    return df2, {
        "upfront_cost": upfront_cost,
        "contribution_per_customer": contribution_per_customer,
        "fixed_cost_monthly": fixed_cost_monthly,
        "break_even_month": be_month,
    }



def parse_pnl(df):
    """
    'Projected P&L' is already nicely structured:

    Column 'Year' = metric labels
    Columns '1','2','3' = years 1–3
    """
    df2 = df.dropna(subset=["Year"]).copy()
    # ensure year cols are numeric
    year_cols = [c for c in df2.columns if c != "Year"]
    for c in year_cols:
        df2[c] = pd.to_numeric(df2[c], errors="coerce")
    df2 = df2.set_index("Year")

    # Quick access
    revenue = df2.loc["Revenue", year_cols] if "Revenue" in df2.index else None
    ebit = df2.loc["EBIT", year_cols] if "EBIT" in df2.index else None
    total_variable = df2.loc["Total variable cost", year_cols] if "Total variable cost" in df2.index else None
    total_fixed = df2.loc["Total fixed costs", year_cols] if "Total fixed costs" in df2.index else None

    # Melt for charting
    pnl_long = df2.reset_index().melt(
        id_vars="Year", var_name="Year_num", value_name="Value"
    )
    pnl_long["Year_num"] = pd.to_numeric(pnl_long["Year_num"], errors="coerce")

    return df2, pnl_long, {
        "revenue": revenue,
        "ebit": ebit,
        "total_variable": total_variable,
        "total_fixed": total_fixed,
        "year_cols": year_cols,
    }


# ---------- Streamlit App ----------

st.set_page_config(page_title="Bento Financial Dashboard", layout="wide")

st.title("📊 Financial Dashboard – Bento Model")

st.write(
    "Upload your `Financial model.xlsx` file (the one with sheets: "
    "`Assumptions`, `Revenue`, `Cost`, `Unit economics`, `Break even analysis`, `Projected P&L`)."
)

uploaded_file = st.file_uploader("Upload Excel file", type=["xlsx"])

if not uploaded_file:
    st.info("Upload the financial model Excel to see the dashboard.")
    st.stop()

# Load all sheets
sheets = load_sheets(uploaded_file)

# Parse each relevant sheet
assump = parse_assumptions(sheets.get("Assumptions"))
unit_eco = parse_unit_economics(sheets.get("Unit economics"))
rev_monthly = parse_revenue_monthly(sheets.get("Revenue"))
be_df, be_meta = parse_break_even(sheets.get("Break even analysis"))
pnl_wide, pnl_long, pnl_meta = parse_pnl(sheets.get("Projected P&L"))

tabs = st.tabs(
    ["Summary", "Revenue (Monthly)", "P&L (Yearly)", "Break-even", "Unit Economics", "Raw Data"]
)


# ---------- TAB 1: Summary ----------
with tabs[0]:
    st.subheader("Key Metrics")

    col1, col2, col3 = st.columns(3)

    # Market size
    with col1:
        st.metric(
            "Market size (customers)",
            f"{assump.get('market_size'):.0f}" if assump.get("market_size") else "N/A",
        )

        # Monthly growth
        mg = assump.get("monthly_growth")
        st.metric(
            "Monthly customer growth rate",
            f"{mg*100:.1f}%" if mg is not None else "N/A",
        )

    # Revenue by year
    with col2:
        rev_series = pnl_meta.get("revenue")
        if rev_series is not None:
            for y in pnl_meta["year_cols"]:
                st.metric(f"Revenue – Year {y}", f"AED {rev_series[y]:,.0f}")
        else:
            st.write("Revenue row not found in P&L sheet.")

    # EBIT by year + break-even
    with col3:
        ebit_series = pnl_meta.get("ebit")
        if ebit_series is not None:
            for y in pnl_meta["year_cols"]:
                st.metric(f"EBIT – Year {y}", f"AED {ebit_series[y]:,.0f}")
        else:
            st.write("EBIT row not found in P&L sheet.")

        be_month = be_meta.get("break_even_month")
        st.metric(
            "Break-even month (Net cash ≥ 0)",
            f"Month {be_month}" if be_month is not None else "Not reached in 36 months",
        )

    st.markdown("---")
    st.subheader("High-level Interpretation")

    st.write(
        "- **Strong economics** if revenue and EBIT are already positive in Year 1 while "
        "fixed costs are modest and variable costs remain under control.\n"
        "- **Break-even timing** is driven by contribution per customer and monthly fixed costs "
        "relative to how fast you scale customers.\n"
        "- Use the other tabs to inspect whether the assumed growth and margins are realistic."
    )


# ---------- TAB 2: Revenue (Monthly) ----------
with tabs[1]:
    st.subheader("Monthly Revenue")

    if rev_monthly is not None and not rev_monthly.empty:
        # --- optional: Year-specific KPIs as before ---
        years = sorted(rev_monthly["Year"].unique())
        selected_year = years[0]

        data_y = (
            rev_monthly[rev_monthly["Year"] == selected_year]
            .sort_values("Month_index")
            .copy()
        )

        total_rev = data_y["Revenue"].sum()
        avg_rev = data_y["Revenue"].mean()
        total_orders = data_y["No. of orders"].sum()

        k1, k2, k3 = st.columns(3)
        k1.metric(f"Total Revenue (Year {selected_year})",
                  f"AED {total_rev:,.0f}")
        k2.metric("Avg Monthly Revenue",
                  f"AED {avg_rev:,.0f}")
        k3.metric("Total Orders",
                  f"{total_orders:,.0f}")

        st.markdown("---")

        # --- 3-year continuous growth graph ---
        st.markdown("### Revenue growth – Year 1 to Year 3")

        growth_df = rev_monthly.sort_values("Month_index")

        fig_growth = px.line(
            growth_df,
            x="Period",          # Y1-Jan ... Y3-Dec
            y="Revenue",
            color="Year",        # different colour for each year
            markers=True,
            title="Revenue growth (continuous, Y1–Y3)",
        )
        fig_growth.update_layout(
            xaxis_title="Timeline",
            yaxis_title="Revenue",
        )
        st.plotly_chart(fig_growth, use_container_width=True)

        st.markdown("#### Data table (all years)")
        st.dataframe(growth_df[["Year","Month","Revenue","GMV",
                                "No. of customers","No. of orders"]],
                     use_container_width=True)
    else:
        st.warning("Could not parse the 'Revenue' sheet correctly.")




# ---------- TAB 3: P&L (Yearly) ----------
with tabs[2]:
    st.subheader("P&L Overview by Year")

    if pnl_long is not None and not pnl_long.empty:
        # Filter for a few key lines
        key_lines = [
            "Revenue",
            "Total fixed costs",
            "Total variable cost",
            "EBIT",
        ]
        pnl_key = pnl_long[pnl_long["Year"].isin(key_lines)].copy()

        fig_pnl = px.bar(
            pnl_key,
            x="Year_num",
            y="Value",
            color="Year",
            barmode="group",
            labels={"Year_num": "Year", "Value": "AED"},
            title="Revenue, Costs, and EBIT by Year",
        )
        st.plotly_chart(fig_pnl, use_container_width=True)

        st.markdown("#### Full P&L (wide format)")
        st.dataframe(pnl_wide, use_container_width=True)
    else:
        st.warning("Could not parse the 'Projected P&L' sheet correctly.")


# ---------- TAB 4: Break-even ----------
with tabs[3]:
    st.subheader("Break-even Analysis (Net Cash Over Time)")

    if be_df is not None and not be_df.empty:
        # Prepare separate positive and negative series for Net cash
        be_plot = be_df.copy()
        be_plot["Net_cash_pos"] = be_plot["Net cash"].where(be_plot["Net cash"] >= 0)
        be_plot["Net_cash_neg"] = be_plot["Net cash"].where(be_plot["Net cash"] < 0)

        # Build 2-colour line chart
        fig_cash = go.Figure()

        # Net cash >= 0  → e.g. green
        fig_cash.add_trace(
            go.Scatter(
                x=be_plot["Month"],
                y=be_plot["Net_cash_pos"],
                mode="lines+markers",
                name="Net cash ≥ 0",
                line=dict(width=3, color="green"),
            )
        )

        # Net cash < 0 → e.g. red
        fig_cash.add_trace(
            go.Scatter(
                x=be_plot["Month"],
                y=be_plot["Net_cash_neg"],
                mode="lines+markers",
                name="Net cash < 0",
                line=dict(width=3, color="red"),
            )
        )

        fig_cash.update_layout(
            title="Net Cash vs Month (Break-even)",
            xaxis_title="Month",
            yaxis_title="Net cash",
        )

        st.plotly_chart(fig_cash, use_container_width=True)

        st.markdown("#### Inputs used in break-even sheet")
        c1, c2, c3 = st.columns(3)
        c1, c2, c3 = st.columns(3)

upfront = be_meta.get("upfront_cost")
if upfront is not None:
    c1.metric("Upfront cost (Month 0)", f"AED {upfront:,.0f}")
else:
    c1.metric("Upfront cost (Month 0)", "N/A")

contrib = be_meta.get("contribution_per_customer")
if contrib is not None:
    c2.metric(
        "Contribution per customer (per month)",
        f"AED {contrib:,.2f}",
    )
else:
c2.metric("Contribution per customer (per month)", "N/A")

fixed = be_meta.get("fixed_cost_monthly")
if fixed is not None:
    c3.metric("Fixed cost (per month)", f"AED {fixed:,.0f}")
else:
    c3.metric("Fixed cost (per month)", "N/A")

        c2.metric(
            "Contribution per customer (per month)",
            f"AED {be_meta['contribution_per_customer']:,.2f}"
            if be_meta["contribution_per_customer"]
            else "N/A",
        )
        c3.metric(
            "Fixed cost (per month)",
            f"AED {be_meta['fixed_cost_monthly']:,.0f}"
            if be_meta["fixed_cost_monthly"]
            else "N/A",
        )

        st.markdown("#### Detailed break-even table")
        st.dataframe(be_df, use_container_width=True)
    else:
        st.warning("Could not parse the 'Break even analysis' sheet correctly.")



# ---------- TAB 5: Unit Economics ----------
with tabs[4]:
    st.subheader("Unit Economics")

    if unit_eco:
        c1, c2, c3 = st.columns(3)

        with c1:
            st.metric(
                "Monthly orders per customer",
                unit_eco.get("monthly_orders", "N/A"),
            )
            st.metric(
                "Order value (AED)",
                unit_eco.get("order_value", "N/A"),
            )

        with c2:
            st.metric(
                "Commission rate",
                f"{unit_eco['commission_rate']*100:.1f}%"
                if unit_eco.get("commission_rate") is not None
                else "N/A",
            )
            st.metric(
                "Revenue per customer (per month)",
                f"AED {unit_eco['revenue_per_customer']:.2f}"
                if unit_eco.get("revenue_per_customer") is not None
                else "N/A",
            )

        with c3:
            st.metric(
                "Contribution per customer (per month)",
                f"AED {unit_eco['contribution_per_customer']:.2f}"
                if unit_eco.get("contribution_per_customer") is not None
                else "N/A",
            )
            st.metric(
                "Contribution per order",
                f"AED {unit_eco['contribution_per_order']:.2f}"
                if unit_eco.get("contribution_per_order") is not None
                else "N/A",
            )

        st.markdown("#### Cost structure per order")
        cost_data = []
        labels = {
            "payment_gateway_per_order": "Payment gateway",
            "support_per_order": "Customer support",
            "refund_per_order": "Refund buffer",
            "infra_per_order": "Infra",
        }
        for key, label in labels.items():
            if unit_eco.get(key) is not None:
                cost_data.append({"Component": label, "AED": unit_eco[key]})

        if cost_data:
            cost_df = pd.DataFrame(cost_data)
            fig_cost = px.pie(
                cost_df,
                names="Component",
                values="AED",
                title="Variable Cost per Order Breakdown",
            )
            st.plotly_chart(fig_cost, use_container_width=True)
            st.dataframe(cost_df, use_container_width=True)
        else:
            st.info("Per-order cost breakdown not fully available in the sheet.")
    else:
        st.warning("Could not parse the 'Unit economics' sheet correctly.")


# ---------- TAB 6: Raw Data ----------
with tabs[5]:
    st.subheader("Raw Sheets Preview")

    for name, df in sheets.items():
        with st.expander(f"Sheet: {name}", expanded=False):
            st.dataframe(df, use_container_width=True)
