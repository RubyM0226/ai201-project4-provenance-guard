# ai201-project4-provenance-guard

# Architecture

                         SUBMISSION FLOW
                         ----------------
   client
     |
     |  POST /submit  { text, creator_id }
     v
+-------------+      +------------------+      +------------------------+
|  Flask app  |----->|  signals.py      |      |                        |
|  /submit    |      |  llm_signal()    |----->|  scoring.py            |
|  route      |      |  stylometric_    |----->|  combine_confidence()  |
+-------------+      |  signal()        |      |  -> {confidence,      |
      |               +------------------+      |     attribution}      |
      |                                          +------------------------+
      |                                                     |
      |                                                     v
      |                                          +------------------------+
      |                                          |  labels.py             |
      |                                          |  generate_label()      |
      |                                          +------------------------+
      |                                                     |
      v                                                     v
+---------------------------+                    response: {content_id,
|  audit_log.py              |<-------------------  attribution, confidence,
|  log_submission()          |                       label, signals}
|  (SQLite: audit_log table) |
+---------------------------+


                         APPEAL FLOW
                         -----------
   client
     |
     |  POST /appeal  { content_id, creator_reasoning }
     v
+-------------+      +---------------------------+
|  Flask app  |----->|  audit_log.py              |
|  /appeal    |      |  log_appeal()              |
|  route      |      |  - find row by content_id  |
+-------------+      |  - status -> under_review  |
      |               |  - store reasoning +       |
      |               |    timestamp               |
      v               +---------------------------+

       response: {content_id, status: "under_review", message}

       
# Provenance Guard

Provenance Guard is an AI content attribution service for a writing platform: submits text through two independent detection signals, produces a confidence score, shows a plain-language transparency label, and lets creators appeal a classification.

See `planning.md` for the full spec and architecture diagram.

## Setup

Create Virtual Environemnt: 
python -m venv .venv
source .venv/bin/activate          # Mac/Linux
source .venv/Scripts/activate      # Windows (Git Bash)
or: .venv\Scripts\activate         # Windows (Command Prompt)

Create API Key and .env file in .gitignore:
GROQ_API_KEY=your_key_here

To run:
python app.py        # in gitbash terminal

## Endpoints

First off, an endpoint in this case is just a URL path on a specific address that tells the host what to do when it is hit. You can call endpoints over the internet versus the terminal. 

In this project:
- `POST /submit` -> attribution result, confidence, label, and both signal outputs
- `POST /appeal` -> confirms the appeal and flips status to under_review
- `GET /log` -> returns the structured audit log in a JSON file


## Detection Signals

**Why these two, and why they're genuinely independent:**

- LLM-based (Groq, llama-3.3-70b-versatile) -> judges holistic semantic/stylistic
  coherence. Does the text read as generated when considered as a whole? 
  Output:
  ai_likelihood: (0–1) plus a one-sentence reasoning string.

- Stylometric heuristics (pure Python) -> measure sentence length
  variance, type token ratio, and other structural properties that don't require understanding meaning at all.


## Confidence Scoring — How It Works and How I Tested It

`confidence = 0.65 * llm_score + 0.35 * stylometric_score`

Thresholds are asymmetric on purpose: 
`>= 0.70` -> `likely_ai`
`<= 0.35` -> `likely_human`

Otherwise `uncertain`. A false positive (flagging a real human as AI) is
worse than a false negative on a writing platform, so it takes more combined evidence to land on "likely_ai" than on "likely_human." 

Testing approach: I ran the four calibration inputs from the assignment spec (clearly AI, clearly human, borderline formal-human, borderline lightly-edited-AI) and checked whether the scores matched intuition.

| Input | LLM score | Stylometric score | Confidence | Attribution |

| Clearly AI-generated | 0.78 | 0.182 | **0.571** | uncertain |
| Clearly human  | 0.30 | 0.0 | **0.195** | likely_human |
| Borderline: formal human | 0.30 | 0.098 | **0.229** | likely_human |
| Borderline: lightly-edited AI | 0.30 | 0.324 | **0.308** | likely_human |

Three of the four matched intuition well. The first one didn't — I expected "clearly
AI-generated" to land in `likely_ai`. 


## Transparency Label — All Three Variants (exact text)

| Variant | Exact label text |

| High-confidence AI | "Likely AI-Generated — Our system detected strong signals that this content was generated by an AI model. If you believe this is incorrect, you can appeal this classification." |
| High-confidence human | "Likely Human-Written — Our system found this content consistent with human authorship." |
| Uncertain | "Uncertain — Our system could not confidently determine whether this content is AI-generated or human-written. Treat this result as inconclusive. You can appeal this classification for human review." |


## Appeals Workflow

The Appeals Workflow exists because the whole point of Provenance Guard is that it is making educated guesses about the inputted text itself. This tool is not 100% reliable, so the results need to be taken with a grain of salt. Because of this, the system needs a way out and allows the user to appeal the decision. If chosen, a human will read the text and make th edetermination themselves.

The system looks up the existing audit log row, sets its status to under_review, and stores the reasoning and a timestamp on that same row. 

How I tested it live:

```bash
curl -s -X POST http://localhost:5000/appeal \
  -H "Content-Type: application/json" \
  -d '{"content_id": "561f5490-21b9-4738-b5a0-a214ec123b9d", "creator_reasoning": "I wrote this myself from personal experience. I am a non-native English speaker and my writing style may appear more formal than typical."}'
```

Response:
```json
{
  "content_id": "561f5490-21b9-4738-b5a0-a214ec123b9d",
  "status": "under_review",
  "message": "Your appeal has been received and logged for human review."
}
```

This confirmed via GET/log that the row now shows status: under_review with
appeal_reasoning and appeal_timestamp populated.


## Rate Limiting

Rate limiting is when the LLM stops a user from hitting a certain endpoint after it has already been hit a number of times. It saves money on Grok API key calls and stops the ability for it to spam certain features. 

"10 per minute; 100 per day" on POST/submit, via Flask-Limiter.

Reasoning: a real writer submitting or revising their own work rarely needs more than
a few submissions per minute. 10/minute comfortably covers drafting purposes
without being noticeable to a genuine user. 100/day caps sustained abuse from a single IP
while still leaving room for a creator to submit many pieces across a day.

**Tested live** — 12 rapid requests against the 10/minute limit:

200
200
200
200
200
200
200
200
200
429
429
429

First 9 succeed, remaining 3 are rejected over 12 tests. Limiter function needs more work, but this demonstrates the overall purpose of having one in the first place.


## Audit Log

AUdit Log exists because it is the accountability layer for the entire project. This allows the human checking pieces (any work that is marked as "under-review") to know exactly what the agent said and if the answer AI gave could be wrong. It returns the information in a structure JSON file.

Example of a possible output:
{
  "content_id": "561f5490-21b9-4738-b5a0-a214ec123b9d",
  "creator_id": "user-appeal-test",
  "timestamp": "2026-07-07T18:56:22.001846+00:00",
  "text_preview": "Artificial intelligence represents a transformative paradigm shift in modern society...",
  "llm_score": 0.54,
  "stylometric_score": 0.092,
  "confidence": 0.383,
  "attribution": "uncertain",
  "label": "Uncertain — ... (confidence score: 0.383)",
  "status": "under_review",
  "appeal_reasoning": "I wrote this myself from personal experience. I am a non-native English speaker and my writing style may appear more formal than typical.",
  "appeal_timestamp": "2026-07-07T18:56:22.036553+00:00"
}
{
  "content_id": "4d319841-...",
  "creator_id": "user-edited",
  "attribution": "likely_human",
  "confidence": 0.308,
  "status": "classified",
  "appeal_reasoning": null
}

Full log available via `GET /log`.


## Known Limitations

1. Stylometric variance is unreliable on short text (usually under 5 sentences):
   Sentence length variance is a noisy estimate on small samples. This is what
   caused the "clearly AI-generated" case above to score lower than expected
   on that signal. A longer sample of the same generated text would very likely show the
   uniformity the metric is designed to catch.

2. Formal/technical human writing scores AI-like on stylometrics: The heuristic can't
   distinguish "written in a formal register" from "generated." This only measures
   uniformity and vocabulary repetition, both of which formal human prose also exhibits.


## Spec Reflection

Where the spec helped: The spec helped for writing out the three exact label variants in planning.md before touching any label-generation code.

Where implementation diverged from spec: I diverged from the spec's example audit log entry because it deosn't mention appeal fields at all; I added appeal_reasoning and appeal_timestamp to the same row rather than creating a separate appeals table, since the appeal endpoint needs
to update an existing record's status in place, and keeping one row per content_id made
the "what would a reviewer see" question in the appeals section.

## AI Usage

1. Confidence scoring logic (Milestone 4): I gave an AI tool the Detection Signals and
   Uncertainty Representation sections of planning.md plus the architecture diagram and
   asked it to generate combine_confidence(). It initially proposed symmetric thresholds
   (`0.6`/`0.4` split evenly). I overrode this to the asymmetric `0.70`/`0.35` thresholds
   described above, since the spec's hint about false-positive asymmetry wasn't reflected
   in the generated version.

2. Stylometric signal (Milestone 4): Asked for stylometric_signal() from the same
   spec section. The generated version used type-token ratio and sentence variance
   independently and returned two separate numbers rather than one score. I
   revised it to combine the three sub-metrics into one weighted 0–1 score with the raw
   metrics still exposed for transparency.

