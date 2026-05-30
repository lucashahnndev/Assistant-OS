import requests
import os

with open("test.png", "wb") as f:
    f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0bIDAT\x08\x99c\xf8\x0f\x04\x00\x09\xfb\x03\xfd\xe3U\xf2\x9c\x00\x00\x00\x00IEND\xaeB`\x82")

res = requests.post(
    "https://127.0.0.1:8000/api/assets/logo",
    files={"file": ("test.png", open("test.png", "rb"), "image/png")},
    verify=False
)
print(res.status_code, res.text)
