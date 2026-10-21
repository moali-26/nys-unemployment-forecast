"""'Ask the forecast': a Claude assistant grounded in the project's own results.

The system prompt holds the Step 2 and Step 3 handoffs, the accuracy table and the
live forecasts, so answers come from our numbers rather than general knowledge.
It is identical on every request, so prompt caching keeps follow-up questions cheap.
"""
import os

import anthropic
import streamlit as st
from dotenv import load_dotenv

from data import MODEL_LABELS, PERIODS, load_forecasts, load_metrics, load_panel, read_text

MODEL = "claude-opus-5-5"

INSTRUCTIONS = """You are the assistant inside a forecasting dashboard built for a UCLA Anderson \
time series course (MGMTMSA 437). The project asks whether economic indicators and alternative \
data improve 1-, 3- and 6-month forecasts of the New York State unemployment rate (FRED NYUR).

Answer questions about the project's data, methods, results and live forecasts using only the \
project material below. Rules:
- Ground every number in the material. If something is not covered, say so plainly instead of guessing.
- Write for a classmate who knows basic statistics: short paragraphs, plain words, define jargon once.
- "Error vs. naive" means RMSE divided by the naive (no-change) forecast's RMSE; below 1 beats naive.
- Be candid about limits: small test samples, pseudo-real-time (not truly out of sample), \
uncertainty ranges calibrated on calm years, and alternative data that was mostly not tested.
- These are forecasts from a class project, not official projections. Do not give financial or \
career advice.
- Keep answers under about 200 words unless the user asks for more detail."""


def get_api_key():
    """Streamlit Cloud secret first, then a local .env file or environment variable."""
    try:
        if "ANTHROPIC_API_KEY" in st.secrets:
            return st.secrets["ANTHROPIC_API_KEY"]
    except FileNotFoundError:
        pass
    load_dotenv()
    return os.environ.get("ANTHROPIC_API_KEY")


@st.cache_data
def build_system_prompt():
    metrics = load_metrics()
    table = metrics[["view", "horizon", "model", "n", "rmse", "rmse_vs_naive", "dm_p_vs_naive"]].copy()
    table["view"] = table["view"].map(PERIODS)
    table["model"] = table["model"].map(MODEL_LABELS)

    live = load_forecasts()
    live = live[live["period"] == "live"].copy()
    live["model"] = live["model"].map(MODEL_LABELS)
    live = live[["origin", "date", "horizon", "model", "yhat", "lower", "upper"]].sort_values(["date", "model"])

    recent = load_panel().tail(14)[["date", "ny_ur", "us_ur", "nj_ur", "ct_ur", "pa_ur",
                                    "ny_claims_avg", "ny_payrolls", "empire_general", "indeed_postings"]]

    sections = [
        INSTRUCTIONS,
        "## Step 2 handoff (time series models)\n" + read_text("docs/STEP2_HANDOFF.md"),
        "## Step 3 handoff (machine learning)\n" + read_text("docs/STEP3_HANDOFF.md"),
        "## Accuracy on the common sample (rmse in percentage points)\n" + table.to_csv(index=False, float_format="%.3f"),
        "## Live forecasts (origin = forecast date, date = target month)\n" + live.to_csv(index=False, float_format="%.2f"),
        "## Latest panel values (reference month, NaN = not yet published)\n" + recent.to_csv(index=False, float_format="%.2f"),
    ]
    return "\n\n".join(sections)


def stream_answer(messages):
    """Yield the answer text as it streams, for st.write_stream."""
    client = anthropic.Anthropic(api_key=get_api_key())
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium"},
        system=[{"type": "text", "text": build_system_prompt(), "cache_control": {"type": "ephemeral"}}],
        messages=messages,
    ) as stream:
        yield from stream.text_stream
        final = stream.get_final_message()
    if final.stop_reason == "refusal":
        yield "\n\nSorry, I can't help with that one. Try asking about the forecasts or models."
    elif final.stop_reason == "max_tokens":
        yield "\n\n_(Answer cut off. Ask me to continue.)_"
