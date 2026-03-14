"""
Auto-discovery module for seat detection.
Automatically discovers seat regions from video without manual configuration.
"""
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from collections import defaultdict
from scipy.spatial import Delaunay
import math

from models.schemas import SeatMapping
from detection.tracker import Track


@dataclass
class DiscoveredSeat:
    """A seat discovered from tracking data."""
    seat_id: int
    track_id: int
    student_id: int  # Same as track_id in auto-discovery
    centroid: Tuple[int, int]
    bbox: List[int]  # [x1, y1, x2, y2]
    neighbors: List[int] = field(default_factory=list)
    position_samples: List[Tuple[int, int]] = field(default_factory=list)
    stability_score: float = 0.0


class SeatAutoDiscovery:
    """
    Automatically discovers seat positions from video.
    
    Process:
    1. Track persons for discovery period (first 2 minutes)
    2. For each stable track, compute average position
    3. Generate bounding boxes around stable positions
    4. Compute neighbor graph based on spatial proximity
    """
    
    def __init__(
        self,
        discovery_duration_sec: int = 120,
        fps: int = 5,
        min_stability_ratio: float = 0.5,
        bbox_padding: int = 75,
        neighbor_distance_multiplier: float = 2.0
    ):
        """
        Initialize auto-discovery.
        
        Args:
            discovery_duration_sec: How long to observe for discovery (seconds)
            fps: Frame rate
            min_stability_ratio: Minimum presence ratio to consider track stable
            bbox_padding: Padding around centroid for bounding box
            neighbor_distance_multiplier: Multiplier of avg distance for neighbor threshold
        """
        self.discovery_duration_sec = discovery_duration_sec
        self.fps = fps
        self.discovery_frames = discovery_duration_sec * fps
        self.min_stability_ratio = min_stability_ratio
        self.bbox_padding = bbox_padding
        self.neighbor_distance_multiplier = neighbor_distance_multiplier
        
        # Track position history: track_id -> list of (frame_idx, centroid)
        self.track_history: Dict[int, List[Tuple[int, Tuple[int, int]]]] = defaultdict(list)
        
        # Track bounding box sizes for better bbox estimation
        self.track_bbox_sizes: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
        
        self.current_frame = 0
        self.discovery_complete = False
        self.discovered_seats: List[DiscoveredSeat] = []
        
        print(f"[SeatAutoDiscovery] Will discover seats during first {discovery_duration_sec}s "
              f"({self.discovery_frames} frames)")
    
    def is_discovering(self) -> bool:
        """Check if still in discovery period."""
        return self.current_frame < self.discovery_frames and not self.discovery_complete
    
    def add_observation(self, tracks: List[Track]):
        """
        Add tracking observations for the current frame.
        
        Args:
            tracks: List of active tracks
        """
        if self.discovery_complete:
            return
        
        for track in tracks:
            self.track_history[track.track_id].append(
                (self.current_frame, track.centroid)
            )
            
            # Store bbox size
            x1, y1, x2, y2 = track.bbox
            self.track_bbox_sizes[track.track_id].append((x2 - x1, y2 - y1))
    
    def advance_frame(self):
        """Advance frame counter and finalize if discovery period ends."""
        self.current_frame += 1
        
        if self.current_frame >= self.discovery_frames and not self.discovery_complete:
            self.finalize_discovery()
    
    def finalize_discovery(self):
        """Process collected data and generate seat mappings."""
        print(f"\n[SeatAutoDiscovery] Finalizing discovery...")
        print(f"  Total tracks observed: {len(self.track_history)}")
        
        # Filter stable tracks
        stable_tracks = self._find_stable_tracks()
        print(f"  Stable tracks: {len(stable_tracks)}")
        
        if not stable_tracks:
            print("  WARNING: No stable tracks found!")
            self.discovery_complete = True
            return
        
        # Generate seats from stable tracks
        self.discovered_seats = self._generate_seats(stable_tracks)
        
        # Compute neighbor relationships
        self._compute_neighbors()
        
        self.discovery_complete = True
        
        print(f"\n[SeatAutoDiscovery] Discovered {len(self.discovered_seats)} seats:")
        for seat in self.discovered_seats:
            print(f"  Seat {seat.seat_id}: student={seat.student_id}, "
                  f"bbox={seat.bbox}, neighbors={seat.neighbors}, "
                  f"stability={seat.stability_score:.2f}")
    
    def _find_stable_tracks(self) -> Dict[int, List[Tuple[int, int]]]:
        """
        Find tracks that are stable (present for sufficient frames).
        
        Returns:
            Dict mapping track_id -> list of centroids
        """
        stable = {}
        
        for track_id, history in self.track_history.items():
            presence_ratio = len(history) / self.discovery_frames
            
            if presence_ratio >= self.min_stability_ratio:
                # Extract just the centroids
                centroids = [pos for _, pos in history]
                stable[track_id] = centroids
        
        return stable
    
    def _generate_seats(
        self, 
        stable_tracks: Dict[int, List[Tuple[int, int]]]
    ) -> List[DiscoveredSeat]:
        """Generate seat definitions from stable tracks."""
        seats = []
        
        for idx, (track_id, centroids) in enumerate(stable_tracks.items()):
            # Compute median position (more robust than mean)
            xs = [c[0] for c in centroids]
            ys = [c[1] for c in centroids]
            
            median_x = int(np.median(xs))
            median_y = int(np.median(ys))
            
            # Compute position variance for stability score
            std_x = np.std(xs)
            std_y = np.std(ys)
            stability = 1.0 / (1.0 + (std_x + std_y) / 100)  # Higher is more stable
            
            # Get average bbox size for this track
            if track_id in self.track_bbox_sizes:
                sizes = self.track_bbox_sizes[track_id]
                avg_width = int(np.median([s[0] for s in sizes]))
                avg_height = int(np.median([s[1] for s in sizes]))
            else:
                avg_width = self.bbox_padding * 2
                avg_height = self.bbox_padding * 2
            
            # Add padding
            half_width = avg_width // 2 + self.bbox_padding
            half_height = avg_height // 2 + self.bbox_padding
            
            # Generate bounding box
            bbox = [
                max(0, median_x - half_width),
                max(0, median_y - half_height),
                median_x + half_width,
                median_y + half_height
            ]
            
            seat = DiscoveredSeat(
                seat_id=idx + 1,
                track_id=track_id,
                student_id=track_id,  # Use track_id as student_id
                centroid=(median_x, median_y),
                bbox=bbox,
                position_samples=centroids,
                stability_score=stability
            )
            
            seats.append(seat)
        
        return seats
    
    def _compute_neighbors(self):
        """Compute neighbor relationships using spatial proximity."""
        if len(self.discovered_seats) < 2:
            return
        
        # Compute average distance between seats
        centroids = [seat.centroid for seat in self.discovered_seats]
        
        distances = []
        for i, c1 in enumerate(centroids):
            for j, c2 in enumerate(centroids):
                if i < j:
                    dist = math.sqrt(
                        (c1[0] - c2[0])**2 + (c1[1] - c2[1])**2
                    )
                    distances.append(dist)
        
        if not distances:
            return
        
        avg_distance = np.mean(distances)
        neighbor_threshold = avg_distance * self.neighbor_distance_multiplier
        
        # Try Delaunay triangulation for better neighbor detection
        if len(centroids) >= 4:
            try:
                points = np.array(centroids)
                tri = Delaunay(points)
                
                # Extract neighbors from triangulation
                neighbor_sets = defaultdict(set)
                for simplex in tri.simplices:
                    for i in range(3):
                        for j in range(3):
                            if i != j:
                                neighbor_sets[simplex[i]].add(simplex[j])
                
                # Apply distance threshold to Delaunay neighbors
                for i, seat in enumerate(self.discovered_seats):
                    seat.neighbors = []
                    for j in neighbor_sets[i]:
                        dist = math.sqrt(
                            (centroids[i][0] - centroids[j][0])**2 +
                            (centroids[i][1] - centroids[j][1])**2
                        )
                        if dist <= neighbor_threshold:
                            seat.neighbors.append(self.discovered_seats[j].seat_id)
                return
            except Exception as e:
                print(f"  Delaunay failed, using distance-based neighbors: {e}")
        
        # Fallback: Simple distance-based neighbors
        for i, seat in enumerate(self.discovered_seats):
            seat.neighbors = []
            for j, other in enumerate(self.discovered_seats):
                if i != j:
                    dist = math.sqrt(
                        (centroids[i][0] - centroids[j][0])**2 +
                        (centroids[i][1] - centroids[j][1])**2
                    )
                    if dist <= neighbor_threshold:
                        seat.neighbors.append(other.seat_id)
    
    def get_seat_mappings(self) -> List[SeatMapping]:
        """
        Convert discovered seats to SeatMapping format.
        
        Returns:
            List of SeatMapping objects
        """
        return [
            SeatMapping(
                seat_id=seat.seat_id,
                student_id=seat.student_id,
                bbox=seat.bbox,
                neighbors=seat.neighbors
            )
            for seat in self.discovered_seats
        ]
    
    def get_track_to_student_map(self) -> Dict[int, int]:
        """
        Get mapping from track_id to student_id.
        
        Returns:
            Dict mapping track_id -> student_id
        """
        return {
            seat.track_id: seat.student_id
            for seat in self.discovered_seats
        }
