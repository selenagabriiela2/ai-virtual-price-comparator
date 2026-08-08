from google import genai
from PIL import Image
from pathlib import Path
import uuid
from licenta import GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)

OUT_DIR = Path("generated_images")
OUT_DIR.mkdir(exist_ok=True)

def generate_visual_response(prompt: str, image_paths: list[str]) -> list[str]:

    styles = [
        "realistic product photo",
        "studio lighting product photo",
        "fashion editorial style"
    ]

    # Dacă utilizatorul adaugă o singură imagine, generăm o singură variantă (primul stil)
    if len(image_paths) < 2:
        styles = styles[:1]

    images = [Image.open(p) for p in image_paths]

    results = []

    for style in styles:

        contents = [prompt + " " + style] + images

        response = client.models.generate_content(
            model="gemini-3.1-flash-image-preview",
            contents=contents,
        )

        parts = None

        # cazul 1
        if hasattr(response, "parts") and response.parts:
            parts = response.parts

        # cazul 2
        elif hasattr(response, "candidates") and response.candidates:
            candidate = response.candidates[0]

            if hasattr(candidate, "content") and candidate.content:
                if hasattr(candidate.content, "parts"):
                    parts = candidate.content.parts

        # dacă nu există parts trecem mai departe
        if not parts:
            continue

        for part in parts:

            if getattr(part, "inline_data", None):

                out = OUT_DIR / f"gen_{uuid.uuid4().hex}.png"
                part.as_image().save(out)

                results.append(str(out))
                break

        if len(results) >= 3:
            break

    return results