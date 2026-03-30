# Pyrmit - Building Permit Agent

<table>
  <tr>
    <td valign="middle">
      Pyrmit is an intelligent building permit agent designed to assist with permit-related queries. The user is able to input their own legal documents and chunk, embed and store them in an SQL database. The agent can then be used to provide an action plan to fast-track the building permit process.
    </td>
    <td valign="middle">
      <img src="frontend/public/pyrmit_middle.jpg" alt="Pyrmit Logo" width="300" />
    </td>
  </tr>
</table>

## Tech Stack

### Frontend
![Next JS](https://img.shields.io/badge/Next-black?style=for-the-badge&logo=next.js&logoColor=white) ![React](https://img.shields.io/badge/React-20232A?style=for-the-badge&logo=react&logoColor=61DAFB) ![TypeScript](https://img.shields.io/badge/TypeScript-007ACC?style=for-the-badge&logo=typescript&logoColor=white) ![TailwindCSS](https://img.shields.io/badge/Tailwind_CSS-38B2AC?style=for-the-badge&logo=tailwind-css&logoColor=white)

### Backend
![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi) ![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white) ![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white) ![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=for-the-badge&logo=openai&logoColor=white)

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
Ensure the file exists and contains either direct OpenAI credentials or Cloudflare AI Gateway credentials.
```properties
# Option 1: direct OpenAI
OPENAI_API_KEY=sk-your_actual_api_key_here

# Option 2: Cloudflare AI Gateway
# CF_AIG_TOKEN=your_cloudflare_gateway_token
# CF_ACCOUNT_ID=your_cloudflare_account_id
# CF_GATEWAY_ID=your_gateway_id
# Optional: use a non-default stored provider key alias
# CF_AIG_BYOK_ALIAS=production
# Optional: force provider selection ("openai" or "cloudflare")
# LLM_PROVIDER=openai

DATABASE_URL=postgresql://user:password@db:5432/pyrmit
JWT_SECRET_KEY=replace-with-openssl-rand-hex-32-output
ACCESS_TOKEN_EXPIRE_MINUTES=30
ACCESS_GATE_PASSWORD=choose-a-shared-password
# Needed when frontend/backend are on different subdomains, e.g. .example.com
# ACCESS_GATE_COOKIE_DOMAIN=.example.com
# Use "none" with secure cookies if your deployment requires cross-site cookie behavior
# ACCESS_GATE_COOKIE_SAMESITE=lax
# ACCESS_GATE_COOKIE_SECURE=true
```

**Frontend** (`frontend/.env`):
Configures the API endpoint.
```properties
NEXT_PUBLIC_API_URL=http://localhost:8000
ACCESS_GATE_PASSWORD=choose-a-shared-password
```

If `ACCESS_GATE_PASSWORD` is set in both apps, the deployed website is password protected before users can reach `/`, `/auth`, or the backend API. The value must match in `backend/.env` and `frontend/.env`. For direct backend access outside the frontend, send the same value in the `x-access-gate-password` header. `DEV_ACCESS_PASSWORD` is still accepted as a backward-compatible fallback.

The password form now talks directly to FastAPI at `/api/access-gate/unlock`; there is no Next.js API route involved. FastAPI issues the shared access cookie, and Next.js blocks protected routes with a server-side App Router layout instead of middleware.

`NEXT_PUBLIC_API_URL` is a build-time Next.js variable. In Docker deployments it must be available during the frontend image build, not only at container runtime. The Dockerfile accepts it as a build arg and injects it into the `next build` step.

Auth now follows FastAPI's OAuth2 password flow with bearer JWTs. The frontend stores the access token in the browser and sends it as `Authorization: Bearer <token>` to protected API routes. In Swagger at `/docs`, use the built-in `Authorize` flow against `/api/auth/token`.

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
      uv venv
      source .venv/bin/activate
      uv pip install -r requirements.txt
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
      

'