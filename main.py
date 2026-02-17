import uvicorn
import config

uvicorn.run(
    "app:app",
    host=config.API_HOST,
    port=config.API_PORT,
    reload=False,
)
