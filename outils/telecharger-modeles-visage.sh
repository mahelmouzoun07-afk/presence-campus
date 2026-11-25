#!/usr/bin/env bash
# Télécharge les deux modèles libres de reconnaissance du visage (OpenCV Zoo) :
#   YuNet (détection, licence MIT) et SFace (comparaison, licence Apache 2.0).
# Ils sont rangés dans school_attendance_qr/face_models/ (ignoré par Git).
# Lancer une fois sur le serveur de l'école :  bash outils/telecharger-modeles-visage.sh
set -euo pipefail
DEST="$(cd "$(dirname "$0")/.." && pwd)/school_attendance_qr/face_models"
mkdir -p "$DEST"
BASE="https://github.com/opencv/opencv_zoo/raw/main/models"
curl -fL --retry 3 -o "$DEST/face_detection_yunet_2023mar.onnx" "$BASE/face_detection_yunet/face_detection_yunet_2023mar.onnx"
curl -fL --retry 3 -o "$DEST/face_recognition_sface_2021dec.onnx" "$BASE/face_recognition_sface/face_recognition_sface_2021dec.onnx"
ls -lh "$DEST"
echo "Terminé. Installer aussi OpenCV :  python -m pip install opencv-python-headless"
