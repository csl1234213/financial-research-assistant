import io
import time

import pytest
import requests

pytestmark = pytest.mark.live


def _run_upload_task():
    resp = requests.post("http://localhost:8000/api/v1/auth/register", json={
        "email": "testuser@example.com",
        "password": "Test@123456",
        "name": "Test User"
    })
    print("REGISTER:", resp.status_code, resp.json())
    token = resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    pdf_content = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 0>>endobj\ntrailer<</Size 3/Root 1 0 R>>\n%%EOF"
    files = {"file": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")}
    resp = requests.post("http://localhost:8000/api/v1/upload", files=files, headers=headers)
    print("UPLOAD:", resp.status_code, resp.json())
    task_id = resp.json()["task_id"]

    for i in range(15):
        time.sleep(3)
        resp = requests.get(f"http://localhost:8000/api/v1/tasks/{task_id}", headers=headers)
        data = resp.json()
        print(f"TASK [{i}]: status={data['status']}, progress={data['progress']}")
        if data["status"] in ("success", "failed"):
            if data["status"] == "failed":
                print(f"ERROR: {data.get('error')}")
            break

    resp = requests.get("http://localhost:8000/api/v1/knowledge/documents", headers=headers)
    print("DOCUMENTS:", resp.status_code)
    docs = resp.json()
    print(f"Count: {len(docs)}")
    for doc in docs:
        print(f"  - {doc.get('filename')}: status={doc.get('status')}")


if __name__ == "__main__":
    _run_upload_task()
