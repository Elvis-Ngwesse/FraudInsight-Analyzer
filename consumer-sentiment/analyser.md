

docker network create app-network

docker compose -f consumer-sentiment/docker-compose.yaml up --build

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
from(bucket: "text_bucket")
|> range(start: -1h)
|> filter(fn: (r) => r._measurement == "text_complaints")
|> limit(n: 10)
' --org "org" --token "3sZtR4jo135hOcs0i-kPakmTyGToy9LmfKk0JXtZZ7ghzcsIsIm-jGJvvFvmOXz3A0u7v6sVziTAHx36bvp2cg==" --host http://localhost:8086


influx query '
from(bucket: "voice_bucket")
|> range(start: -1h)
|> filter(fn: (r) => r._measurement == "voice_complaints")
|> limit(n:10)
' --org "org" --token "iQR2Im5uSfaAYysoyyk8qfSV2N473QPh5231vEigm6dsg7CG2SOURDMv2BWBrZhjc0oGNswwANqG-glEz_UnXA==" --host http://localhost:8086


Open your browser and go to:
http://localhost:3000

Login default:
User: admin
Password: admin


2. Add InfluxDB as a Data Source in Grafana
   Login to Grafana UI.

On the left sidebar, click Gear Icon → Data Sources → Add data source.

Select InfluxDB from the list.

Configure the data source fields:

URL:
http://influxdb:8086 (or your InfluxDB host URL)

Query Language:
Choose Flux

Organization:
Your InfluxDB org name (e.g., "org")

Token:
Your InfluxDB token (the one you use in your code)

Default Bucket:
Choose your bucket (e.g., voice_bucket or text_bucket)

Click Save & Test — you should see a success message.


curl -i http://localhost:8086/health


3. Create a Dashboard & Panels
   Click the + icon on the left → Dashboard → Add new panel.

In the Query section, enter your Flux query. For example:

from(bucket: "voice_bucket")
|> range(start: -1h)
|> filter(fn: (r) => r._measurement == "voice_complaints")
|> filter(fn: (r) => r._field == "compound")
|> aggregateWindow(every: 1m, fn: mean, createEmpty: false)
|> yield(name: "mean")

This query will show average compound sentiment scores over time.

Choose Visualization type, e.g., Time series or Bar gauge.

Adjust the panel settings as you like, then Save the dashboard.