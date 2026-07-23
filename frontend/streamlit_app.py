"""SubFit — local Streamlit UI for the SubFit backend (FastAPI).

Run with: streamlit run frontend/streamlit_app.py
"""

import html as html_mod
import os

import requests
import streamlit as st

DEFAULT_BACKEND_URL = os.environ.get("SUBFIT_BACKEND_URL", "http://127.0.0.1:8000")

RISK_EMOJI = {"low": "🟢", "medium": "🟡", "high": "🔴", "unknown": "⚪"}
HIGHLIGHT_COLORS = {"automod": "#ef4444", "oov": "#f97316", "rare": "#eab308"}
HIGHLIGHT_LABELS = {
    "automod": "AutoModerator rule match",
    "oov": "Absent from subreddit vocabulary",
    "rare": "Rare in subreddit vocabulary",
}

st.set_page_config(page_title="SubFit", page_icon="🧭", layout="wide")


def _backend_url() -> str:
    return st.session_state.get("backend_url", DEFAULT_BACKEND_URL).rstrip("/")


def api_get(path: str, **kwargs):
    try:
        r = requests.get(f"{_backend_url()}{path}", timeout=kwargs.pop("timeout", 30), **kwargs)
        return r
    except requests.exceptions.ConnectionError:
        st.error(
            f"Cannot reach the SubFit backend at {_backend_url()}. Is it running?\n\n"
            "Start it with: `cd backend && uvicorn app.main:app --reload`"
        )
        return None


def api_post(path: str, json: dict, timeout: int = 600):
    try:
        r = requests.post(f"{_backend_url()}{path}", json=json, timeout=timeout)
        return r
    except requests.exceptions.ConnectionError:
        st.error(
            f"Cannot reach the SubFit backend at {_backend_url()}. Is it running?\n\n"
            "Start it with: `cd backend && uvicorn app.main:app --reload`"
        )
        return None


def api_delete(path: str, timeout: int = 30):
    try:
        r = requests.delete(f"{_backend_url()}{path}", timeout=timeout)
        return r
    except requests.exceptions.ConnectionError:
        st.error(f"Cannot reach the SubFit backend at {_backend_url()}.")
        return None


def render_highlighted(text: str, spans: list[dict]) -> str:
    if not text:
        return "<em style='opacity:0.6'>(empty)</em>"
    spans = sorted(spans, key=lambda s: s["start"])
    out = []
    cursor = 0
    for s in spans:
        if s["start"] < cursor:
            continue
        out.append(html_mod.escape(text[cursor : s["start"]]))
        color = HIGHLIGHT_COLORS.get(s["type"], "#999999")
        tooltip = s["reason"]
        if s.get("rule_text"):
            tooltip += " | Rule: " + s["rule_text"]
        tooltip = html_mod.escape(tooltip)
        snippet = html_mod.escape(text[s["start"] : s["end"]])
        out.append(
            f'<span style="background-color:{color}33;border-bottom:2px solid {color};'
            f'border-radius:2px;padding:0 1px;" title="{tooltip}">{snippet}</span>'
        )
        cursor = s["end"]
    out.append(html_mod.escape(text[cursor:]))
    return "".join(out).replace("\n", "<br>")


def render_result(result: dict) -> None:
    name = result["subreddit"]
    status = result["status"]

    if status in ("not_fetched", "private", "banned", "not_found", "quarantined", "error"):
        emoji = {"not_fetched": "❔", "private": "🔒", "banned": "🚫", "not_found": "❓", "quarantined": "☣️", "error": "⚠️"}.get(status, "⚠️")
        st.markdown(f"### {emoji} r/{name}")
        st.warning(result["status_detail"] or f"Status: {status}")
        return

    risk_emoji = RISK_EMOJI.get(result["risk_level"], "⚪")
    st.markdown(f"### {risk_emoji} r/{name} — risk: **{result['risk_level'].upper()}** ({result['risk_score']}/100)")

    if result.get("status_detail"):
        st.info(result["status_detail"])

    st.caption(
        f"Corpus: {result['corpus_size']} posts, fetched {result.get('corpus_fetched_at') or 'unknown'}"
    )

    if result["top_concerns"]:
        st.markdown("**Top concerns:**")
        for c in result["top_concerns"]:
            st.markdown(f"- {c}")

    if result["automod_hits"]:
        with st.expander(f"AutoModerator rule matches ({len(result['automod_hits'])})", expanded=True):
            for h in result["automod_hits"]:
                conf_note = "" if h["confidence"] == "explicit" else " _(low-confidence heuristic match)_"
                action_note = f" → action: `{h['action']}`" if h.get("action") else ""
                st.markdown(f"- **'{h['matched_text']}'** in *{h['field']}*{action_note}{conf_note}")

    if result["rules"]:
        with st.expander(f"Subreddit rules ({len(result['rules'])})"):
            for r in result["rules"]:
                st.markdown(f"**{r['short_name']}**: {r['description'] or r['violation_reason']}")

    title_spans = [h for h in result["highlights"] if h["field"] == "title"]
    body_spans = [h for h in result["highlights"] if h["field"] == "body"]

    st.markdown("**Highlighted draft:**")
    st.markdown(
        f"<div style='padding:10px;border:1px solid rgba(128,128,128,0.3);border-radius:6px;margin-bottom:6px'>"
        f"<b>Title:</b> {render_highlighted(st.session_state.get('draft_title', ''), title_spans)}</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div style='padding:10px;border:1px solid rgba(128,128,128,0.3);border-radius:6px'>"
        f"<b>Body:</b> {render_highlighted(st.session_state.get('draft_body', ''), body_spans)}</div>",
        unsafe_allow_html=True,
    )

    legend = "  ".join(
        f"<span style='background-color:{c}33;border-bottom:2px solid {c};padding:0 4px;border-radius:2px'>{HIGHLIGHT_LABELS[k]}</span>"
        for k, c in HIGHLIGHT_COLORS.items()
    )
    st.markdown(f"<div style='margin-top:6px;font-size:0.85em'>{legend}</div>", unsafe_allow_html=True)

    if result["semantic_similarity"] is not None:
        st.metric("Semantic topical fit (cosine similarity to corpus)", f"{result['semantic_similarity']:.2f}")
    else:
        st.caption("Semantic similarity unavailable (embedding model not loaded / corpus has no embeddings).")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("🧭 SubFit")
    st.caption("Check a draft against a subreddit's norms before you post.")
    st.text_input("Backend URL", value=DEFAULT_BACKEND_URL, key="backend_url")
    health = api_get("/health")
    if health is not None:
        if health.status_code == 200:
            data = health.json()
            if data.get("reddit_configured"):
                st.success("Backend connected. Reddit credentials configured.")
            else:
                st.warning(
                    "Backend connected, but Reddit API credentials are not set. "
                    "Add REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET to your .env and restart the backend."
                )
        else:
            st.error(f"Backend returned status {health.status_code}")

st.session_state.setdefault("draft_title", "")
st.session_state.setdefault("draft_body", "")

tab_setup, tab_check, tab_drafts = st.tabs(["🧭 Subreddit Setup", "✅ Draft Checker", "💾 Saved Drafts"])

# ---------------------------------------------------------------------------
# Tab: Subreddit Setup
# ---------------------------------------------------------------------------
with tab_setup:
    st.subheader("Fetch & cache a subreddit's corpus, rules, and AutoModerator config")
    col1, col2 = st.columns([2, 1])
    with col1:
        sub_name = st.text_input("Subreddit name (without r/)", key="setup_sub_name", placeholder="e.g. buildapc")
    with col2:
        post_limit = st.slider("Posts to sample", min_value=2000, max_value=5000, value=3000, step=500)

    if st.button("Fetch / Refresh corpus", type="primary", disabled=not sub_name):
        with st.spinner(f"Fetching r/{sub_name} (posts, rules, AutoModerator config, embeddings)... this can take a minute or two."):
            resp = api_post(f"/subreddits/{sub_name}/fetch", {"limit": post_limit, "force_refresh": True})
        if resp is not None:
            if resp.status_code == 200:
                info = resp.json()
                st.success(f"Fetched r/{info['name']} — status: {info['status']}")
            elif resp.status_code == 503:
                st.error(resp.json().get("detail", "Reddit credentials not configured."))
            else:
                st.error(f"Fetch failed ({resp.status_code}): {resp.text}")

    st.divider()
    st.subheader("Cached subreddits")
    listing = api_get("/subreddits")
    if listing is not None and listing.status_code == 200:
        subs = listing.json()
        if not subs:
            st.caption("No subreddits cached yet. Fetch one above.")
        for s in subs:
            status_emoji = {"ok": "✅", "private": "🔒", "banned": "🚫", "not_found": "❓", "quarantined": "☣️", "error": "⚠️"}.get(s["status"], "⚪")
            with st.expander(f"{status_emoji} r/{s['name']} — {s['num_posts']} posts — fetched {s.get('fetched_at') or 'never'}"):
                st.write(f"**Status:** {s['status']}")
                if s["status_detail"]:
                    st.write(s["status_detail"])
                st.write(f"**Subscribers:** {s['subscribers']:,}  |  **NSFW:** {s['over18']}  |  **Quarantined:** {s['quarantined']}")
                st.write(
                    "**AutoModerator config:** "
                    + ("available ✅" if s["automod_available"] else "not publicly available — vocabulary-fit analysis only")
                )
                if s["rules"]:
                    st.write(f"**Rules ({len(s['rules'])}):**")
                    for r in s["rules"]:
                        st.markdown(f"- **{r['short_name']}**: {r['description'] or r['violation_reason']}")
                else:
                    st.write("**Rules:** none published.")

# ---------------------------------------------------------------------------
# Tab: Draft Checker
# ---------------------------------------------------------------------------
with tab_check:
    st.subheader("Check your draft against one or more subreddits")

    listing = api_get("/subreddits")
    available_subs = []
    if listing is not None and listing.status_code == 200:
        available_subs = [s["name"] for s in listing.json()]

    st.text_input("Draft title", key="draft_title")
    st.text_area("Draft body", key="draft_body", height=180)

    selected = st.multiselect(
        "Check against subreddit(s) (must be fetched in Subreddit Setup first)",
        options=available_subs,
        default=available_subs[:1] if available_subs else [],
    )
    extra = st.text_input("Or type another subreddit name to check (comma-separated, no r/)", key="extra_subs")

    col_a, col_b = st.columns([1, 1])
    with col_a:
        check_clicked = st.button("Check draft", type="primary")
    with col_b:
        save_name = st.text_input("Save this draft as (optional name)", key="save_name", label_visibility="collapsed", placeholder="Name to save this draft as...")
        if st.button("💾 Save draft"):
            resp = api_post("/drafts", {"name": save_name or None, "title": st.session_state.draft_title, "body": st.session_state.draft_body})
            if resp is not None and resp.status_code == 200:
                st.success("Draft saved.")

    if check_clicked:
        all_targets = list(selected)
        if extra.strip():
            all_targets += [s.strip() for s in extra.split(",") if s.strip()]
        all_targets = list(dict.fromkeys(all_targets))  # dedupe, preserve order

        if not all_targets:
            st.warning("Select or type at least one subreddit to check against.")
        elif not (st.session_state.draft_title or st.session_state.draft_body):
            st.warning("Enter a draft title and/or body first.")
        else:
            with st.spinner("Scoring draft..."):
                resp = api_post(
                    "/check",
                    {"title": st.session_state.draft_title, "body": st.session_state.draft_body, "subreddits": all_targets},
                )
            if resp is not None:
                if resp.status_code == 200:
                    results = resp.json()["results"]
                    results.sort(key=lambda r: {"high": 0, "medium": 1, "low": 2, "unknown": 3}.get(r["risk_level"], 4))
                    for r in results:
                        render_result(r)
                        st.divider()
                else:
                    st.error(f"Check failed ({resp.status_code}): {resp.text}")

# ---------------------------------------------------------------------------
# Tab: Saved Drafts
# ---------------------------------------------------------------------------
with tab_drafts:
    st.subheader("Saved drafts")
    resp = api_get("/drafts")
    if resp is not None and resp.status_code == 200:
        drafts = resp.json()
        if not drafts:
            st.caption("No saved drafts yet. Save one from the Draft Checker tab.")
        for d in drafts:
            label = d["name"] or (d["title"][:60] or "(untitled)")
            with st.expander(f"{label} — saved {d['created_at']}"):
                st.write(f"**Title:** {d['title']}")
                st.write(f"**Body:** {d['body']}")
                col_load, col_del = st.columns([1, 1])
                with col_load:
                    if st.button("Load into Draft Checker", key=f"load_{d['id']}"):
                        st.session_state.draft_title = d["title"]
                        st.session_state.draft_body = d["body"]
                        st.success("Loaded — switch to the Draft Checker tab.")
                with col_del:
                    if st.button("Delete", key=f"del_{d['id']}"):
                        api_delete(f"/drafts/{d['id']}")
                        st.rerun()
