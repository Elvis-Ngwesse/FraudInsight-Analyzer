

docker network create app-network

docker compose -f consumer-sentiment/docker-compose.yaml up --build
docker compose -f consumer-sentiment/docker-compose.yaml up --scale voice_consumer=2

docker compose -f consumer-sentiment/docker-compose.yaml down


get token
************
Open your browser to: http://localhost:8086
username= admin
password = admin123
Login with your username and password (the admin user you created during initial setup)
Once logged in, go to "Load Data" > "Tokens" on the left sidebar


query influxdb
macos
- brew install influxdb-cli
- brew install influxdb
- brew link --overwrite influxdb
- which influx
- influx version
windows
- choco install influxdb
influx query '
from(bucket: "voice_bucket")
|> range(start: -1h)
|> filter(fn: (r) => r._measurement == "voice_complaints" and r._field == "compound")
|> limit(n: 10)
' --org "org" --token "opTyNmbY5UQssS4uqxXd3RRR3mZdM6R-EonzbROab1eyqRseVNOMGPewlBoIZBm4Xl7t4F2kumO273DBy1AgQQ==" --host http://localhost:8086


influx query '
from(bucket: "text_bucket")
|> range(start: -1h)
|> filter(fn: (r) => r._measurement == "text_complaints" and r._field == "compound")
|> limit(n: 20)
' --org "org" \
--token "43yGjpGckeqEHxBh4GRbjGVYpgS8bdCEDUSz0sJ934V9wFu6BxXMmje8k_RlPn4GOrMfp2OcA-0h2Sf4vuGdEA==" \
--host http://localhost:8086


curl -i http://localhost:8086/health


Open your browser and go to:
http://localhost:3000

Login default:
User: admin
Password: admin


2. Add InfluxDB as a Data Source in Grafana

✅ Step 1: Ensure InfluxDB is a Data Source
Login to Grafana (usually at http://localhost:3000)

Go to ⚙️ Settings → Data Sources

Click “Add data source”

Select InfluxDB

Configure:

Query Language: Flux

URL: http://influxdb:8086

Organization: org
username: admin
password: admin123

Token: Paste your InfluxDB token

Default Bucket: voice_bucket

Click “Save & Test”


✅ Step 2: Create the Dashboard
Go to + Create → Dashboard

Click “Add new panel”

✅ Step 3: Add Panel Query
Choose your InfluxDB data source

Use this Flux query to plot the compound score over time:



from(bucket: "voice_bucket")
|> range(start: -3h)
|> filter(fn: (r) => r._measurement == "voice_complaints" and r._field == "compound")
|> aggregateWindow(every: 1m, fn: mean)
|> yield(name: "mean")

🔍 You can adjust range(start: -1h) to -24h, -7d, etc., and aggregateWindow interval as needed.

✅ Step 4: Customize the Panel
Panel title: "Voice Sentiment (Compound Score)"

Visualization type: Time series, Gauge, or Bar chart

Add thresholds (e.g., red < -0.5, green > 0.5)

✅ Step 5: Save the Dashboard
Click “Apply” to save the panel

Click the disk icon 💾 at the top to save the dashboard

🧠 Bonus Tips
Add multiple panels: one for compound, another for neg/pos/neu

Add filters for message_id, time ranges, etc.

Set alerts if compound sentiment is too negative over time.

