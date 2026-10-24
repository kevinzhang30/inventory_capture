"""Lambda entry point (API Gateway HTTP API → Mangum → FastAPI)."""

from mangum import Mangum

from core_api.app import app

handler = Mangum(app, lifespan="off")
