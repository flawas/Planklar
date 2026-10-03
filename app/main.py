from fastapi import FastAPI

app = FastAPI(title="Planklar")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
