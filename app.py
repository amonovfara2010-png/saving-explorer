from pathlib import Path
import requests
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Savings Explorer", page_icon="📈", layout="wide")
BASE=Path(__file__).parent
META={
"Argentina":("ARG","ARS","S&P Merval"),"Australia":("AUS","AUD","S&P/ASX 200"),
"Brazil":("BRA","BRL","Ibovespa"),"China":("CHN","CNY","Shanghai Composite"),
"Egypt":("EGY","EGP","EGX — exact series unconfirmed"),"Germany":("DEU","EUR","DAX — version unconfirmed"),
"India":("IND","INR","Nifty 50"),"Japan":("JPN","JPY","Nikkei 225"),
"South Africa":("ZAF","ZAR","FTSE/JSE All Share"),"United Kingdom":("GBR","GBP","FTSE 100"),
"United States":("USA","USD","S&P 500"),"Uzbekistan":("UZB","UZS","UCI — annual data unavailable")}
METHODS={"Deposit":"deposit","USD cash":"usd","Gold":"gold","Stock-market index":"stocks"}

@st.cache_data(ttl=86400)
def fetch_fx(iso, first, last):
    url=f"https://api.worldbank.org/v2/country/{iso}/indicator/PA.NUS.FCRF"
    response=requests.get(url,params={"date":f"{first}:{last}","format":"json","per_page":1000},timeout=25)
    response.raise_for_status()
    payload=response.json()
    if not isinstance(payload,list) or len(payload)<2 or not payload[1]:
        raise ValueError("World Bank returned no observations.")
    return pd.Series({int(x["date"]):float(x["value"]) for x in payload[1] if x.get("value") is not None},dtype=float).sort_index()

st.title("Savings Explorer")
st.caption("12 countries · Historical educational prototype · Research data: 2020–2024 returns, 2019 baseline")
data=pd.read_csv(BASE/"returns.csv")
with st.sidebar:
    st.header("Build your comparison")
    country=st.selectbox("Country",list(META),index=list(META).index("United States"))
    amount=st.number_input("Starting amount (USD)",min_value=1.0,value=100.0,step=10.0)
    available=sorted(data.loc[data.country==country,"year"].unique().tolist())
    baseline=min(available)-1
    start=st.selectbox("Starting observation",[baseline]+available[:-1])
    endings=[y for y in available if y>start]
    end=st.selectbox("Ending observation",endings,index=len(endings)-1)
    index_label = META[country][2]
    stock_label = f"Stocks — {index_label}"
    METHODS = {"Deposit": "deposit", "USD cash": "usd", "Gold": "gold", stock_label: "stocks"}
    selected=st.multiselect("Saving methods",list(METHODS),default=list(METHODS))
    basis=st.radio("Value basis",["Nominal","Real (inflation-adjusted)"])
    units=st.radio("Chart display",["Percentage return","Local-currency amount","USD amount"])
    fx_mode=st.selectbox("Exchange-rate input",["World Bank annual averages","Upload exchange rates (CSV)"])
    uploaded=st.file_uploader("Optional CSV: country,year,lcu_per_usd",type="csv") if fx_mode.startswith("Upload") else None

iso,currency,index_name=META[country]
st.caption(f"Stock benchmark: {index_name}")
st.warning("Prototype: supplied asset returns and inflation have not been independently verified. Exact observation dates, deposit definitions and index dividend treatment still need confirmation. No fees or taxes; earnings remain invested.")
rows=data.loc[(data.country==country)&(data.year>start)&(data.year<=end)].sort_values("year").set_index("year")
expected=list(range(start+1,end+1))
if rows.index.tolist()!=expected or rows.inflation.isna().any():
    st.error("Missing or duplicate annual observations. This period cannot be simulated.");st.stop()
if not selected:
    st.info("Choose at least one saving method.");st.stop()
if (rows.inflation<=-1).any():
    st.error("Invalid inflation input.");st.stop()

# FX failure never blocks percentage-only comparisons.
fx=None
fx_source="Unavailable"
if country=="United States":
    fx=pd.Series(1.0,index=range(start,end+1));fx_source="USD/USD = 1"
else:
    try:
        if uploaded is not None:
            table=pd.read_csv(uploaded)
            required={"country","year","lcu_per_usd"}
            if not required.issubset(table.columns):raise ValueError("CSV needs country, year, lcu_per_usd columns.")
            table=table.loc[table.country==country].copy()
            table["year"]=pd.to_numeric(table.year,errors="raise").astype(int)
            if table.year.duplicated().any():raise ValueError("Duplicate exchange-rate years.")
            fx=pd.to_numeric(table.set_index("year").lcu_per_usd,errors="raise").sort_index()
            fx_source="User-uploaded rates (not independently verified)"
        elif fx_mode.startswith("World Bank"):
            with st.spinner("Loading official exchange-rate observations…"):
                fx=fetch_fx(iso,start,end)
            fx_source="World Bank PA.NUS.FCRF: annual-average official rates"
        else:
            st.info("Upload rates to enable currency amounts. Percentage results remain available.")
        if fx is not None:
            needed=fx.reindex(range(start,end+1))
            if needed.isna().any() or (needed<=0).any():
                raise ValueError("Positive exchange rates are required for every selected observation year.")
            fx=needed
    except Exception as exc:
        fx=None
        st.warning(f"Currency amounts unavailable: {exc}. Percentage comparisons still work; no rates have been fabricated.")

# Differences above 0.05 percentage points exceed ordinary displayed rounding.
consistent=False
fx_check=None
if fx is not None:
    fx_returns=fx.pct_change().reindex(rows.index)
    fx_check=pd.DataFrame({"Research USD return (%)":rows.usd*100,"FX-implied USD return (%)":fx_returns*100})
    fx_check["Difference (percentage points)"]=fx_check.iloc[:,0]-fx_check.iloc[:,1]
    consistent=bool((fx_check["Difference (percentage points)"].abs()<=0.05).all())
    st.caption(f"Exchange-rate source: {fx_source}")
    if not consistent:
        st.warning("Exchange rates do not match the supplied USD-return series within 0.05 percentage points. Local-currency amounts use these FX observations only to set the starting amount. USD equivalents are disabled for this period until the datasets are reconciled. Do not treat the mixed-source comparison as validated history.")
    if country!="United States":
        st.caption("World Bank mode uses annual averages, not a quoted transaction-date exchange rate. Currency amounts are illustrative under that convention.")

inflation=(1+rows.inflation).cumprod()
records=[];summary=[]
for name in selected:
    col=METHODS[name]
    if rows[col].isna().any():
        st.warning(f"{name}: unavailable for this period. No annual history has been invented.");continue
    if (rows[col]<-1).any():
        st.warning(f"{name}: invalid return below −100%.");continue
    factors=(1+rows[col]).cumprod()
    factors=pd.concat([pd.Series({start:1.0}),factors])
    price_factors=pd.concat([pd.Series({start:1.0}),inflation])
    local_factor=factors if basis=="Nominal" else factors/price_factors
    local_amount=amount*fx.loc[start]*local_factor if fx is not None else None
    nominal_usd=amount*fx.loc[start]*factors/fx if fx is not None and consistent else None
    # Real USD amounts are intentionally not labelled as US purchasing power.
    for year in factors.index:
        records.append({"Year":int(year),"Method":name,"Return (%)":float((local_factor.loc[year]-1)*100),"Local amount":float(local_amount.loc[year]) if local_amount is not None else float("nan"),"USD amount":float(nominal_usd.loc[year]) if nominal_usd is not None and basis=="Nominal" else float("nan")})
    row={"Method":name,"NOMINAL return — local currency (%)":(factors.loc[end]-1)*100,"REAL return — after local inflation (%)":(factors.loc[end]/price_factors.loc[end]-1)*100}
    if fx is not None:
        row[f"NOMINAL balance ({currency})"]=amount*fx.loc[start]*factors.loc[end]
        row[f"REAL value ({start} {currency})"]=amount*fx.loc[start]*factors.loc[end]/price_factors.loc[end]
    if nominal_usd is not None:
        row["Nominal USD equivalent"]=nominal_usd.loc[end]
        row["USD return (%)"]=(nominal_usd.loc[end]/amount-1)*100
    summary.append(row)

st.subheader(f"{country} · {start} → {end} · Starting USD: ${amount:,.2f}")
if fx is not None:st.write(f"Starting conversion: **{amount*fx.loc[start]:,.2f} {currency}** at {fx.loc[start]:,.6f} {currency}/USD")
if not records:st.stop()
chart=pd.DataFrame(records)
y={"Percentage return":"Return (%)","Local-currency amount":"Local amount","USD amount":"USD amount"}[units]
if units=="USD amount" and basis!="Nominal":
    st.info("Real values describe local purchasing power, not US purchasing power. Choose Nominal for USD amounts, or use local amounts/percentage returns for real results.")
elif chart[y].isna().all():
    st.info("This amount view needs valid, consistent exchange rates. Choose Percentage return to explore your research returns now.")
else:
    custom=["Return (%)"]
    hover="Local return: %{customdata[0]:.2f}%"
    if fx is not None:
        custom.append("Local amount")
        label=f"Balance ({currency})" if basis=="Nominal" else f"REAL value ({start} {currency})"
        hover+=f"<br>{label}: %{{customdata[1]:,.2f}}"
    if consistent and basis=="Nominal":
        custom.append("USD amount")
        hover+=f"<br>USD equivalent: $%{{customdata[{len(custom)-1}]:,.2f}}"
    hover+="<extra>%{fullData.name}</extra>"
    fig=px.line(chart,x="Year",y=y,color="Method",markers=True,custom_data=custom,template="plotly_white")
    fig.update_traces(hovertemplate=hover,line_width=3,marker_size=8)
    fig.update_layout(hovermode="x unified",hoverdistance=-1,height=500)
    fig.update_xaxes(dtick=1,tickformat="d",hoverformat="d")
    st.plotly_chart(fig,use_container_width=True)
    st.caption("Hover to compare methods. Only annual observations are available; connecting lines do not represent monthly data.")
result=pd.DataFrame(summary).set_index("Method")
st.subheader("Ending results — nominal and real")
st.caption("NOMINAL = before inflation. REAL = after local inflation. Both returns are shown below; the Value basis control selects which one appears on the graph.")
st.dataframe(result.style.format("{:,.2f}"),use_container_width=True)
st.download_button("Download results",result.to_csv().encode(),"simulation_results.csv","text/csv")

with st.expander("How it works — formulas and definitions",expanded=False):
    st.markdown("All percentages are converted to decimals before calculation: 10% becomes 0.10. Let P be starting USD, E be local-currency units per USD, r be annual local nominal returns, and π be annual local inflation.")
    st.markdown("### 1. Initial currency conversion")
    st.latex(r"L_0=P E_0")
    st.write("Starting local money equals starting USD multiplied by the starting exchange rate.")
    st.markdown("### 2. Nominal growth and ending local balance")
    st.latex(r"G=\prod_{t=1}^{n}(1+r_t),\qquad L_T=L_0G")
    st.write("Nominal means before inflation. Annual returns compound; they are not added together. Deposit interest is assumed reinvested.")
    st.markdown("### 3. Total nominal local return")
    st.latex(r"R_{nominal}=100(G-1)\%")
    st.markdown("### 4. Cumulative inflation")
    st.latex(r"F=\prod_{t=1}^{n}(1+\pi_t),\qquad Inflation=100(F-1)\%")
    st.markdown("### 5. Real value and real local return")
    st.latex(r"L_{real}=\frac{L_T}{F},\qquad R_{real}=100\left(\frac{G}{F}-1\right)\%")
    st.write("Real value is purchasing power expressed in starting-year local prices, not cash available to withdraw. Existing real-return columns are not used; real results are recalculated consistently.")
    st.markdown("### 6. Ending USD equivalent and USD return")
    st.latex(r"U_T=\frac{L_T}{E_T},\qquad R_{USD}=100\left(\frac{U_T}{P}-1\right)\%")
    st.write("USD equivalents are enabled only when exchange-rate changes agree with the research USD-return column within 0.05 percentage points for every selected interval. This check is not independent verification of all asset returns.")
    st.markdown("### 7. Holding USD cash")
    st.latex(r"r_{USD,local,t}=\frac{E_t}{E_{t-1}}-1")
    st.write("Without interest or costs, holding USD preserves the number of dollars. In this app the supplied USD returns are retained, and their consistency with exchange rates is checked, not silently overwritten.")
    st.markdown("### 8. Gold and stocks")
    st.write("Their supplied returns are already in local currency. Compound them directly; do not apply another FX adjustment to local growth. Converting the final balance back to USD is a separate step.")
    st.markdown("### Timing and limitations")
    st.write("Selecting 2019–2024 uses the 2020, 2021, 2022, 2023 and 2024 rows. No additional contributions or withdrawals. Exact observation dates, rate definitions, index variants, dividend treatment and asset accessibility require confirmation. Historical performance is not a forecast or personalized advice.")
with st.expander("Data, sources and exchange-rate checks"):
    st.write("Asset returns and inflation: supplied research table, transcribed without independent verification. 2019 deposit-only returns are excluded so every comparison uses identical intervals. Uzbekistan annual stock returns remain unavailable.")
    st.markdown("World Bank FX series: [PA.NUS.FCRF](https://data.worldbank.org/indicator/PA.NUS.FCRF), official local-currency units per USD, period average. Annual averages are not investment-date rates.")
    if fx is not None:
        st.dataframe(fx.rename("LCU per USD").rename_axis("year"))
        st.download_button("Download exchange rates used",pd.DataFrame({"country":country,"year":fx.index,"lcu_per_usd":fx.values}).to_csv(index=False).encode(),"exchange_rates_used.csv","text/csv")
    if fx_check is not None:st.dataframe(fx_check.style.format("{:,.4f}"))
    st.markdown("To add years: append complete annual rows to returns.csv using decimal returns. Selectors update automatically. Keep period and source conventions consistent; FX must cover the starting and ending observations too.")
