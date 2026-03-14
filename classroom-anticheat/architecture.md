# Classroom Anti-Cheat System - Architecture Diagram

## System Overview

```mermaid
flowchart TB
    subgraph Input["📥 INPUT"]
        Video["🎥 CCTV Video File"]
        Config["⚙️ Exam Config"]
        SeatMap["🪑 Seat Map (optional)"]
    end

    subgraph Java["☕ JAVA ORCHESTRATOR"]
        Main["Main.java<br/>CLI Parser"]
        Client["AnalysisClient.java<br/>HTTP Client"]
        Reporter["TerminalReporter.java<br/>Output Formatter"]
    end

    subgraph Python["🐍 PYTHON CV SERVICE (FastAPI :8000)"]
        API["main.py<br/>/analyze endpoint"]
        
        subgraph Pipeline["Pipeline Processor"]
            direction TB
            
            subgraph Detection["Detection Layer"]
                Detector["detector.py<br/>YOLOv8n"]
                Tracker["tracker.py<br/>ByteTrack"]
            end
            
            subgraph Discovery["Seat Discovery (Optional)"]
                AutoDisc["auto_discovery.py<br/>First 120s"]
                Assigner["seat_assigner.py<br/>Centroid Matching"]
            end
            
            subgraph Analysis["Analysis Layer"]
                Pose["pose_estimator.py<br/>MediaPipe Face Mesh"]
                Baseline["baseline.py<br/>Calibration (60s)"]
                Signals["signals.py<br/>Head/Gaze/Proximity"]
                Scorer["scorer.py<br/>Weighted Scoring"]
                Aggregator["aggregator.py<br/>Temporal Windows"]
            end
        end
    end

    subgraph Output["📤 OUTPUT"]
        Results["📊 Analysis Results"]
        Intervals["⚠️ Suspicious Intervals"]
        Report["📝 Terminal Report"]
    end

    Video --> Main
    Config --> Main
    SeatMap --> Main
    Main --> Client
    Client -->|"POST /analyze<br/>JSON Request"| API
    API --> Pipeline
    
    Detector --> Tracker
    Tracker --> AutoDisc
    AutoDisc --> Assigner
    Assigner --> Pose
    Pose --> Baseline
    Baseline --> Signals
    Signals --> Scorer
    Scorer --> Aggregator
    
    Aggregator -->|"JSON Response"| Client
    Client --> Reporter
    Reporter --> Results
    Reporter --> Intervals
    Reporter --> Report
```

## Processing Pipeline Detail

```mermaid
flowchart LR
    subgraph Phase1["Phase 1: Ingestion"]
        V["Video"] -->|"5 FPS"| Frames["Frame<br/>Queue"]
    end
    
    subgraph Phase2["Phase 2: Detection"]
        Frames --> YOLO["YOLOv8n<br/>Person Detection"]
        YOLO --> BT["ByteTrack<br/>Multi-Object Tracking"]
        BT --> Seats["Seat<br/>Assignment"]
    end
    
    subgraph Phase3["Phase 3: Calibration"]
        Seats -->|"First 60s"| BL["Baseline<br/>Collection"]
        BL --> Metrics["Per-Student<br/>Baseline Metrics"]
    end
    
    subgraph Phase4["Phase 4: Analysis"]
        Metrics --> MP["MediaPipe<br/>Face Mesh"]
        MP --> Sig["Signal<br/>Computation"]
        Sig --> Score["Frame<br/>Scoring"]
    end
    
    subgraph Phase5["Phase 5: Aggregation"]
        Score --> Win["30s Sliding<br/>Window"]
        Win --> Merge["Interval<br/>Merging"]
        Merge --> Out["Suspicious<br/>Intervals"]
    end
```

## Signal Detection & Scoring

```mermaid
flowchart TB
    subgraph Inputs["Per-Frame Inputs"]
        Yaw["Head Yaw"]
        Gaze["Gaze Direction"]
        Dist["Neighbor Distance"]
    end
    
    subgraph Signals["Binary Signals (0 or 1)"]
        Head["HeadSignal<br/>|yaw - baseline| > 25°"]
        GazeSig["GazeSignal<br/>|gaze_x - baseline| > 0.15"]
        Prox["ProximitySignal<br/>distance < baseline × 0.7"]
    end
    
    subgraph Scoring["Weighted Scoring"]
        Formula["S(t) = 0.35 × Head<br/>+ 0.25 × Gaze<br/>+ 0.55 × Proximity"]
        Threshold["Suspicious if<br/>S(t) ≥ 0.75"]
    end
    
    Yaw --> Head
    Gaze --> GazeSig
    Dist --> Prox
    
    Head -->|"weight: 0.35"| Formula
    GazeSig -->|"weight: 0.25"| Formula
    Prox -->|"weight: 0.55"| Formula
    Formula --> Threshold
```

## API Communication Sequence

```mermaid
sequenceDiagram
    participant User
    participant Java as Java Orchestrator
    participant Python as Python CV Service
    participant CV as CV Pipeline

    User->>Java: Run with config/video
    Java->>Java: Parse CLI args
    Java->>Java: Load configuration
    
    Java->>Python: POST /analyze
    Note over Java,Python: JSON: exam_id, video_path,<br/>fps_sampling, seat_map (optional)
    
    Python->>CV: Process video
    
    alt Auto-Discovery Mode
        CV->>CV: Discover seats (120s)
    end
    
    CV->>CV: Baseline calibration (60s)
    CV->>CV: Detect & track persons
    CV->>CV: Estimate poses
    CV->>CV: Compute signals
    CV->>CV: Score frames
    CV->>CV: Aggregate intervals
    
    CV->>Python: Analysis complete
    Python->>Java: JSON Response
    Note over Python,Java: results[], discovered_seats[]
    
    Java->>Java: Format report
    Java->>User: Display terminal report
```

## Component Dependencies

```mermaid
graph TB
    subgraph External["External Dependencies"]
        YOLO["ultralytics<br/>YOLOv8n"]
        MediaPipe["mediapipe<br/>Face Mesh"]
        OpenCV["opencv-python"]
        FastAPI["FastAPI + Uvicorn"]
        NumPy["numpy + scipy"]
    end
    
    subgraph Detection["Detection Module"]
        Det["detector.py"]
        Track["tracker.py"]
    end
    
    subgraph Analysis["Analysis Module"]
        Auto["auto_discovery.py"]
        Seat["seat_assigner.py"]
        Pose["pose_estimator.py"]
        Base["baseline.py"]
        Sig["signals.py"]
        Scr["scorer.py"]
        Agg["aggregator.py"]
    end
    
    subgraph Pipeline["Pipeline"]
        Proc["processor.py"]
    end
    
    YOLO --> Det
    OpenCV --> Det
    OpenCV --> Track
    NumPy --> Track
    MediaPipe --> Pose
    NumPy --> Base
    NumPy --> Sig
    NumPy --> Scr
    NumPy --> Agg
    
    Det --> Proc
    Track --> Proc
    Auto --> Proc
    Seat --> Proc
    Pose --> Proc
    Base --> Proc
    Sig --> Proc
    Scr --> Proc
    Agg --> Proc
    
    FastAPI --> Proc
```

## Execution Modes

```mermaid
flowchart TB
    Start["Start"] --> Mode{Seat Map<br/>Provided?}
    
    Mode -->|Yes| Predefined["Predefined Seats Mode"]
    Mode -->|No| AutoMode["Auto-Discovery Mode"]
    
    Predefined --> Load["Load seat_map.json"]
    AutoMode --> Discover["Discover seats<br/>(first 120s)"]
    
    Load --> Calibrate["Baseline Calibration<br/>(60s)"]
    Discover --> Calibrate
    
    Calibrate --> Process["Process All Frames"]
    Process --> Detect["Detect & Track<br/>Persons"]
    Detect --> Analyze["Analyze Behavior<br/>per Student"]
    Analyze --> Aggregate["Temporal<br/>Aggregation"]
    Aggregate --> Report["Generate<br/>Report"]
    Report --> End["End"]
```
