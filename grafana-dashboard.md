✅ 1. Prerequisites
Grafana and InfluxDB are running and connected.
InfluxDB data source is added to Grafana:
Go to Grafana → Settings → Data Sources → Add data source
Select InfluxDB
Set:
URL: http://influxdb:8086
user: admin
Password:admin123
Organization: org
Token: your INFLUXDB_TOKEN
Default Bucket: init_bucket


📊 2. Data Structure Assumed in InfluxDB
Each data point has:
Measurement: voice_complaints
Tags: message_id, scenario, customer_id, channel
Fields: transcript, neg, neu, pos, compound
Time: UTC timestamp from processing time

📊 Data Structure Assumed in InfluxDB
Each data point has:
Measurement: text_complaints
Tags: message_id, scenario, customer_id, channel
Fields: text, neg, neu, pos, compound
Time: UTC timestamp from processing time

🎨 3. Create Dashboard Panels
📌 Panel 1: Sentiment Over Time
Type: Time series

Query:
from(bucket: "INFLUXDB_BUCKET")
|> range(start: -6h)
|> filter(fn: (r) => r._measurement == "voice_complaints" and r._field == "compound")
|> aggregateWindow(every: 5m, fn: mean)
|> yield(name: "mean")

Title: "Sentiment Score Over Time"

📌 Panel 2: Scenario Breakdown (Bar Chart)
Type: Bar chart

Query:
from(bucket: "INFLUXDB_BUCKET")
|> range(start: -6h)
|> filter(fn: (r) => r._measurement == "voice_complaints" and r._field == "compound")
|> group(columns: ["scenario"])
|> mean()

Title: "Average Sentiment by Scenario"

📌 Panel 3: Sentiment Distribution (Gauge or Pie)
Type: Gauge or Pie Chart (Grafana Pie Chart Plugin)

Query:
from(bucket: "INFLUXDB_BUCKET")
|> range(start: -6h)
|> filter(fn: (r) => r._measurement == "voice_complaints" and r._field == "compound")
|> group()
|> mean()

Title: "Average Sentiment Today"


📌 Panel 4: Transcript Word Cloud or Table
Type: Table (Grafana has limited support for Word Clouds without plugins)

Query:
from(bucket: "INFLUXDB_BUCKET")
|> range(start: -6h)
|> filter(fn: (r) => r._measurement == "voice_complaints" and r._field == "transcript")

Title: "Recent Transcripts"

You can limit results or sort by _time to get most recent complaints.

📌 Panel 5: Negative Complaints Count
Type: Stat

Query:
from(bucket: "INFLUXDB_BUCKET")
|> range(start: -24h)
|> filter(fn: (r) => r._measurement == "voice_complaints" and r._field == "compound")
|> filter(fn: (r) => r._value < -0.4)
|> count()

Title: "Negative Complaints Today"

✅ Final Touch
Set dashboard time range to last 6h or last 24h.
Save dashboard as “Voice Complaints Sentiment Analysis”


How to import:
Copy the JSON below.
In Grafana, go to Dashboards → Import → Upload JSON file (paste JSON).
Select your InfluxDB datasource.
Save and open the dashboard.