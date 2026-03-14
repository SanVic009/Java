"""
Analysis module exports.
"""
from .seat_assigner import SeatAssigner, SeatAssignment
from .pose_estimator import PoseEstimator, PoseEstimate
from .baseline import BaselineCalibrator, StudentBaseline
from .signals import SignalComputer, SignalResult, compute_distance
from .scorer import Scorer, FrameScore
from .aggregator import TemporalAggregator, SuspiciousInterval
from .auto_discovery import SeatAutoDiscovery, DiscoveredSeat

__all__ = [
    'SeatAssigner', 'SeatAssignment',
    'PoseEstimator', 'PoseEstimate',
    'BaselineCalibrator', 'StudentBaseline',
    'SignalComputer', 'SignalResult', 'compute_distance',
    'Scorer', 'FrameScore',
    'TemporalAggregator', 'SuspiciousInterval',
    'SeatAutoDiscovery', 'DiscoveredSeat'
]
