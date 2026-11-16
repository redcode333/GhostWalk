FROM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY ghostwalk ghostwalk
COPY gwsim gwsim
COPY baselines baselines
COPY eval eval
COPY results.json ./
COPY docs/replays docs/replays
RUN pip install --no-cache-dir -e .
COPY --from=web /web/dist web/dist
ENV GW_STATE=/data/state.json AUTH_MODE=none
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "ghostwalk.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
