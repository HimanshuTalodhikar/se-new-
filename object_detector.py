from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


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


class ObjectDetector:
    """OpenCV-only detector for production demos without external model downloads."""

    def __init__(self) -> None:
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        self.face_detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        self.previous_gray: np.ndarray | None = None

    def detect(self, frame: np.ndarray) -> tuple[list[dict[str, Any]], np.ndarray]:
        annotated = frame.copy()
        detections: list[Detection] = []

        detections.extend(self._detect_people(frame))
        detections.extend(self._detect_faces(frame))
        detections.extend(self._detect_motion(frame))

        for detection in detections:
            self._draw_detection(annotated, detection)

        return [detection.to_dict() for detection in detections], annotated

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
