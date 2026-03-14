"""
Video processing pipeline.
Orchestrates the full analysis workflow with auto-discovery support.
"""
import cv2
import numpy as np
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from models.schemas import SeatMapping, AnalysisRequest
from detection import PersonDetector, ByteTracker, Track
from analysis import (
    SeatAssigner,
    PoseEstimator,
    BaselineCalibrator,
    SignalComputer,
    Scorer,
    TemporalAggregator,
    SeatAutoDiscovery,
    compute_distance
)
from config import config


class VideoProcessor:
    """
    Main video processing pipeline with auto-discovery support.
    
    Flow (with auto-discovery):
    1. Sample frames at specified FPS
    2. Detect persons (YOLOv8)
    3. Track persons (ByteTrack)
    4. [Discovery Phase] Collect stable positions → generate seat map
    5. Assign tracks to seats
    6. Estimate head pose and gaze (MediaPipe)
    7. Calibrate baseline
    8. Compute signals
    9. Score frames
    10. Aggregate into intervals
    """
    
    def __init__(self, request: AnalysisRequest):
        """
        Initialize processor with request parameters.
        
        Args:
            request: Analysis request with video path and optional seat mapping
        """
        self.request = request
        self.fps_sampling = request.fps_sampling
        self.baseline_duration = request.baseline_duration_sec
        
        # Check if we need auto-discovery
        self.use_auto_discovery = (request.seat_map is None or len(request.seat_map) == 0)
        
        # Initialize components
        print("\n" + "="*60)
        print("Initializing Video Processor")
        print("="*60)
        
        self.detector = PersonDetector(confidence=config.YOLO_CONFIDENCE)
        self.tracker = ByteTracker()
        self.pose_estimator = PoseEstimator()
        self.signal_computer = SignalComputer()
        self.scorer = Scorer()
        self.aggregator = TemporalAggregator(self.fps_sampling)
        
        # Auto-discovery or predefined seats
        self.auto_discovery: Optional[SeatAutoDiscovery] = None
        self.seat_assigner: Optional[SeatAssigner] = None
        self.discovered_seats: List[SeatMapping] = []
        
        if self.use_auto_discovery:
            print("\n*** AUTO-DISCOVERY MODE ***")
            print(f"No seat map provided - will auto-discover seats")
            self.auto_discovery = SeatAutoDiscovery(
                discovery_duration_sec=request.discovery_duration_sec,
                fps=self.fps_sampling
            )
            # Baseline calibrator will be initialized after discovery
            self.baseline_calibrator: Optional[BaselineCalibrator] = None
        else:
            print(f"\nUsing predefined seat map ({len(request.seat_map)} seats)")
            self.seat_assigner = SeatAssigner(request.seat_map)
            self.baseline_calibrator = BaselineCalibrator(
                self.baseline_duration, 
                self.fps_sampling
            )
        
        # State
        self.track_poses: Dict[int, 'PoseEstimate'] = {}
        self.student_to_track: Dict[int, int] = {}
        
        print("="*60 + "\n")
    
    def process(self) -> Tuple[Dict[int, List['SuspiciousInterval']], bool, List]:
        """
        Process the video and return suspicious intervals.
        
        Returns:
            Tuple of:
            - Dict mapping student_id -> list of SuspiciousInterval
            - bool indicating if auto-discovery was used
            - List of discovered seat info (if auto-discovered)
        """
        video_path = Path(self.request.video_path)
        
        if not video_path.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")
        
        cap = cv2.VideoCapture(str(video_path))
        
        if not cap.isOpened():
            raise RuntimeError(f"Failed to open video: {video_path}")
        
        # Get video properties
        original_fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / original_fps if original_fps > 0 else 0
        
        print(f"Video: {video_path.name}")
        print(f"  Original FPS: {original_fps:.1f}")
        print(f"  Total frames: {total_frames}")
        print(f"  Duration: {duration:.1f}s")
        print(f"  Sampling at: {self.fps_sampling} FPS")
        
        # Calculate frame skip
        frame_skip = max(1, int(original_fps / self.fps_sampling))
        expected_samples = total_frames // frame_skip
        
        print(f"  Frame skip: {frame_skip}")
        print(f"  Expected samples: {expected_samples}")
        
        if self.use_auto_discovery:
            print(f"\n  Phase 1: Auto-discovery ({self.request.discovery_duration_sec}s)")
            print(f"  Phase 2: Baseline calibration ({self.baseline_duration}s)")
            print(f"  Phase 3: Analysis")
        else:
            print(f"\n  Phase 1: Baseline calibration ({self.baseline_duration}s)")
            print(f"  Phase 2: Analysis")
        
        print()
        
        frame_idx = 0
        sample_idx = 0
        
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # Sample at target FPS
                if frame_idx % frame_skip == 0:
                    timestamp = frame_idx / original_fps
                    self._process_frame(frame, sample_idx, timestamp)
                    sample_idx += 1
                    
                    # Progress update
                    if sample_idx % 100 == 0:
                        phase = self._get_current_phase()
                        print(f"  [{phase}] Processed {sample_idx} frames "
                              f"({timestamp:.1f}s / {duration:.1f}s)")
                
                frame_idx += 1
        
        finally:
            cap.release()
            self.pose_estimator.close()
        
        print(f"\nProcessed {sample_idx} frames total")
        print("Aggregating results...")
        
        # Get discovered seat info for response
        discovered_info = []
        if self.use_auto_discovery and self.auto_discovery:
            for seat in self.auto_discovery.discovered_seats:
                discovered_info.append({
                    'seat_id': seat.seat_id,
                    'student_id': seat.student_id,
                    'bbox': seat.bbox,
                    'neighbors': seat.neighbors,
                    'stability_score': round(seat.stability_score, 2)
                })
        
        # Aggregate and return results
        return self.aggregator.aggregate(), self.use_auto_discovery, discovered_info
    
    def _get_current_phase(self) -> str:
        """Get current processing phase for status display."""
        if self.use_auto_discovery:
            if self.auto_discovery and self.auto_discovery.is_discovering():
                return "Discovery"
            elif self.baseline_calibrator and self.baseline_calibrator.is_calibrating():
                return "Baseline"
            else:
                return "Analysis"
        else:
            if self.baseline_calibrator and self.baseline_calibrator.is_calibrating():
                return "Baseline"
            else:
                return "Analysis"
    
    def _process_frame(
        self, 
        frame: np.ndarray, 
        frame_idx: int, 
        timestamp: float
    ):
        """Process a single frame."""
        # 1. Detect persons
        detections = self.detector.detect(frame)
        
        # 2. Track persons
        tracks = self.tracker.update(detections)
        
        # 3. Handle auto-discovery phase
        if self.use_auto_discovery and self.auto_discovery:
            if self.auto_discovery.is_discovering():
                # Still discovering - collect observations
                self.auto_discovery.add_observation(tracks)
                self.auto_discovery.advance_frame()
                return
            
            # Discovery just completed - initialize seat assigner and baseline
            if self.seat_assigner is None:
                self._initialize_after_discovery()
        
        # 4. Assign tracks to seats
        if self.seat_assigner:
            self.student_to_track = self.seat_assigner.update(tracks)
        
        # Build track lookup
        track_lookup = {t.track_id: t for t in tracks}
        
        # 5. Process each assigned student
        for student_id, track_id in self.student_to_track.items():
            track = track_lookup.get(track_id)
            if track is None:
                continue
            
            # 6. Estimate pose
            pose = self.pose_estimator.estimate(frame, track.bbox)
            if pose is None:
                continue
            
            self.track_poses[track_id] = pose
            
            # 7. During calibration, collect samples
            if self.baseline_calibrator and self.baseline_calibrator.is_calibrating():
                # Compute neighbor distance for baseline
                neighbor_dist = self._compute_neighbor_distance(
                    student_id, track, track_lookup
                )
                
                self.baseline_calibrator.add_sample(
                    student_id=student_id,
                    yaw=pose.yaw,
                    gaze_x=pose.gaze_x,
                    neighbor_distance=neighbor_dist
                )
            elif self.baseline_calibrator:
                # 8. After calibration, compute signals and score
                baseline = self.baseline_calibrator.get_baseline(student_id)
                if baseline is None or not baseline.is_ready():
                    continue
                
                # Compute neighbor distance and get neighbor's yaw
                neighbor_dist, neighbor_yaw = self._get_neighbor_info(
                    student_id, track, track_lookup
                )
                
                # Compute signals
                signals = self.signal_computer.compute(
                    student_id=student_id,
                    baseline=baseline,
                    yaw=pose.yaw,
                    gaze_x=pose.gaze_x,
                    neighbor_distance=neighbor_dist,
                    neighbor_yaw=neighbor_yaw
                )
                
                # Score frame
                frame_score = self.scorer.score_frame(
                    frame_idx=frame_idx,
                    timestamp=timestamp,
                    student_id=student_id,
                    signals=signals
                )
                
                # Add to aggregator
                self.aggregator.add_score(frame_score)
        
        # Advance calibration frame counter
        if self.baseline_calibrator:
            self.baseline_calibrator.advance_frame()
    
    def _initialize_after_discovery(self):
        """Initialize components after auto-discovery completes."""
        print("\n" + "-"*40)
        print("Auto-discovery complete. Initializing analysis components...")
        
        # Get discovered seat mappings
        self.discovered_seats = self.auto_discovery.get_seat_mappings()
        
        if not self.discovered_seats:
            print("WARNING: No seats discovered! Analysis may fail.")
            return
        
        # Initialize seat assigner with discovered seats
        self.seat_assigner = SeatAssigner(self.discovered_seats)
        
        # Initialize baseline calibrator
        self.baseline_calibrator = BaselineCalibrator(
            self.baseline_duration,
            self.fps_sampling
        )
        
        print(f"Initialized with {len(self.discovered_seats)} discovered seats")
        print("-"*40 + "\n")
    
    def _compute_neighbor_distance(
        self,
        student_id: int,
        track: Track,
        track_lookup: Dict[int, Track]
    ) -> Optional[float]:
        """Compute distance to nearest neighbor."""
        if not self.seat_assigner:
            return None
        
        neighbors = self.seat_assigner.get_student_neighbors(student_id)
        
        min_distance = None
        
        for neighbor_id in neighbors:
            neighbor_track_id = self.student_to_track.get(neighbor_id)
            if neighbor_track_id is None:
                continue
            
            neighbor_track = track_lookup.get(neighbor_track_id)
            if neighbor_track is None:
                continue
            
            dist = compute_distance(track.centroid, neighbor_track.centroid)
            
            if min_distance is None or dist < min_distance:
                min_distance = dist
        
        return min_distance
    
    def _get_neighbor_info(
        self,
        student_id: int,
        track: Track,
        track_lookup: Dict[int, Track]
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Get nearest neighbor's distance and yaw.
        
        Returns:
            Tuple of (distance, neighbor_yaw)
        """
        if not self.seat_assigner:
            return None, None
        
        neighbors = self.seat_assigner.get_student_neighbors(student_id)
        
        min_distance = None
        nearest_yaw = None
        
        for neighbor_id in neighbors:
            neighbor_track_id = self.student_to_track.get(neighbor_id)
            if neighbor_track_id is None:
                continue
            
            neighbor_track = track_lookup.get(neighbor_track_id)
            if neighbor_track is None:
                continue
            
            dist = compute_distance(track.centroid, neighbor_track.centroid)
            
            if min_distance is None or dist < min_distance:
                min_distance = dist
                
                # Get neighbor's pose if available
                neighbor_pose = self.track_poses.get(neighbor_track_id)
                if neighbor_pose and self.baseline_calibrator:
                    neighbor_baseline = self.baseline_calibrator.get_baseline(neighbor_id)
                    if neighbor_baseline:
                        nearest_yaw = neighbor_pose.yaw - neighbor_baseline.baseline_yaw
        
        return min_distance, nearest_yaw
