#!/bin/bash
# Load environment variables from .env
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Run the Java Orchestrator CLI mode
# You can append any additional arguments to this script
java -jar target/classroom-anticheat-orchestrator-1.0.0.jar "$@"
