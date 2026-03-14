"""
MediaPipe-based head pose and gaze estimation.
"""
import mediapipe as mp
import numpy as np
import cv2
from typing import Optional, Tuple, Dict, List
from dataclasses import dataclass


@dataclass
class PoseEstimate:
    """Head pose and gaze estimation result."""
    yaw: float  # Head rotation left/right (degrees)
    pitch: float  # Head rotation up/down (degrees)
    roll: float  # Head tilt (degrees)
    gaze_x: float  # Normalized gaze direction x (-1 to 1)
    gaze_y: float  # Normalized gaze direction y (-1 to 1)
    confidence: float


class PoseEstimator:
    """
    MediaPipe Face Mesh-based pose and gaze estimator.
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
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            max_num_faces=max_faces,
            refine_landmarks=True,  # Enable iris landmarks
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=0.5
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
        
        print("[PoseEstimator] Initialized MediaPipe Face Mesh")
    
    def estimate(
        self, 
        frame: np.ndarray, 
        bbox: Tuple[int, int, int, int]
    ) -> Optional[PoseEstimate]:
        """
        Estimate head pose and gaze for a person in the frame.
        
        Args:
            frame: Full BGR frame
            bbox: Person bounding box (x1, y1, x2, y2)
            
        Returns:
            PoseEstimate or None if face not detected
        """
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
        
        # Convert to RGB for MediaPipe
        rgb_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        
        # Process with Face Mesh
        results = self.face_mesh.process(rgb_crop)
        
        if not results.multi_face_landmarks:
            return None
        
        landmarks = results.multi_face_landmarks[0]
        crop_h, crop_w = crop.shape[:2]
        
        # Extract 2D image points
        image_points = self._get_image_points(landmarks, crop_w, crop_h)
        
        # Estimate head pose
        yaw, pitch, roll = self._estimate_pose(image_points, crop_w, crop_h)
        
        # Estimate gaze
        gaze_x, gaze_y = self._estimate_gaze(landmarks, crop_w, crop_h)
        
        return PoseEstimate(
            yaw=yaw,
            pitch=pitch,
            roll=roll,
            gaze_x=gaze_x,
            gaze_y=gaze_y,
            confidence=1.0  # Face mesh doesn't provide confidence
        )
    
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
    ) -> Tuple[float, float, float]:
        """Estimate yaw, pitch, roll from image points."""
        # Camera matrix (approximation)
        focal_length = width
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
            return 0.0, 0.0, 0.0
        
        # Convert rotation vector to rotation matrix
        rotation_mat, _ = cv2.Rodrigues(rotation_vec)
        
        # Get Euler angles
        pose_mat = cv2.hconcat((rotation_mat, translation_vec))
        _, _, _, _, _, _, euler_angles = cv2.decomposeProjectionMatrix(pose_mat)
        
        pitch = float(euler_angles[0])
        yaw = float(euler_angles[1])
        roll = float(euler_angles[2])
        
        return yaw, pitch, roll
    
    def _estimate_gaze(
        self, 
        landmarks, 
        width: int, 
        height: int
    ) -> Tuple[float, float]:
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
            gaze_x = max(-1.0, min(1.0, gaze_x * 3))  # Scale up for sensitivity
            gaze_y = max(-1.0, min(1.0, gaze_y * 10))
            
            return gaze_x, gaze_y
            
        except (IndexError, AttributeError):
            return 0.0, 0.0
    
    def close(self):
        """Release resources."""
        self.face_mesh.close()
