# Install necessary packages if you haven't already (run this once)
# !pip install influxdb-client matplotlib pandas

from influxdb_client import InfluxDBClient
from influxdb_client.client.query_api import QueryApi
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

# --- Setup InfluxDB Client ---

# Replace these with your real environment values
INFLUXDB_URL = "http://localhost:8086"
INFLUXDB_TOKEN = "cKx4XPuKuHnD5xyvWhxfji3lweLK7X0fRfdidS8wlhiyPxEmk8l-WSyOhx3gXzNIBr8LonzD7OuuYY_5xGpPxw=="
INFLUXDB_ORG = "org"
INFLUXDB_BUCKET = "voice_bucket"

client = InfluxDBClient(
    url=INFLUXDB_URL,
    token=INFLUXDB_TOKEN,
    org=INFLUXDB_ORG
)

query_api = client.query_api()

# --- Flux Query to get first 2 sentiment records with all fields ---

flux_query = f'''
from(bucket: "{INFLUXDB_BUCKET}")
  |> range(start: -5h)
  |> filter(fn: (r) => r._measurement == "voice_complaints")
  |> filter(fn: (r) => r._field == "neg" or r._field == "neu" or r._field == "pos" or r._field == "compound")
  |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
  |> limit(n:40)
'''

# Execute query
tables = query_api.query(flux_query)

# Convert query result to a pandas DataFrame
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
df["time"] = pd.to_datetime(df["time"])

print("Query Results:")
print(df)

# --- Plotting Sentiment Scores ---

plt.figure(figsize=(10, 6))

plt.plot(df["time"], df["neg"], label="Negative", marker='o')
plt.plot(df["time"], df["neu"], label="Neutral", marker='o')
plt.plot(df["time"], df["pos"], label="Positive", marker='o')
plt.plot(df["time"], df["compound"], label="Compound", marker='o')

plt.title("Sentiment Analysis Scores from InfluxDB")
plt.xlabel("Time")
plt.ylabel("Sentiment Score")
plt.legend()
plt.grid(True)
plt.show()
