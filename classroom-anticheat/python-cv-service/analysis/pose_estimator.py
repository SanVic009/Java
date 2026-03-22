"""
Face-first head pose and gaze estimation with robust fallbacks.
"""
from __future__ import annotations

import mediapipe as mp
import numpy as np
import cv2
import torch
from pathlib import Path
from typing import Optional, Tuple, Dict, List, Any
from dataclasses import dataclass

from config import config


def _resolve_model_path(model_name: str) -> str:
    candidates = [
        Path(__file__).resolve().parents[1] / model_name,
        Path(__file__).resolve().parents[1] / "models" / model_name,
        Path.cwd() / model_name,
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            return str(p)
    return model_name


@dataclass
class PoseEstimate:
    """Head pose and gaze estimation result."""
    yaw: float  # Head rotation left/right (degrees)
    pitch: float  # Head rotation up/down (degrees)
    roll: float  # Head tilt (degrees)
    gaze_x: float  # Normalized gaze direction x (-1 to 1)
    gaze_y: float  # Normalized gaze direction y (-1 to 1)
    landmark_visibility: float  # 0..1
    head_pose_confidence: float  # 0..1
    gaze_reliability: float  # 0..1
    confidence: float  # combined 0..1
    pose_keypoints_2d: List[List[float]]  # 2D points used for PnP (crop-local pixels)
    face_visible: bool  # face detector indicates visible face
    estimation_mode: str  # mediapipe_face_crop | profile_face_detected | coarse_face_fallback | body_pose_landmarks | bbox_proxy_face_not_visible
    face_detect_confidence: float  # 0..1
    bbox_aspect_ratio: float  # width / height of person bbox
    bbox_orientation_deg: float  # coarse orientation proxy from bbox/crop


class PoseEstimator:
    """
    Face-detection-first pose estimator.

    Strategy:
    1) Detect face in person crop (YuNet when available, otherwise Haar fallback).
    2) If face is detected and large enough, run MediaPipe Face Mesh on face crop.
    3) If Face Mesh fails, use detector-guided coarse pose.
    4) If no face visible, emit bbox-orientation proxy pose (low confidence) instead of None.
    """
    
    # Key face mesh landmark indices
    NOSE_TIP = 1
    CHIN = 152
    LEFT_EYE_LEFT = 33
    LEFT_EYE_RIGHT = 133
    RIGHT_EYE_LEFT = 362
    RIGHT_EYE_RIGHT = 263
    LEFT_MOUTH = 61
    RIGHT_MOUTH = 291
    
    # Iris landmarks (for gaze)
    LEFT_IRIS = [468, 469, 470, 471, 472]
    RIGHT_IRIS = [473, 474, 475, 476, 477]
    
    def __init__(self, max_faces: int = 1, min_detection_confidence: float = 0.5):
        """
        Initialize pose estimator.
        
        Args:
            max_faces: Maximum faces to detect per crop
            min_detection_confidence: Minimum detection confidence
        """
        self.mp_face_mesh = mp.solutions.face_mesh
        self._frame_width: int = 0
        self._frame_height: int = 0
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            max_num_faces=max_faces,
            static_image_mode=True,
            refine_landmarks=True,  # Enable iris landmarks
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_detection_confidence
        )
        # YOLOv8-pose: multi-person keypoint detection in one call
        # Replaces MediaPipe Pose which only returns one skeleton per image
        from ultralytics import YOLO as _YOLO
        try:
            from ultralytics.nn.tasks import PoseModel
            if hasattr(np, "__version__") and hasattr(__import__("torch").serialization, "add_safe_globals"):
                __import__("torch").serialization.add_safe_globals([PoseModel])
        except Exception:
            pass
        _pose_model_path = _resolve_model_path("yolov8m-pose.pt")
        self.yolo_pose = _YOLO(_pose_model_path)
        self.yolo_device = 0 if torch.cuda.is_available() else "cpu"
        print(f"[PoseEstimator] YOLOv8-pose loaded for body landmark estimation (device={self.yolo_device})")

        self.min_face_crop_px = int(getattr(config, "MIN_FACE_CROP_PX", 35))
        self._face_detector, self._face_detector_name = self._init_face_detector()
        self._haar = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        self._haar_profile = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_profileface.xml"
        )
        
        # 3D model points for pose estimation (generic face model)
        self.model_points = np.array([
            (0.0, 0.0, 0.0),          # Nose tip
            (0.0, -330.0, -65.0),     # Chin
            (-225.0, 170.0, -135.0),  # Left eye left corner
            (225.0, 170.0, -135.0),   # Right eye right corner
            (-150.0, -150.0, -125.0), # Left mouth corner
            (150.0, -150.0, -125.0)   # Right mouth corner
        ], dtype=np.float64)
        
        print(f"[PoseEstimator] Initialized (detector={self._face_detector_name}, min_face_crop_px={self.min_face_crop_px})")
        print("[PoseEstimator] Body pose estimator initialized (YOLOv8-pose)")
    
    def estimate(
        self, 
        frame: np.ndarray, 
        bbox: Tuple[int, int, int, int],
        detection_confidence: float = 0.0,
        pose_result_cache=None,
    ) -> Optional[PoseEstimate]:
        """
        Estimate head pose and gaze for a person in the frame.
        
        Args:
            frame: Full BGR frame
            bbox: Person bounding box (x1, y1, x2, y2)
            
        Returns:
            PoseEstimate or None if crop is invalid.
        """
        self._frame_width = int(frame.shape[1])
        self._frame_height = int(frame.shape[0])

        x1, y1, x2, y2 = bbox
        
        # Expand bbox slightly for better face detection
        h, w = frame.shape[:2]
        pad_x = int((x2 - x1) * 0.1)
        pad_y = int((y2 - y1) * 0.1)
        
        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(w, x2 + pad_x)
        y2 = min(h, y2 + pad_y)
        
        # Crop person region
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None

        crop_h, crop_w = crop.shape[:2]
        bbox_aspect_ratio = float(crop_w / max(crop_h, 1))
        bbox_orientation_deg = self._estimate_bbox_orientation_deg(crop)

        face = self._detect_face(crop)
        if face is not None:
            fx, fy, fw, fh = face["bbox"]
            face_conf = float(face.get("confidence", 0.0))
            keypoints = face.get("keypoints", {})

            if bool(face.get("is_profile", False)):
                return self._profile_pose_from_detection(
                    fw=fw,
                    fh=fh,
                    detect_conf=face_conf,
                    yaw_sign=float(face.get("profile_yaw_sign", 1.0)),
                    bbox_aspect_ratio=bbox_aspect_ratio,
                    bbox_orientation_deg=bbox_orientation_deg,
                )

            if min(fw, fh) >= self.min_face_crop_px:
                # Run MediaPipe only on confirmed face region.
                face_crop = crop[fy:fy + fh, fx:fx + fw]
                if face_crop.size > 0:
                    rgb_face = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)
                    results = self.face_mesh.process(rgb_face)
                    if results.multi_face_landmarks:
                        landmarks = results.multi_face_landmarks[0]
                        image_points_face = self._get_image_points(landmarks, fw, fh)

                        # Convert keypoints to person-crop coordinates.
                        image_points_crop = image_points_face.copy()
                        image_points_crop[:, 0] += float(fx)
                        image_points_crop[:, 1] += float(fy)
                        pose_keypoints_2d = [[float(p[0]), float(p[1])] for p in image_points_crop]

                        landmark_visibility = self._compute_landmark_visibility(landmarks)
                        yaw, pitch, roll, head_pose_confidence = self._estimate_pose(
                            image_points_face, fw, fh
                        )
                        gaze_x, gaze_y, gaze_reliability = self._estimate_gaze(landmarks, fw, fh)

                        confidence = self._combine_confidences(
                            landmark_visibility,
                            head_pose_confidence,
                            gaze_reliability,
                            mode="mediapipe_face_crop",
                        )

                        return PoseEstimate(
                            yaw=yaw,
                            pitch=pitch,
                            roll=roll,
                            gaze_x=gaze_x,
                            gaze_y=gaze_y,
                            landmark_visibility=landmark_visibility,
                            head_pose_confidence=head_pose_confidence,
                            gaze_reliability=gaze_reliability,
                            confidence=confidence,
                            pose_keypoints_2d=pose_keypoints_2d,
                            face_visible=True,
                            estimation_mode="mediapipe_face_crop",
                            face_detect_confidence=face_conf,
                            bbox_aspect_ratio=bbox_aspect_ratio,
                            bbox_orientation_deg=bbox_orientation_deg,
                        )

            # Face found but MediaPipe unavailable/failed or face too small => coarse face-based fallback.
            return self._coarse_pose_from_face(
                fx=fx,
                fy=fy,
                fw=fw,
                fh=fh,
                keypoints=keypoints,
                detect_conf=face_conf,
                bbox_aspect_ratio=bbox_aspect_ratio,
                bbox_orientation_deg=bbox_orientation_deg,
            )

        # No face found.
        # Try MediaPipe Pose body landmarks first — works for seated students looking down.
        if float(detection_confidence) >= float(getattr(config, "MIN_TRACK_CONFIDENCE", 0.35)):
            body_est = self._estimate_from_body_landmarks(
                pose_result=pose_result_cache,
                bbox=bbox,
                bbox_aspect_ratio=bbox_aspect_ratio,
                bbox_orientation_deg=bbox_orientation_deg,
            )
            if body_est is not None:
                return body_est

        # bbox proxy is unconditional — always fires as last resort.
        # _coarse_pose_from_bbox only needs crop dimensions, not detection confidence.
        return self._coarse_pose_from_bbox(
            bbox_w=crop_w,
            bbox_h=crop_h,
            detect_conf=float(detection_confidence),
            bbox_aspect_ratio=bbox_aspect_ratio,
            bbox_orientation_deg=bbox_orientation_deg,
        )

    def run_yolo_pose(self, frame: np.ndarray):
        """Run YOLOv8-pose on the full frame once. Cache and reuse per frame."""
        try:
            results = self.yolo_pose(frame, verbose=False, conf=0.3, device=self.yolo_device)
            return results[0] if results else None
        except Exception:
            return None

    def _init_face_detector(self):
        """Initialize YuNet when model exists; fallback is handled separately."""
        if not hasattr(cv2, "FaceDetectorYN_create"):
            return None, "haar"

        candidates = [
            Path(__file__).resolve().parents[1] / "models" / "face_detection_yunet_2023mar.onnx",
            Path(__file__).resolve().parents[1] / "face_detection_yunet_2023mar.onnx",
            Path.cwd() / "face_detection_yunet_2023mar.onnx",
        ]
        for model_path in candidates:
            if model_path.exists():
                try:
                    detector = cv2.FaceDetectorYN_create(
                        str(model_path),
                        "",
                        (320, 320),
                        0.6,
                        0.3,
                        5000,
                    )
                    return detector, "yunet"
                except Exception:
                    continue
        return None, "haar"

    def _detect_face(self, crop: np.ndarray) -> Optional[Dict[str, Any]]:
        """
        Detect face in person crop.

        Returns dict with bbox=(x,y,w,h), keypoints, confidence in crop coordinates.
        """
        h, w = crop.shape[:2]
        if h <= 0 or w <= 0:
            return None

        if self._face_detector is not None and self._face_detector_name == "yunet":
            try:
                self._face_detector.setInputSize((w, h))
                _, faces = self._face_detector.detect(crop)
                if faces is not None and len(faces) > 0:
                    # Format: [x,y,w,h, l_eye_x,l_eye_y, r_eye_x,r_eye_y, nose_x,nose_y, l_mouth_x,l_mouth_y, r_mouth_x,r_mouth_y, score]
                    best = max(faces, key=lambda row: float(row[14]))
                    x, y, fw, fh = [int(v) for v in best[:4]]
                    x = max(0, x)
                    y = max(0, y)
                    fw = max(1, min(int(fw), w - x))
                    fh = max(1, min(int(fh), h - y))
                    return {
                        "bbox": (x, y, fw, fh),
                        "confidence": float(best[14]),
                        "keypoints": {
                            "left_eye": (float(best[4]), float(best[5])),
                            "right_eye": (float(best[6]), float(best[7])),
                            "nose": (float(best[8]), float(best[9])),
                            "left_mouth": (float(best[10]), float(best[11])),
                            "right_mouth": (float(best[12]), float(best[13])),
                        },
                    }
            except Exception:
                # Fallback to Haar below
                pass

        # Haar fallback (no explicit confidence/keypoints from detector).
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        faces = self._haar.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(25, 25))
        if len(faces) > 0:
            # Choose largest face candidate.
            x, y, fw, fh = max(faces, key=lambda b: int(b[2] * b[3]))
            x = int(max(0, x))
            y = int(max(0, y))
            fw = int(max(1, min(fw, w - x)))
            fh = int(max(1, min(fh, h - y)))
            if fw / max(fh, 1) >= 0.6 and fw / max(fh, 1) <= 1.4:
                return {
                    "bbox": (x, y, fw, fh),
                    "confidence": 0.55,
                    "keypoints": {
                        "left_eye": (x + 0.35 * fw, y + 0.42 * fh),
                        "right_eye": (x + 0.65 * fw, y + 0.42 * fh),
                        "nose": (x + 0.50 * fw, y + 0.56 * fh),
                        "left_mouth": (x + 0.40 * fw, y + 0.72 * fh),
                        "right_mouth": (x + 0.60 * fw, y + 0.72 * fh),
                    },
                }

        # Profile fallback: detect left/right profile via original+flipped crop.
        for flip, sign in [(False, 1.0), (True, -1.0)]:
            img = cv2.flip(gray, 1) if flip else gray
            faces = self._haar_profile.detectMultiScale(
                img,
                scaleFactor=1.1,
                minNeighbors=4,
                minSize=(20, 20),
            )
            if len(faces) == 0:
                continue

            x, y, fw, fh = max(faces, key=lambda b: int(b[2] * b[3]))
            if fw / max(fh, 1) > 1.2:
                continue

            if flip:
                x = int(w - (x + fw))

            x = int(max(0, x))
            y = int(max(0, y))
            fw = int(max(1, min(fw, w - x)))
            fh = int(max(1, min(fh, h - y)))

            eye_x = float(x + fw * 0.55)
            eye_y = float(y + fh * 0.38)
            return {
                "bbox": (x, y, fw, fh),
                "confidence": 0.52,
                "is_profile": True,
                "profile_yaw_sign": float(sign),
                "keypoints": {
                    "left_eye": (eye_x, eye_y),
                    "right_eye": (eye_x, eye_y),
                    "nose": (float(x + fw * 0.80), float(y + fh * 0.55)),
                    "left_mouth": (float(x + fw * 0.70), float(y + fh * 0.75)),
                    "right_mouth": (float(x + fw * 0.80), float(y + fh * 0.75)),
                },
            }

        return None

    def _profile_pose_from_detection(
        self,
        fw: int,
        fh: int,
        detect_conf: float,
        yaw_sign: float,
        bbox_aspect_ratio: float,
        bbox_orientation_deg: float,
    ) -> PoseEstimate:
        """
        Pose estimate when a profile face is detected.
        """
        yaw = float(yaw_sign * 75.0)
        pitch = 0.0
        roll = 0.0

        size_conf = float(np.clip(min(fw, fh) / float(max(self.min_face_crop_px, 1) * 2), 0.0, 1.0))
        head_pose_confidence = float(np.clip(0.50 + 0.30 * detect_conf + 0.20 * size_conf, 0.0, 0.85))
        landmark_visibility = float(np.clip(0.55 + 0.30 * size_conf, 0.0, 0.85))
        gaze_reliability = 0.20

        gaze_x = float(yaw_sign * 1.0)
        gaze_y = 0.0

        confidence = self._combine_confidences(
            landmark_visibility,
            head_pose_confidence,
            gaze_reliability,
            mode="coarse_face_fallback",
        )

        return PoseEstimate(
            yaw=yaw,
            pitch=pitch,
            roll=roll,
            gaze_x=gaze_x,
            gaze_y=gaze_y,
            landmark_visibility=landmark_visibility,
            head_pose_confidence=head_pose_confidence,
            gaze_reliability=gaze_reliability,
            confidence=confidence,
            pose_keypoints_2d=[],
            face_visible=True,
            estimation_mode="profile_face_detected",
            face_detect_confidence=float(np.clip(detect_conf, 0.0, 1.0)),
            bbox_aspect_ratio=float(bbox_aspect_ratio),
            bbox_orientation_deg=float(bbox_orientation_deg),
        )

    def _estimate_from_body_landmarks(
        self,
        pose_result,
        bbox: Tuple[int, int, int, int],
        bbox_aspect_ratio: float,
        bbox_orientation_deg: float,
    ) -> Optional[PoseEstimate]:
        """
        Estimate head direction using YOLOv8-pose keypoints.

        YOLOv8-pose detects all people simultaneously and returns per-person
        keypoints already matched to their bounding box. We find the detected
        person whose bounding box best overlaps with the target YOLO track bbox.

        COCO keypoint indices used:
            0  = nose
            3  = left ear
            4  = right ear
            5  = left shoulder
            6  = right shoulder
        """
        if pose_result is None:
            return None
        result = pose_result
        if result.keypoints is None or result.keypoints.xy is None:
            return None

        kp_xy = result.keypoints.xy.cpu().numpy()  # shape: (N, 17, 2)
        kp_vis = result.keypoints.conf             # shape: (N, 17) or None
        boxes = result.boxes.xyxy.cpu().numpy()    # shape: (N, 4)

        if kp_xy.shape[0] == 0:
            return None

        x1, y1, x2, y2 = bbox

        def _iou(a, b):
            ix1 = max(a[0], b[0]); iy1 = max(a[1], b[1])
            ix2 = min(a[2], b[2]); iy2 = min(a[3], b[3])
            inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
            area_a = (a[2] - a[0]) * (a[3] - a[1])
            area_b = (b[2] - b[0]) * (b[3] - b[1])
            union = area_a + area_b - inter
            return inter / union if union > 0 else 0.0

        target = [x1, y1, x2, y2]
        best_idx = -1
        best_iou = 0.15

        for i, box in enumerate(boxes):
            iou = _iou(target, box)
            if iou > best_iou:
                best_iou = iou
                best_idx = i

        if best_idx < 0:
            return None

        kps = kp_xy[best_idx]

        NOSE = 0
        L_EAR = 3
        R_EAR = 4
        L_SHLDR = 5
        R_SHLDR = 6

        if kp_vis is not None:
            vis = kp_vis.cpu().numpy()[best_idx]
        else:
            vis = np.ones(17, dtype=np.float32)

        MIN_VIS = 0.3
        if vis[L_SHLDR] < MIN_VIS or vis[R_SHLDR] < MIN_VIS:
            return None
        if vis[NOSE] < MIN_VIS:
            return None

        if kps[NOSE][0] == 0 and kps[NOSE][1] == 0:
            return None
        if kps[L_SHLDR][0] == 0 or kps[R_SHLDR][0] == 0:
            return None

        nose_x = float(kps[NOSE][0])
        nose_y = float(kps[NOSE][1])
        l_shldr_x = float(kps[L_SHLDR][0])
        l_shldr_y = float(kps[L_SHLDR][1])
        r_shldr_x = float(kps[R_SHLDR][0])
        r_shldr_y = float(kps[R_SHLDR][1])

        shldr_mid_x = (l_shldr_x + r_shldr_x) / 2.0
        shldr_mid_y = (l_shldr_y + r_shldr_y) / 2.0

        shldr_width = abs(r_shldr_x - l_shldr_x)
        if shldr_width < 5.0:
            return None

        lateral_offset = (nose_x - shldr_mid_x) / (shldr_width * 0.5 + 1e-6)
        yaw = float(np.clip(
            lateral_offset * float(getattr(config, "BODY_POSE_YAW_SCALE_DEG", 35.0)),
            -75.0,
            75.0,
        ))

        expected_head_height = shldr_width * 0.8
        vertical_offset = (shldr_mid_y - nose_y) / (expected_head_height + 1e-6)
        pitch = float(np.clip(vertical_offset * 30.0, -60.0, 30.0))

        shldr_angle_rad = np.arctan2(r_shldr_y - l_shldr_y, r_shldr_x - l_shldr_x)
        roll = float(np.degrees(shldr_angle_rad))

        l_ear_vis = float(vis[L_EAR])
        r_ear_vis = float(vis[R_EAR])
        nose_vis = float(vis[NOSE])
        shldr_vis = float((vis[L_SHLDR] + vis[R_SHLDR]) / 2.0)

        max_ear_vis = max(l_ear_vis, r_ear_vis)
        head_pose_confidence = float(np.clip(
            0.4 * nose_vis + 0.4 * max_ear_vis + 0.2 * shldr_vis,
            0.0,
            0.80,
        ))
        landmark_visibility = float(np.clip(
            0.5 * nose_vis + 0.3 * max_ear_vis + 0.2 * shldr_vis,
            0.0,
            0.85,
        ))

        gaze_reliability = 0.0
        gaze_x = 0.0
        gaze_y = 0.0

        confidence = self._combine_confidences(
            landmark_visibility,
            head_pose_confidence,
            gaze_reliability,
            mode="body_pose_landmarks",
        )

        return PoseEstimate(
            yaw=yaw,
            pitch=pitch,
            roll=roll,
            gaze_x=gaze_x,
            gaze_y=gaze_y,
            landmark_visibility=landmark_visibility,
            head_pose_confidence=head_pose_confidence,
            gaze_reliability=gaze_reliability,
            confidence=confidence,
            pose_keypoints_2d=[
                [nose_x, nose_y],
                [l_shldr_x, l_shldr_y],
                [r_shldr_x, r_shldr_y],
            ],
            face_visible=False,
            estimation_mode="body_pose_landmarks",
            face_detect_confidence=0.0,
            bbox_aspect_ratio=bbox_aspect_ratio,
            bbox_orientation_deg=bbox_orientation_deg,
        )

    def _coarse_pose_from_face(
        self,
        fx: int,
        fy: int,
        fw: int,
        fh: int,
        keypoints: Dict[str, Tuple[float, float]],
        detect_conf: float,
        bbox_aspect_ratio: float,
        bbox_orientation_deg: float,
    ) -> PoseEstimate:
        """Coarse pose estimate when face is detected but MediaPipe fails or is skipped."""
        left_eye = keypoints.get("left_eye")
        right_eye = keypoints.get("right_eye")
        nose = keypoints.get("nose")

        yaw = 0.0
        pitch = 0.0
        roll = 0.0

        if left_eye is not None and right_eye is not None:
            eye_dx = float(right_eye[0] - left_eye[0])
            eye_dy = float(right_eye[1] - left_eye[1])
            roll = float(np.degrees(np.arctan2(eye_dy, eye_dx)))
            eye_mid_x = 0.5 * (left_eye[0] + right_eye[0])
            eye_mid_y = 0.5 * (left_eye[1] + right_eye[1])

            if nose is not None:
                half_eye_span = max(abs(eye_dx) * 0.5, 1.0)
                yaw = float(np.clip(((nose[0] - eye_mid_x) / half_eye_span) * 45.0, -60.0, 60.0))
                pitch = float(np.clip(((nose[1] - eye_mid_y) / max(fh * 0.35, 1.0)) * 30.0, -40.0, 40.0))
            else:
                yaw = float(np.clip((fw / max(fh, 1) - 0.75) * 60.0, -45.0, 45.0))
                pitch = float(np.clip((0.42 - eye_mid_y / max(fh, 1)) * 35.0, -35.0, 35.0))
        else:
            yaw = float(np.clip((fw / max(fh, 1) - 0.75) * 60.0, -45.0, 45.0))
            pitch = 0.0

        min_face_side = float(min(fw, fh))
        size_conf = float(np.clip(min_face_side / float(max(self.min_face_crop_px, 1) * 2), 0.0, 1.0))

        head_pose_confidence = float(np.clip(0.30 + 0.40 * detect_conf + 0.30 * size_conf, 0.0, 0.85))
        landmark_visibility = float(np.clip(0.45 + 0.40 * size_conf, 0.0, 0.90))
        gaze_reliability = float(np.clip(0.45 + 0.35 * detect_conf, 0.0, 0.85))

        gaze_x = float(np.clip(yaw / 55.0, -1.0, 1.0))
        gaze_y = float(np.clip(pitch / 40.0, -1.0, 1.0))

        confidence = self._combine_confidences(
            landmark_visibility,
            head_pose_confidence,
            gaze_reliability,
            mode="coarse_face_fallback",
        )

        pose_keypoints_2d = []
        for k in ["left_eye", "right_eye", "nose", "left_mouth", "right_mouth"]:
            if k in keypoints:
                pose_keypoints_2d.append([float(keypoints[k][0]), float(keypoints[k][1])])

        return PoseEstimate(
            yaw=yaw,
            pitch=pitch,
            roll=roll,
            gaze_x=gaze_x,
            gaze_y=gaze_y,
            landmark_visibility=landmark_visibility,
            head_pose_confidence=head_pose_confidence,
            gaze_reliability=gaze_reliability,
            confidence=confidence,
            pose_keypoints_2d=pose_keypoints_2d,
            face_visible=True,
            estimation_mode="coarse_face_fallback",
            face_detect_confidence=float(np.clip(detect_conf, 0.0, 1.0)),
            bbox_aspect_ratio=float(bbox_aspect_ratio),
            bbox_orientation_deg=float(bbox_orientation_deg),
        )

    def _coarse_pose_from_bbox(
        self,
        bbox_w: int,
        bbox_h: int,
        detect_conf: float,
        bbox_aspect_ratio: float,
        bbox_orientation_deg: float,
    ) -> PoseEstimate:
        """Coarse proxy pose when face is not visible."""
        # Proxy for side turn from person box elongation.
        yaw = float(np.clip((bbox_aspect_ratio - 0.45) * 90.0, -40.0, 40.0))
        roll = float(np.clip(bbox_orientation_deg, -45.0, 45.0))
        pitch = float(np.clip(-0.25 * bbox_orientation_deg, -25.0, 25.0))

        # Keep low-but-usable confidence so Phase 2 can down-weight rather than drop all frames.
        size_conf = float(np.clip(min(bbox_w, bbox_h) / float(max(self.min_face_crop_px, 1) * 4), 0.0, 1.0))
        head_pose_confidence = float(np.clip(0.35 + 0.25 * detect_conf + 0.20 * size_conf, 0.0, 0.70))
        landmark_visibility = float(np.clip(0.50 + 0.20 * size_conf, 0.0, 0.75))
        gaze_reliability = 0.30

        gaze_x = 0.0
        gaze_y = 0.0

        confidence = self._combine_confidences(
            landmark_visibility,
            head_pose_confidence,
            gaze_reliability,
            mode="bbox_proxy_face_not_visible",
        )

        return PoseEstimate(
            yaw=yaw,
            pitch=pitch,
            roll=roll,
            gaze_x=gaze_x,
            gaze_y=gaze_y,
            landmark_visibility=landmark_visibility,
            head_pose_confidence=head_pose_confidence,
            gaze_reliability=gaze_reliability,
            confidence=confidence,
            pose_keypoints_2d=[],
            face_visible=False,
            estimation_mode="bbox_proxy_face_not_visible",
            face_detect_confidence=0.0,
            bbox_aspect_ratio=float(bbox_aspect_ratio),
            bbox_orientation_deg=float(bbox_orientation_deg),
        )

    def _estimate_bbox_orientation_deg(self, crop: np.ndarray) -> float:
        """
        Approximate orientation using edge-point PCA in person crop.
        Returns angle in degrees in [-90, 90].
        """
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        ys, xs = np.where(edges > 0)
        if len(xs) < 20:
            return 0.0
        pts = np.column_stack((xs.astype(np.float64), ys.astype(np.float64)))
        pts -= pts.mean(axis=0, keepdims=True)
        cov = np.cov(pts.T)
        vals, vecs = np.linalg.eigh(cov)
        principal = vecs[:, int(np.argmax(vals))]
        angle = float(np.degrees(np.arctan2(principal[1], principal[0])))
        while angle > 90.0:
            angle -= 180.0
        while angle < -90.0:
            angle += 180.0
        return angle

    def _combine_confidences(
        self,
        landmark_visibility: float,
        head_pose_confidence: float,
        gaze_reliability: float,
        mode: str,
    ) -> float:
        """
        Combined confidence used by Phase 2 quality gates.

        Use weighted average instead of strict product so useful coarse estimates
        are retained with lower confidence rather than collapsing to zero.
        """
        base = (
            0.45 * float(head_pose_confidence)
            + 0.30 * float(landmark_visibility)
            + 0.25 * float(gaze_reliability)
        )
        if mode == "coarse_face_fallback":
            base *= 0.88
        elif mode == "bbox_proxy_face_not_visible":
            base *= 0.82
        elif mode == "body_pose_landmarks":
            base *= 0.92
        return float(np.clip(base, 0.0, 1.0))
    
    def _compute_landmark_visibility(self, landmarks) -> float:
        """
        Compute a visibility score from landmarks when available.

        MediaPipe's FaceMesh may or may not provide `visibility` per landmark depending
        on runtime/version; this is therefore best-effort.
        """
        vis: List[float] = []
        geo_valid = 0
        total = 0
        for idx in [
            self.NOSE_TIP,
            self.CHIN,
            self.LEFT_EYE_LEFT,
            self.LEFT_EYE_RIGHT,
            self.RIGHT_EYE_LEFT,
            self.RIGHT_EYE_RIGHT,
            self.LEFT_MOUTH,
            self.RIGHT_MOUTH,
        ]:
            lm = landmarks.landmark[idx]
            total += 1
            if not np.isfinite(lm.x) or not np.isfinite(lm.y):
                continue
            if lm.x < 0.0 or lm.x > 1.0 or lm.y < 0.0 or lm.y > 1.0:
                continue
            geo_valid += 1
            v = getattr(lm, "visibility", None)
            if v is not None and float(v) > 0.0:
                vis.append(float(np.clip(v, 0.0, 1.0)))

        # If visibility values are unavailable/invalid, fallback to geometric validity.
        if vis:
            return float(np.clip(np.mean(vis), 0.0, 1.0))
        if total <= 0:
            return 0.0
        return float(np.clip(geo_valid / float(total), 0.0, 1.0))

    def _get_image_points(
        self, 
        landmarks, 
        width: int, 
        height: int
    ) -> np.ndarray:
        """Extract 2D image points from landmarks."""
        points = []
        indices = [
            self.NOSE_TIP, self.CHIN,
            self.LEFT_EYE_LEFT, self.RIGHT_EYE_RIGHT,
            self.LEFT_MOUTH, self.RIGHT_MOUTH
        ]
        
        for idx in indices:
            lm = landmarks.landmark[idx]
            points.append((lm.x * width, lm.y * height))
        
        return np.array(points, dtype=np.float64)
    
    def _estimate_pose(
        self, 
        image_points: np.ndarray,
        width: int,
        height: int
    ) -> Tuple[float, float, float, float]:
        """Estimate yaw, pitch, roll from image points."""
        # Camera matrix approximation: use full-frame width as focal length.
        focal_length = float(self._frame_width) if self._frame_width > 0 else float(width * 16)
        center = (width / 2, height / 2)
        camera_matrix = np.array([
            [focal_length, 0, center[0]],
            [0, focal_length, center[1]],
            [0, 0, 1]
        ], dtype=np.float64)
        
        dist_coeffs = np.zeros((4, 1))
        
        # Solve PnP
        success, rotation_vec, translation_vec = cv2.solvePnP(
            self.model_points,
            image_points,
            camera_matrix,
            dist_coeffs,
            flags=cv2.SOLVEPNP_ITERATIVE
        )
        
        if not success:
            return 0.0, 0.0, 0.0, 0.0
        
        # Convert rotation vector to rotation matrix
        rotation_mat, _ = cv2.Rodrigues(rotation_vec)
        
        # Get Euler angles
        pose_mat = cv2.hconcat((rotation_mat, translation_vec))
        _, _, _, _, _, _, euler_angles = cv2.decomposeProjectionMatrix(pose_mat)
        
        pitch = float(euler_angles[0])
        yaw = float(euler_angles[1])
        roll = float(euler_angles[2])
        yaw = -yaw
        
        # Confidence based on reprojection error: smaller error => higher confidence.
        projected, _ = cv2.projectPoints(
            self.model_points,
            rotation_vec,
            translation_vec,
            camera_matrix,
            dist_coeffs
        )
        projected = projected.reshape(-1, 2)
        err = np.linalg.norm(projected - image_points, axis=1).mean()  # pixels
        # Map reprojection error to confidence with an explicit 8px operating point:
        # err < 8px => confidence > 0.5
        head_pose_confidence = float(np.clip(1.0 / (1.0 + (err / 8.0)), 0.0, 1.0))
        
        return yaw, pitch, roll, head_pose_confidence
    
    def _estimate_gaze(
        self, 
        landmarks, 
        width: int, 
        height: int
    ) -> Tuple[float, float, float]:
        """
        Estimate gaze direction from iris landmarks.
        Returns normalized gaze offset from eye center.
        """
        try:
            # Get left eye bounds
            left_eye_inner = landmarks.landmark[self.LEFT_EYE_RIGHT]
            left_eye_outer = landmarks.landmark[self.LEFT_EYE_LEFT]
            left_eye_center_x = (left_eye_inner.x + left_eye_outer.x) / 2
            left_eye_width = abs(left_eye_inner.x - left_eye_outer.x)
            
            # Get left iris center
            left_iris_x = np.mean([landmarks.landmark[i].x for i in self.LEFT_IRIS])
            left_iris_y = np.mean([landmarks.landmark[i].y for i in self.LEFT_IRIS])
            
            # Get right eye bounds
            right_eye_inner = landmarks.landmark[self.RIGHT_EYE_LEFT]
            right_eye_outer = landmarks.landmark[self.RIGHT_EYE_RIGHT]
            right_eye_center_x = (right_eye_inner.x + right_eye_outer.x) / 2
            right_eye_width = abs(right_eye_inner.x - right_eye_outer.x)
            
            # Get right iris center
            right_iris_x = np.mean([landmarks.landmark[i].x for i in self.RIGHT_IRIS])
            right_iris_y = np.mean([landmarks.landmark[i].y for i in self.RIGHT_IRIS])

            # Tiny eye width means the face is too small for reliable iris tracking.
            MIN_EYE_WIDTH_NORMALIZED = 0.04
            if left_eye_width < MIN_EYE_WIDTH_NORMALIZED or right_eye_width < MIN_EYE_WIDTH_NORMALIZED:
                return 0.0, 0.0, 0.0
            
            # Calculate gaze offset (normalized by eye width)
            left_gaze_x = (left_iris_x - left_eye_center_x) / (left_eye_width + 1e-6)
            right_gaze_x = (right_iris_x - right_eye_center_x) / (right_eye_width + 1e-6)
            
            # Average gaze direction
            gaze_x = (left_gaze_x + right_gaze_x) / 2
            
            # Y gaze (simplified - using iris vertical position)
            eye_center_y = (left_eye_inner.y + right_eye_inner.y) / 2
            iris_center_y = (left_iris_y + right_iris_y) / 2
            gaze_y = iris_center_y - eye_center_y
            
            # Clamp to reasonable range
            gaze_x = max(
                -1.0,
                min(1.0, gaze_x * float(getattr(config, "GAZE_X_SCALE_FACTOR", 2.0))),
            )
            gaze_y = max(-1.0, min(1.0, gaze_y * 10))

            # Gaze reliability: left/right agreement + basic iris geometry sanity.
            agreement = 1.0 - (abs(left_gaze_x - right_gaze_x) / 2.0)
            iris_vertical_diff = abs(left_iris_y - right_iris_y)
            iris_present = float(np.clip(1.0 - (iris_vertical_diff / 0.05), 0.0, 1.0))
            gaze_reliability = float(
                np.clip(0.5 * agreement + 0.5 * iris_present, 0.0, 1.0)
            )
            return gaze_x, gaze_y, gaze_reliability
            
        except (IndexError, AttributeError):
            return 0.0, 0.0, 0.0
    
    def close(self):
        """Release resources."""
        self.face_mesh.close()
