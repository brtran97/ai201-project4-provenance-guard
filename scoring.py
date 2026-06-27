"""Confidence scoring for Provenance Guard (planning.md §2).

Combines the two signal scores into a single AI-likeness score S in [0,1],
maps it to one of three verdicts via asymmetric thresholds, and derives the
user-facing confidence (how sure we are of the verdict we landed on).

    S = 0.7 * llm_score + 0.3 * stylometric_score      (normal)
    S = 0.9 * llm_score + 0.1 * stylometric_score      (short text < SHORT_TEXT_WORDS)

Thresholds (asymmetric to protect against false positives):
    S >= 0.70           -> likely_ai
    0.40 <= S < 0.70    -> uncertain
    S <  0.40           -> likely_human
"""

AI_THRESHOLD = 0.70
HUMAN_THRESHOLD = 0.40
SHORT_TEXT_WORDS = 40


def classify(llm_score, stylometric_score, word_count):
    """Return a dict: combined score S, attribution, user-facing confidence,
    and the blend weights used (recorded for transparency).

    `word_count` drives the short-text exception; pass the count the stylometric
    signal already computed.
    """
    short = word_count < SHORT_TEXT_WORDS
    llm_weight, stylo_weight = (0.9, 0.1) if short else (0.7, 0.3)

    s = llm_weight * llm_score + stylo_weight * stylometric_score
    s = max(0.0, min(1.0, s))

    if s >= AI_THRESHOLD:
        attribution = "likely_ai"
        confidence = s
    elif s >= HUMAN_THRESHOLD:
        attribution = "uncertain"
        confidence = None  # uncertain deliberately carries no headline percentage
    else:
        attribution = "likely_human"
        confidence = 1.0 - s

    return {
        "score": round(s, 4),
        "attribution": attribution,
        "confidence": round(confidence, 4) if confidence is not None else None,
        "weights": {"llm": llm_weight, "stylometric": stylo_weight},
        "short_text": short,
    }


def generate_label(attribution, confidence):
    """Map a verdict + confidence to the user-facing transparency label text
    (planning.md §3). Plain language, no jargon. The text differs by verdict,
    and the AI/human variants embed the confidence as a percentage; the
    uncertain variant deliberately carries no number.
    """
    pct = f"{round(confidence * 100)}" if confidence is not None else None

    if attribution == "likely_ai":
        return (
            f"⚠️ Likely AI-generated. Our analysis found strong signs this text was "
            f"produced by an AI tool (about {pct}% confidence). Automated detection "
            f"isn't perfect — if you wrote this yourself, you can appeal this result."
        )
    if attribution == "likely_human":
        return (
            f"✓ Likely human-written. This text reads as human-authored (about {pct}% "
            f"confidence). We found no strong signs of AI generation."
        )
    # uncertain
    return (
        "❓ Inconclusive. We couldn't determine with confidence whether this text was "
        "written by a person or an AI tool. Please treat this result as uncertain — it "
        "should not be taken as a judgment either way."
    )
