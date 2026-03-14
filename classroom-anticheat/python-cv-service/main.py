"""
Classroom Anti-Cheat CV Service
FastAPI application for video analysis.
"""
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from models import (
    AnalysisRequest, 
    AnalysisResponse, 
    StudentResult,
    SuspiciousInterval as SuspiciousIntervalSchema,
    DiscoveredSeatInfo,
    HealthResponse
)
from pipeline import VideoProcessor
from config import config

app = FastAPI(
    title="Classroom Anti-Cheat CV Service",
    description="Computer Vision service for detecting suspicious behavior in classroom videos",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(status="healthy", version="1.0.0")


@app.post("/analyze", response_model=AnalysisResponse)
async def analyze_video(request: AnalysisRequest):
    """
    Analyze a classroom video for suspicious behavior.
    
    This endpoint processes the video file specified in the request,
    detects and tracks students, analyzes their behavior, and returns
    suspicious time intervals for each student.
    
    If no seat_map is provided, the system will auto-discover seat positions
    from the first 2 minutes of video.
    """
    print("\n" + "="*60)
    print("ANALYSIS REQUEST RECEIVED")
    print("="*60)
    print(f"Exam ID: {request.exam_id}")
    print(f"Video: {request.video_path}")
    print(f"FPS Sampling: {request.fps_sampling}")
    print(f"Baseline Duration: {request.baseline_duration_sec}s")
    
    if request.seat_map:
        print(f"Seats Configured: {len(request.seat_map)}")
    else:
        print(f"Seat Map: AUTO-DISCOVERY (first {request.discovery_duration_sec}s)")
    
    print("="*60 + "\n")
    
    try:
        # Create processor and run analysis
        processor = VideoProcessor(request)
        results, auto_discovered, discovered_info = processor.process()
        
        # Convert results to response format
        student_results = []
        
        for student_id, intervals in results.items():
            interval_schemas = [
                SuspiciousIntervalSchema(
                    start=interval.start,
                    end=interval.end,
                    peak_score=round(interval.peak_score, 2),
                    reasons=interval.reasons
                )
                for interval in intervals
            ]
            
            student_results.append(StudentResult(
                student_id=student_id,
                intervals=interval_schemas
            ))
        
        # Sort by student_id for consistent output
        student_results.sort(key=lambda x: x.student_id)
        
        # Convert discovered seats info
        discovered_seats = None
        if auto_discovered and discovered_info:
            discovered_seats = [
                DiscoveredSeatInfo(
                    seat_id=s['seat_id'],
                    student_id=s['student_id'],
                    bbox=s['bbox'],
                    neighbors=s['neighbors'],
                    stability_score=s['stability_score']
                )
                for s in discovered_info
            ]
        
        print("\n" + "="*60)
        print("ANALYSIS COMPLETE")
        print("="*60)
        if auto_discovered:
            print(f"Mode: AUTO-DISCOVERY")
            print(f"Seats discovered: {len(discovered_info) if discovered_info else 0}")
        else:
            print(f"Mode: PREDEFINED SEATS")
        print(f"Students with suspicious activity: {len(student_results)}")
        total_intervals = sum(len(r.intervals) for r in student_results)
        print(f"Total suspicious intervals: {total_intervals}")
        print("="*60 + "\n")
        
        return AnalysisResponse(
            exam_id=request.exam_id,
            results=student_results,
            auto_discovered=auto_discovered,
            discovered_seats=discovered_seats
        )
        
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        print(f"Error during analysis: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@app.get("/")
async def root():
    """Root endpoint with service info."""
    return {
        "service": "Classroom Anti-Cheat CV Service",
        "version": "1.0.0",
        "features": [
            "Auto-discovery mode (no seat map required)",
            "YOLOv8 person detection",
            "ByteTrack multi-object tracking",
            "MediaPipe head pose and gaze estimation"
        ],
        "endpoints": {
            "health": "/health",
            "analyze": "/analyze (POST)"
        }
    }


if __name__ == "__main__":
    print("\n" + "="*60)
    print("CLASSROOM ANTI-CHEAT CV SERVICE")
    print("="*60)
    print(f"Starting server on {config.HOST}:{config.PORT}")
    print("="*60 + "\n")
    
    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=False,
        log_level="info"
    )
