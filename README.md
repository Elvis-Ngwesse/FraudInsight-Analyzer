# FraudInsight-Analyzer
FraudInsight-Analyzer processes and analyzes customer fraud complaints from text and voice. 
It uses RabbitMQ for data streaming, Whisper for voice transcription, and NLP tools for sentiment a
nd keyword analysis. Ideal for learning multimodal data pipelines and fraud detection analytics.

Download Docker Desktop
Visit: https://www.docker.com/products/docker-desktop/
docker --version


activate virtual env
- steps on how to do this on fraud_analyser.md

Generate Token
Log in to your InfluxDB UI (typically at http://localhost:8086 or your InfluxDB Cloud URL).
Go to the Data section in the left sidebar.
Click on Tokens.
Click Generate Token.
Choose the token type:
All-Access Token: Full access (admin-level, be careful).
Read/Write Token: Restrict to specific buckets.
Select the bucket(s) and permissions if creating a scoped token.
Click Save.
Copy the generated token — this is your InfluxDB token.
paste in .env file INFLUXDB_TOKEN={generated token}

influxdb cli
brew update
brew install influxdb
brew install influxdb-cli

choco install influxdb-cli

influx version

set config
influx config create \
--config-name default \
--host-url http://localhost:8086 \
--org org \
--token eyJhbGciOi... \
--active
