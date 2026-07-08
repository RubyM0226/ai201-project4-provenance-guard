"""
Detection signals for Provenance Guard.

Signal 1 (llm_signal):    semantic/holistic — asks an LLM (Groq llama-3.3-70b-versatile)
                           to judge whether text reads as human or AI-generated.
Signal 2 (stylometric_signal): structural — measurable statistical properties
                           (sentence length variance, type-token ratio, punctuation
                           density) computed in pure Python.

These are intentionally independent: one reasons about meaning and coherence,
the other counts things. Blind spots are documented inline for each.
"""

import os
import re
import json
import statistics


# ---------------------------------------------------------------------------
# Signal 2: Stylometric heuristics
# ---------------------------------------------------------------------------
# What it captures: AI-generated text tends toward uniform sentence lengths,
# a narrower vocabulary relative to length (lower type-token ratio), and a
# habit of leaning on certain transitional punctuation patterns. Human writing
# tends to be "noisier" -- mixing short fragments with long sentences, more
# varied word choice, more irregular punctuation.
#
# Blind spot: a skilled human writer imitating a formal register (e.g. an
# academic writing about economics) can score AI-like on these metrics even
# though they wrote every word themselves. This signal cannot tell "polished"
# from "generated" -- it only measures uniformity, not authorship.

def _split_sentences(text):
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s for s in sentences if s.strip()]


def _split_words(text):
    return re.findall(r"[A-Za-z']+", text.lower())


def stylometric_signal(text):
    sentences = _split_sentences(text)
    words = _split_words(text)

    if len(sentences) < 2 or len(words) < 10:
        return {
            "score": 0.5,
            "metrics": {"note": "text too short for reliable stylometric analysis"},
            "confidence_in_signal": "low",
        }

    sentence_lengths = [len(_split_words(s)) for s in sentences]
    mean_len = statistics.mean(sentence_lengths)
    len_variance = statistics.pvariance(sentence_lengths) if len(sentence_lengths) > 1 else 0

    # Low variance in sentence length -> more AI-like (uniform). Variance of
    # ~40+ (a good mix of short and long sentences) is treated as strongly
    # human-like; variance near 0 (every sentence about the same length) is
    # treated as strongly AI-like. These cutoffs were chosen by eyeballing
    # the sample inputs in the assignment spec, not derived statistically.
    variance_score = max(0.0, min(1.0, 1 - (len_variance / 40)))

    ttr = len(set(words)) / len(words)
    # Lower type-token ratio (more repeated words relative to length) ->
    # more AI-like in this heuristic. ttr ~0.8 (varied vocabulary) scores
    # near 0 (human-like); ttr ~0.4 (repetitive) scores near 1 (AI-like).
    ttr_score = max(0.0, min(1.0, 1 - ((ttr - 0.4) / 0.4)))

    punctuation_count = len(re.findall(r"[,;:\u2014-]", text))
    punctuation_density = punctuation_count / max(len(words), 1)
    # Moderate-to-high density of commas/semicolons/dashes (hedging,
    # transitional phrasing) nudges the score toward AI-like.
    punct_score = max(0.0, min(1.0, punctuation_density / 0.15))

    combined = (variance_score * 0.4) + (ttr_score * 0.35) + (punct_score * 0.25)

    return {
        "score": round(combined, 3),
        "metrics": {
            "avg_sentence_length": round(mean_len, 2),
            "sentence_length_variance": round(len_variance, 2),
            "type_token_ratio": round(ttr, 3),
            "punctuation_density": round(punctuation_density, 3),
        },
        "confidence_in_signal": "normal",
    }


# ---------------------------------------------------------------------------
# Signal 1: LLM-based classification (Groq)
# ---------------------------------------------------------------------------
# What it captures: holistic semantic and stylistic coherence -- does the
# text "feel" generated when read as a whole, including things stylometrics
# can't see (generic reasoning patterns, hedge-everything argument structure,
# implausible/overly-tidy narrative arcs).
#
# Blind spot: LLM judges are themselves miscalibrated and can be fooled by
# short text, can carry bias against non-native-English phrasing (flagging
# it as "AI-like" when it's just a different fluency register), and give
# no guarantees of consistency between calls.
#
# NOTE: If GROQ_API_KEY is not set (e.g. running in an offline sandbox),
# this falls back to a deterministic keyword heuristic so the rest of the
# pipeline can still be developed and tested. Swap in your real key to use
# the actual model -- the fallback is NOT a substitute for the real signal.

def llm_signal(text):
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return _fallback_llm_signal(text, error="GROQ_API_KEY not set")

    try:
        from groq import Groq

        client = Groq(api_key=api_key)
        prompt = (
            "You are an AI content attribution assistant. Assess whether the "
            "following text was likely written by a human or generated by an AI "
            "language model. Consider semantic coherence, natural imperfection, "
            "idiosyncratic phrasing, and holistic style.\n\n"
            f"TEXT:\n{text}\n\n"
            "Respond ONLY with a JSON object with two fields: "
            '"ai_likelihood" (a float between 0 and 1, where 1 means certainly '
            'AI-generated and 0 means certainly human-written) and "reasoning" '
            "(a one-sentence explanation). Do not include any other text, "
            "markdown, or code fences."
        )
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        content = response.choices[0].message.content.strip()
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:].strip()
        parsed = json.loads(content)
        return {
            "score": round(float(parsed["ai_likelihood"]), 3),
            "reasoning": parsed.get("reasoning", ""),
            "source": "groq-llama-3.3-70b-versatile",
        }
    except Exception as e:
        return _fallback_llm_signal(text, error=str(e))


def _fallback_llm_signal(text, error=None):
    lowered = text.lower()
    ai_markers = [
        "furthermore", "it is important to note", "in conclusion", "moreover",
        "additionally", "it is essential", "paradigm", "stakeholders",
        "holistic", "leverage", "delve", "underscore", "robust",
    ]
    marker_hits = sum(1 for m in ai_markers if m in lowered)
    score = min(1.0, 0.3 + marker_hits * 0.12)
    return {
        "score": round(score, 3),
        "reasoning": f"fallback heuristic in use (Groq unavailable: {error})",
        "source": "fallback-heuristic",
    }
