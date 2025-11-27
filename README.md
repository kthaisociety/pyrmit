# Pyrmit - Building Permit Agent

Pyrmit is an intelligent building permit agent designed to assist with permit-related queries. It features a modern React frontend and a robust Python FastAPI backend, orchestrated via Docker.

## Tech Stack

- **Frontend**: [Next.js](https://nextjs.org/) (React, TypeScript)
- **Backend**: [FastAPI](https://fastapi.tiangolo.com/) (Python)
- **Database**: PostgreSQL with [SQLAlchemy](https://www.sqlalchemy.org/)
- **AI Integration**: OpenAI GPT models
- **Containerization**: Docker & Docker Compose

## Project Structure

```
pyrmit/
├── backend/                 # FastAPI application
│   ├── routers/            # API route definitions
│   ├── database.py         # Database connection & session
│   ├── main.py             # App entry point
│   ├── models.py           # SQLAlchemy database models
│   ├── schemas.py          # Pydantic data models
│   ├── requirements.txt    # Python dependencies
│   └── Dockerfile
├── frontend/                # Next.js application
│   ├── app/                # App Router source code
│   │   ├── page.tsx        # Main chat page
│   │   ├── layout.tsx      # Root layout
│   │   └── globals.css     # Global styles
│   ├── next.config.js      # Next.js configuration
│   ├── package.json        # Node dependencies
│   └── Dockerfile
├── docker-compose.yml      # Service orchestration
└── README.md
```

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed
- An [OpenAI API Key](https://platform.openai.com/api-keys)

## Getting Started

### 1. Configuration

The project uses environment variables for configuration.

**Backend** (`backend/.env`):
Ensure the file exists and contains your OpenAI API key.
```properties
OPENAI_API_KEY=sk-your_actual_api_key_here
DATABASE_URL=postgresql://user:password@db:5432/pyrmit
```

**Frontend** (`frontend/.env`):
Configures the API endpoint.
```properties
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 2. Running the Application

Start the entire stack using Docker Compose:

```bash
docker-compose up --build
```

This command will:
- Start the PostgreSQL database.
- Build and start the Backend service (available at port 8000).
- Build and start the Frontend service (available at port 3000).

### 3. Accessing the App

- **User Interface**: Open [http://localhost:3000](http://localhost:3000) to chat with the agent.
- **API Documentation**: Open [http://localhost:8000/docs](http://localhost:8000/docs) to explore the backend API via Swagger UI.

## Development

To stop the application, press `Ctrl+C` in the terminal where docker-compose is running, or run:

```bash
docker-compose down
```

### Data Persistence

Database data is persisted in a Docker volume named `postgres_data`. To reset the database, you can remove this volume:

```bash
docker-compose down -v
```

### Alternative: Running Locally (Hybrid Mode)

If you prefer to run the backend and frontend locally for faster development (hot-reloading, debugging) while keeping the database in Docker:

1.  **Start only the Database:**
    ```bash
    docker-compose up -d db
    ```

2.  **Backend Setup:**
    - Update `backend/.env`: Set `DATABASE_URL=postgresql://user:password@localhost:5432/pyrmit`
    - Install dependencies:
      ```bash
      cd backend
      python3 -m venv venv
      source venv/bin/activate
      pip install -r requirements.txt
      ```
    - Run server:
      ```bash
      uvicorn main:app --reload
      ```

3.  **Frontend Setup:**
    - Install dependencies:
      ```bash
      cd frontend
      bun install
      ```
    - Run dev server:
      ```bash
      bun run dev
      ```
