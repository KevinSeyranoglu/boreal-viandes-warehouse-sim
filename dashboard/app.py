"""Boréal Viandes – operations dashboard (Streamlit mirror of the Power BI report).

    python analytics/build_db.py          # once, after generating data
    streamlit run dashboard/app.py

Reads data/warehouse.db. One tab per report page; the scenario selector compares every
card against the baseline run.
"""
from __future__ import annotations

import os
import sqlite3
import sys

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "analytics"))
sys.path.insert(0, ROOT)

import run_sql  # noqa: E402

DB = os.environ.get("WAREHOUSE_DB", os.path.join(ROOT, "data", "warehouse.db"))

# ---- validated palette (dataviz reference instance): fixed slot order, colour follows the entity
SLOTS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SCENARIOS = ["baseline", "lean_staff", "extra_pickers", "chaos", "summer_bbq"]
SCEN_COLOR = dict(zip(SCENARIOS, SLOTS))
ZONE_COLOR = {"freezer": SLOTS[0], "processed": SLOTS[1], "fresh": SLOTS[2], "dock": SLOTS[3], "qa": SLOTS[4]}
SHIFT_COLOR = {"day": SLOTS[0], "evening": SLOTS[1], "night": SLOTS[2]}
INK, INK2, MUTED, GRID, BASE, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
CRITICAL = "#d03b3b"

T = {  # fr, en
    "title": ("Boréal Viandes – tableau de bord des opérations", "Boréal Viandes – operations dashboard"),
    "subtitle": ("Données simulées · 180 jours · centre de distribution sous froid, Québec",
                 "Simulated data · 180 days · cold-chain distribution center, Québec"),
    "scenario": ("Scénario", "Scenario"), "lang": ("Langue", "Language"),
    "vs_base": ("vs référence", "vs baseline"),
    "tab_ops": ("Opérations", "Operations"), "tab_cold": ("Chaîne du froid", "Cold chain"),
    "tab_inv": ("Inventaire et péremption", "Inventory & expiry"), "tab_lab": ("Main-d'œuvre", "Labour"),
    "tab_sup": ("Fournisseurs et cour", "Suppliers & yard"), "tab_safe": ("Santé-sécurité", "Safety"),
    "tab_recall": ("Rappel de lot", "Recall trace"), "tab_scen": ("Scénarios", "Scenarios"),
    "otif": ("OTIF (à temps et complet)", "OTIF (on time, in full)"), "on_time": ("À temps", "On time"),
    "fill": ("Taux de service", "Fill rate"), "cases_day": ("Caisses / jour", "Cases / day"),
    "profit_day": ("Profit / jour", "Profit / day"),
    "otif_daily": ("OTIF par jour", "OTIF by day"),
    "cases_weekday": ("Caisses expédiées par jour de la semaine (moyenne)", "Cases shipped by weekday (average)"),
    "stores": ("Service par client (pires en premier)", "Service by customer (worst first)"),
    "compliance": ("Conformité chaîne du froid (produit)", "Cold-chain compliance (product)"),
    "air_spec": ("Air dans les normes", "Air temperature in spec"), "alarms": ("Alarmes", "Alarms"),
    "temp_zone": ("Température moyenne horaire par zone (ligne pointillée = maximum permis)",
                  "Hourly average temperature by zone (dotted line = upper spec)"),
    "rejects_plant": ("Palettes refusées à la réception par usine", "Pallets rejected at receiving by plant"),
    "spoil_value": ("Pertes (périmés)", "Spoilage"), "spoil_pct": ("Pertes / caisses expédiées", "Spoilage / cases shipped"),
    "stock_zone": ("Stock en caisses par zone", "Stock (cases) by zone"),
    "spoil_sku": ("Pertes par produit ($)", "Spoilage by product ($)"),
    "expiry": ("Position de stock au dernier jour", "Stock position on the last day"),
    "cph": ("Caisses / heure préparateur", "Cases / picker hour"), "hours": ("Heures payées", "Paid hours"),
    "skill_cph": ("Productivité selon l'habileté (chaque point = un préparateur)",
                  "Productivity vs skill (each dot = one picker)"),
    "hours_role": ("Heures payées par rôle", "Paid hours by role"),
    "sup_ontime": ("Camions à l'heure (±15 min)", "Trucks on time (±15 min)"),
    "short": ("Palettes manquantes", "Short-shipped pallets"), "yard_wait": ("Attente moyenne dans la cour", "Average yard wait"),
    "scorecard": ("Fiche de rendement des fournisseurs", "Supplier scorecard"),
    "wait_hour": ("Attente dans la cour selon l'heure d'arrivée (minutes)", "Yard wait by arrival hour (minutes)"),
    "lti": ("Accidents avec perte de temps", "Lost-time injuries"),
    "lti_rate": ("Taux LTI / 100 ETC", "LTI rate / 100 FTE"),
    "lti_help": ("Référence canadienne : 1,30 (transport et entreposage, Ontario 2022)",
                 "Canadian benchmark: 1.30 (transportation & warehousing, Ontario 2022)"),
    "forklift": ("Incidents de chariot", "Forklift incidents"),
    "incidents": ("Registre des incidents", "Incident log"),
    "inc_type": ("Incidents par type", "Incidents by type"),
    "lot": ("Lot", "Lot"), "stores_reached": ("Magasins touchés", "Stores reached"),
    "cases_lot": ("Caisses expédiées du lot", "Cases of the lot shipped"),
    "trace": ("Traçabilité du lot", "Lot trace"),
    "scen_note": ("Chaque scénario change un seul paramètre par rapport à la référence (même graine).",
                  "Each scenario changes one setting from the baseline (same random seed)."),
    "no_db": ("Base de données introuvable. Lancez d'abord : python analytics/build_db.py",
              "Database not found. Run first: python analytics/build_db.py"),
    "table": ("Voir les données", "Show data"),
}


def t(key):
    return T[key][0 if st.session_state.get("lang", "FR") == "FR" else 1]


# ---------------------------------------------------------------- data
@st.cache_resource
def connect():
    return sqlite3.connect(DB, check_same_thread=False)


@st.cache_data(show_spinner=False)
def q(sql, **params):
    return pd.read_sql_query(sql, connect(), params=params)


@st.cache_data(show_spinner=False)
def sqlfile(prefix, scenario, lot=0):
    return run_sql.run(run_sql.queries(prefix)[0], connect(), {"scenario": scenario, "lot": lot})


@st.cache_data(show_spinner=False)
def kpis(scenario):
    o = q("""SELECT AVG(on_time) on_time, AVG(CASE WHEN on_time = 1 AND fill_rate >= 0.999 THEN 1.0 ELSE 0 END) otif,
                    SUM(cases_shipped) * 1.0 / SUM(cases_ordered) fill FROM fact_orders WHERE scenario = :s""", s=scenario)
    k = q("""SELECT AVG(cases_shipped) cases_day, AVG(profit) profit_day, AVG(compliance) compliance,
                    SUM(temp_alarms) alarms, SUM(spoilage) spoilage, SUM(spoiled_cases) * 1.0 / SUM(cases_shipped) spoil_pct
             FROM fact_daily_kpi WHERE scenario = :s""", s=scenario)
    lab = q("""SELECT SUM(hours) hours, SUM(CASE WHEN role = 'picker' THEN hours END) picker_hours
               FROM fact_labor WHERE scenario = :s""", s=scenario)
    picks = q("SELECT SUM(cases) cases FROM fact_picks WHERE scenario = :s", s=scenario)
    tr = q("""SELECT AVG(CASE WHEN late_min <= 15 THEN 1.0 ELSE 0 END) sup_ontime,
                     1 - SUM(pallets) * 1.0 / SUM(pallets_ordered) short,
                     AVG((julianday(dock_ts) - julianday(gate_ts)) * 1440) yard_wait
              FROM fact_inbound_trucks WHERE scenario = :s""", s=scenario)
    inc = q("""SELECT SUM(severity = 'lost_time') lti, SUM(category = 'forklift') forklift,
                      COUNT(*) n FROM fact_incidents WHERE scenario = :s""", s=scenario)
    air = q("""SELECT AVG(CASE WHEN t.temp_c BETWEEN z.min_c AND z.max_c THEN 1.0 ELSE 0 END) air
               FROM fact_temperature t JOIN dim_zone z USING (zone) WHERE t.scenario = :s""", s=scenario)
    r = {**o.iloc[0], **k.iloc[0], **lab.iloc[0], **tr.iloc[0], **inc.iloc[0], **air.iloc[0]}
    r["cph"] = picks.iloc[0]["cases"] / r["picker_hours"]
    r["lti"] = int(r["lti"] or 0)
    r["forklift"] = int(r["forklift"] or 0)
    r["lti_rate"] = r["lti"] * 2000 * 100 / r["hours"]
    return r


# ---------------------------------------------------------------- chart helpers
def style(fig, height=320, legend=True):
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=8, b=8), paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", color=INK2, size=13),
        hoverlabel=dict(bgcolor="white", font_color=INK, bordercolor=BASE),
        legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, title_text="") if legend else None,
        showlegend=legend, bargap=0.25,
    )
    fig.update_xaxes(showgrid=False, linecolor=BASE, tickfont_color=MUTED, title_font_color=MUTED)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=BASE, tickfont_color=MUTED, title_font_color=MUTED)
    fig.update_traces(selector=dict(type="scatter", mode="lines"), line_width=2)
    fig.update_traces(selector=dict(type="bar"), marker_line_width=0)
    return fig


def show(fig):
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def num(text):
    """French number style: 1 542 $, 89,0 %."""
    if st.session_state.get("lang", "FR") != "FR":
        return text
    text = text.replace(",", "\u202f").replace(".", ",")
    return text.replace("%", "\u00a0%")


def metric(col, label, value, base=None, fmt="{:.1%}", good_up=True, help=None):
    delta = None
    if base is not None and value is not None and abs(value - base) > 1e-12:
        d = value - base
        if "%" in fmt and "$" not in fmt:                      # change in percentage points
            delta = num(f"{d * 100:+.1f}") + " pts " + t("vs_base")
        else:
            delta = num(("+" if d > 0 else "") + fmt.format(d)) + " " + t("vs_base")
    col.metric(label, num(fmt.format(value)) if value is not None else "–", delta,
               delta_color="normal" if good_up else "inverse", help=help)


def money(v):
    return f"{v:,.0f} $".replace(",", " ") if st.session_state.get("lang", "FR") == "FR" else f"${v:,.0f}"


def data_expander(df):
    with st.expander(t("table")):
        st.dataframe(df, width="stretch", hide_index=True)


# ---------------------------------------------------------------- page
def main():
    st.set_page_config(page_title="Boréal Viandes", page_icon="🧊", layout="wide")
    with st.sidebar:
        st.radio(t("lang"), ["FR", "EN"], horizontal=True, key="lang")
        if not os.path.exists(DB):
            st.error(t("no_db"))
            st.stop()
        available = [s for s in SCENARIOS if s in set(q("SELECT DISTINCT scenario FROM fact_daily_kpi")["scenario"])]
        sc = st.selectbox(t("scenario"), available, index=0)
        st.caption(t("scen_note"))
    st.title(t("title"))
    st.caption(t("subtitle"))
    k = kpis(sc)
    b = kpis("baseline") if sc != "baseline" and "baseline" in available else None
    bk = (lambda key: b[key]) if b is not None else (lambda key: None)

    tabs = st.tabs([t(x) for x in ("tab_ops", "tab_cold", "tab_inv", "tab_lab", "tab_sup", "tab_safe",
                                   "tab_recall", "tab_scen")])

    # 1. operations
    with tabs[0]:
        c = st.columns(4)
        metric(c[0], t("otif"), k["otif"], bk("otif"))
        metric(c[1], t("fill"), k["fill"], bk("fill"), "{:.2%}")
        metric(c[2], t("cases_day"), k["cases_day"], bk("cases_day"), "{:,.0f}")
        metric(c[3], t("profit_day"), k["profit_day"], bk("profit_day"), "{:,.0f} $")
        d = sqlfile("01_", sc)
        left, right = st.columns([3, 2])
        with left:
            st.markdown("##### " + t("otif_daily"))
            fig = px.line(d, x="date", y="otif_pct", color_discrete_sequence=[SCEN_COLOR[sc]],
                          labels={"otif_pct": "OTIF %", "date": ""})
            fig.update_traces(hovertemplate="%{x}<br>OTIF %{y:.1f} %<extra></extra>")
            show(style(fig, legend=False))
        with right:
            st.markdown("##### " + t("cases_weekday"))
            wk = q("""SELECT d.weekday, d.weekday_fr, d.weekday_en, AVG(k.cases_shipped) cases
                      FROM fact_daily_kpi k JOIN dim_date d USING (date) WHERE k.scenario = :s
                      GROUP BY d.weekday ORDER BY d.weekday""", s=sc)
            wk["label"] = wk["weekday_fr"] if st.session_state.lang == "FR" else wk["weekday_en"]
            fig = px.bar(wk, x="label", y="cases", color_discrete_sequence=[SCEN_COLOR[sc]], labels={"label": "", "cases": ""})
            fig.update_traces(hovertemplate="%{x}<br>%{y:,.0f}<extra></extra>")
            show(style(fig, legend=False))
        st.markdown("##### " + t("stores"))
        st.dataframe(sqlfile("02_", sc), width="stretch", hide_index=True)

    # 2. cold chain
    with tabs[1]:
        c = st.columns(3)
        metric(c[0], t("compliance"), k["compliance"], bk("compliance"), "{:.2%}")
        metric(c[1], t("air_spec"), k["air"], bk("air"), "{:.2%}")
        metric(c[2], t("alarms"), k["alarms"], bk("alarms"), "{:,.0f}", good_up=False)
        st.markdown("##### " + t("temp_zone"))
        h = q("""SELECT substr(ts, 1, 13) || ':00' AS hour, zone, AVG(temp_c) temp FROM fact_temperature
                 WHERE scenario = :s AND zone IN ('fresh', 'processed', 'freezer') GROUP BY 1, 2""", s=sc)
        zones = q("SELECT zone, max_c FROM dim_zone").set_index("zone")["max_c"]
        cols = st.columns(3)
        for col, z in zip(cols, ("freezer", "processed", "fresh")):
            dz = h[h.zone == z]
            fig = go.Figure(go.Scatter(x=dz["hour"], y=dz["temp"], mode="lines", line=dict(color=ZONE_COLOR[z], width=1.5),
                                       hovertemplate="%{x}<br>%{y:.1f} °C<extra></extra>"))
            fig.add_hline(y=zones[z], line=dict(color=CRITICAL, dash="dot", width=1.5))
            col.caption(z)
            with col:
                show(style(fig, height=240, legend=False))
        st.markdown("##### " + t("rejects_plant"))
        rj = q("""SELECT p.name_en plant, SUM(t.pallets_rejected) rejected, SUM(t.reefer_failure) reefer_failures
                  FROM fact_inbound_trucks t JOIN dim_plant p USING (plant_code) WHERE t.scenario = :s
                  GROUP BY 1 ORDER BY 2 DESC""", s=sc)
        fig = px.bar(rj, x="rejected", y="plant", orientation="h", color_discrete_sequence=[SCEN_COLOR[sc]],
                     labels={"rejected": "", "plant": ""}, hover_data=["reefer_failures"])
        show(style(fig, height=220, legend=False))

    # 3. inventory & expiry
    with tabs[2]:
        c = st.columns(2)
        metric(c[0], t("spoil_value"), k["spoilage"], bk("spoilage"), "{:,.0f} $", good_up=False)
        metric(c[1], t("spoil_pct"), k["spoil_pct"], bk("spoil_pct"), "{:.2%}", good_up=False)
        left, right = st.columns(2)
        with left:
            st.markdown("##### " + t("stock_zone"))
            inv = q("""SELECT date, zone, SUM(cases_on_hand) cases FROM fact_inventory_daily
                       WHERE scenario = :s GROUP BY 1, 2""", s=sc)
            fig = px.line(inv, x="date", y="cases", color="zone", color_discrete_map=ZONE_COLOR,
                          category_orders={"zone": ["freezer", "processed", "fresh"]}, labels={"date": "", "cases": ""})
            show(style(fig))
        with right:
            st.markdown("##### " + t("spoil_sku"))
            sp = q("""SELECT k.name_en product, k.category, SUM(s.value) value, COUNT(*) pallets
                      FROM fact_spoilage s JOIN dim_sku k USING (sku_code) WHERE s.scenario = :s
                      GROUP BY 1 ORDER BY 3 DESC""", s=sc)
            fig = px.bar(sp, x="value", y="product", orientation="h", color_discrete_sequence=[SCEN_COLOR[sc]],
                         labels={"value": "", "product": ""}, hover_data=["pallets"])
            fig.update_yaxes(autorange="reversed")
            show(style(fig, legend=False))
        st.markdown("##### " + t("expiry"))
        st.dataframe(sqlfile("04_", sc), width="stretch", hide_index=True)

    # 4. labour
    with tabs[3]:
        c = st.columns(2)
        metric(c[0], t("cph"), k["cph"], bk("cph"), "{:.1f}")
        metric(c[1], t("hours"), k["hours"], bk("hours"), "{:,.0f}", good_up=False)
        left, right = st.columns([3, 2])
        with left:
            st.markdown("##### " + t("skill_cph"))
            lp = sqlfile("05_", sc)
            fig = px.scatter(lp, x="skill", y="cases_per_hour", color="shift", color_discrete_map=SHIFT_COLOR,
                             category_orders={"shift": ["day", "evening", "night"]}, hover_name="name",
                             labels={"skill": "skill", "cases_per_hour": ""})
            fig.update_traces(marker=dict(size=10, line=dict(color=SURFACE, width=2)))
            show(style(fig))
        with right:
            st.markdown("##### " + t("hours_role"))
            hr = q("""SELECT role, SUM(hours) hours FROM fact_labor WHERE scenario = :s GROUP BY 1 ORDER BY 2 DESC""", s=sc)
            fig = px.bar(hr, x="hours", y="role", orientation="h", color_discrete_sequence=[SCEN_COLOR[sc]],
                         labels={"hours": "", "role": ""})
            fig.update_yaxes(autorange="reversed")
            show(style(fig, legend=False))

    # 5. suppliers & yard
    with tabs[4]:
        c = st.columns(3)
        metric(c[0], t("sup_ontime"), k["sup_ontime"], bk("sup_ontime"))
        metric(c[1], t("short"), k["short"], bk("short"), "{:.2%}", good_up=False)
        metric(c[2], t("yard_wait"), k["yard_wait"], bk("yard_wait"), "{:.0f} min", good_up=False)
        st.markdown("##### " + t("scorecard"))
        st.dataframe(sqlfile("06_", sc), width="stretch", hide_index=True)
        st.markdown("##### " + t("wait_hour"))
        yw = q("""SELECT CAST(substr(gate_ts, 12, 2) AS INTEGER) hour,
                         AVG((julianday(dock_ts) - julianday(gate_ts)) * 1440) wait, COUNT(*) trucks
                  FROM fact_inbound_trucks WHERE scenario = :s GROUP BY 1 ORDER BY 1""", s=sc)
        fig = px.bar(yw, x="hour", y="wait", color_discrete_sequence=[SCEN_COLOR[sc]], hover_data=["trucks"],
                     labels={"hour": "", "wait": ""})
        fig.update_traces(hovertemplate="%{x}:00<br>%{y:.0f} min · %{customdata[0]} trucks<extra></extra>")
        fig.update_xaxes(dtick=2)
        show(style(fig, height=260, legend=False))

    # 6. safety
    with tabs[5]:
        c = st.columns(3)
        metric(c[0], t("lti"), k["lti"], bk("lti"), "{:,.0f}", good_up=False)
        metric(c[1], t("lti_rate"), k["lti_rate"], bk("lti_rate"), "{:.2f}", good_up=False, help=t("lti_help"))
        metric(c[2], t("forklift"), k["forklift"], bk("forklift"), "{:,.0f}", good_up=False)
        inc = q("""SELECT date(ts) date, category, incident_type, severity, role, zone, days_lost, cases_damaged, cost
                   FROM fact_incidents WHERE scenario = :s ORDER BY ts""", s=sc)
        left, right = st.columns([2, 3])
        with left:
            st.markdown("##### " + t("inc_type"))
            if len(inc):
                it = inc.groupby(["incident_type", "severity"]).size().reset_index(name="n")
                sev_color = {"lost_time": SLOTS[7], "medical_aid": SLOTS[3], "property_damage": SLOTS[0]}
                fig = px.bar(it, x="n", y="incident_type", color="severity", orientation="h",
                             color_discrete_map=sev_color, labels={"n": "", "incident_type": ""})
                show(style(fig, height=300))
            else:
                st.info("—")
        with right:
            st.markdown("##### " + t("incidents"))
            st.dataframe(inc, width="stretch", hide_index=True)
        st.caption(t("lti_help"))

    # 7. recall trace
    with tabs[6]:
        recalls = q("""SELECT DISTINCT CAST(json_extract(detail, '$.lot') AS INTEGER) lot FROM fact_events
                       WHERE scenario = :s AND event_type = 'ev_recall'""", s=sc)["lot"].tolist()
        lots = recalls or [run_sql.default_lot(connect(), sc)]
        lot = st.selectbox(t("lot"), lots, index=0)
        tr = sqlfile("07_", sc, int(lot))
        shipped = tr[tr.step == "shipped"]
        c = st.columns(2)
        c[0].metric(t("stores_reached"), shipped["party"].nunique())
        c[1].metric(t("cases_lot"), f"{int(shipped['cases'].sum()):,}")
        st.markdown("##### " + t("trace"))
        st.dataframe(tr, width="stretch", hide_index=True)

    # 8. scenarios: dots for rates near 100 % (a bar must start at zero), bars for money
    with tabs[7]:
        import export_powerbi
        cmp = sqlfile("08_", sc)
        cmp = cmp.set_index("scenario").loc[[s for s in SCENARIOS if s in set(cmp["scenario"])]].reset_index()
        lang_i = 0 if st.session_state.lang == "FR" else 1
        cmp["label"] = cmp["scenario"].map(lambda s: export_powerbi.SCENARIO_LABELS[s][lang_i])
        order = cmp["label"].tolist()
        charts = [("on_time_pct", t("on_time") + " (%)", "dot"), ("fill_rate_pct", t("fill") + " (%)", "dot"),
                  ("profit_per_day", t("profit_day") + " ($)", "bar"),
                  ("spoilage_per_day", t("spoil_value") + " / jour ($)" if lang_i == 0 else "Spoilage / day ($)", "bar")]
        cols = st.columns(2)
        for i, (col_name, label, form) in enumerate(charts):
            with cols[i % 2]:
                st.markdown("##### " + label)
                if form == "dot":
                    fig = go.Figure()
                    for _, r in cmp.iterrows():
                        fig.add_trace(go.Scatter(x=[r[col_name]], y=[r["label"]], mode="markers+text",
                                                 marker=dict(size=14, color=SCEN_COLOR[r["scenario"]],
                                                             line=dict(color=SURFACE, width=2)),
                                                 text=[num(f"{r[col_name]:.1f}")], textposition="middle right",
                                                 textfont=dict(color=INK2), name=r["label"],
                                                 hovertemplate=f"{r['label']}<br>%{{x:.2f}} %<extra></extra>"))
                    lo = cmp[col_name].min()
                    fig.update_xaxes(range=[lo - (100 - lo) * 0.3, 100 + (100 - lo) * 0.25], ticksuffix=" %")
                else:
                    fig = px.bar(cmp, x=col_name, y="label", orientation="h", color="scenario",
                                 color_discrete_map=SCEN_COLOR, labels={col_name: "", "label": ""})
                    fig.update_traces(hovertemplate="%{y}<br>%{x:,.0f} $<extra></extra>")
                fig.update_yaxes(categoryorder="array", categoryarray=order[::-1], title="")
                show(style(fig, height=250, legend=False))
        data_expander(cmp)


if __name__ == "__main__":
    main()
