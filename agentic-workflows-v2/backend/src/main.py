from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()


@app.get("/example")
async def example_endpoint():
    """An example endpoint that returns a simple JSON response."""
    return JSONResponse({"message": "Hello, world!"})
