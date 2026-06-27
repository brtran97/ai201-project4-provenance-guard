"""Provenance Guard — Flask API.

Milestone 3 scope:
  - POST /submit : accepts {text, creator_id}, runs Signal 1 (LLM), writes a
    structured audit entry, returns {content_id, attribution, confidence, label}.
  - GET  /log    : returns recent audit-log entries as JSON.

Confidence scoring (Signal 2 + combined score) and the real transparency labels
arrive in Milestones 4–5. For now confidence and label are placeholders, and
attribution is derived from the single LLM signal.
"""

import uuid
from datetime import datetime, timezone

from flask import Flask, jsonify, request

import db
from signals import llm_signal

app = Flask(__name__)
db.init_db()


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _placeholder_attribution(score):
    """Milestone 3 placeholder: map the single LLM score to a verdict using the
    thresholds from planning.md §2. Replaced by combined scoring in M4."""
    if score >= 0.70:
        return "likely_ai"
    if score >= 0.40:
        return "uncertain"
    return "likely_human"


@app.route("/submit", methods=["POST"])
def submit():
    body = request.get_json(silent=True) or {}
    text = body.get("text")
    creator_id = body.get("creator_id")

    if not text or not creator_id:
        return jsonify({"error": "Both 'text' and 'creator_id' are required."}), 400

    # Signal 1
    signal1 = llm_signal(text)
    llm_score = signal1["llm_score"]

    attribution = _placeholder_attribution(llm_score)

    record = {
        "content_id": str(uuid.uuid4()),
        "creator_id": creator_id,
        "text": text,
        "timestamp": _now_iso(),
        "attribution": attribution,
        "confidence": llm_score,        # PLACEHOLDER until M4 combined scoring
        "llm_score": llm_score,
        "stylometric_score": None,      # added in M4
        "status": "classified",
    }
    db.record_submission(record)

    return jsonify(
        {
            "content_id": record["content_id"],
            "attribution": attribution,
            "confidence": record["confidence"],     # placeholder
            "label": "[placeholder label — implemented in Milestone 5]",
            "signals": {
                "llm_score": llm_score,
                "llm_rationale": signal1["rationale"],
                "stylometric_score": None,
            },
        }
    )


@app.route("/log", methods=["GET"])
def log():
    return jsonify({"entries": db.get_log()})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
