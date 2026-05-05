# FinSight Frontend

Next.js workbench UI for FinSight.

## Local Run

Start the FastAPI backend from the repo root:

```bash
venv/bin/python backend/main.py
```

Then start the frontend:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000.

## Environment

Create `frontend/.env.local`:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

For deployment, point `NEXT_PUBLIC_API_BASE_URL` at the deployed FastAPI backend.
