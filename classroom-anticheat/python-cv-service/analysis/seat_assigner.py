"""
Seat assignment logic.
Maps tracked persons to seats based on centroid containment.
"""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from models.schemas import SeatMapping
from detection.tracker import Track
from config import config


@dataclass
class SeatAssignment:
    """Assignment of a track to a seat."""
    seat_id: int
    student_id: int
    track_id: int
    consecutive_frames: int = 0
    confirmed: bool = False


class SeatAssigner:
    """
    Assigns tracked persons to predefined seat regions.
    Uses centroid containment with stabilization.
    """
    
    def __init__(self, seat_map: List[SeatMapping]):
        """
        Initialize seat assigner.
        
        Args:
            seat_map: List of seat mappings with bounding boxes
        """
        self.seats = {s.seat_id: s for s in seat_map}
        self.assignments: Dict[int, SeatAssignment] = {}  # track_id -> assignment
        self.seat_to_track: Dict[int, int] = {}  # seat_id -> track_id
        
        # Build neighbor lookup
        self.neighbors: Dict[int, List[int]] = {
            s.seat_id: s.neighbors for s in seat_map
        }
        
        print(f"[SeatAssigner] Initialized with {len(seat_map)} seats")
    
    def update(self, tracks: List[Track]) -> Dict[int, int]:
        """
        Update seat assignments based on current tracks.
        
        Args:
            tracks: List of active tracks
            
        Returns:
            Dict mapping student_id -> track_id for confirmed assignments
        """
        current_track_ids = {t.track_id for t in tracks}
        
        # Remove assignments for tracks that no longer exist
        expired = [
            tid for tid in self.assignments 
            if tid not in current_track_ids
        ]
        for tid in expired:
            assignment = self.assignments.pop(tid)
            if assignment.seat_id in self.seat_to_track:
                if self.seat_to_track[assignment.seat_id] == tid:
                    del self.seat_to_track[assignment.seat_id]
        
        # Process each track
        for track in tracks:
            self._process_track(track)
        
        # Return confirmed student_id -> track_id mapping
        return {
            self.seats[a.seat_id].student_id: a.track_id
            for a in self.assignments.values()
            if a.confirmed
        }
    
    def _process_track(self, track: Track):
        """Process a single track for seat assignment."""
        centroid = track.centroid
        containing_seat = self._find_containing_seat(centroid)
        
        if track.track_id in self.assignments:
            # Existing assignment
            assignment = self.assignments[track.track_id]
            
            if containing_seat == assignment.seat_id:
                # Still in same seat
                assignment.consecutive_frames += 1
                if assignment.consecutive_frames >= config.STABILIZATION_FRAMES:
                    assignment.confirmed = True
            else:
                # Moved to different seat or outside
                assignment.consecutive_frames = 0
                assignment.confirmed = False
                
                if containing_seat is not None:
                    # Check if new seat is unoccupied
                    if self._can_assign_to_seat(containing_seat, track.track_id):
                        # Update to new seat
                        old_seat = assignment.seat_id
                        if old_seat in self.seat_to_track:
                            del self.seat_to_track[old_seat]
                        
                        assignment.seat_id = containing_seat
                        assignment.student_id = self.seats[containing_seat].student_id
                        assignment.consecutive_frames = 1
                        self.seat_to_track[containing_seat] = track.track_id
        else:
            # New track - try to assign
            if containing_seat is not None:
                if self._can_assign_to_seat(containing_seat, track.track_id):
                    assignment = SeatAssignment(
                        seat_id=containing_seat,
                        student_id=self.seats[containing_seat].student_id,
                        track_id=track.track_id,
                        consecutive_frames=1
                    )
                    self.assignments[track.track_id] = assignment
                    self.seat_to_track[containing_seat] = track.track_id
    
    def _find_containing_seat(self, centroid: Tuple[int, int]) -> Optional[int]:
        """Find which seat contains the given centroid."""
        cx, cy = centroid
        
        for seat_id, seat in self.seats.items():
            x1, y1, x2, y2 = seat.bbox
            if x1 <= cx <= x2 and y1 <= cy <= y2:
                return seat_id
        
        return None
    
    def _can_assign_to_seat(self, seat_id: int, track_id: int) -> bool:
        """Check if a track can be assigned to a seat."""
        if seat_id not in self.seat_to_track:
            return True
        
        # Seat already has a track - check if it's the same one
        return self.seat_to_track[seat_id] == track_id
    
    def get_student_track(self, student_id: int) -> Optional[int]:
        """Get track_id for a student."""
        for assignment in self.assignments.values():
            if assignment.student_id == student_id and assignment.confirmed:
                return assignment.track_id
        return None
    
    def get_student_neighbors(self, student_id: int) -> List[int]:
        """Get neighbor student IDs for a student."""
        for seat_id, seat in self.seats.items():
            if seat.student_id == student_id:
                neighbor_seats = self.neighbors.get(seat_id, [])
                return [
                    self.seats[ns].student_id 
                    for ns in neighbor_seats 
                    if ns in self.seats
                ]
        return []
    
    def get_all_confirmed_assignments(self) -> Dict[int, Tuple[int, int]]:
        """
        Get all confirmed assignments.
        
        Returns:
            Dict mapping student_id -> (track_id, seat_id)
        """
        return {
            a.student_id: (a.track_id, a.seat_id)
            for a in self.assignments.values()
            if a.confirmed
        }
