import os
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

from signals import stylometric_signal, llm_signal
from scoring import combine_confidence
from labels import generate_label
import audit_log as log_store

load_dotenv()
log_store.init_db()

app = Flask(__name__)

# Rate limiting rationale (see README): a real writer submitting their own
# work rarely needs more than a handful of submissions per minute (drafts,
# revisions). 10/minute comfortably covers that while making a flooding
# script hit 429s almost immediately. 100/day caps sustained abuse from a
# single IP without blocking a genuinely prolific creator.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    creator_id = data.get("creator_id", "anonymous")

    if not text:
        return jsonify({"error": "text field is required"}), 400

    content_id = log_store.new_content_id()

    llm_result = llm_signal(text)
    stylo_result = stylometric_signal(text)
    combined = combine_confidence(llm_result, stylo_result)
    label = generate_label(combined["attribution"], combined["confidence"])

    log_store.log_submission(
        content_id, creator_id, text,
        llm_result["score"], stylo_result["score"],
        combined["confidence"], combined["attribution"], label,
    )

    return jsonify({
        "content_id": content_id,
        "attribution": combined["attribution"],
        "confidence": combined["confidence"],
        "label": label,
        "signals": {
            "llm": llm_result,
            "stylometric": stylo_result,
        },
    })


@app.route("/appeal", methods=["POST"])
def appeal():
    data = request.get_json(silent=True) or {}
    content_id = data.get("content_id")
    creator_reasoning = (data.get("creator_reasoning") or "").strip()

    if not content_id or not creator_reasoning:
        return jsonify({"error": "content_id and creator_reasoning are required"}), 400

    success = log_store.log_appeal(content_id, creator_reasoning)
    if not success:
        return jsonify({"error": "content_id not found"}), 404

    return jsonify({
        "content_id": content_id,
        "status": "under_review",
        "message": "Your appeal has been received and logged for human review.",
    })


@app.route("/log", methods=["GET"])
def get_log():
    limit = int(request.args.get("limit", 20))
    entries = log_store.get_log(limit=limit)
    return jsonify({"entries": entries})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
