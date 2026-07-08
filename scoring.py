"""
Confidence scoring: combines the two signal scores into one calibrated
confidence value and maps it to an attribution bucket.

Design decision (see planning.md): a false positive -- telling a human
creator their work was flagged as AI -- is worse than a false negative on
a writing platform. So the thresholds are asymmetric: it takes a HIGHER
combined score to commit to "likely_ai" than it takes a LOW score to commit
to "likely_human". The middle band is wider on the AI side on purpose.
"""

LLM_WEIGHT = 0.65
STYLOMETRIC_WEIGHT = 0.35

AI_THRESHOLD = 0.70     # confidence >= this -> likely_ai
HUMAN_THRESHOLD = 0.35  # confidence <= this -> likely_human
                        # anything in between -> uncertain


def combine_confidence(llm_result, stylo_result):
    llm_score = llm_result["score"]
    stylo_score = stylo_result["score"]

    confidence = round((llm_score * LLM_WEIGHT) + (stylo_score * STYLOMETRIC_WEIGHT), 3)

    if confidence >= AI_THRESHOLD:
        attribution = "likely_ai"
    elif confidence <= HUMAN_THRESHOLD:
        attribution = "likely_human"
    else:
        attribution = "uncertain"

    return {
        "confidence": confidence,
        "attribution": attribution,
        "llm_score": llm_score,
        "stylometric_score": stylo_score,
    }
