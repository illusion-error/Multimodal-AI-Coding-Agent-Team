import io
import time

from PIL import Image


def make_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color=(255, 255, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def make_broken_png() -> bytes:
    content = bytearray(make_png())
    # Keep the PNG signature and chunk layout, but corrupt the image data CRC.
    content[-8] ^= 0xFF
    return bytes(content)


def test_image_validation_and_workflow(client):
    invalid = client.post(
        "/api/tasks/image",
        files={"image": ("problem.txt", b"text", "text/plain")},
    )
    assert invalid.status_code == 400

    empty = client.post(
        "/api/tasks/image",
        files={"image": ("problem.png", b"", "image/png")},
    )
    assert empty.status_code == 400

    disguised = client.post(
        "/api/tasks/image",
        files={"image": ("problem.png", b"not-a-real-image", "image/png")},
        data={"supplement": "two sum: nums and target"},
    )
    assert disguised.status_code == 400

    broken_png = client.post(
        "/api/tasks/image",
        files={"image": ("problem.png", make_broken_png(), "image/png")},
        data={"supplement": "two sum: nums and target"},
    )
    assert broken_png.status_code == 400

    missing_key_and_text = client.post(
        "/api/tasks/image",
        files={"image": ("problem.png", make_png(), "image/png")},
    )
    assert missing_key_and_text.status_code == 400

    created = client.post(
        "/api/tasks/image",
        files={"image": ("problem.png", make_png(), "image/png")},
        data={"supplement": "two sum: nums and target"},
    )
    assert created.status_code == 200
    task_id = created.json()["data"]["task_id"]

    # 等待任务完成
    for _ in range(30):
        detail = client.get(f"/api/tasks/{task_id}").json()["data"]
        if detail["status"] != "running":
            break
        time.sleep(0.5)

    detail = client.get(f"/api/tasks/{task_id}").json()["data"]
    assert detail["status"] == "completed"
    assert detail["input_type"] == "image"
    assert detail["image_format"] == "PNG"
    assert detail["image_width"] == 8
    assert len(client.get(f"/api/tasks/{task_id}/steps").json()["data"]) == 5
