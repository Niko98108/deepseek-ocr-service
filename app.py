import base64
import json
import logging
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from google.cloud import storage
import ollama

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
storage_client = storage.Client()

DOCUMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "id_number": {"type": "string"},
        "address": {"type": "string"},
        "date_of_birth": {"type": "string"},
        "place_of_birth": {"type": "string"},
        "sex": {"type": "string"},
        "nationality": {"type": "string"},
    },
    "required": ["name", "id_number", "address", "date_of_birth"],
}

DEFAULT_PROMPT = "Extract the name, ID number, and address from this document."


class GCSOCRRequest(BaseModel):
    gcs_uri: str
    prompt: str = DEFAULT_PROMPT


def read_gcs_image_as_base64(gcs_uri: str) -> str:
    if not gcs_uri.startswith("gs://"):
        raise ValueError("gcs_uri must start with gs://")

    _, path = gcs_uri.split("gs://", 1)
    bucket_name, blob_path = path.split("/", 1)

    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_path)

    if not blob.exists():
        raise FileNotFoundError(f"Object not found: {gcs_uri}")

    image_bytes = blob.download_as_bytes()
    return base64.b64encode(image_bytes).decode("utf-8")


def run_ocr_extraction(image_b64: str, prompt: str) -> dict:
    response = ollama.chat(
        model="deepseek-ocr",
        messages=[
            {
                "role": "user",
                "content": prompt,
                "images": [image_b64],
            }
        ],
        format=DOCUMENT_SCHEMA,
    )
    return json.loads(response["message"]["content"])


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ocr")
def run_ocr_from_gcs(req: GCSOCRRequest):
    """OCR from a GCS URI. Send JSON body: {"gcs_uri": "gs://bucket/file.jpg"}"""
    try:
        image_b64 = read_gcs_image_as_base64(req.gcs_uri)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read from GCS: {e}")

    try:
        result = run_ocr_extraction(image_b64, req.prompt)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"Model returned invalid JSON: {e}")
    except Exception as e:
        logger.error(f"OCR failed for {req.gcs_uri}: {e}")
        raise HTTPException(status_code=500, detail=f"OCR failed: {e}")

    return {"gcs_uri": req.gcs_uri, "result": result}


@app.post("/ocr/upload")
async def run_ocr_from_upload(
    file: UploadFile = File(...),
    prompt: str = Form(DEFAULT_PROMPT),
):
    """OCR from a direct file upload — use this one in Postman."""
    try:
        image_bytes = await file.read()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read uploaded file: {e}")

    try:
        result = run_ocr_extraction(image_b64, prompt)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"Model returned invalid JSON: {e}")
    except Exception as e:
        logger.error(f"OCR failed for uploaded file {file.filename}: {e}")
        raise HTTPException(status_code=500, detail=f"OCR failed: {e}")

    return {"filename": file.filename, "result": result}