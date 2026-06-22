from flask import Flask, request, jsonify
from ai_grader import run_grading

app = Flask(__name__)


# =======================================================
# HEALTH CHECK (optional tapi penting)
# =======================================================
@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "running",
        "service": "AI Grader API"
    })


# =======================================================
# MAIN GRADING ENDPOINT
# =======================================================
@app.route("/grade", methods=["POST"])
def grade():
    data = request.get_json()

    # ambil data dari request
    student_id = data.get("student_id")
    quiz_id = data.get("quiz_id")

    # validasi input
    if not student_id or not quiz_id:
        return jsonify({
            "status": "error",
            "message": "student_id dan quiz_id wajib diisi"
        }), 400

    try:
        # panggil logic utama kamu
        result = run_grading(student_id, quiz_id)

        return jsonify(result)

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# =======================================================
# RUN LOCAL (untuk test sebelum deploy)
# =======================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)