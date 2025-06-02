

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