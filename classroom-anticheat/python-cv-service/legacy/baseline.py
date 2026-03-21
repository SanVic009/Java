"""
Baseline calibration for each student.
Computes baseline metrics during the first N seconds of the exam.
"""
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from config import config


@dataclass
class StudentBaseline:
    """Baseline metrics for a single student."""
    student_id: int
    baseline_yaw: float = 0.0
    baseline_gaze: float = 0.0
    yaw_std: float = 10.0  # Default if not enough data
    baseline_neighbor_distance: float = 100.0  # Default
    samples_collected: int = 0
    
    # Raw samples for computing statistics
    yaw_samples: List[float] = field(default_factory=list)
    gaze_samples: List[float] = field(default_factory=list)
    distance_samples: List[float] = field(default_factory=list)
    
    def is_ready(self) -> bool:
        """Check if baseline has enough samples."""
        return self.samples_collected >= 10  # Minimum samples
    
    def finalize(self):
        """Compute final baseline statistics from samples."""
        if self.yaw_samples:
            self.baseline_yaw = float(np.median(self.yaw_samples))
            self.yaw_std = float(np.std(self.yaw_samples)) if len(self.yaw_samples) > 1 else 10.0
        
        if self.gaze_samples:
            self.baseline_gaze = float(np.median(self.gaze_samples))
        
        if self.distance_samples:
            self.baseline_neighbor_distance = float(np.median(self.distance_samples))
        
        # Clear samples to free memory
        self.yaw_samples = []
        self.gaze_samples = []
        self.distance_samples = []


class BaselineCalibrator:
    """
    Calibrates baseline behavior for each student during the initial period.
    """
    
    def __init__(self, baseline_duration_sec: int, fps: int):
        """
        Initialize calibrator.
        
        Args:
            baseline_duration_sec: Duration of baseline period in seconds
            fps: Frame rate for sampling
        """
        self.baseline_duration_sec = baseline_duration_sec
        self.fps = fps
        self.baseline_frames = baseline_duration_sec * fps
        
        self.baselines: Dict[int, StudentBaseline] = {}
        self.current_frame = 0
        self.calibration_complete = False
        
        print(f"[BaselineCalibrator] Will calibrate for {baseline_duration_sec}s "
              f"({self.baseline_frames} frames)")
    
    def is_calibrating(self) -> bool:
        """Check if still in calibration period."""
        return self.current_frame < self.baseline_frames
    
    def add_sample(
        self,
        student_id: int,
        yaw: float,
        gaze_x: float,
        neighbor_distance: Optional[float] = None
    ):
        """
        Add a sample during calibration period.
        
        Args:
            student_id: Student identifier
            yaw: Head yaw angle
            gaze_x: Horizontal gaze direction
            neighbor_distance: Distance to nearest neighbor (if available)
        """
        if self.calibration_complete:
            return
        
        if student_id not in self.baselines:
            self.baselines[student_id] = StudentBaseline(student_id=student_id)
        
        baseline = self.baselines[student_id]
        baseline.yaw_samples.append(yaw)
        baseline.gaze_samples.append(gaze_x)
        
        if neighbor_distance is not None:
            baseline.distance_samples.append(neighbor_distance)
        
        baseline.samples_collected += 1
    
    def advance_frame(self):
        """Advance to next frame. Finalize calibration if period ends."""
        self.current_frame += 1
        
        if self.current_frame >= self.baseline_frames and not self.calibration_complete:
            self.finalize_calibration()
    
    def finalize_calibration(self):
        """Finalize all baselines."""
        print(f"[BaselineCalibrator] Finalizing calibration for {len(self.baselines)} students")
        
        for student_id, baseline in self.baselines.items():
            baseline.finalize()
            print(f"  Student {student_id}: yaw={baseline.baseline_yaw:.1f}°, "
                  f"yaw_std={baseline.yaw_std:.1f}°, "
                  f"gaze={baseline.baseline_gaze:.2f}, "
                  f"neighbor_dist={baseline.baseline_neighbor_distance:.1f}")
        
        self.calibration_complete = True
    
    def get_baseline(self, student_id: int) -> Optional[StudentBaseline]:
        """Get baseline for a student."""
        return self.baselines.get(student_id)
    
    def get_all_baselines(self) -> Dict[int, StudentBaseline]:
        """Get all baselines."""
        return self.baselines
