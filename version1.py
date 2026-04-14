import streamlit as st
import pandas as pd
import numpy as np
import os
import uuid
import ast
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(
    page_title="POC Questionnaire",
    layout="wide"
)




AI_BANK_FILE = "mock_ai_bank.csv"
SHEET_NAME = "Participant Responses"
EVENTS_TAB = "response_events"
ANALYSIS_TAB = "analysis_ready"
QUESTIONS_FILE = 'question_bank_2.csv'

NUM_STOCH = 5

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]



if not os.path.exists(AI_BANK_FILE):
    st.error(f"AI bank file '{AI_BANK_FILE}' not found. Run generate_ai_bank.py first.")
    st.stop()

try:
    ai_bank = pd.read_csv(AI_BANK_FILE, encoding="utf-8-sig")
except UnicodeDecodeError:
    ai_bank = pd.read_csv(AI_BANK_FILE, encoding="cp949")
required_ai_cols = ["question_id", "variant_type", "variant_index", "answer"]
missing_ai_cols = [c for c in required_ai_cols if c not in ai_bank.columns]
if missing_ai_cols:
    st.error(f"AI bank file is missing required columns: {missing_ai_cols}")
    st.stop()
ai_bank["question_id"] = ai_bank["question_id"].astype(str)
ai_bank["variant_index"] = ai_bank["variant_index"].astype(int)
ai_bank["variant_type"] = ai_bank["variant_type"].astype(str)

st.markdown("""
<style>
/* reduce the huge top whitespace */
div.block-container {
    padding-top: 1rem;
    padding-bottom: 1rem;
    max-width: 95%;
}

/* tighten header spacing */
h1 {
    margin-top: 0 !important;
    margin-bottom: 0.2rem !important;
}

/* reduce extra space above first element */
section.main > div:has(div.block-container) {
    padding-top: 0rem !important;
}

/* ===== Likert Table ===== */
.likert-table {
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    padding: 0.8rem;
    background: #fafafa;
}

.likert-header-row {
    display: grid;
    grid-template-columns: 220px repeat(5, 1fr);
    text-align: center;
    font-weight: 600;
    margin-bottom: 0.4rem;
}

.likert-row {
    display: grid;
    grid-template-columns: 220px repeat(5, 1fr);
    align-items: center;
    padding: 0.4rem 0;
    border-top: 1px solid #e5e7eb;
}

.likert-label {
    font-weight: 600;
}

div[data-testid="stButton"] > button {
    min-height: 1.9rem;
    padding: 0.1rem 0.3rem;
    font-size: 0.85rem;
    border-radius: 0.5rem;
}
            
div[data-testid="stHorizontalBlock"] {
    gap: 0.2rem;
}
div[data-testid="stHorizontalBlock"] {
    gap: 0.2rem;
}

</style>
""", unsafe_allow_html=True)
st.markdown("""
<div style="text-align: center; margin-top: 0; margin-bottom: 0.6rem;">
    <h1 style="margin: 0; font-size: 2rem;">POC Questionnaire</h1>
    <p style="margin: 0.15rem 0 0 0; color: #6b7280; font-size: 0.98rem;">
        Please answer each question and rate the AI responses.
    </p>
</div>
""", unsafe_allow_html=True)





if not os.path.exists(QUESTIONS_FILE):
    st.error(f"Questions file '{QUESTIONS_FILE}' not found.")
    st.stop()

try:
    df = pd.read_csv(QUESTIONS_FILE, encoding="utf-8-sig")
except UnicodeDecodeError:
    df = pd.read_csv(QUESTIONS_FILE, encoding="cp949")
required_question_cols = ["question_id", "topic", "question", "translation"]
missing_question_cols = [c for c in required_question_cols if c not in df.columns]
if missing_question_cols:
    st.error(f"Questions file is missing required columns: {missing_question_cols}")
    st.stop()
df['question_id'] = df['question_id'].astype(str)

query_params = st.query_params

if 'participant_id' not in st.session_state:
    existing_pid = query_params.get("pid", None)
    if existing_pid:
        st.session_state.participant_id = str(existing_pid)
    else:
        st.session_state.participant_id = str(uuid.uuid4())

if 'last_logged_drafts' not in st.session_state:
    st.session_state.last_logged_drafts = {}
    
if "stoch_choice" not in st.session_state:
    st.session_state.stoch_choice = {}

if 'phase' not in st.session_state:
    st.session_state.phase = 'disclaimer'

if 'demographics' not in st.session_state:
    st.session_state.demographics = {}

if 'consent_given' not in st.session_state:
    st.session_state.consent_given = False

if 'finish_clicked' not in st.session_state:
    st.session_state.finish_clicked = False

if 'locked' not in st.session_state:
    st.session_state.locked = False

if 'idx' not in st.session_state:
    st.session_state.idx = 0

if 'answers' not in st.session_state:
    st.session_state.answers = {}

if 'answers_json' not in st.session_state:
    st.session_state.answers_json = {}

if 'drafts' not in st.session_state:
    st.session_state.drafts = {}

if 'visited' not in st.session_state:
    st.session_state.visited = {}

if 'active_qid' not in st.session_state:
    st.session_state.active_qid = None
if 'gsheet_saved' not in st.session_state:
    st.session_state.gsheet_saved = False
if 'recovery_loaded' not in st.session_state:
    st.session_state.recovery_loaded = False


ui_locked = st.session_state.locked or st.session_state.finish_clicked

def get_spreadsheet():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=SCOPES,
    )
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME)

def get_worksheet(tab_name: str):
    spreadsheet = get_spreadsheet()
    return spreadsheet.worksheet(tab_name)

def append_dataframe_to_sheet(out_df: pd.DataFrame, tab_name: str):
    worksheet = get_worksheet(tab_name)
    rows = out_df.fillna("").values.tolist()
    worksheet.append_rows(rows, value_input_option="RAW")

def log_event(event_type: str, qid: str = "", event_data: dict | None = None):
    if event_data is None:
        event_data = {}

    event_row = {
        "event_timestamp": datetime.utcnow().isoformat(),
        "participant_id": st.session_state.participant_id,
        "phase": st.session_state.get("phase", ""),
        "question_id": qid,
        "event_type": event_type,
        "event_data": str(event_data),
    }

    event_df = pd.DataFrame([event_row])
    append_dataframe_to_sheet(event_df, EVENTS_TAB)
def load_participant_events() -> pd.DataFrame:
    worksheet = get_worksheet(EVENTS_TAB)
    records = worksheet.get_all_records()
    if not records:
        return pd.DataFrame()

    events_df = pd.DataFrame(records)
    if events_df.empty:
        return events_df

    events_df["participant_id"] = events_df["participant_id"].astype(str)
    events_df = events_df[events_df["participant_id"] == str(st.session_state.participant_id)].copy()

    if not events_df.empty and "event_timestamp" in events_df.columns:
        events_df = events_df.sort_values("event_timestamp")

    return events_df


def parse_event_data(raw):
    if raw in [None, ""]:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return ast.literal_eval(raw)
    except Exception:
        return {}

def restore_state_from_events():
    events_df = load_participant_events()
    if events_df.empty:
        st.session_state.recovery_loaded = True
        return

    latest_answers = {}
    latest_ratings = {}
    disclaimer_seen = False
    demographics_payload = None
    survey_finished = False

    for _, event in events_df.iterrows():
        event_type = event.get("event_type", "")
        qid = str(event.get("question_id", "") or "")
        payload = parse_event_data(event.get("event_data", ""))

        if event_type == "disclaimer_accepted":
            disclaimer_seen = True

        elif event_type == "demographics_submitted":
            demographics_payload = payload

        elif event_type in ["answer_completed", "answer_updated_after_ai"]:
            latest_answers[qid] = {
                "answer": payload.get("answer", ""),
                "pna_flag": payload.get("pna_flag", 0),
                "timestamp": payload.get("timestamp", event.get("event_timestamp")),
            }

        elif event_type == "question_fully_rated":
            latest_ratings[qid] = payload

        elif event_type == "survey_finished":
            survey_finished = True

    if disclaimer_seen:
        st.session_state.consent_given = True

    if demographics_payload:
        st.session_state.demographics = {
            "age_group": demographics_payload.get("age_group", ""),
            "gender": demographics_payload.get("gender", ""),
            "korean_familiarity": demographics_payload.get("korean_familiarity", ""),
            "nationality_background": demographics_payload.get("nationality_background", ""),
            "demographic_comments": demographics_payload.get("demographic_comments", ""),
            "demographics_timestamp": demographics_payload.get("demographics_timestamp", ""),
        }

    for qid, payload in latest_answers.items():
        st.session_state.answers[qid] = payload
        st.session_state.answers_json[qid] = payload
        st.session_state.drafts[qid] = payload.get("answer", "")

    for qid, payload in latest_ratings.items():
        chosen_idx = int(payload.get("chosen_index", 1))

        det_row = get_ai_from_bank(qid, "det", 0)
        stoch_row = get_ai_from_bank(qid, "stoch", chosen_idx)

        if qid not in st.session_state.answers_json:
            st.session_state.answers_json[qid] = {
                "answer": "",
                "pna_flag": None,
                "timestamp": None,
            }

        st.session_state.answers_json[qid]["ai_det"] = {
            "answer": det_row.get("answer", ""),
            "temperature": det_row.get("temperature", None),
            "model": det_row.get("model", None),
            "run_id": det_row.get("run_id", None),
            "generated_at_utc": det_row.get("generated_at_utc", None),
            "error": det_row.get("error", None),
        }

        st.session_state.answers_json[qid]["ai_stoch"] = {
            "chosen_index": chosen_idx,
            "answer": stoch_row.get("answer", ""),
            "temperature": stoch_row.get("temperature", None),
            "model": stoch_row.get("model", None),
            "run_id": stoch_row.get("run_id", None),
            "generated_at_utc": stoch_row.get("generated_at_utc", None),
            "error": stoch_row.get("error", None),
        }

        st.session_state.answers_json[qid]["ratings_det"] = {
            "correctness": payload.get("det_correctness"),
            "cultural_sensitivity": payload.get("det_cultural_sensitivity"),
            "stereotypes": payload.get("det_stereotypes"),
            "nuance": payload.get("det_nuance"),
            "overall": payload.get("det_overall"),
            "rated_timestamp": payload.get("timestamp"),
        }

        st.session_state.answers_json[qid]["ratings_stoch"] = {
            "correctness": payload.get("stoch_correctness"),
            "cultural_sensitivity": payload.get("stoch_cultural_sensitivity"),
            "stereotypes": payload.get("stoch_stereotypes"),
            "nuance": payload.get("stoch_nuance"),
            "overall": payload.get("stoch_overall"),
            "rated_timestamp": payload.get("timestamp"),
        }

        st.session_state.stoch_choice[qid] = chosen_idx

    # Restore app phase
    if survey_finished:
        st.session_state.finish_clicked = True
        st.session_state.locked = True
    elif demographics_payload:
        st.session_state.phase = "answer"
    elif disclaimer_seen:
        st.session_state.phase = "demographics"

    # Restore current question index to first incomplete question
    if not survey_finished:
        qids = df["question_id"].astype(str).tolist()
        first_incomplete_idx = 0

        for i, qid in enumerate(qids):
            resp = st.session_state.answers_json.get(qid, {})
            has_answer = qid in st.session_state.answers_json
            has_det = "ratings_det" in resp
            has_stoch = "ratings_stoch" in resp

            if not (has_answer and has_det and has_stoch):
                first_incomplete_idx = i
                break
        else:
            first_incomplete_idx = len(qids) - 1

        st.session_state.idx = first_incomplete_idx

    st.session_state.recovery_loaded = True



def get_ai_from_bank(qid: str, variant_type: str, variant_index: int):
    subset = ai_bank[
        (ai_bank["question_id"] == qid) &
        (ai_bank["variant_type"] == variant_type) &
        (ai_bank["variant_index"] == variant_index)
    ]
    if subset.empty:
        return {"answer": "", "temperature": None, "model": None, "run_id": None, "generated_at_utc": None, "error": "missing_row"}

    row = subset.iloc[0].to_dict()
    return row

def get_status(qid):
    answered = qid in st.session_state.answers_json
    resp = st.session_state.answers_json.get(qid, {})

    det_rated = "ratings_det" in resp
    stoch_rated = "ratings_stoch" in resp

    draft = (st.session_state.drafts.get(qid, "").strip() != "")
    visited = st.session_state.visited.get(qid, False)

    if answered and det_rated and stoch_rated:
        return "fully_rated"

    if answered and (det_rated or stoch_rated):
        return "one_rating_done"

    if answered:
        return "answered_only"

    if draft:
        return "draft"

    if visited:
        return "unanswered"

    return "untouched"


def set_likert_value(state_key, value):
    st.session_state[state_key] = value

def likert_row(label, key, default):
    if key not in st.session_state:
        st.session_state[key] = default if default in [1, 2, 3, 4, 5] else 3

    cols = st.columns([2, 1, 1, 1, 1, 1])

    with cols[0]:
        st.markdown(
            f"<div style='font-weight:600; padding-top:0.2rem; font-size:0.9rem;'>{label}</div>",
            unsafe_allow_html=True
        )

    for idx, option in enumerate([1, 2, 3, 4, 5], start=1):
        with cols[idx]:
            is_selected = st.session_state[key] == option
            st.button(
                str(option),
                key=f"{key}_btn_{option}",
                use_container_width=True,
                type="primary" if is_selected else "secondary",
                on_click=set_likert_value,
                args=(key, option),
            )

    return st.session_state[key]

def prime_textbox(qid):
    saved = st.session_state.answers.get(qid)
    if saved is not None:
        initial = saved.get("answer", "")
    else:
        initial = st.session_state.drafts.get(qid, "")
    st.session_state[f"answer_box_{qid}"] = initial

def go_to_index(new_idx):
    st.session_state.idx = max(0, min(new_idx, len(df) - 1))
    target_qid = df.iloc[st.session_state.idx]["question_id"]
    prime_textbox(target_qid)
    st.rerun()

def default_ratings():
    return {
        "correctness": 3,
        "cultural_sensitivity": 3,
        "stereotypes": 3,
        "nuance": 3,
        "overall": 3,
    }

def unanswered_count():
    return len(df) - len(st.session_state.answers_json)

def all_answered():
    return len(st.session_state.answers_json) == len(df)

def all_rated():
    for qid_iter in df["question_id"].astype(str).tolist():
        resp = st.session_state.answers_json.get(qid_iter, {})
        if "ratings_det" not in resp or "ratings_stoch" not in resp:
            return False
    return True

if not st.session_state.recovery_loaded:
    restore_state_from_events()

st.write("participant_id:", st.session_state.participant_id)
st.write("url pid:", st.query_params.get("pid", None))

if st.session_state.phase == "disclaimer":
    st.markdown("## Disclaimer")
    st.markdown("""
Please read this before continuing.

- Your responses will be recorded for research purposes.
- You will be asked to answer demographic questions first.
- Then you will answer survey questions and rate AI-generated responses.
- Please answer honestly and thoughtfully.
    """)

    consent = st.checkbox("I have read the disclaimer and agree to continue.")

    if st.button("Continue", type="primary", disabled=not consent):
        st.session_state.consent_given = True
        st.query_params["pid"] = st.session_state.participant_id
        log_event("disclaimer_accepted")
        st.session_state.phase = "demographics"
        st.rerun()

    st.stop()

elif st.session_state.phase == "demographics":
    st.markdown("## Demographic Questions")

    age = st.selectbox(
        "Age group",
        ["", "18-24", "25-34", "35-44", "45-54", "55+"],
        index=0
    )

    gender = st.selectbox(
        "Gender",
        ["", "Female", "Male", "Non-binary", "Prefer not to say", "Other"],
        index=0
    )

    korean_familiarity = st.selectbox(
        "How familiar are you with Korean culture?",
        ["", "Not at all familiar", "Slightly familiar", "Moderately familiar", "Very familiar", "Extremely familiar"],
        index=0
    )

    nationality = st.text_input("Nationality / cultural background (optional)")
    comments = st.text_area("Anything else you'd like to share? (optional)", height=100)

    demo_complete = age != "" and gender != "" and korean_familiarity != ""

    if st.button("Continue to Survey", type="primary", disabled=not demo_complete):
        st.session_state.demographics = {
            "age_group": age,
            "gender": gender,
            "korean_familiarity": korean_familiarity,
            "nationality_background": nationality.strip(),
            "demographic_comments": comments.strip(),
            "demographics_timestamp": datetime.now().isoformat(),
        }
        log_event(
            "demographics_submitted",
            event_data={
                "age_group": age,
                "gender": gender,
                "korean_familiarity": korean_familiarity,
                "nationality_background": nationality.strip(),
                "demographic_comments": comments.strip(),
                "demographics_timestamp": st.session_state.demographics["demographics_timestamp"],
            },
        )
        st.session_state.phase = "answer"
        st.rerun()

    st.stop()


row = df.iloc[st.session_state.idx]
qid = str(row['question_id'])
if st.session_state.active_qid != qid:
    st.session_state.active_qid = qid
question = str(row.get("question", "")).strip().replace('"', '').replace("'", "")
translation = str(row.get("translation", "")).strip().replace('"', '').replace("'", "")

st.session_state.visited[qid] = True
st.markdown(
    f"""
    <div style="
        margin-top: 0.15rem;
        margin-bottom: 0.7rem;
        padding: 0.85rem 1rem;
        border: 1px solid #e5e7eb;
        border-radius: 1rem;
        background: #fafafa;
    ">
        <div style="
            margin-bottom: 0.25rem;
            color: #6b7280;
            font-size: 0.92rem;
            font-weight: 600;
        ">
            Question {st.session_state.idx + 1} of {len(df)}
        </div>
        <div style="
            font-size: 1.35rem;
            line-height: 1.4;
            font-weight: 700;
            color: #111827;
            margin-bottom: 0.45rem;
        ">
            {question}
        </div>
        <div style="
            font-size: 1.05rem;
            line-height: 1.5;
            font-weight: 500;
            color: #374151;
        ">
            {translation}
        </div>
    </div>
    """,
    unsafe_allow_html=True
)
saved = st.session_state.answers.get(qid)

if saved is not None:
    initial_value = saved.get("answer", "")
else:
    initial_value = st.session_state.drafts.get(qid, "")

answer_key = f"answer_box_{qid}"
st.sidebar.header("Questions Navigation")

st.sidebar.markdown("""
    <style>
    div[data-testid="stSidebar"] div[data-testid="stButton"] > button {
        width: 100%;
        text-align: left;
        justify-content: flex-start;
        border-radius: 0.75rem;
        padding: 0.45rem 0.75rem;
        font-weight: 600;
        margin-bottom: 0.55rem;
        min-height: 2.2rem;
    }
    div[data-testid="stSidebar"] div[data-testid="stButton"] > button p {
        font-size: 0.9rem;
    }
    </style>
    """, unsafe_allow_html=True)


for i, row in df.iterrows():
    qid_side = str(row["question_id"])
    status = get_status(qid_side)
    topic = str(row.get("topic", "")).strip().replace('"', '').replace("'", "")

    color_map = {
        "untouched": "#d1d5db",      # gray
        "unanswered": "#ef4444",     # red
        "draft": "#f59e0b",          # yellow
        "answered_only": "#3b82f6",  # blue
        "one_rating_done": "#6366f1",# indigo
        "fully_rated": "#22c55e",    # green
    }
    color = color_map.get(status, "#d1d5db")

    prefix = "▶ " if i == st.session_state.idx else ""

    st.sidebar.markdown(
        f"""
        <div style="
            display:flex;
            align-items:center;
            gap:0.55rem;
            margin-bottom:0.2rem;
            text-align:left;
        ">
            <div style="
                width:10px;
                height:10px;
                border-radius:50%;
                background:{color};
                flex-shrink:0;
            "></div>
            <div style="text-align:left;">
                {prefix}Q{i + 1} - <b>{topic}</b>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    label_map = {
        "untouched": "Open",
        "unanswered": "Open",
        "draft": "Finish Answering",
        "answered_only": "Finish Rating",
        "one_rating_done": "Finish Rating",
        "fully_rated": "All Done!",
    }

    button_type_map = {
        "untouched": "secondary",
        "unanswered": "secondary",
        "draft": "primary",
        "answered_only": "primary",
        "one_rating_done": "primary",
        "fully_rated": "secondary",
    }

    btn_label = label_map.get(status, "Open")
    btn_type = button_type_map.get(status, "secondary")

    if st.sidebar.button(
        btn_label,
        key=f"nav_{qid_side}",
        disabled=ui_locked,
        use_container_width=True,
        type=btn_type
    ):
        st.session_state.phase = "answer"
        go_to_index(i)

st.sidebar.divider()

if answer_key not in st.session_state:
    st.session_state[answer_key] = initial_value

st.markdown("""
<style>
div[data-testid="stTextArea"] textarea {
    border-radius: 0.9rem;
    padding: 0.95rem 1rem;
    font-size: 1rem;
    line-height: 1.55;
}
div[data-testid="stTextArea"] label p {
    font-size: 1.02rem;
    font-weight: 600;
}
div[data-testid="stHorizontalBlock"] div[data-testid="stButton"] > button {
    min-height: 3.1rem;
    border-radius: 0.85rem;
    font-weight: 600;
}
</style>
""", unsafe_allow_html=True)


if st.session_state.phase == 'answer':
    st.markdown(
        """
        <div style="margin-top: 0.25rem; margin-bottom: 0.45rem; font-size: 1.02rem; font-weight: 600;">
            Your response
        </div>
        """,
        unsafe_allow_html=True
    )

    answer = st.text_area(
        label="Write your answer here",
        key=answer_key,
        height=170,
        disabled=ui_locked,
        label_visibility="collapsed"
    )

    st.session_state.drafts[qid] = answer

    submitted_before = (qid in st.session_state.answers)
    submitted_answer = st.session_state.answers.get(qid, {}).get('answer', '') if submitted_before else ''

    is_dirty = (answer.strip() != submitted_answer.strip()) if submitted_before else (answer.strip() != '')
    can_submit = is_dirty and (answer.strip() != '')

    if submitted_before and not is_dirty:
        submit_label = "Submitted"
        submit_disabled = True
    elif submitted_before and is_dirty:
        submit_label = "Update Answer"
        submit_disabled = False
    else:
        submit_label = "Submit Answer"
        submit_disabled = not can_submit

    col1, col2, col3 = st.columns([1.15, 1.25, 1.6])

    with col1:
        go_to_ratings = st.button(
            "Go to Ratings",
            disabled=(qid not in st.session_state.answers_json or ui_locked),
            key=f"go_to_ratings_{qid}",
            use_container_width=True
        )

    with col2:
        submitted = st.button(
            submit_label,
            disabled=(submit_disabled or ui_locked),
            type="primary",
            key=f"submit_{qid}",
            use_container_width=True
        )

    with col3:
        skip = st.button(
            "Prefer not to answer / Skip",
            disabled=ui_locked,
            key=f"skip_{qid}",
            use_container_width=True
        )
    
    if go_to_ratings:
        resp = st.session_state.answers_json.get(qid, {})
        if "ratings_det" not in resp:
            st.session_state.phase = "rate_det"
        elif "ratings_stoch" not in resp:
            st.session_state.phase = "rate_stoch"
        else:
            st.session_state.phase = "rate_det"  # review
        st.rerun()


    if submitted:        
        payload = {'answer': answer.strip(), 'pna_flag': 0, 'timestamp': datetime.now().isoformat()}

        had_ai_exposure = (
            "ratings_det" in st.session_state.answers_json.get(qid, {}) or
            "ratings_stoch" in st.session_state.answers_json.get(qid, {})
        )
        prior_answer = st.session_state.answers.get(qid, {}).get("answer", "").strip()
        is_update_after_ai = had_ai_exposure and (answer.strip() != prior_answer)

        st.session_state.answers[qid] = payload
        st.session_state.answers_json[str(qid)] = payload

        if is_update_after_ai:
            log_event(
                "answer_updated_after_ai",
                qid=qid,
                event_data={
                    "answer": answer.strip(),
                    "pna_flag": 0,
                    "timestamp": payload["timestamp"],
                },
            )
        else:
            log_event(
                "answer_completed",
                qid=qid,
                event_data={
                    "answer": answer.strip(),
                    "pna_flag": 0,
                    "timestamp": payload["timestamp"],
                },
            )

        st.session_state.drafts[qid] = ''
        st.session_state.phase = 'rate_det'
        st.rerun()

    if skip:
        payload = {'answer': '', 'pna_flag': 1, 'timestamp': datetime.now().isoformat()}
        st.session_state.answers[qid] = payload
        st.session_state.answers_json[str(qid)] = payload

        log_event(
            "answer_completed",
            qid=qid,
            event_data={
                "answer": "",
                "pna_flag": 1,
                "timestamp": payload["timestamp"],
            },
        )

        st.session_state.drafts[qid] = ''
        st.session_state.phase = 'rate_det'
        st.rerun()

       
elif st.session_state.phase == "rate_det":
    st.subheader("AI Answer (Deterministic)")

    det_row = get_ai_from_bank(qid, "det", 0)
    det_answer = det_row.get("answer", "")
    st.write(det_answer if det_answer else "[No deterministic answer available]")

    # ratings load
    prior = st.session_state.answers_json.get(qid, {}).get("ratings_det", default_ratings())

    for metric_key, metric_default in {
        f"det_correct_{qid}": prior.get("correctness", 3),
        f"det_cultural_{qid}": prior.get("cultural_sensitivity", 3),
        f"det_stereo_{qid}": prior.get("stereotypes", 3),
        f"det_nuance_{qid}": prior.get("nuance", 3),
        f"det_overall_{qid}": prior.get("overall", 3),
    }.items():
        if metric_key not in st.session_state:
            st.session_state[metric_key] = metric_default


    with st.container(border=True):
        header_cols = st.columns([2.2, 1, 1, 1, 1, 1])
        headers = [
            "Rate the AI response",
            "Strongly Disagree",
            "Somewhat Disagree",
            "Neutral",
            "Somewhat Agree",
            "Strongly Agree"
        ]

        for col, text in zip(header_cols, headers):
            with col:
                st.markdown(
                    f"<div style='text-align:center; font-weight:600; font-size:0.82rem; line-height:1.2;'>{text}</div>",
                    unsafe_allow_html=True
                )
        st.divider()
        r_correctness = likert_row("Correctness", f"det_correct_{qid}", prior.get("correctness", 3))
        st.markdown("<div style='margin:0.2rem 0;'></div>", unsafe_allow_html=True)
        r_cultural = likert_row("Cultural Sensitivity", f"det_cultural_{qid}", prior.get("cultural_sensitivity", 3))
        st.markdown("<div style='margin:0.2rem 0;'></div>", unsafe_allow_html=True)
        r_stereotypes = likert_row("Stereotypes / Bias", f"det_stereo_{qid}", prior.get("stereotypes", 3))
        st.markdown("<div style='margin:0.2rem 0;'></div>", unsafe_allow_html=True)
        r_nuance = likert_row("Nuance", f"det_nuance_{qid}", prior.get("nuance", 3))
        st.markdown("<div style='margin:0.2rem 0;'></div>", unsafe_allow_html=True)
        r_overall = likert_row("Overall", f"det_overall_{qid}", prior.get("overall", 3))

    colA, colB = st.columns([1, 1])
    with colA:
        if st.button("Back to Answer", key=f"back_to_answer_det_{qid}", disabled=ui_locked):
            st.session_state.phase = "answer"
            st.rerun()

    with colB:
        if st.button("Save deterministic ratings", type="primary", key=f"save_det_{qid}", disabled=ui_locked):
            # ensure answer_json exists
            if qid not in st.session_state.answers_json:
                st.session_state.answers_json[qid] = {"answer": "", "pna_flag": None, "timestamp": None}

            st.session_state.answers_json[qid]["ai_det"] = {
                "answer": det_answer,
                "temperature": det_row.get("temperature", None),
                "model": det_row.get("model", None),
                "run_id": det_row.get("run_id", None),
                "generated_at_utc": det_row.get("generated_at_utc", None),
                "error": det_row.get("error", None),
            }

            st.session_state.answers_json[qid]["ratings_det"] = {
                "correctness": r_correctness,
                "cultural_sensitivity": r_cultural,
                "stereotypes": r_stereotypes,
                "nuance": r_nuance,
                "overall": r_overall,
                "rated_timestamp": datetime.utcnow().isoformat(),
            }
            st.session_state.phase = "rate_stoch"
            st.rerun()

elif st.session_state.phase == "rate_stoch":
    st.subheader("AI Answer (Stochastic)")

    # stable per participant/question choice in [1..5]
    if qid not in st.session_state.stoch_choice:
        st.session_state.stoch_choice[qid] = int(np.random.randint(1, NUM_STOCH + 1))

    chosen_idx = int(st.session_state.stoch_choice[qid])

    st_row = get_ai_from_bank(qid, "stoch", chosen_idx)
    st_answer = st_row.get("answer", "")
    st.write(st_answer if st_answer else f"[No stochastic answer available for variant {chosen_idx}]")

    prior = st.session_state.answers_json.get(qid, {}).get("ratings_stoch", default_ratings())

    for metric_key, metric_default in {
        f"st_correct_{qid}": prior.get("correctness", 3),
        f"st_cultural_{qid}": prior.get("cultural_sensitivity", 3),
        f"st_stereo_{qid}": prior.get("stereotypes", 3),
        f"st_nuance_{qid}": prior.get("nuance", 3),
        f"st_overall_{qid}": prior.get("overall", 3),
    }.items():
        if metric_key not in st.session_state:
            st.session_state[metric_key] = metric_default

    with st.container(border=True):
        header_cols = st.columns([2, 1, 1, 1, 1, 1])
        headers = [
            "Rate the AI response",
            "Strongly Disagree",
            "Somewhat Disagree",
            "Neutral",
            "Somewhat Agree",
            "Strongly Agree"
        ]

        for col, text in zip(header_cols, headers):
            with col:
                st.markdown(
                    f"<div style='text-align:center; font-weight:600; font-size:0.82rem; line-height:1.2;'>{text}</div>",
                    unsafe_allow_html=True
                )
        st.divider()
        r_correctness = likert_row("Correctness", f"st_correct_{qid}", prior.get("correctness", 3))
        st.markdown("<div style='margin:0.2rem 0;'></div>", unsafe_allow_html=True)
        r_cultural = likert_row("Cultural Sensitivity", f"st_cultural_{qid}", prior.get("cultural_sensitivity", 3))
        st.markdown("<div style='margin:0.2rem 0;'></div>", unsafe_allow_html=True)
        r_stereotypes = likert_row("Stereotypes / Bias", f"st_stereo_{qid}", prior.get("stereotypes", 3))
        st.markdown("<div style='margin:0.2rem 0;'></div>", unsafe_allow_html=True)
        r_nuance = likert_row("Nuance", f"st_nuance_{qid}", prior.get("nuance", 3))
        st.markdown("<div style='margin:0.2rem 0;'></div>", unsafe_allow_html=True)
        r_overall = likert_row("Overall", f"st_overall_{qid}", prior.get("overall", 3))
    colA, colB = st.columns([1, 1])
    with colA:
        if st.button("Back to Deterministic Ratings", key=f"back_to_det_{qid}", disabled=ui_locked):
            st.session_state.phase = "rate_det"
            st.rerun()

    with colB:
        if st.button("Save stochastic ratings & continue", type="primary", key=f"save_stoch_{qid}", disabled=ui_locked):
            if qid not in st.session_state.answers_json:
                st.session_state.answers_json[qid] = {"answer": "", "pna_flag": None, "timestamp": None}

            st.session_state.answers_json[qid]["ai_stoch"] = {
                "chosen_index": chosen_idx,
                "answer": st_answer,
                "temperature": st_row.get("temperature", None),
                "model": st_row.get("model", None),
                "run_id": st_row.get("run_id", None),
                "generated_at_utc": st_row.get("generated_at_utc", None),
                "error": st_row.get("error", None),
            }

            st.session_state.answers_json[qid]["ratings_stoch"] = {
                "correctness": r_correctness,
                "cultural_sensitivity": r_cultural,
                "stereotypes": r_stereotypes,
                "nuance": r_nuance,
                "overall": r_overall,
                "rated_timestamp": datetime.utcnow().isoformat(),
            }
            det_payload = st.session_state.answers_json[qid].get("ratings_det", {})

            log_event(
                "question_fully_rated",
                qid=qid,
                event_data={
                    "chosen_index": chosen_idx,
                    "det_correctness": det_payload.get("correctness"),
                    "det_cultural_sensitivity": det_payload.get("cultural_sensitivity"),
                    "det_stereotypes": det_payload.get("stereotypes"),
                    "det_nuance": det_payload.get("nuance"),
                    "det_overall": det_payload.get("overall"),
                    "stoch_correctness": r_correctness,
                    "stoch_cultural_sensitivity": r_cultural,
                    "stoch_stereotypes": r_stereotypes,
                    "stoch_nuance": r_nuance,
                    "stoch_overall": r_overall,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

            st.session_state.phase = "answer"
            if st.session_state.idx < len(df) - 1:
                st.session_state.idx += 1
                next_qid = df.iloc[st.session_state.idx]["question_id"]
                prime_textbox(next_qid)
                st.rerun()
            else:
                st.success("All ratings saved. You can finish the survey.")
                st.rerun()


st.divider()
if st.session_state.phase == "answer":
    if all_rated() and not st.session_state.finish_clicked:
        st.success("You have answered and rated all questions. You can review your responses or finish the survey.")
    elif all_answered() and not all_rated() and not st.session_state.finish_clicked:
        st.info("You have answered all questions. Please complete both ratings for each question to finish the survey.")

st.markdown("""
<div style="
    margin-top: 0.35rem;
    margin-bottom: 0.5rem;
    padding: 0.85rem 1rem;
    border: 1px solid #e5e7eb;
    border-radius: 1rem;
    background: #fafafa;
">
""", unsafe_allow_html=True)

col3, col4, col5 = st.columns([1, 1, 1.2])

with col3:
    if st.button(
        "Previous Question",
        disabled=(st.session_state.idx == 0 or ui_locked),
        use_container_width=True
    ):
        st.session_state.phase = "answer"
        go_to_index(st.session_state.idx - 1)

with col4:
    if st.button(
        "Next Question",
        disabled=(st.session_state.idx == len(df) - 1 or ui_locked),
        use_container_width=True
    ):
        st.session_state.phase = "answer"
        go_to_index(st.session_state.idx + 1)

with col5:
    all_done = all_rated() and all_answered()
    current_answered_count = len(st.session_state.answers_json)

    if st.button(
        "Finish Survey",
        disabled=(not all_done or ui_locked),
        type="primary",
        use_container_width=True
    ):
        log_event(
            "survey_finished",
            qid=qid,
            event_data={
                "all_done": all_done,
                "answered_count": current_answered_count,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
        st.session_state.finish_clicked = True
        st.session_state.locked = True
        st.rerun()

st.markdown("</div>", unsafe_allow_html=True)

all_done = all_rated() and all_answered()
if all_done and st.session_state.finish_clicked:
    st.success("Survey completed! You can download your responses as a CSV file below.")

answered_count = len(st.session_state.answers_json)

det_rated_count = sum(
    1 for q in df["question_id"].tolist()
    if "ratings_det" in st.session_state.answers_json.get(q, {})
)
stoch_rated_count = sum(
    1 for q in df["question_id"].tolist()
    if "ratings_stoch" in st.session_state.answers_json.get(q, {})
)

# define total "steps": each question has 3 steps (answer, det rating, stoch rating)
total_steps = len(df) * 3
done_steps = answered_count + det_rated_count + stoch_rated_count
progress = (done_steps / total_steps) if total_steps else 0

st.progress(progress)
st.caption(
    f"Progress: Answers {answered_count}/{len(df)} | "
    f"Det ratings {det_rated_count}/{len(df)} | "
    f"Stoch ratings {stoch_rated_count}/{len(df)}"
)

all_done = all_rated() and all_answered()
if all_done and st.session_state.finish_clicked:
    rows = []
    for _, r in df.iterrows():
        qid_iter = str(r["question_id"])
        topic_iter = str(r.get("topic", "")).strip().replace('"', '').replace("'", "")
        qtext_iter = str(r.get("question", "")).strip().replace('"', '').replace("'", "")
        translation_iter = str(r.get("translation", "")).strip().replace('"', '').replace("'", "")
        resp = st.session_state.answers_json.get(qid_iter, {})
        

        ai_det = resp.get("ai_det", {})
        ai_stoch = resp.get("ai_stoch", {})

        rd = resp.get("ratings_det", {})
        rs = resp.get("ratings_stoch", {})

        rows.append({
            "participant_id": st.session_state.participant_id,
            "question_id": qid_iter,
            "topic": topic_iter,
            "question": qtext_iter,
            "translation": translation_iter,

            # Demographics
            "age_group": st.session_state.demographics.get("age_group", None),
            "gender": st.session_state.demographics.get("gender", None),
            "korean_familiarity": st.session_state.demographics.get("korean_familiarity", None),
            "nationality_background": st.session_state.demographics.get("nationality_background", None),
            "demographic_comments": st.session_state.demographics.get("demographic_comments", None),
            "demographics_timestamp": st.session_state.demographics.get("demographics_timestamp", None),

            # Human answer
            "answer": resp.get("answer", ""),
            "pna_flag": resp.get("pna_flag", None),
            "answer_timestamp": resp.get("timestamp", None),

            # Deterministic AI
            "ai_det_answer": ai_det.get("answer", None),
            "ai_det_temperature": ai_det.get("temperature", None),
            "ai_det_model": ai_det.get("model", None),
            "ai_det_run_id": ai_det.get("run_id", None),
            "ai_det_generated_at_utc": ai_det.get("generated_at_utc", None),
            "ai_det_error": ai_det.get("error", None),

            # Stochastic AI (chosen)
            "ai_stoch_chosen_index": ai_stoch.get("chosen_index", None),
            "ai_stoch_answer": ai_stoch.get("answer", None),
            "ai_stoch_temperature": ai_stoch.get("temperature", None),
            "ai_stoch_model": ai_stoch.get("model", None),
            "ai_stoch_run_id": ai_stoch.get("run_id", None),
            "ai_stoch_generated_at_utc": ai_stoch.get("generated_at_utc", None),
            "ai_stoch_error": ai_stoch.get("error", None),

            # Deterministic ratings
            "det_rating_correctness": rd.get("correctness", None),
            "det_rating_cultural_sensitivity": rd.get("cultural_sensitivity", None),
            "det_rating_stereotypes": rd.get("stereotypes", None),
            "det_rating_nuance": rd.get("nuance", None),
            "det_rating_overall": rd.get("overall", None),
            "det_rated_timestamp": rd.get("rated_timestamp", None),

            # Stochastic ratings
            "stoch_rating_correctness": rs.get("correctness", None),
            "stoch_rating_cultural_sensitivity": rs.get("cultural_sensitivity", None),
            "stoch_rating_stereotypes": rs.get("stereotypes", None),
            "stoch_rating_nuance": rs.get("nuance", None),
            "stoch_rating_overall": rs.get("overall", None),
            "stoch_rated_timestamp": rs.get("rated_timestamp", None),
        })
    out_df = pd.DataFrame(rows)
    csv_bytes = out_df.to_csv(index=False).encode("utf-8")

    if not st.session_state.gsheet_saved:
        try:
            append_dataframe_to_sheet(out_df, ANALYSIS_TAB)
            st.session_state.gsheet_saved = True
            st.success("Responses saved to Google Sheets.")
        except Exception as e:
            st.error(f"Could not save responses to Google Sheets: {e}")
    if "csv_download_logged" not in st.session_state:
        st.session_state.csv_download_logged = False
    downloaded = st.download_button(
        label="Download Responses CSV",
        data=csv_bytes,
        file_name='participant_responses.csv',
        mime="text/csv",
        use_container_width=True,
    )

    if downloaded and not st.session_state.csv_download_logged:
        log_event(
            "survey_csv_downloaded",
            event_data={
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
        st.session_state.csv_download_logged = True
        
