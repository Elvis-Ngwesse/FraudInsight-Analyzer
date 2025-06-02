

docker network create app-network

docker compose -f consumer-sentiment/docker-compose.yaml up --build

docker compose -f consumer-sentiment/docker-compose.yaml down
