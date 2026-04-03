const uploadForm = document.getElementById('upload-form');
const videoFileInput = document.getElementById('video-file');
const submitBtn = document.getElementById('submit-btn');

const uploadCard = document.getElementById('upload-card');
const progressCard = document.getElementById('progress-card');
const resultCard = document.getElementById('result-card');
const errorBox = document.getElementById('error-box');

const progressBar = document.getElementById('progress-bar');
const progressText = document.getElementById('progress-text');
const resultVideo = document.getElementById('result-video');
const errorText = document.getElementById('error-text');
const resetBtn = document.getElementById('reset-btn');

let pollIntervalId = null;

uploadForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!videoFileInput.files.length) return;

    // Reset UI
    hideError();
    uploadCard.classList.add('hidden');
    progressCard.classList.remove('hidden');
    submitBtn.disabled = true;
    updateProgress(0, "Uploading video to Java Orchestrator...");

    const formData = new FormData(uploadForm);
    // Optionally append exam ID: formData.append('examId', 'some_id');

    try {
        const response = await fetch('/api/analyze', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.error || 'Upload failed');
        }

        const data = await response.json();
        const jobId = data.jobId;

        updateProgress(5, "Job submitted. Waiting for CV analysis...");
        startPolling(jobId);

    } catch (error) {
        showError(error.message);
        resetUI();
    }
});

function startPolling(jobId) {
    if (pollIntervalId) clearInterval(pollIntervalId);
    
    pollIntervalId = setInterval(async () => {
        try {
            const response = await fetch(`/api/status/${jobId}`);
            if (!response.ok) throw new Error("Failed to fetch status");
            
            const statusData = await response.json();

            // Progress comes back as a fraction (0.0 to 1.0)
            const pct = Math.round((statusData.progress || 0) * 100);
            updateProgress(pct, statusData.message || statusData.status);

            if (statusData.status === 'completed') {
                clearInterval(pollIntervalId);
                loadResult(jobId);
            } else if (statusData.status === 'failed') {
                clearInterval(pollIntervalId);
                showError("Analysis failed: " + statusData.message);
                resetUI();
            }
        } catch (error) {
            clearInterval(pollIntervalId);
            showError("Status polling error: " + error.message);
            resetUI();
        }
    }, 3000);
}

async function loadResult(jobId) {
    try {
        updateProgress(100, "Fetching final results...");
        const response = await fetch(`/api/result/${jobId}`);
        if (!response.ok) throw new Error("Failed to fetch result");
        
        // Fetch video dynamically from Java backend which streams it from the absolute file path
        const videoUrl = `/api/video/${jobId}`;

        resultVideo.src = videoUrl;
        
        progressCard.classList.add('hidden');
        resultCard.classList.remove('hidden');
    } catch (error) {
        showError("Failed to load result: " + error.message);
        resetUI();
    }
}

function updateProgress(percent, text) {
    progressBar.style.width = `${percent}%`;
    progressText.innerText = text;
}

function showError(msg) {
    errorText.innerText = msg;
    errorBox.classList.remove('hidden');
}

function hideError() {
    errorBox.classList.add('hidden');
    errorText.innerText = "";
}

function resetUI() {
    submitBtn.disabled = false;
    uploadCard.classList.remove('hidden');
    progressCard.classList.add('hidden');
    resultCard.classList.add('hidden');
    if (pollIntervalId) clearInterval(pollIntervalId);
}

resetBtn.addEventListener('click', () => {
    videoFileInput.value = "";
    resetUI();
    hideError();
    resultVideo.src = "";
});
