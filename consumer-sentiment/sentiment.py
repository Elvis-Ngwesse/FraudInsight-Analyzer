from influxdb_client import InfluxDBClient
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
from dotenv import load_dotenv
import os

# --- Load environment variables ---
load_dotenv()


# --- Plot Config ---
plot_time_series = True
plot_mean_sentiment = False
plot_distribution = False
plot_by_scenario = False
plot_volume_and_sentiment = False

# --- Aesthetics ---
sns.set(style="darkgrid")

# --- Config ---
INFLUXDB_URL = "http://localhost:8086"
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN")
INFLUXDB_ORG = "org"

bucket_type = "voice"  # 'text' or 'voice'
if bucket_type == "voice":
    INFLUXDB_BUCKET = "voice_bucket"
    measurement = "voice_complaints"
elif bucket_type == "text":
    INFLUXDB_BUCKET = "text_bucket"
    measurement = "text_complaints"
else:
    raise ValueError("bucket_type must be either 'text' or 'voice'")

client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
query_api = client.query_api()

# --- Flux Query ---
flux_query = f'''
from(bucket: "{INFLUXDB_BUCKET}")
  |> range(start: -12h)
  |> filter(fn: (r) => r._measurement == "{measurement}")
  |> filter(fn: (r) => r._field == "neg" or r._field == "neu" or r._field == "pos" or r._field == "compound")
  |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
  |> limit(n: 200)
'''

# --- Fetch and Format ---
tables = query_api.query(flux_query)
results = []
for table in tables:
    for record in table.records:
        results.append({
            "time": record.get_time(),
            "neg": record.values.get("neg"),
            "neu": record.values.get("neu"),
            "pos": record.values.get("pos"),
            "compound": record.values.get("compound"),
            "scenario": record.values.get("scenario", "unknown"),
        })

df = pd.DataFrame(results)
if df.empty:
    print("No data found.")
    exit()

df["time"] = pd.to_datetime(df["time"])

# --- Plotting Section ---

if plot_time_series:
    plt.figure(figsize=(12, 7))
    plt.plot(df["time"], df["neg"], label="Negative", color='red', marker='o', markevery=4)
    plt.plot(df["time"], df["neu"], label="Neutral", color='gray', linestyle='--', marker='s', markevery=4)
    plt.plot(df["time"], df["pos"], label="Positive", color='green', linestyle='-.', marker='^', markevery=4)
    plt.plot(df["time"], df["compound"], label="Compound", color='blue', linestyle=':', marker='d', markevery=4)
    plt.title(f"Sentiment Over Time ({bucket_type.title()} Complaints)")
    plt.xlabel("Timestamp")
    plt.ylabel("Sentiment Score")
    plt.ylim(-1, 1)
    plt.legend()
    plt.grid(True)
    plt.gca().xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    plt.show()

if plot_mean_sentiment:
    mean_values = df[["neg", "neu", "pos", "compound"]].mean()
    mean_values.plot(kind="bar", color=["red", "gray", "green", "blue"], title="Mean Sentiment Scores")
    plt.ylim(-1, 1)
    plt.ylabel("Score")
    plt.tight_layout()
    plt.show()

if plot_distribution:
    plt.figure(figsize=(10, 6))
    sns.boxplot(data=df[["neg", "neu", "pos", "compound"]])
    plt.title("Sentiment Score Distribution")
    plt.ylim(-1, 1)
    plt.tight_layout()
    plt.show()

if plot_by_scenario and "scenario" in df.columns:
    grouped = df.groupby("scenario")[["neg", "neu", "pos", "compound"]].mean()
    grouped.plot(kind="bar", figsize=(12, 6), colormap="coolwarm", title="Average Sentiment per Scenario")
    plt.ylabel("Sentiment Score")
    plt.ylim(-1, 1)
    plt.tight_layout()
    plt.show()

if plot_volume_and_sentiment:
    df["hour"] = df["time"].dt.hour
    volume = df.groupby("hour").size()
    avg_sentiment = df.groupby("hour")["compound"].mean()

    fig, ax1 = plt.subplots(figsize=(12, 6))
    ax2 = ax1.twinx()
    volume.plot(ax=ax1, kind="bar", alpha=0.4, color="gray", label="Volume")
    avg_sentiment.plot(ax=ax2, color="blue", marker="o", label="Compound")

    ax1.set_ylabel("Complaint Volume")
    ax2.set_ylabel("Mean Compound Sentiment")
    ax1.set_xlabel("Hour of Day")
    plt.title("Complaint Volume & Sentiment Over the Day")
    fig.legend(loc="upper left")
    plt.tight_layout()
    plt.show()
