Topic Modeling
Automatically uncover the main themes in customer complaints to group and understand them at scale.
Examples:
Loans
Mobile app issues
Credit card problems
Technical failures
Tool: LDA, BERTopic
Use case: Discover trends, auto-label complaints, and detect emerging issues.

docker compose -f consumer-topic/docker-compose.yaml up --build
docker compose -f consumer-topic/docker-compose.yaml up --scale voice_consumer=2
docker compose -f consumer-topic/docker-compose.yaml down


get token
************
Open your browser to: http://localhost:8086
username= admin
password = admin123
Login with your username and password (the admin user you created during initial setup)
Once logged in, go to "Load Data" > "Tokens" on the left sidebar

set influxdb cli config
- get command from readme.md

text model query

influx query --org org '
from(bucket: "topic_text_bucket")
|> range(start: -30d)
|> filter(fn: (r) => r._measurement == "text_complaints_topic_model" and r._field == "topic_probability")
|> group(columns: ["topic_id"])
|> mean()
'
influx query '
from(bucket: "topic_text_bucket")
|> range(start: -30d)
|> filter(fn: (r) => r._measurement == "text_complaints_topic_model" and r._field == "topic_words")
|> filter(fn: (r) => contains(value: r.topic_id, set: ["0", "1", "2", "3"]))
|> group(columns: ["topic_id"])
|> last()
'





