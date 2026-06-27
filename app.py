"""Provenance Guard — Flask API.

Endpoints:
  - POST /submit : accepts {text, creator_id}, runs both detection signals
    (LLM + stylometric), combines them into a calibrated confidence score,
    writes a structured audit entry, and returns {content_id, attribution,
    confidence, label, signals}. Rate-limited at 5/min + 50/day per IP.
  - POST /appeal : accepts {content_id, creator_reasoning}, flips the content's
    status to under_review, and logs the appeal beside the original decision.
  - GET  /log    : returns recent audit-log entries as JSON.
"""

import uuid
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import db
from scoring import classify, generate_label
from signals import llm_signal, stylometric_signal

app = Flask(__name__)
db.init_db()

# Rate limiting (planning.md / README): 5/min + 50/day per IP on /submit.
# A human revising their own work won't exceed 5/min; 50/day is far above any
# honest creator's volume but caps a flood script and shields the Groq quota.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


@app.errorhandler(429)
def ratelimit_handler(e):
    return (
        jsonify(
            {
                "error": "rate_limit_exceeded",
                "message": "Too many submissions. Please slow down and try again later.",
                "limit": str(e.description),
            }
        ),
        429,
    )


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


@app.route("/submit", methods=["POST"])
@limiter.limit("5 per minute;50 per day")
def submit():
    body = request.get_json(silent=True) or {}
    text = body.get("text")
    creator_id = body.get("creator_id")

    if not text or not creator_id:
        return jsonify({"error": "Both 'text' and 'creator_id' are required."}), 400

    # Signal 1 — LLM (semantic)
    signal1 = llm_signal(text)
    llm_score = signal1["llm_score"]

    # Signal 2 — stylometric (structural)
    signal2 = stylometric_signal(text)
    stylometric_score = signal2["stylometric_score"]

    # Combine into a single calibrated confidence score (planning.md §2)
    result = classify(llm_score, stylometric_score, signal2["word_count"])

    record = {
        "content_id": str(uuid.uuid4()),
        "creator_id": creator_id,
        "text": text,
        "timestamp": _now_iso(),
        "attribution": result["attribution"],
        "confidence": result["confidence"],       # user-facing (None when uncertain)
        "combined_score": result["score"],         # raw AI-likeness S
        "llm_score": llm_score,
        "stylometric_score": stylometric_score,
        "status": "classified",
    }
    db.record_submission(record)

    label = generate_label(result["attribution"], result["confidence"])

    return jsonify(
        {
            "content_id": record["content_id"],
            "attribution": result["attribution"],
            "confidence": result["confidence"],
            "label": label,
            "signals": {
                "llm_score": llm_score,
                "llm_rationale": signal1["rationale"],
                "stylometric_score": stylometric_score,
                "stylometric_metrics": signal2["metrics"],
                "combined_score": result["score"],
                "weights": result["weights"],
            },
        }
    )


@app.route("/appeal", methods=["POST"])
def appeal():
    body = request.get_json(silent=True) or {}
    content_id = body.get("content_id")
    creator_reasoning = body.get("creator_reasoning")

    if not content_id or not creator_reasoning:
        return (
            jsonify(
                {"error": "Both 'content_id' and 'creator_reasoning' are required."}
            ),
            400,
        )

    updated = db.record_appeal(content_id, creator_reasoning, _now_iso())
    if updated is None:
        return jsonify({"error": f"No content found for content_id {content_id}."}), 404

    return jsonify(
        {
            "content_id": content_id,
            "status": "under_review",
            "message": "Your appeal has been received. This content is now under review "
            "by a human moderator.",
        }
    )


@app.route("/log", methods=["GET"])
def log():
    return jsonify({"entries": db.get_log()})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
