import os
import time
import uuid
import pandas as pd
from datetime import datetime
from openai import OpenAI

# ---------- CONFIG ----------
QUESTIONS_FILE = "questions.csv"
COMBINED_OUTPUT_FILE = "ai_bank.csv"

MODELS = [
    "gpt-4.1-mini",
    "gpt-5-mini",
    "gpt-5.4-mini"
]

DET_TEMP = 0.0
STOCH_TEMP = 1.0
NUM_STOCH = 5

MAX_OUTPUT_TOKENS = 220

# basic retry/backoff for transient rate limiting
MAX_RETRIES = 5
BACKOFF_SECONDS = 3
# ---------------------------

client = OpenAI()

SYSTEM_PROMPT = """
You are answering questions about Korean culture.

Rules:
- Answer based on Korean cultural norms and context.
- Use the topic as additional context.
- Be accurate to the best of your knowledge.
- Give the answer first in English, then in Korean.
- In the English answer, do NOT use Hangul/Korean script.
- If Korean words or phrases are needed in the English answer, use romanized transliteration only.
- In the Korean answer, use natural Korean/Hangul.
- Keep each language response short: one paragraph, under 3 lines.
- Do not include explanations, disclaimers, bullet points, markdown, or extra text.
- Output only in this format:

English:
<answer using English and romanized Korean only>

Korean:
<answer in Korean>
""".strip()


def call_openai(topic: str, question_text: str, translation: str, temperature: float, model_name: str) -> str:
    last_err = None

    user_prompt = f"""
Topic: {topic}

Question in English:
{question_text}

Question in Korean:
{translation}

Answer the question in relation to Korean culture. In the English answer, use romanized Korean only for Korean phrases. Do not include Hangul in the English answer.
""".strip()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.responses.create(
                model=model_name,
                temperature=temperature,
                max_output_tokens=220,
                input=[
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT
                    },
                    {
                        "role": "user",
                        "content": user_prompt
                    }
                ]
            )

            return resp.output_text.strip()

        except Exception as e:
            last_err = e
            time.sleep(BACKOFF_SECONDS * attempt)

    raise last_err


def generate_for_model(model_name: str, dfq: pd.DataFrame):

    rows = []

    run_id = str(uuid.uuid4())
    generated_at_utc = datetime.utcnow().isoformat()

    safe_model_name = model_name.replace(".", "_")
    output_file = f"ai_bank_{safe_model_name}.csv"

    print(f"\n========== GENERATING FOR {model_name} ==========\n")

    for _, r in dfq.iterrows():

        qid = str(r["question_id"])
        topic = str(r["topic"])
        qtext = str(r["question"])
        translation = str(r["translation"])

        # ---------------- DETERMINISTIC ----------------

        try:
            det_answer = call_openai(
                topic=topic,
                question_text=qtext,
                translation=translation,
                temperature=DET_TEMP,
                model_name=model_name
            )
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
            "model": model_name,
            "answer": det_answer,
            "error": det_err,
        })

        # ---------------- STOCHASTIC ----------------

        for j in range(1, NUM_STOCH + 1):

            try:
                st_answer = call_openai(
                    topic=topic,
                    question_text=qtext,
                    translation=translation,
                    temperature=STOCH_TEMP,
                    model_name=model_name
                )
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
                "variant_index": j,
                "temperature": STOCH_TEMP,
                "model": model_name,
                "answer": st_answer,
                "error": st_err,
            })

        print(f"Generated answers for question_id={qid}")

    # save model-specific CSV
    df_model = pd.DataFrame(rows)

    df_model.to_csv(
        output_file,
        index=False,
        encoding="utf-8-sig"
    )

    print(f"\nSaved model file -> {output_file}")

    return df_model


def main():

    if not os.path.exists(QUESTIONS_FILE):
        raise FileNotFoundError(f"Missing {QUESTIONS_FILE}")

    dfq = pd.read_csv(QUESTIONS_FILE, encoding="utf-8-sig")

    required_cols = [
        "question_id",
        "topic",
        "question",
        "translation"
    ]

    missing = [c for c in required_cols if c not in dfq.columns]

    if missing:
        raise ValueError(
            f"questions.csv is missing required columns: {missing}"
        )

    dfq["question_id"] = dfq["question_id"].astype(str)

    all_dfs = []

    # generate for each model
    for model_name in MODELS:

        df_model = generate_for_model(
            model_name=model_name,
            dfq=dfq
        )

        all_dfs.append(df_model)

    # combine everything
    combined_df = pd.concat(
        all_dfs,
        ignore_index=True
    )

    combined_df.to_csv(
        COMBINED_OUTPUT_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    print(f"\n========== COMPLETE ==========")
    print(f"Combined CSV saved -> {COMBINED_OUTPUT_FILE}")
    print(f"Total rows: {len(combined_df)}")

    print("\nTip:")
    print("Filter rows where 'error' is not null to inspect failures.")


if __name__ == "__main__":
    main()