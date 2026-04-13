import os
import time
import uuid
import pandas as pd
from datetime import datetime
from openai import OpenAI

# ---------- CONFIG ----------
QUESTIONS_FILE = "questions.csv"
OUTPUT_FILE = "ai_bank.csv"

MODEL = "gpt-4.1-mini"

DET_TEMP = 0.2
STOCH_TEMP = 1.0
NUM_STOCH = 5

# basic retry/backoff for transient rate limiting
MAX_RETRIES = 5
BACKOFF_SECONDS = 3
# ---------------------------

client = OpenAI()


def call_openai(question_text: str, temperature: float) -> str:
    """One OpenAI call. Raises if persistent failures."""
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.responses.create(
                model=MODEL,
                input=question_text,
                temperature=temperature,
            )
            return resp.output_text
        except Exception as e:
            last_err = e
            # backoff and retry
            time.sleep(BACKOFF_SECONDS * attempt)
    raise last_err


def main():
    if not os.path.exists(QUESTIONS_FILE):
        raise FileNotFoundError(f"Missing {QUESTIONS_FILE}")

    dfq = pd.read_csv(QUESTIONS_FILE)
    required_cols = ["question_id", "topic", "question", "translation"]
    missing = [c for c in required_cols if c not in dfq.columns]
    if missing:
        raise ValueError(f"questions.csv is missing required columns: {missing}")

    dfq["question_id"] = dfq["question_id"].astype(str)

    rows = []
    run_id = str(uuid.uuid4())
    generated_at_utc = datetime.utcnow().isoformat()

    for _, r in dfq.iterrows():
        qid = str(r["question_id"])
        topic = str(r["topic"])
        qtext = str(r["question"])
        translation = str(r["translation"])

        # deterministic
        try:
            det_answer = call_openai(qtext, DET_TEMP)
            det_err = None
        except Exception as e:
            det_answer = ""
            det_err = str(e)

        rows.append({
            "run_id": run_id,
            "generated_at_utc": generated_at_utc,
            "question_id": qid,
            "topic": topic,
            "question": qtext,
            "translation": translation,
            "variant_type": "det",
            "variant_index": 0,
            "temperature": DET_TEMP,
            "model": MODEL,
            "answer": det_answer,
            "error": det_err,
        })

        # stochastic variants
        for j in range(1, NUM_STOCH + 1):
            try:
                st_answer = call_openai(qtext, STOCH_TEMP)
                st_err = None
            except Exception as e:
                st_answer = ""
                st_err = str(e)

            rows.append({
                "run_id": run_id,
                "generated_at_utc": generated_at_utc,
                "question_id": qid,
                "topic": topic,
                "question": qtext,
                "translation": translation,
                "variant_type": "stoch",
                "variant_index": j,  # 1..NUM_STOCH
                "temperature": STOCH_TEMP,
                "model": MODEL,
                "answer": st_answer,
                "error": st_err,
            })

        print(f"Generated AI answers for question_id={qid}")

    out = pd.DataFrame(rows)
    out.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")
    print(f"\nSaved AI bank to: {OUTPUT_FILE}")
    print("Tip: filter rows where error is not null to see failures.")


if __name__ == "__main__":
    main()