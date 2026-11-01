"""Google My Maps KML sync → PLAQUE_COORDS and PLAQUE_MEDIA.

Coordinates & media (photos / YouTube videos) are synced automatically
from Google My Maps :
    - at server startup
    - from admin : /admin/sync-map

The matching between KML placemark names and DB street names is done
automatically — no manual mapping is required.
"""

from __future__ import annotations

import html
import json
import os
import re
import urllib.request

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from .extensions import db
from .models import Question

# Media (images + YouTube videos) extracted from KML, indexed by code
PLAQUE_MEDIA: dict = {}

# Coordinates — hardcoded fallback in case the KML is unreachable.
# sync_plaque_coords() refreshes these automatically at startup.
PLAQUE_COORDS: dict = {
    "1876": {"lat": 37.4959051, "lng": 126.9980559},
    "1002": {"lat": 37.4957373, "lng": 126.9980425},
    "5730": {"lat": 37.4955904, "lng": 126.9980103},
    "1004": {"lat": 37.4954457, "lng": 126.9980934},
    "2734": {"lat": 37.4950526, "lng": 126.9980049},
    "4782": {"lat": 37.4950303, "lng": 126.9978051},
    "6187": {"lat": 37.4940008, "lng": 127.0010921},
    "1008": {"lat": 37.4933793, "lng": 127.001988},
    "6976": {"lat": 37.4933176, "lng": 127.0021006},
    "9168": {"lat": 37.4959756, "lng": 127.0014677},
    "1011": {"lat": 37.4960437, "lng": 127.0014032},
    "1012": {"lat": 37.4973652, "lng": 127.0004779},
    "1493": {"lat": 37.4973923, "lng": 127.0004759},
    "1014": {"lat": 37.4975163, "lng": 127.0004779},
    "4594": {"lat": 37.4969333, "lng": 126.9987505},
    "4391": {"lat": 37.496665, "lng": 126.9975526},
    "8941": {"lat": 37.4986442, "lng": 126.9989276},
    "1018": {"lat": 37.4989846, "lng": 126.9988336},
    "1019": {"lat": 37.4993368, "lng": 126.9990014},
    "3841": {"lat": 37.4998954, "lng": 126.9981176},
    "5382": {"lat": 37.4991985, "lng": 126.9982879},
    "1022": {"lat": 37.4988782, "lng": 126.9984542},
    "3619": {"lat": 37.4987208, "lng": 126.997683},
    "1024": {"lat": 37.4983334, "lng": 126.9976401},
    "7364": {"lat": 37.4960192, "lng": 126.9997229},
    "5942": {"lat": 37.4974036, "lng": 126.9983349},
    "8397": {"lat": 37.4969694, "lng": 126.9981685},
    "7194": {"lat": 37.4982314, "lng": 126.9982919},
    "9462": {"lat": 37.4960054, "lng": 126.9980934},
    "3942": {"lat": 37.4957117, "lng": 126.9974953},
}


def _normalize(text: str) -> str:
    """Normalise a string for loose comparison."""
    text = text.lower().strip()
    for a, b in [
        ("é", "e"),
        ("è", "e"),
        ("ê", "e"),
        ("ë", "e"),
        ("à", "a"),
        ("â", "a"),
        ("î", "i"),
        ("ï", "i"),
        ("ô", "o"),
        ("ù", "u"),
        ("û", "u"),
        ("ü", "u"),
        ("ç", "c"),
        ("œ", "oe"),
    ]:
        text = text.replace(a, b)
    text = re.sub(r"[^\w\s]", " ", text)
    for mot in ["rue", "avenue", "boulevard", "place", "allee", "impasse", "passage"]:
        text = re.sub(r"\b" + mot + r"\b", "", text)
    return " ".join(text.split())


def _match_kml_name_to_question(kml_name: str, questions) -> str | None:
    """Find the question whose rue best matches the KML placemark name."""
    kml_norm = _normalize(kml_name)
    kml_words = set(kml_norm.split())

    best_match = None
    best_score = 0

    for q in questions:
        rue_norm = _normalize(q.rue)
        rue_words = set(rue_norm.split())
        common = {w for w in kml_words & rue_words if len(w) > 2}
        score = len(common)
        if kml_norm in rue_norm or rue_norm in kml_norm:
            score += 3
        if score > best_score:
            best_score = score
            best_match = q.code

    return best_match if best_score >= 1 else None


def sync_plaque_coords() -> tuple[int, str]:
    """Download the KML from Google My Maps and refresh PLAQUE_COORDS /
    PLAQUE_MEDIA by matching KML names against questions in the DB."""
    mymaps_id = current_app.config.get("GOOGLE_MYMAPS_ID", "")
    kml_url = f"https://www.google.com/maps/d/kml?mid={mymaps_id}&forcekml=1"

    try:
        req = urllib.request.Request(
            kml_url, headers={"User-Agent": "FranceSeorae-Quiz/1.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            kml_data = resp.read().decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        msg = f"Téléchargement KML échoué : {e}"
        print(f"[sync] {msg}")
        return 0, msg

    placemarks = []
    for block in kml_data.split("<Placemark>")[1:]:
        block = block.split("</Placemark>")[0]
        name_match = re.search(
            r"<name>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</name>", block, re.DOTALL
        )
        coords_match = re.search(r"<coordinates>\s*([\d\.\-]+),([\d\.\-]+)", block)
        if name_match and coords_match:
            # Extract media links (images + YouTube videos).
            # Uploaded photos live in <ExtendedData> gx_media_links,
            # YouTube videos are embedded in <description> as HTML.
            images = []
            videos = []
            seen_imgs = set()
            seen_vids = set()

            media_links_raw = ""
            media_match = re.search(
                r"gx_media_links.*?<value>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</value>",
                block,
                re.DOTALL,
            )
            if media_match:
                media_links_raw = media_match.group(1).strip()

            desc_match = re.search(
                r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>",
                block,
                re.DOTALL,
            )
            description_html = desc_match.group(1) if desc_match else ""

            haystack = html.unescape(media_links_raw + " " + description_html)

            youtube_re = re.compile(
                r"(?:youtube(?:-nocookie)?\.com/(?:embed/|watch\?v=|v/)"
                r"|youtu\.be/)([A-Za-z0-9_-]{11})"
            )
            for vid_id in youtube_re.findall(haystack):
                if vid_id not in seen_vids:
                    seen_vids.add(vid_id)
                    videos.append(vid_id)

            for link in html.unescape(media_links_raw).split():
                link = link.strip()
                if (
                    link.startswith("http")
                    and "youtube" not in link
                    and "youtu.be" not in link
                ) and link not in seen_imgs:
                    seen_imgs.add(link)
                    images.append(link)

            desc_unescaped = html.unescape(description_html)
            for m in re.finditer(r'(?:src|href)=["\']([^"\']+)["\']', desc_unescaped):
                link = m.group(1)
                if (
                    link.startswith("http")
                    and "youtube" not in link
                    and "youtu.be" not in link
                    and link not in seen_imgs
                ):
                    seen_imgs.add(link)
                    images.append(link)

            placemarks.append(
                {
                    "name": name_match.group(1).strip(),
                    "lat": float(coords_match.group(2)),
                    "lng": float(coords_match.group(1)),
                    "images": images[:3],
                    "videos": videos[:2],
                }
            )

    if not placemarks:
        msg = "KML téléchargé mais aucun placemark trouvé."
        print(f"[sync] {msg}")
        return 0, msg

    try:
        questions = Question.query.all()
    except SQLAlchemyError:
        questions = []

    if not questions:
        msg = "Aucune question en base pour le matching."
        print(f"[sync] {msg}")
        return 0, msg

    new_coords = {}
    unmatched = []

    # Ensure a local directory exists for the images
    img_dir = os.path.join(current_app.static_folder, "images", "plaques")
    os.makedirs(img_dir, exist_ok=True)

    for pm in placemarks:
        code = _match_kml_name_to_question(pm["name"], questions)
        if code:
            new_coords[code] = {"lat": pm["lat"], "lng": pm["lng"]}

            # Find the actual Question object from our list
            q_obj = next((q for q in questions if q.code == code), None)
            if q_obj:
                # 1. Videos: Just save the YouTube IDs directly
                if pm["videos"]:
                    q_obj.media_videos = json.dumps(pm["videos"])

                # 2. Images: Download them and save the local file paths
                local_images = []
                for idx, img_url in enumerate(pm["images"]):
                    filename = f"{code}_{idx}.jpg"
                    filepath = os.path.join(img_dir, filename)

                    # Only download if we haven't saved it previously
                    if not os.path.exists(filepath):
                        try:
                            # Add user-agent to avoid 403 Forbidden from Google
                            req = urllib.request.Request(
                                img_url, headers={"User-Agent": "Mozilla/5.0"}
                            )
                            with (
                                urllib.request.urlopen(req, timeout=10) as response,
                                open(filepath, "wb") as out_file,
                            ):
                                out_file.write(response.read())
                        except Exception as e:
                            print(f"[sync] Erreur de téléchargement pour {code}: {e}")
                            continue

                    local_images.append(f"images/plaques/{filename}")

                if local_images:
                    q_obj.media_images = json.dumps(local_images)

                # Print log for this specific question
                print(
                    f"[sync] 🖼️  code={code}: {len(local_images)} image(s), {len(pm['videos'])} video(s)"
                )
        else:
            unmatched.append(pm["name"])

    # Commit all media updates to the database
    db.session.commit()

    if new_coords:
        PLAQUE_COORDS.update(new_coords)

    if unmatched:
        print(f"[sync] ⚠️  Non matchés : {', '.join(unmatched)}")

    msg = f"{len(new_coords)} coordonnées synchronisées depuis Google My Maps."
    if unmatched:
        msg += f" ({len(unmatched)} placemarks non matchés)"
    print(f"[sync] ✅ {msg}")
    return len(new_coords), msg
