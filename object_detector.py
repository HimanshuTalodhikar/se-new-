from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import requests

from config import settings


@dataclass
class Detection:
    label: str
    confidence: float
    box: tuple[int, int, int, int]

    def to_dict(self) -> dict[str, Any]:
        x, y, width, height = self.box
        return {
            "label": self.label,
            "confidence": round(float(self.confidence), 3),
            "box": {"x": int(x), "y": int(y), "width": int(width), "height": int(height)},
        }


VOC_CLASSES = [
    "background",
    "aeroplane",
    "bicycle",
    "bird",
    "boat",
    "bottle",
    "bus",
    "car",
    "cat",
    "chair",
    "cow",
    "diningtable",
    "dog",
    "horse",
    "motorbike",
    "person",
    "pottedplant",
    "sheep",
    "sofa",
    "train",
    "tvmonitor",
]


class ObjectDetector:
    """OpenCV DNN detector with a lightweight classical OpenCV fallback."""

    def __init__(self) -> None:
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        self.face_detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        self.previous_gray: np.ndarray | None = None
        self.dnn = None
        self.backend = "opencv"
        if settings.object_detection_backend.lower() in {"auto", "dnn"}:
            self._load_dnn()

    def detect(self, frame: np.ndarray) -> tuple[list[dict[str, Any]], np.ndarray]:
        annotated = frame.copy()
        detections = self._detect_dnn(frame) if self.dnn is not None else []

        if not detections and settings.object_detection_backend.lower() != "dnn":
            detections.extend(self._detect_people(frame))
            detections.extend(self._detect_faces(frame))
            detections.extend(self._detect_motion(frame))

        for detection in detections:
            self._draw_detection(annotated, detection)

        return [detection.to_dict() for detection in detections], annotated

    def _load_dnn(self) -> None:
        try:
            prototxt_path = self._ensure_model_file("MobileNetSSD_deploy.prototxt", settings.dnn_prototxt_url)
            model_path = self._ensure_model_file("MobileNetSSD_deploy.caffemodel", settings.dnn_model_url)
            self.dnn = cv2.dnn.readNetFromCaffe(str(prototxt_path), str(model_path))
            self.backend = "dnn"
        except Exception:
            self.dnn = None
            self.backend = "opencv"

    def _ensure_model_file(self, filename: str, url: str) -> Path:
        path = settings.dnn_model_dir / filename
        if path.exists() and path.stat().st_size > 0:
            return path

        response = requests.get(url, timeout=30)
        response.raise_for_status()
        temporary_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        temporary_path.write_bytes(response.content)
        temporary_path.replace(path)
        return path

    def _detect_dnn(self, frame: np.ndarray) -> list[Detection]:
        if self.dnn is None:
            return []

        frame_height, frame_width = frame.shape[:2]
        blob = cv2.dnn.blobFromImage(cv2.resize(frame, (300, 300)), 0.007843, (300, 300), 127.5)
        self.dnn.setInput(blob)
        output = self.dnn.forward()
        detections: list[Detection] = []

        for index in range(output.shape[2]):
            confidence = float(output[0, 0, index, 2])
            if confidence < settings.object_confidence_threshold:
                continue
            class_id = int(output[0, 0, index, 1])
            x1, y1, x2, y2 = (output[0, 0, index, 3:7] * np.array([frame_width, frame_height, frame_width, frame_height])).astype("int")
            x1 = max(0, min(int(x1), frame_width - 1))
            y1 = max(0, min(int(y1), frame_height - 1))
            x2 = max(0, min(int(x2), frame_width - 1))
            y2 = max(0, min(int(y2), frame_height - 1))
            box_width = max(1, x2 - x1)
            box_height = max(1, y2 - y1)
            label = VOC_CLASSES[class_id] if class_id < len(VOC_CLASSES) else f"class_{class_id}"
            detections.append(Detection(label=label, confidence=confidence, box=(x1, y1, box_width, box_height)))
        return detections

    def _detect_people(self, frame: np.ndarray) -> list[Detection]:
        resized = cv2.resize(frame, (640, int(frame.shape[0] * 640 / frame.shape[1])))
        scale_x = frame.shape[1] / resized.shape[1]
        scale_y = frame.shape[0] / resized.shape[0]
        boxes, weights = self.hog.detectMultiScale(resized, winStride=(8, 8), padding=(8, 8), scale=1.05)
        detections = []
        for (x, y, width, height), weight in zip(boxes, weights):
            detections.append(
                Detection(
                    label="person",
                    confidence=float(weight),
                    box=(int(x * scale_x), int(y * scale_y), int(width * scale_x), int(height * scale_y)),
                )
            )
        return detections

    def _detect_faces(self, frame: np.ndarray) -> list[Detection]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.face_detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        return [Detection(label="face", confidence=0.85, box=(int(x), int(y), int(w), int(h))) for x, y, w, h in faces]

    def _detect_motion(self, frame: np.ndarray) -> list[Detection]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        if self.previous_gray is None:
            self.previous_gray = gray
            return []

        delta = cv2.absdiff(self.previous_gray, gray)
        self.previous_gray = gray
        threshold = cv2.threshold(delta, 25, 255, cv2.THRESH_BINARY)[1]
        threshold = cv2.dilate(threshold, None, iterations=2)
        contours, _ = cv2.findContours(threshold, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        detections = []
        frame_area = frame.shape[0] * frame.shape[1]
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < max(frame_area * 0.01, 900):
                continue
            x, y, width, height = cv2.boundingRect(contour)
            confidence = min(area / max(frame_area * 0.12, 1), 1.0)
            detections.append(Detection(label="motion", confidence=confidence, box=(x, y, width, height)))
        return detections[:8]

    def _draw_detection(self, frame: np.ndarray, detection: Detection) -> None:
        x, y, width, height = detection.box
        color = {"person": (66, 245, 138), "face": (76, 201, 240), "motion": (255, 190, 92)}.get(detection.label, (255, 255, 255))
        cv2.rectangle(frame, (x, y), (x + width, y + height), color, 2)
        label = f"{detection.label} {detection.confidence:.2f}"
        cv2.rectangle(frame, (x, max(0, y - 24)), (x + max(120, len(label) * 9), y), color, -1)
        cv2.putText(frame, label, (x + 6, max(16, y - 7)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (16, 20, 24), 1, cv2.LINE_AA)
