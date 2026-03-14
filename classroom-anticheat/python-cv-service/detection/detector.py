"""
YOLOv8-based person detection.
"""
from ultralytics import YOLO
import numpy as np
from typing import List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class Detection:
    """Single person detection result."""
    bbox: Tuple[int, int, int, int]  # x1, y1, x2, y2
    confidence: float
    centroid: Tuple[int, int]
    
    @classmethod
    def from_xyxy(cls, xyxy: np.ndarray, conf: float) -> 'Detection':
        x1, y1, x2, y2 = map(int, xyxy)
        centroid = ((x1 + x2) // 2, (y1 + y2) // 2)
        return cls(bbox=(x1, y1, x2, y2), confidence=conf, centroid=centroid)


class PersonDetector:
    """YOLOv8-based person detector."""
    
    PERSON_CLASS_ID = 0  # COCO class ID for person
    
    def __init__(self, model_name: str = "yolov8n.pt", confidence: float = 0.5):
        """
        Initialize detector with YOLOv8 model.
        
        Args:
            model_name: YOLOv8 model variant
            confidence: Minimum confidence threshold
        """
        self.model = YOLO(model_name)
        self.confidence = confidence
        print(f"[Detector] Loaded {model_name} with confidence threshold {confidence}")
    
    def detect(self, frame: np.ndarray) -> List[Detection]:
        """
        Detect persons in a frame.
        
        Args:
            frame: BGR image as numpy array
            
        Returns:
            List of Detection objects
        """
        results = self.model(frame, verbose=False, conf=self.confidence)
        
        detections = []
        for result in results:
            boxes = result.boxes
            for i in range(len(boxes)):
                cls_id = int(boxes.cls[i])
                if cls_id == self.PERSON_CLASS_ID:
                    xyxy = boxes.xyxy[i].cpu().numpy()
                    conf = float(boxes.conf[i])
                    detections.append(Detection.from_xyxy(xyxy, conf))
        
        return detections
    
    def detect_batch(self, frames: List[np.ndarray]) -> List[List[Detection]]:
        """
        Detect persons in multiple frames.
        
        Args:
            frames: List of BGR images
            
        Returns:
            List of detection lists per frame
        """
        return [self.detect(frame) for frame in frames]
