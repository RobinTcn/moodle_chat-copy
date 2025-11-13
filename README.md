# Start backend:
.\.venv\Scripts\Activate.ps1 

uvicorn backend:app --reload --port 8000

# Start frontend:
npm install

npm run dev
