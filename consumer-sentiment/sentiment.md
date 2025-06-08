
## 🧠 Sentiment Analysis with VADER
This section explains how to use the **VADER (Valence Aware Dictionary and sEntiment Reasoner)**
sentiment analysis tool to evaluate the **emotional tone** of customer complaint transcripts.
It is part of a larger audio processing pipeline that transcribes voice messages and stores
analysis results in a time-series database.
---
## 🎯 Objective
To **automatically detect emotional tone** in a customer's voice complaint using text transcription
and VADER sentiment analysis. This enables downstream systems to act on **customer mood**, **anger**,
or **satisfaction**.
---
## 📚 What is VADER?
VADER is a **lexicon and rule-based** sentiment analysis tool built especially for **short texts**
like social media posts, dialogues, and reviews.
> ✅ No model training required  
> ✅ Fast and lightweight  
> ✅ Handles intensifiers, negations, slang, and punctuation  
> ✅ Works great for real-time feedback systems
---
## 🧠 Core Code
```python
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

analyzer = SentimentIntensityAnalyzer()
sentiment = analyzer.polarity_scores(transcript)
```
## 💬 Input Example
transcript = "I’m really frustrated! I’ve been charged twice and nobody is helping me."

## 🧪 Output
{
"neg": 0.56,
"neu": 0.34,
"pos": 0.10,
"compound": -0.69
}

## 🔎 Breakdown of Sentiment Scores
| Key        | Description                        | Range       | Example Interpretation                             |
|------------|------------------------------------|-------------|----------------------------------------------------|
| `neg`      | Negative sentiment intensity       | 0.0 → 1.0   | High when the customer expresses anger/frustration |
| `neu`      | Neutral sentiment intensity        | 0.0 → 1.0   | High when message is factual or non-emotional      |
| `pos`      | Positive sentiment intensity       | 0.0 → 1.0   | High when the message includes praise/happiness    |
| `compound` | Overall normalized sentiment score | -1.0 → +1.0 | Aggregated score showing total emotional weight    |


## ⚖️ How to Interpret compound
| Score         | Meaning  |
|---------------|----------|
| > 0.05        | Positive |
| < -0.05       | Negative |
| [-0.05, 0.05] | Neutral  |

## 🎓 Teaching Tips
The compound score is best for quick decisions.
The neg, neu, pos scores are useful for analytics dashboards.
Students should observe different transcripts and observe score changes

## ✅ What Students Should Learn
How to extract tone/emotion from text using VADER.
How to interpret polarity scores and act on them.
How to combine transcription + sentiment for real-world analytics

## 🧠 Suggested Exercises
Write five different transcripts and manually score their tone.
Run them through VADER and compare your prediction to the actual score.
Modify a transcript to flip the sentiment from negative to positive.

## Start docker compose
docker compose -f consumer-sentiment/docker-compose.yaml up --build
docker compose -f consumer-sentiment/docker-compose.yaml up --scale voice_consumer=2
docker compose -f consumer-sentiment/docker-compose.yaml down

## Set InfluxDB Local Config
- Go to README.md
- set config

## Query InfluxDB and Display graph
Make sure you have installed required packages
- pip install notebook influxdb-client matplotlib pandas
- pip install seaborn

Replace the placeholder values
- INFLUXDB_TOKEN = "your-influxdb-token"
- bucket_type = "voice"

Run the code
- python consumer-sentiment/sentiment.py

