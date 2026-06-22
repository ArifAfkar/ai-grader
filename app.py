import os
from flask import Flask, request, jsonify
from ai_grader import run_grading

app = Flask(__name__)

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "running",
        "service": "AI Grader API"
    })

@app.route("/grade", methods=["POST"])
def grade():
    data = request.get_json()

    student_id = data.get("student_id")
    quiz_id = data.get("quiz_id")

    if not student_id or not quiz_id:
        return jsonify({
            "status": "error",
            "message": "student_id dan quiz_id wajib diisi"
        }), 400

    try:
        result = run_grading(student_id, quiz_id)
        return jsonify(result)

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)