# Stage 1: build the Vue SPA
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
# npm here, pnpm for local dev: corepack/pnpm is flaky in the container build.
# The repo has no package-lock.json, so each build resolves the package.json
# ranges fresh. For a reproducible image, commit a lockfile and use `npm ci`.
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: FastAPI backend serving the built SPA from ./static
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=frontend /app/frontend/dist ./static
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
