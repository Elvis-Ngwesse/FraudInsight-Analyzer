from influxdb_client import InfluxDBClient
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns

# Set seaborn style for better aesthetics
sns.set(style="darkgrid")

# --- Configurable Settings ---
INFLUXDB_URL = "http://localhost:8086"
INFLUXDB_TOKEN = "cKx4XPuKuHnD5xyvWhxfji3lweLK7X0fRfdidS8wlhiyPxEmk8l-WSyOhx3gXzNIBr8LonzD7OuuYY_5xGpPxw=="
INFLUXDB_ORG = "org"

# --- Choose between 'text' or 'voice' ---
bucket_type = "voice"  # Change to "voice" to switch datasets

# Set bucket and measurement based on type
if bucket_type == "voice":
    INFLUXDB_BUCKET = "voice_bucket"
    measurement = "voice_complaints"
elif bucket_type == "text":
    INFLUXDB_BUCKET = "text_bucket"
    measurement = "text_complaints"
else:
    raise ValueError("bucket_type must be either 'text' or 'voice'")

# --- Connect to InfluxDB ---
client = InfluxDBClient(
    url=INFLUXDB_URL,
    token=INFLUXDB_TOKEN,
    org=INFLUXDB_ORG
)
query_api = client.query_api()

# --- Flux Query ---
flux_query = f'''
from(bucket: "{INFLUXDB_BUCKET}")
  |> range(start: -12h)
  |> filter(fn: (r) => r._measurement == "{measurement}")
  |> filter(fn: (r) => r._field == "neg" or r._field == "neu" or r._field == "pos" or r._field == "compound")
  |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
  |> limit(n: 40)
'''

# --- Query and Format ---
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
        })

df = pd.DataFrame(results)

if df.empty:
    print("No data found for the given query.")
    exit()

df["time"] = pd.to_datetime(df["time"])

# --- Plot ---
plt.figure(figsize=(12, 7))

plt.plot(df["time"], df["neg"], label="Negative", color='red', linestyle='-', marker='o', markersize=5, markevery=4)
plt.plot(df["time"], df["neu"], label="Neutral", color='gray', linestyle='--', marker='s', markersize=5, markevery=4)
plt.plot(df["time"], df["pos"], label="Positive", color='green', linestyle='-.', marker='^', markersize=5, markevery=4)
plt.plot(df["time"], df["compound"], label="Compound", color='blue', linestyle=':', marker='d', markersize=5, markevery=4)

plt.title(f"Sentiment Analysis Scores Over Time ({bucket_type.title()} Complaints)")
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
