const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const previewArea = document.getElementById('previewArea');
const previewContainer = document.getElementById('previewContainer');
const uploadPrompt = document.getElementById('uploadPrompt');
const analyzeBtn = document.getElementById('analyzeBtn');
const analysisSection = document.getElementById('analysisSection');

let selectedFiles = [];
let currentAnalysis = null;
let allAnalyses = [];
let currentAnalysisIdx = 0;
let currentSliceIdx = 0;
let appendInterval = null;
let replayInterval = null;

dropZone.addEventListener('click', () => fileInput.click());

dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('drag-over');
});

dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'));
    if (files.length > 0) {
        handleFiles(files);
    }
});

fileInput.addEventListener('change', () => {
    const files = Array.from(fileInput.files);
    if (files.length > 0) {
        handleFiles(files);
    }
});

function handleFiles(files) {
    selectedFiles = files;
    previewContainer.innerHTML = '';
    
    files.forEach((file, idx) => {
        const reader = new FileReader();
        reader.onload = (e) => {
            const wrapper = document.createElement('div');
            wrapper.className = 'position-relative';
            wrapper.innerHTML = `
                <img src="${e.target.result}" class="rounded" style="max-height: 150px; max-width: 200px;">
                <button class="btn btn-sm btn-danger position-absolute top-0 end-0 m-1 remove-btn" data-idx="${idx}">&times;</button>
            `;
            previewContainer.appendChild(wrapper);
            
            wrapper.querySelector('.remove-btn').addEventListener('click', (ev) => {
                ev.stopPropagation();
                const idx = parseInt(ev.target.dataset.idx);
                selectedFiles = selectedFiles.filter((_, i) => i !== idx);
                handleFiles(selectedFiles);
            });
        };
        reader.readAsDataURL(file);
    });
    
    previewArea.classList.remove('d-none');
    uploadPrompt.classList.add('d-none');
}

analyzeBtn.addEventListener('click', async () => {
    if (selectedFiles.length === 0) {
        alert('Please upload at least one image');
        return;
    }

    const concatenatedMode = document.getElementById('concatenatedMode').checked;
    const noImageMode = document.getElementById('noImageMode').checked;
    const denseMode = document.getElementById('denseMode').checked;

    analyzeBtn.disabled = true;
    analyzeBtn.textContent = 'Analyzing...';

    try {
        const uploadPromises = selectedFiles.map(async (file) => {
            const formData = new FormData();
            formData.append('image', file);
            const res = await fetch('/api/upload', { method: 'POST', body: formData });
            return res.json();
        });
        
        const uploadResults = await Promise.all(uploadPromises);
        const filepaths = uploadResults.map(r => r.filepath);

        if (concatenatedMode && filepaths.length > 1) {
            const analyzeRes = await fetch('/api/analyze-concatenated', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filepaths, no_image: noImageMode, dense_mode: denseMode })
            });
            const data = await analyzeRes.json();
            allAnalyses = [data];
        } else if (filepaths.length === 1) {
            const analyzeRes = await fetch('/api/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filepath: filepaths[0], no_image: noImageMode, dense_mode: denseMode })
            });
            const data = await analyzeRes.json();
            allAnalyses = [data];
        } else {
            const analyzeRes = await fetch('/api/analyze-multiple', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filepaths, no_image: noImageMode, dense_mode: denseMode })
            });
            const data = await analyzeRes.json();
            allAnalyses = data.analyses;
        }

        currentAnalysisIdx = 0;
        currentAnalysis = allAnalyses[0];
        renderAnalysis();
    } catch (err) {
        console.error(err);
        alert('Analysis failed');
    } finally {
        analyzeBtn.disabled = false;
        analyzeBtn.textContent = 'Analyze';
    }
});

document.querySelectorAll('#viewTabs button').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('#viewTabs button').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        
        const view = btn.dataset.view;
        document.getElementById('appendView').classList.toggle('d-none', view !== 'append');
        document.getElementById('semiView').classList.toggle('d-none', view !== 'semi');
        document.getElementById('fullView').classList.toggle('d-none', view !== 'full');
        document.getElementById('interactiveView').classList.toggle('d-none', view !== 'interactive');
    });
});

function renderAnalysis() {
    analysisSection.classList.remove('d-none');
    
    if (currentAnalysis.is_concatenated) {
        document.getElementById('multiImageNav').classList.add('d-none');
        const infoDiv = document.createElement('div');
        infoDiv.className = 'alert alert-info py-2 mb-3';
        infoDiv.innerHTML = `<small>Concatenated from ${currentAnalysis.source_count} images</small>`;
        const existingInfo = analysisSection.querySelector('.alert-info');
        if (existingInfo) existingInfo.remove();
        analysisSection.querySelector('.col-lg-10').insertBefore(infoDiv, analysisSection.querySelector('.nav-tabs'));
    } else if (allAnalyses.length > 1) {
        document.getElementById('multiImageNav').classList.remove('d-none');
        renderImageThumbs();
    } else {
        document.getElementById('multiImageNav').classList.add('d-none');
    }
    
    renderSliceList(currentAnalysis.slices);
    renderSemiAnnotated();
    
    document.getElementById('fullAnnotatedImage').src = currentAnalysis.full_annotated || currentAnalysis.full_image;
    
    if (currentAnalysis.append_slices && currentAnalysis.append_slices.length > 0) {
        resetAppend();
    }
    
    if (currentAnalysis.slices.length > 0) {
        showSlice(0);
    }
}

function renderImageThumbs() {
    const container = document.getElementById('imageThumbs');
    container.innerHTML = '';
    
    allAnalyses.forEach((analysis, idx) => {
        const div = document.createElement('div');
        div.className = `thumb-item rounded p-1 ${idx === currentAnalysisIdx ? 'active' : ''}`;
        div.innerHTML = `<img src="${analysis.full_image}" class="rounded" style="max-height: 80px; max-width: 100px;">`;
        div.addEventListener('click', () => {
            currentAnalysisIdx = idx;
            currentAnalysis = allAnalyses[idx];
            renderImageThumbs();
            renderAnalysis();
        });
        container.appendChild(div);
    });
}

function renderSemiAnnotated() {
    const container = document.getElementById('semiContainer');
    container.innerHTML = '';
    
    if (currentAnalysis.semi_annotated) {
        const img = document.createElement('img');
        img.src = currentAnalysis.semi_annotated;
        img.className = 'img-fluid rounded';
        img.style.maxWidth = '100%';
        container.appendChild(img);
    } else {
        const img = document.createElement('img');
        img.src = currentAnalysis.full_image;
        img.className = 'img-fluid rounded';
        img.style.maxWidth = '100%';
        container.appendChild(img);
        
        currentAnalysis.slices.forEach((slice, idx) => {
            const iconWrapper = document.createElement('div');
            iconWrapper.className = 'analysis-badge slide-in';
            iconWrapper.style.position = 'absolute';
            iconWrapper.style.top = `${(slice.y_start + slice.y_end) / 2 / currentAnalysis.slices.reduce((max, s) => Math.max(max, s.y_end), 0) * 100}%`;
            iconWrapper.style.right = '10px';
            iconWrapper.style.transform = 'translateY(-50%)';
            
            iconWrapper.innerHTML = `
                <img src="/static/images/${slice.evaluation}.svg" class="semi-annotated-icon">
            `;
            
            setTimeout(() => container.appendChild(iconWrapper), idx * 100);
        });
    }
}

function getEvalColor(evaluation) {
    const colors = {
        brilliant: '#1abc9c',
        great_find: '#1abc9c',
        best: '#1abc9c',
        excellent: '#27ae60',
        good: '#3498db',
        book: '#7f8c8d',
        inaccuracy: '#f1c40f',
        mistake: '#e67e22',
        blunder: '#e74c3c',
        missed_win: '#9b59b6',
        winner: '#f1c40f',
        threat: '#e74c3c',
        take_back: '#e67e22',
        sharp: '#1abc9c',
        mate: '#9b59b6',
        forced: '#7f8c8d',
        free_piece: '#27ae60',
        fast_win: '#1abc9c',
        critical: '#e67e22',
        alternative: '#3498db'
    };
    return colors[evaluation] || '#7f8c8d';
}

function renderSliceList(slices) {
    const container = document.getElementById('sliceList');
    container.innerHTML = '';
    
    slices.forEach((slice, idx) => {
        const div = document.createElement('div');
        div.className = 'slice-item border rounded p-2 mb-2 d-flex align-items-center gap-2';
        div.dataset.idx = idx;
        div.innerHTML = `
            <img src="/static/images/${slice.evaluation}.svg" height="24" alt="${slice.evaluation}">
            <div>
                <div class="small fw-bold">${formatEval(slice.evaluation)}</div>
                <div class="small text-muted truncate">${escapeHtml(slice.explanation.slice(0, 30))}...</div>
            </div>
        `;
        div.addEventListener('click', () => showSlice(idx));
        container.appendChild(div);
    });
}

function showSlice(idx) {
    if (!currentAnalysis || !currentAnalysis.slices[idx]) return;
    
    currentSliceIdx = idx;
    const slice = currentAnalysis.slices[idx];
    
    document.querySelectorAll('.slice-item').forEach((el, i) => {
        el.classList.toggle('active', i === idx);
    });
    
    document.getElementById('interactiveSlice').src = slice.url;
    
    const explContainer = document.getElementById('interactiveExplanation');
    let notableHtml = '';
    if (slice.notable && slice.notable.length > 0) {
        notableHtml = slice.notable.map(n => 
            `<img src="/static/images/${n}.svg" height="20" alt="${n}" title="${formatEval(n)}">`
        ).join(' ');
    }
    
    explContainer.innerHTML = `
        <div class="d-flex align-items-center gap-2 mb-2">
            <img src="/static/images/${slice.evaluation}.svg" height="28">
            <span class="eval-badge eval-${slice.evaluation}">${formatEval(slice.evaluation)}</span>
            ${notableHtml}
        </div>
        <p class="mb-0">${escapeHtml(slice.explanation)}</p>
    `;
}

document.getElementById('playAllBtn').addEventListener('click', () => {
    if (!currentAnalysis || currentAnalysis.slices.length === 0) return;
    
    if (replayInterval) {
        clearInterval(replayInterval);
        replayInterval = null;
        document.getElementById('playAllBtn').textContent = 'Play All';
    } else {
        let idx = 0;
        showSlice(idx);
        replayInterval = setInterval(() => {
            idx++;
            if (idx >= currentAnalysis.slices.length) {
                clearInterval(replayInterval);
                replayInterval = null;
                document.getElementById('playAllBtn').textContent = 'Play All';
            } else {
                showSlice(idx);
            }
        }, 2000);
        document.getElementById('playAllBtn').textContent = 'Stop';
    }
});

document.getElementById('startAppendBtn').addEventListener('click', startAppend);
document.getElementById('stopAppendBtn').addEventListener('click', stopAppend);

function startAppend() {
    if (!currentAnalysis || !currentAnalysis.append_slices || currentAnalysis.append_slices.length === 0) return;
    
    document.getElementById('startAppendBtn').disabled = true;
    document.getElementById('stopAppendBtn').disabled = false;
    
    let idx = 0;
    const total = currentAnalysis.append_slices.length;
    
    showAppendSlice(idx, true);
    
    appendInterval = setInterval(() => {
        idx++;
        if (idx >= total) {
            stopAppend();
        } else {
            showAppendSlice(idx, true);
            document.getElementById('appendProgress').style.width = `${((idx + 1) / total) * 100}%`;
        }
    }, 3000);
}

function stopAppend() {
    if (appendInterval) {
        clearInterval(appendInterval);
        appendInterval = null;
    }
    document.getElementById('startAppendBtn').disabled = false;
    document.getElementById('stopAppendBtn').disabled = true;
    document.getElementById('appendProgress').style.width = '0%';
}

function showAppendSlice(idx, animate = false) {
    if (!currentAnalysis || !currentAnalysis.append_slices[idx]) return;
    
    const slice = currentAnalysis.append_slices[idx];
    const analysisSlice = currentAnalysis.slices[idx];
    
    const img = document.getElementById('appendImage');
    const overlay = document.getElementById('appendOverlay');
    
    let notableHtml = '';
    if (analysisSlice.notable && analysisSlice.notable.length > 0) {
        notableHtml = analysisSlice.notable.map(n => 
            `<img src="/static/images/${n}.svg" height="20" alt="${n}" title="${formatEval(n)}">`
        ).join(' ');
    }
    
    document.getElementById('appendExplanation').innerHTML = `
        <div class="d-flex align-items-center gap-2 mb-2">
            <img src="/static/images/${analysisSlice.evaluation}.svg" height="28">
            <span class="eval-badge eval-${analysisSlice.evaluation}">${formatEval(analysisSlice.evaluation)}</span>
            ${notableHtml}
        </div>
        <p class="mb-0">${escapeHtml(analysisSlice.explanation)}</p>
    `;
    
    if (animate) {
        const tempImg = new Image();
        tempImg.onload = () => {
            overlay.className = 'append-overlay';
            overlay.classList.add(analysisSlice.evaluation);
            overlay.style.opacity = '0.7';
            
            const flyingIcon = document.createElement('img');
            flyingIcon.src = `/static/images/${analysisSlice.evaluation}.svg`;
            flyingIcon.className = 'flying-icon';
            flyingIcon.style.left = '50%';
            flyingIcon.style.top = '50%';
            flyingIcon.style.transform = 'translate(-50%, -50%)';
            document.body.appendChild(flyingIcon);
            
            setTimeout(() => {
                flyingIcon.classList.add('pulse');
            }, 50);
            
            setTimeout(() => {
                const badgeTarget = document.getElementById('appendExplanation');
                const rect = badgeTarget.getBoundingClientRect();
                flyingIcon.style.left = `${rect.left + 40}px`;
                flyingIcon.style.top = `${rect.top + 20}px`;
                flyingIcon.style.width = '32px';
                flyingIcon.style.height = '32px';
                flyingIcon.style.opacity = '0';
            }, 600);
            
            setTimeout(() => {
                flyingIcon.remove();
            }, 1200);
            
            img.src = slice.url;
            img.classList.add('slide-in');
            
            setTimeout(() => {
                overlay.style.opacity = '0';
            }, 200);
            
            setTimeout(() => {
                img.classList.remove('slide-in');
            }, 400);
        };
        tempImg.src = slice.url;
    } else {
        img.src = slice.url;
    }
}

function resetAppend() {
    stopAppend();
    const img = document.getElementById('appendImage');
    img.src = currentAnalysis.append_slices[0].url;
    document.getElementById('appendExplanation').innerHTML = '';
}

function formatEval(evaluation) {
    return evaluation.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
