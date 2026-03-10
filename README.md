Here is a clean, precise summary for your coding agent:

Project: Hypertube — Base Structure Setup

Goal

Scaffold the full project so that docker compose up starts 5 services, all healthy and running in standby. No business logic, no routes beyond a health check, no database tables yet — just the skeleton.

Services

1. nginx Reverse proxy, single entry point on port 80. Routes traffic to the other services based on URL prefix. Config file at nginx/nginx.conf.

2. nextjs (port 3000) Next.js 14 with App Router and Tailwind CSS. TypeScript. No pages beyond a basic index confirming the service is up. Communicates with both FastAPI backends via Nginx, never directly.

3. user-service (port 8000) FastAPI + Python 3.12. Handles auth, users, search, comments, movies metadata, RESTful API. Single /health GET endpoint returning {"status": "ok"}. Uses SQLAlchemy async + asyncpg to connect to PostgreSQL. No models, no routes beyond health check.

4. torrent-service (port 8001) FastAPI + Python 3.12. Handles torrent downloading, video streaming, FFmpeg transcoding, subtitles. Single /health GET endpoint returning {"status": "ok"}. Uses SQLAlchemy async + asyncpg to connect to PostgreSQL. No models, no routes beyond health check.

5. db PostgreSQL 16 official Docker image. Single database, shared by both FastAPI services. Credentials via environment variables.

Nginx Routing Rules

/                        → nextjs:3000
/api/auth/*              → user-service:8000
/api/users/*             → user-service:8000
/api/movies/*            → user-service:8000
/api/comments/*          → user-service:8000
/api/oauth/*             → user-service:8000
/api/torrent/*           → torrent-service:8001
/api/stream/*            → torrent-service:8001
/api/subtitles/*         → torrent-service:8001

Folder Structure

hypertube/
├── docker-compose.yml
├── .env                        ← single env file at root
├── nginx/
│   └── nginx.conf
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   └── app/
│       ├── layout.tsx
│       └── page.tsx
├── user-service/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py
└── torrent-service/
    ├── Dockerfile
    ├── requirements.txt
    └── main.py

Environment Variables (single .env at root)

POSTGRES_USER=hypertube
POSTGRES_PASSWORD=hypertube
POSTGRES_DB=hypertube
DATABASE_URL=postgresql+asyncpg://hypertube:hypertube@db:5432/hypertube

Both FastAPI services read DATABASE_URL from environment. NextJS reads nothing from the DB directly. The .env file must be in .gitignore.

Key Requirements





docker compose up must start all 5 services with no errors



Both FastAPI services must confirm a successful database connection on startup (log it, don't crash if DB is momentarily not ready — use a retry/wait strategy)



All services must have a health check defined in docker-compose.yml



FastAPI services use uvicorn as the ASGI server



NextJS runs with next dev in the container for now



No business logic, no database schema, no authentication — purely structural



A README.md at the root explaining how to run the project with docker compose up

## How to Run

1.  Ensure Docker and Docker Compose are installed.
2.  Navigate to the project root.
3.  Run the following command to build and start all services:
    ```bash
    docker compose up --build
    ```
4.  Once started, access the application at:
    *   **Frontend**: [http://localhost:8080](http://localhost:8080) (via Nginx)
5.  Check waiting services via health endpoints:
    *   **User Service**: [http://localhost:8080/api/users/health](http://localhost:8080/api/users/health)
    *   **Torrent Service**: [http://localhost:8080/api/torrent/health](http://localhost:8080/api/torrent/health)
