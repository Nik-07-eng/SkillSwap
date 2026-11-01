# Feedback Analyzer

The Feedback Analyzer is integrated into the SkillSwap Flask app.

## User-facing features
- Private dashboard of feedback received by the signed-in user.
- Average rating and positive/neutral/negative distribution.
- Review-by-review sentiment labels, sentiment score, confidence estimate and detected aspects.
- Recurring themes: teaching clarity, communication, preparation/punctuality, practical learning, and engagement/support.
- Text-analysis playground for demonstration; pasted text is analysed in memory and is not persisted.

## API
- `GET /api/feedback/analyzer` — requires login; analyses up to the latest 100 reviews received by the current user.
- `POST /api/feedback/analyze-text` — requires login; JSON body `{ "comment": "...", "rating": 1 }`; analyses text without saving it.

## Method and limitations
A built-in sentiment lexicon handles negation (for example, "not helpful") and intensity (for example, "very helpful"). Its text score is blended with the star rating. Aspect labels are based on keyword groups. This is an explainable NLP heuristic, not a trained neural model. It may misread sarcasm, context, spelling variations and mixed-language comments. Confidence is a heuristic strength estimate, not a calibrated statistical probability.
