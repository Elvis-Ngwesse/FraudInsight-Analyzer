

# Step 1: Open Terminal
# Step 2: Navigate to your project directory
cd /path/to/your/project

# Step 3: Create a virtual environment
python3 -m venv venv

# Step 4: Activate the virtual environment
source venv/bin/activate

# Step 5: Deactivate when done
deactivate



:: Step 1: Open Command Prompt or PowerShell
:: Step 2: Navigate to your project directory
cd path\to\your\project

:: Step 3: Create a virtual environment
python -m venv venv

:: Step 4: Activate the virtual environment
venv\Scripts\activate


:: Step 5: Deactivate when done
deactivate



docker-compose -f producer/docker-compose.yml up --build


1. RabbitMQ Management UI
   URL: http://localhost:15672

Login:

Username: guest

Password: guest

Once logged in, you can:

See all queues (like your voice_complaints queue).

Monitor messages (ready, unacknowledged, total).

Publish, consume, or delete messages manually.

Check connections, channels, exchanges, and more.

2. MinIO Console (UI for object storage)
   URL: http://localhost:9001

Login:

Username: minioadmin (or your ${MINIO_ACCESS_KEY})

Password: minioadmin (or your ${MINIO_SECRET_KEY})

Once logged in, you can:

See buckets (like your audiofiles bucket).

Browse and download/upload objects (audio files).

Manage users, policies, and settings.

3. Redis UI (Redis Commander)
   URL: http://localhost:8081

This UI connects to your Redis service and lets you:

Browse keys, hashes, lists, sets, etc.

Run commands interactively.

View, edit, or delete Redis keys and values.

Summary of your service ports:
Service	URL/Port	Default Credentials
RabbitMQ UI	http://localhost:15672	guest / guest
MinIO Console	http://localhost:9001	minioadmin / minioadmin
Redis Commander	http://localhost:8081	No login required