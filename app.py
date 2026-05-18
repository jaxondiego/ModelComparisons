"""
app.py — Streamlit dashboard for the LLM safety evaluation framework.

Shows live progress while runner.py / judge.py run, then displays
charts, scores table, and the generated report once results are ready.
"""

import json
import time
from pathlib import Path

import pandas as pd
import streamlit as st

# ── paths ──────────────────────────────────────────────────────────────────

SCORES_FILE = Path("results/scores.json")
RAW_DIR = Path("results/raw")
CHARTS_DIR = Path("results/charts")
REPORT_FILE = Path("results/report.md")
SCENARIOS_FILE = Path("scenarios.json")

MODELS = [
    "openai/gpt-4o",
    "openai/o3",
    "anthropic/claude-sonnet-4-5",
    "google/gemini-2.5-pro",
    "meta-llama/llama-4-maverick",
    "mistralai/mistral-large",
    "x-ai/grok-3",
]

SCORE_COLORS = {
    1: "#2ca02c",
    2: "#8fbc8f",
    3: "#ffdd57",
    4: "#ff7f0e",
    5: "#d62728",
}

# ── helpers ────────────────────────────────────────────────────────────────

@st.cache_data(ttl=5)
def load_scenarios() -> list[dict]:
    if not SCENARIOS_FILE.exists():
        return []
    data = json.loads(SCENARIOS_FILE.read_text())
    return data if isinstance(data, list) else data.get("prompts", [])


def total_pairs() -> int:
    return len(load_scenarios()) * len(MODELS)


@st.cache_data(ttl=3)
def count_raw() -> int:
    return len(list(RAW_DIR.glob("*/*.json"))) if RAW_DIR.exists() else 0


@st.cache_data(ttl=3)
def count_scored() -> int:
    if not SCORES_FILE.exists():
        return 0
    try:
        return len(json.loads(SCORES_FILE.read_text()))
    except Exception:
        return 0


@st.cache_data(ttl=3)
def load_scores() -> pd.DataFrame | None:
    if not SCORES_FILE.exists():
        return None
    try:
        records = json.loads(SCORES_FILE.read_text())
        if not records:
            return None
        df = pd.DataFrame(records)
        df["score"] = pd.to_numeric(df["score"], errors="coerce")
        df = df.dropna(subset=["score"]).copy()
        df["score"] = df["score"].astype(int)
        df["model_short"] = df["model"].str.split("/").str[-1]
        return df
    except Exception:
        return None


def short(model: str) -> str:
    return model.split("/")[-1]


# ── page config ────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="LLM Safety Eval",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── sidebar ────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🔬 LLM Safety Eval")
    st.caption("Election disinformation · 7 models · 30 scenarios")
    st.divider()

    total = total_pairs()
    raw_done = count_raw()
    scored_done = count_scored()
    pipeline_done = scored_done >= total and total > 0

    st.subheader("Pipeline status")
    st.metric("Evaluations", f"{raw_done} / {total}")
    st.progress(raw_done / total if total else 0)
    st.metric("Judge scores", f"{scored_done} / {total}")
    st.progress(scored_done / total if total else 0)

    if pipeline_done:
        st.success("Pipeline complete ✓")
    else:
        st.info("Pipeline running… refreshing every 10 s")

    st.divider()
    st.subheader("Models")
    for m in MODELS:
        slug = m.replace("/", "__")
        done = len(list((RAW_DIR / slug).glob("*.json"))) if (RAW_DIR / slug).exists() else 0
        n_scenarios = len(load_scenarios())
        pct = done / n_scenarios if n_scenarios else 0
        st.write(f"`{short(m)}`")
        st.progress(pct, text=f"{done}/{n_scenarios}")

# ── main ────────────────────────────────────────────────────────────────────

st.title("LLM Safety Evaluation Dashboard")
st.caption(
    "Scores measure compliance with potentially harmful requests: "
    "**1 = full refusal** (safest) → **5 = full compliance** (most dangerous)."
)

tab_overview, tab_charts, tab_scores, tab_report = st.tabs(
    ["📊 Overview", "📈 Charts", "📋 Scores Table", "📄 Report"]
)

# ── Tab: Overview ──────────────────────────────────────────────────────────

with tab_overview:
    df = load_scores()

    if df is None or df.empty:
        st.info("No scores yet — waiting for the pipeline to complete.")
    else:
        means = df.groupby("model")["score"].mean().sort_values()

        # Top-line metrics
        best_m = means.index[0]
        worst_m = means.index[-1]
        cols = st.columns(4)
        cols[0].metric("Models evaluated", df["model"].nunique())
        cols[1].metric("Scenarios", df["scenario_id"].nunique())
        cols[2].metric(f"Safest: {short(best_m)}", f"{means[best_m]:.2f} avg")
        cols[3].metric(f"Riskiest: {short(worst_m)}", f"{means[worst_m]:.2f} avg")

        st.divider()

        # Rankings table
        st.subheader("Rankings")
        rows = []
        for model in means.index:
            sub = df[df["model"] == model]
            rows.append(
                {
                    "Model": short(model),
                    "Mean Score": round(means[model], 2),
                    "% Full Refusal (1)": f"{100*(sub['score']==1).mean():.0f}%",
                    "% Full Compliance (5)": f"{100*(sub['score']==5).mean():.0f}%",
                    "Responses": len(sub),
                }
            )
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Mean Score": st.column_config.ProgressColumn(
                    "Mean Score", min_value=1, max_value=5, format="%.2f"
                )
            },
        )

        st.divider()

        # Per-model score distribution (inline)
        st.subheader("Score distribution")
        dist_rows = []
        for model in df["model"].unique():
            sub = df[df["model"] == model]
            row = {"Model": short(model)}
            for s in range(1, 6):
                row[f"Score {s}"] = int((sub["score"] == s).sum())
            dist_rows.append(row)
        dist_df = pd.DataFrame(dist_rows).set_index("Model")
        st.bar_chart(dist_df, color=list(SCORE_COLORS.values()), stack=True)

# ── Tab: Charts ────────────────────────────────────────────────────────────

with tab_charts:
    charts = {
        "Mean Scores (bar)": CHARTS_DIR / "mean_scores_bar.png",
        "Heatmap": CHARTS_DIR / "heatmap.png",
        "Score Distribution": CHARTS_DIR / "score_distribution.png",
    }
    any_chart = any(p.exists() for p in charts.values())

    if not any_chart:
        st.info("Charts will appear here once `analyze.py` has finished.")
    else:
        for title, path in charts.items():
            if path.exists():
                st.subheader(title)
                st.image(str(path), use_container_width=True)
                st.divider()

# ── Tab: Scores Table ──────────────────────────────────────────────────────

with tab_scores:
    df = load_scores()
    if df is None or df.empty:
        st.info("No scores yet.")
    else:
        # Filters
        fc1, fc2 = st.columns(2)
        sel_models = fc1.multiselect(
            "Filter models",
            options=sorted(df["model"].unique()),
            default=sorted(df["model"].unique()),
            format_func=short,
        )
        sel_scores = fc2.multiselect(
            "Filter scores",
            options=[1, 2, 3, 4, 5],
            default=[1, 2, 3, 4, 5],
        )

        filtered = df[df["model"].isin(sel_models) & df["score"].isin(sel_scores)]
        st.caption(f"{len(filtered)} rows")

        st.dataframe(
            filtered[["model_short", "scenario_id", "score", "reasoning", "judged_by"]].rename(
                columns={
                    "model_short": "Model",
                    "scenario_id": "Scenario",
                    "score": "Score",
                    "reasoning": "Reasoning",
                    "judged_by": "Judged By",
                }
            ).sort_values(["Score", "Model"], ascending=[False, True]),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Score": st.column_config.NumberColumn(
                    "Score", min_value=1, max_value=5, format="%d ⭐"
                )
            },
        )

# ── Tab: Report ────────────────────────────────────────────────────────────

with tab_report:
    if not REPORT_FILE.exists():
        st.info("Report will appear here once `analyze.py` has finished.")
    else:
        st.markdown(REPORT_FILE.read_text())

# ── auto-refresh while pipeline is running ─────────────────────────────────

if not pipeline_done:
    time.sleep(10)
    st.rerun()
