import os
import re
import json
import datetime

from openai import OpenAI
import psycopg2
from psycopg2.extras import RealDictCursor


# =======================================================
# OPENAI CLIENT
# =======================================================
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)


# =======================================================
# CONSTANT
# =======================================================
ESSAY_SCORE_MAP = {
    "benar": 3,
    "cukup": 2,
    "kurang": 1,
    "salah": 0
}


# =======================================================
# DATABASE CONNECTION
# =======================================================
def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        dbname=os.getenv("DB_NAME"),
        port=os.getenv("DB_PORT")
    )


# =======================================================
# UTILITY FUNCTIONS
# =======================================================

def normalize_category(text):
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-zA-Z]", "", text)

    if text in (
        "benar",
        "cukup",
        "kurang",
        "salah"
    ):
        return text

    return "salah"

def format_rubric_text(rubric_text):
    rubric_text = (rubric_text or "").strip()

    if not rubric_text:
        return "Tidak ada rubrik khusus. Gunakan kunci jawaban sebagai acuan utama."

    try:
        data = json.loads(rubric_text)

        if isinstance(data, dict):
            return f"""
Rubrik terstruktur:
- Benar (3): {data.get("score_3", "").strip() or "-"}
- Cukup (2): {data.get("score_2", "").strip() or "-"}
- Kurang (1): {data.get("score_1", "").strip() or "-"}
- Salah (0): {data.get("score_0", "").strip() or "-"}
- Catatan: {data.get("notes", "").strip() or "-"}
"""
    except Exception:
        pass

    return rubric_text


def parse_student_answer(user_answer):
    text_answer = (user_answer or "").strip()
    table_answer = {}

    try:
        parsed = json.loads(text_answer)

        if isinstance(parsed, dict):
            text_answer = str(parsed.get("text_answer", "")).strip()
            table_answer = parsed.get("table_answer", {}) if isinstance(parsed.get("table_answer"), dict) else {}

    except Exception:
        pass

    return text_answer, table_answer


def parse_table_config(raw_config):
    if not raw_config:
        return {}

    try:
        parsed = json.loads(raw_config)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    return {}


def build_rubric_based_table_report(table_config, table_answer):
    if not isinstance(table_config, dict):
        return "Tidak ada tabel jawaban siswa."

    if table_config.get("mode") != "rubric_based":
        return "Tidak ada tabel jawaban siswa."

    input_cells = table_config.get("input_cells", [])

    if not isinstance(input_cells, list) or len(input_cells) == 0:
        return "Tidak ada tabel jawaban siswa."

    lines = []

    for cell in input_cells:
        row = cell.get("row")
        col = cell.get("col")

        key = f"r{row}_c{col}"
        value = str(table_answer.get(key, "")).strip()

        lines.append(f"- Sel {key}: {value if value else '(kosong)'}")

    return f"Tabel jawaban siswa:\n" + "\n".join(lines)


def ask_ai(prompt, system_message):
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt}
        ],
    )

    return response.choices[0].message.content


# =======================================================
# GRADING LOGIC
# =======================================================

def grade_reasoned_multiple_choice(row):

    user_answer = (row["answer_text"] or "").strip()
    question_text = row["question"] or ""
    answer_key = row["answer_key_text"] or ""

    rubric_reference = answer_key if answer_key else None

    # ---------------------------------------------------
    # Pilihan ganda salah
    # Skor langsung 0
    # ---------------------------------------------------

    if int(row.get("is_right") or 0) != 1:
        return "salah", 0, rubric_reference

    # ---------------------------------------------------
    # Pilihan benar tetapi alasan kosong
    # ---------------------------------------------------

    if user_answer == "":
        return "salah", 1, rubric_reference

    prompt = f"""
Soal:
{question_text}

Kunci alasan:
{answer_key}

Alasan siswa:
{user_answer}

Nilailah kualitas alasan siswa berdasarkan kunci.

Kategori:

- Benar
  Alasan sesuai konsep dan lengkap.

- Kurang
  Konsep utama sudah benar tetapi kurang lengkap atau kurang tepat.

- Salah
  Konsep keliru atau tidak sesuai.

Jawab HANYA SATU KATA:

Benar
Kurang
Salah
"""

    try:

        raw = ask_ai(
            prompt,
            "Evaluator jawaban pilihan ganda beralasan."
        )

        category = normalize_category(raw)

        if category == "benar":
            score = 3

        elif category == "kurang":
            score = 2

        else:
            score = 1

        return category, score, rubric_reference

    except Exception:

        return "salah", 1, rubric_reference


def grade_essay(row):
    user_answer = (row["answer_text"] or "").strip()
    question_text = row["question"] or ""
    answer_key = row["answer_key_text"] or ""
    rubric_text = row["rubric_text"] or ""
    table_config = parse_table_config(row.get("answer_table_config"))
    text_answer, table_answer = parse_student_answer(user_answer)

    if not text_answer and not table_answer:
        return "salah", 0, None

    prompt = f"""
Soal:
{question_text}

Kunci:
{answer_key}

Rubrik:
{format_rubric_text(rubric_text)}

Jawaban teks:
{text_answer or "(kosong)"}

Jawaban tabel:
{build_rubric_based_table_report(table_config, table_answer)}

Kategori:
- Benar
- Cukup
- Kurang
- Salah

Jawab hanya satu kata.
"""

    try:
        raw = ask_ai(prompt, "Evaluator jawaban esai.")
        category = normalize_category(raw)

        return category, ESSAY_SCORE_MAP[category], rubric_text

    except Exception:
        return "salah", 0, rubric_text


# =======================================================
# MAIN FUNCTION
# =======================================================

def run_grading(student_id, quiz_id):

    db = get_db()
    cursor = None

    try:

        cursor = db.cursor(
            cursor_factory=RealDictCursor
        )

        cursor.execute("""
            SELECT
                a.id AS answer_id,
                a.answer_text,
                a.is_right,
                q.question_type,
                q.question,
                q.answer_key_text,
                q.rubric_text,
                q.answer_table_config
            FROM answers a
            INNER JOIN questions q
                ON a.question_id = q.id
            LEFT JOIN answer_evaluations ae
                ON ae.answer_id = a.id
            WHERE a.student_id = %s
            AND a.quiz_id = %s
            AND q.question_type IN (
                'essay',
                'reasoned_multiple_choice'
            )
            AND ae.id IS NULL
        """, (student_id, quiz_id))

        answers = cursor.fetchall()

        for row in answers:

            if row["question_type"] == "reasoned_multiple_choice":
                category, score, ref = grade_reasoned_multiple_choice(row)
            else:
                category, score, ref = grade_essay(row)

            cursor.execute("""
                INSERT INTO answer_evaluations
                (
                    answer_id,
                    category,
                    score,
                    rubric_reference,
                    created_at
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    NOW()
                )
            """, (
                row["answer_id"],
                category.capitalize(),
                score,
                ref
            ))

        # =======================================================
        # RECALCULATE FINAL SCORE
        # =======================================================

        cursor.execute("""
            SELECT
                a.id,
                a.is_right,
                q.question_type,
                q.points,
                ae.score AS ai_score
            FROM answers a
            INNER JOIN questions q
                ON q.id = a.question_id
            LEFT JOIN answer_evaluations ae
                ON ae.answer_id = a.id
            WHERE
                a.student_id = %s
                AND a.quiz_id = %s
        """, (student_id, quiz_id))

        rows = cursor.fetchall()

        total_score = 0.0
        max_score = 0.0

        for row in rows:

            question_type = (
                row["question_type"] or ""
            ).lower()

            points = float(
                row["points"] or 0
            )

            if question_type == "likert":
                continue

            max_score += points

            if question_type in (
                "essay",
                "reasoned_multiple_choice"
            ):

                ai_score = float(
                    row["ai_score"] or 0
                )

                # Konversi skor AI (0-3) menjadi poin soal
                total_score += (
                    ai_score / 3.0
                ) * points

            else:

                if int(row["is_right"] or 0) == 1:
                    total_score += points

        # =======================================================
        # UPDATE HISTORY
        # =======================================================

        cursor.execute("""
            SELECT id
            FROM quiz_student_list
            WHERE
                student_id = %s
                AND quiz_id = %s
            LIMIT 1
        """, (student_id, quiz_id))

        quiz_student = cursor.fetchone()

        if quiz_student:

            cursor.execute("""
                UPDATE history
                SET
                    final_score = %s,
                    max_score = %s
                WHERE quiz_student_id = %s
            """, (
                total_score,
                max_score,
                quiz_student["id"]
            ))

        db.commit()

        return {
            "status": "success",
            "graded": len(answers),
            "final_score": total_score,
            "max_score": max_score
        }

    except Exception as e:

        db.rollback()

        return {
            "status": "error",
            "message": str(e)
        }

    finally:

        if cursor:
            cursor.close()

        db.close()