/**
 * ExamCrop AI - Frontend Application Logic
 * 모의고사 20문제 130% 자동 분할 추출기
 */

document.addEventListener('DOMContentLoaded', () => {
  // ==========================================
  // App State
  // ==========================================
  const state = {
    apiKey: localStorage.getItem('gemini_api_key') || '',
    sessionId: null,
    pdfFilename: '',
    pages: [], // [{page_num, preview_url, width, height}]
    currentPageNum: 1,
    questions: [], // [{question_number, page_num, box_2d: [ymin, xmin, ymax, xmax]}]
    croppedResults: [],
    selectedBoxIndex: null,
    zoomRatio: 1.30,
    padding: 9,
    detectionMode: 'hybrid',
    currentStep: 1,
  };

  // ==========================================
  // DOM Elements
  // ==========================================
  const elements = {
    // Steppers
    stepIndicator1: document.getElementById('stepIndicator1'),
    stepIndicator2: document.getElementById('stepIndicator2'),
    stepIndicator3: document.getElementById('stepIndicator3'),
    stepLine1: document.getElementById('stepLine1'),
    stepLine2: document.getElementById('stepLine2'),

    // Sections
    sectionUpload: document.getElementById('sectionUpload'),
    sectionDetect: document.getElementById('sectionDetect'),
    sectionResults: document.getElementById('sectionResults'),

    // Upload
    dropzone: document.getElementById('dropzone'),
    pdfFileInput: document.getElementById('pdfFileInput'),
    detectModeSelect: document.getElementById('detectModeSelect'),
    marginPaddingSelect: document.getElementById('marginPaddingSelect'),
    zoomSelector: document.getElementById('zoomSelector'),

    // Detection & Canvas
    pageTabsContainer: document.getElementById('pageTabsContainer'),
    canvasWrapper: document.getElementById('canvasWrapper'),
    pagePreviewImage: document.getElementById('pagePreviewImage'),
    boxOverlay: document.getElementById('boxOverlay'),
    pageQuestionsList: document.getElementById('pageQuestionsList'),
    detectedCountBadge: document.getElementById('detectedCountBadge'),
    btnBackToUpload: document.getElementById('btnBackToUpload'),
    btnAutoCropAll: document.getElementById('btnAutoCropAll'),
    btnAddManualBox: document.getElementById('btnAddManualBox'),
    btnResetPageBoxes: document.getElementById('btnResetPageBoxes'),

    // Results Gallery
    galleryGrid: document.getElementById('galleryGrid'),
    resultTotalBadge: document.getElementById('resultTotalBadge'),
    btnDownloadZip: document.getElementById('btnDownloadZip'),
    btnBackToEdit: document.getElementById('btnBackToEdit'),
    btnNewPdf: document.getElementById('btnNewPdf'),
    btnBottomNewPdf: document.getElementById('btnBottomNewPdf'),
    btnBottomDownloadZip: document.getElementById('btnBottomDownloadZip'),

    // Modals & Overlays
    loadingOverlay: document.getElementById('loadingOverlay'),
    loadingTitle: document.getElementById('loadingTitle'),
    loadingDesc: document.getElementById('loadingDesc'),
    progressBarFill: document.getElementById('progressBarFill'),

    // API Key Modal
    apiKeyModal: document.getElementById('apiKeyModal'),
    btnOpenApiKeyModal: document.getElementById('btnOpenApiKeyModal'),
    btnCloseApiKeyModal: document.getElementById('btnCloseApiKeyModal'),
    inputGeminiApiKey: document.getElementById('inputGeminiApiKey'),
    btnToggleApiKeyVisibility: document.getElementById('btnToggleApiKeyVisibility'),
    btnTestApiKey: document.getElementById('btnTestApiKey'),
    btnSaveApiKey: document.getElementById('btnSaveApiKey'),
    apiKeyTestResult: document.getElementById('apiKeyTestResult'),
    apiKeyStatusText: document.getElementById('apiKeyStatusText'),

    // Lightbox
    lightboxModal: document.getElementById('lightboxModal'),
    btnCloseLightbox: document.getElementById('btnCloseLightbox'),
    lightboxTitle: document.getElementById('lightboxTitle'),
    lightboxImg: document.getElementById('lightboxImg'),
    btnLightboxCopy: document.getElementById('btnLightboxCopy'),
    btnLightboxDownload: document.getElementById('btnLightboxDownload'),

    // Toast
    toastContainer: document.getElementById('toastContainer'),
  };

  // ==========================================
  // Initialization
  // ==========================================
  initApiKeyStatus();
  bindEvents();

  function initApiKeyStatus() {
    if (state.apiKey) {
      elements.apiKeyStatusText.textContent = 'Gemini API 키 등록됨';
      elements.inputGeminiApiKey.value = state.apiKey;
    } else {
      elements.apiKeyStatusText.textContent = 'Gemini API 키 설정';
    }
  }

  // ==========================================
  // Event Bindings
  // ==========================================
  function bindEvents() {
    // Zoom selector
    elements.zoomSelector.addEventListener('change', (e) => {
      state.zoomRatio = parseFloat(e.target.value);
      showToast(`추출 배율이 ${Math.round(state.zoomRatio * 100)}%로 설정되었습니다.`, 'info');
    });

    // Padding selector
    elements.marginPaddingSelect.addEventListener('change', (e) => {
      state.padding = parseInt(e.target.value, 10);
    });

    // Detect mode
    elements.detectModeSelect.addEventListener('change', (e) => {
      state.detectionMode = e.target.value;
    });

    // Drag & Drop Upload
    const dropzone = elements.dropzone;
    dropzone.addEventListener('click', () => elements.pdfFileInput.click());
    
    ['dragenter', 'dragover'].forEach(eventName => {
      dropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        dropzone.classList.add('drag-over');
      });
    });

    ['dragleave', 'drop'].forEach(eventName => {
      dropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        dropzone.classList.remove('drag-over');
      });
    });

    dropzone.addEventListener('drop', (e) => {
      const files = e.dataTransfer.files;
      if (files.length > 0 && files[0].name.toLowerCase().endsWith('.pdf')) {
        handleFileUpload(files[0]);
      } else {
        showToast('PDF 파일만 업로드할 수 있습니다.', 'error');
      }
    });

    elements.pdfFileInput.addEventListener('change', (e) => {
      if (e.target.files.length > 0) {
        handleFileUpload(e.target.files[0]);
      }
    });

    // Crop Button
    elements.btnAutoCropAll.addEventListener('click', executeCrop);

    // Return to Step 1 handlers
    if (elements.btnBackToUpload) {
      elements.btnBackToUpload.addEventListener('click', () => {
        resetToStep1(false);
      });
    }

    if (elements.btnNewPdf) {
      elements.btnNewPdf.addEventListener('click', () => {
        resetToStep1(true);
      });
    }

    if (elements.btnBottomNewPdf) {
      elements.btnBottomNewPdf.addEventListener('click', () => {
        resetToStep1(true);
      });
    }

    // Stepper navigation clicks
    elements.stepIndicator1.addEventListener('click', () => {
      if (state.currentStep > 1) {
        resetToStep1(true);
      }
    });

    elements.stepIndicator2.addEventListener('click', () => {
      if (state.currentStep === 3) {
        setStep(2);
      }
    });

    // Back to edit
    elements.btnBackToEdit.addEventListener('click', () => {
      setStep(2);
    });

    // Reset boxes on current page
    elements.btnResetPageBoxes.addEventListener('click', resetCurrentPageBoxes);

    // Add manual box
    elements.btnAddManualBox.addEventListener('click', addManualBoxToPage);

    // Image resize sync for canvas overlay
    window.addEventListener('resize', renderOverlayBoxes);
    elements.pagePreviewImage.addEventListener('load', renderOverlayBoxes);

    // API Key Modal Events
    elements.btnOpenApiKeyModal.addEventListener('click', () => {
      elements.inputGeminiApiKey.value = state.apiKey;
      elements.apiKeyTestResult.className = 'test-result-msg';
      elements.apiKeyTestResult.textContent = '';
      elements.apiKeyModal.classList.add('active');
    });

    elements.btnCloseApiKeyModal.addEventListener('click', () => {
      elements.apiKeyModal.classList.remove('active');
    });

    elements.btnToggleApiKeyVisibility.addEventListener('click', () => {
      const type = elements.inputGeminiApiKey.getAttribute('type') === 'password' ? 'text' : 'password';
      elements.inputGeminiApiKey.setAttribute('type', type);
      elements.btnToggleApiKeyVisibility.innerHTML = type === 'password' 
        ? '<i class="fa-solid fa-eye"></i>' 
        : '<i class="fa-solid fa-eye-slash"></i>';
    });

    elements.btnTestApiKey.addEventListener('click', testApiKey);
    elements.btnSaveApiKey.addEventListener('click', saveApiKey);

    // Lightbox Events
    elements.btnCloseLightbox.addEventListener('click', () => {
      elements.lightboxModal.classList.remove('active');
    });

    elements.lightboxModal.addEventListener('click', (e) => {
      if (e.target === elements.lightboxModal) {
        elements.lightboxModal.classList.remove('active');
      }
    });
  }

  // ==========================================
  // Step Navigation & State Reset
  // ==========================================
  function setStep(stepNum) {
    state.currentStep = stepNum;

    // Reset indicator classes
    [elements.stepIndicator1, elements.stepIndicator2, elements.stepIndicator3].forEach((ind, idx) => {
      if (idx + 1 <= stepNum) {
        ind.classList.add('active');
      } else {
        ind.classList.remove('active');
      }
    });

    // Stepper clickable states
    if (stepNum > 1) {
      elements.stepIndicator1.classList.add('clickable');
      elements.stepIndicator1.title = '1단계로 돌아가기 (새 PDF 선택)';
    } else {
      elements.stepIndicator1.classList.remove('clickable');
      elements.stepIndicator1.removeAttribute('title');
    }

    if (stepNum === 3) {
      elements.stepIndicator2.classList.add('clickable');
      elements.stepIndicator2.title = '2단계로 돌아가기 (문제 영역 수정)';
    } else {
      elements.stepIndicator2.classList.remove('clickable');
      elements.stepIndicator2.removeAttribute('title');
    }

    elements.stepLine1.classList.toggle('active', stepNum >= 2);
    elements.stepLine2.classList.toggle('active', stepNum >= 3);

    // Show active section
    elements.sectionUpload.classList.toggle('active', stepNum === 1);
    elements.sectionDetect.classList.toggle('active', stepNum === 2);
    elements.sectionResults.classList.toggle('active', stepNum === 3);

    if (stepNum === 2) {
      setTimeout(renderOverlayBoxes, 100);
    }
  }

  function resetToStep1(promptConfirm = false) {
    if (promptConfirm && state.currentStep === 3 && state.croppedResults.length > 0) {
      const proceed = confirm('새로운 PDF 작업을 시작하면 현재 결과가 초기화됩니다. 1단계로 돌아가시겠습니까?');
      if (!proceed) return;
    }

    // 1. Reset state (keep user preference settings like apiKey, zoomRatio, padding, detectionMode)
    state.sessionId = null;
    state.pdfFilename = '';
    state.pages = [];
    state.currentPageNum = 1;
    state.questions = [];
    state.croppedResults = [];
    state.selectedBoxIndex = null;

    // 2. Reset DOM elements
    elements.pdfFileInput.value = '';
    elements.pagePreviewImage.src = '';
    elements.boxOverlay.innerHTML = '';
    elements.pageQuestionsList.innerHTML = '';
    elements.galleryGrid.innerHTML = '';
    elements.pageTabsContainer.innerHTML = '';
    elements.detectedCountBadge.textContent = '총 0개 문제 검출됨';
    elements.resultTotalBadge.textContent = '0 / 20 문제 완료';

    if (elements.btnDownloadZip) {
      elements.btnDownloadZip.href = '#';
      elements.btnDownloadZip.removeAttribute('download');
    }
    if (elements.btnBottomDownloadZip) {
      elements.btnBottomDownloadZip.href = '#';
      elements.btnBottomDownloadZip.removeAttribute('download');
    }

    // 3. Switch to Step 1
    setStep(1);
    showToast('새로운 모의고사 PDF를 업로드할 준비가 되었습니다.', 'info');
  }

  // ==========================================
  // File Upload & Detection Pipeline
  // ==========================================
  async function handleFileUpload(file) {
    state.pdfFilename = file.name;
    showLoading('PDF 업로드 중...', '모의고사 시험지 페이지를 고해상도로 렌더링하고 있습니다.', 25);

    const formData = new FormData();
    formData.append('file', file);

    try {
      // 1. Upload PDF
      const uploadRes = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
      });

      if (!uploadRes.ok) {
        const err = await uploadRes.json();
        throw new Error(err.detail || '업로드 실패');
      }

      const uploadData = await uploadRes.json();
      state.sessionId = uploadData.session_id;
      state.pages = uploadData.pages;
      state.currentPageNum = 1;

      // 2. Start Detection
      updateLoading('문제 영역 AI 검출 중...', 'Google Gemini Vision AI 및 시험지 레이아웃을 분석 중입니다.', 60);

      const detectPayload = {
        session_id: state.sessionId,
        api_key: state.apiKey || null,
        model_name: 'gemini-3.6-flash',
        detection_mode: state.detectionMode,
      };

      const detectRes = await fetch('/api/detect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(detectPayload),
      });

      if (!detectRes.ok) {
        const err = await detectRes.json();
        throw new Error(err.detail || '문제 검출 실패');
      }

      const detectData = await detectRes.json();
      state.questions = detectData.questions;

      hideLoading();
      showToast(`총 ${state.questions.length}개 문제 영역이 검출되었습니다.`, 'success');

      // Setup Step 2
      setupPageTabs();
      loadPagePreview(1);
      setStep(2);

    } catch (err) {
      hideLoading();
      showToast(`오류: ${err.message}`, 'error');
    }
  }

  // ==========================================
  // Step 2: Page Tabs & Interactive Canvas
  // ==========================================
  function setupPageTabs() {
    elements.pageTabsContainer.innerHTML = '';
    state.pages.forEach((page) => {
      const btn = document.createElement('button');
      btn.className = `page-tab-btn ${page.page_num === state.currentPageNum ? 'active' : ''}`;
      
      const qCount = state.questions.filter(q => q.page_num === page.page_num).length;
      btn.innerHTML = `<i class="fa-regular fa-file-image"></i> ${page.page_num} 페이지 <span class="badge-accent">${qCount}문제</span>`;

      btn.addEventListener('click', () => {
        state.currentPageNum = page.page_num;
        document.querySelectorAll('.page-tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        loadPagePreview(page.page_num);
      });

      elements.pageTabsContainer.appendChild(btn);
    });

    elements.detectedCountBadge.textContent = `총 ${state.questions.length}개 문제 검출됨`;
  }

  function loadPagePreview(pageNum) {
    const pageData = state.pages.find(p => p.page_num === pageNum);
    if (!pageData) return;

    elements.pagePreviewImage.src = pageData.preview_url;
    renderPageSidebarQuestions();
  }

  function renderPageSidebarQuestions() {
    elements.pageQuestionsList.innerHTML = '';
    const pageQs = state.questions
      .filter(q => q.page_num === state.currentPageNum)
      .sort((a, b) => a.question_number - b.question_number);

    if (pageQs.length === 0) {
      elements.pageQuestionsList.innerHTML = `<div style="color:var(--text-muted);font-size:0.85rem;text-align:center;padding:1rem;">이 페이지에 등록된 문제가 없습니다.</div>`;
      return;
    }

    pageQs.forEach(q => {
      const item = document.createElement('div');
      item.className = `page-q-item ${state.selectedBoxIndex === q.question_number ? 'active' : ''}`;
      item.dataset.qnum = q.question_number;
      item.innerHTML = `
        <span class="q-badge"><i class="fa-solid fa-hashtag"></i> 문제 ${q.question_number}번</span>
        <button class="btn-input-action text-accent delete-q-btn" title="삭제"><i class="fa-solid fa-trash-can"></i></button>
      `;

      item.addEventListener('click', (e) => {
        if (e.target.closest('.delete-q-btn')) {
          deleteQuestion(q.question_number);
          return;
        }
        highlightQuestion(q.question_number);
      });

      elements.pageQuestionsList.appendChild(item);
    });
  }

  function deleteQuestion(qNum) {
    state.questions = state.questions.filter(q => q.question_number !== qNum);
    renderOverlayBoxes();
    renderPageSidebarQuestions();
    setupPageTabs();
    showToast(`문제 ${qNum}번 영역이 삭제되었습니다.`, 'info');
  }

  function highlightQuestion(qNum) {
    state.selectedBoxIndex = qNum;
    // Fast in-place class toggle without re-rendering DOM elements
    document.querySelectorAll('.crop-bounding-box').forEach(el => {
      el.classList.toggle('selected', el.dataset.qnum == qNum);
    });
    document.querySelectorAll('.page-q-item').forEach(el => {
      el.classList.toggle('active', el.dataset.qnum == qNum);
    });
  }

  function resetCurrentPageBoxes() {
    showToast(`${state.currentPageNum}페이지 영역을 기본 2단 레이아웃으로 초기화합니다.`, 'info');
    renderOverlayBoxes();
  }

  function addManualBoxToPage() {
    const existingNums = state.questions.map(q => q.question_number);
    let nextNum = 1;
    while (existingNums.includes(nextNum)) {
      nextNum++;
    }

    const newBox = {
      question_number: nextNum,
      page_num: state.currentPageNum,
      box_2d: [120, 25, 380, 485],
      source: 'manual'
    };

    state.questions.push(newBox);
    state.selectedBoxIndex = nextNum;
    renderOverlayBoxes();
    renderPageSidebarQuestions();
    setupPageTabs();
    showToast(`새 문제 영역 (${nextNum}번)이 추가되었습니다. 사각형을 원하는 위치로 드래그하세요.`, 'success');
  }

  // ==========================================
  // Interactive Bounding Boxes Overlay
  // ==========================================
  function renderOverlayBoxes() {
    const img = elements.pagePreviewImage;
    if (!img.complete || img.naturalWidth === 0) return;

    const imgWidth = img.clientWidth;
    const imgHeight = img.clientHeight;

    elements.boxOverlay.style.width = `${imgWidth}px`;
    elements.boxOverlay.style.height = `${imgHeight}px`;
    elements.boxOverlay.innerHTML = '';

    const pageQs = state.questions.filter(q => q.page_num === state.currentPageNum);

    pageQs.forEach(q => {
      const [ymin, xmin, ymax, xmax] = q.box_2d;

      // 0-1000 coordinates to display pixels
      const top = (ymin / 1000.0) * imgHeight;
      const left = (xmin / 1000.0) * imgWidth;
      const width = ((xmax - xmin) / 1000.0) * imgWidth;
      const height = ((ymax - ymin) / 1000.0) * imgHeight;

      const boxEl = document.createElement('div');
      boxEl.className = `crop-bounding-box ${state.selectedBoxIndex === q.question_number ? 'selected' : ''}`;
      boxEl.dataset.qnum = q.question_number;
      boxEl.style.top = `${top}px`;
      boxEl.style.left = `${left}px`;
      boxEl.style.width = `${width}px`;
      boxEl.style.height = `${height}px`;

      boxEl.innerHTML = `
        <div class="crop-box-label">문제 ${q.question_number}번</div>
        <div class="box-resize-handle handle-n" data-handle="n"></div>
        <div class="box-resize-handle handle-s" data-handle="s"></div>
        <div class="box-resize-handle handle-w" data-handle="w"></div>
        <div class="box-resize-handle handle-e" data-handle="e"></div>
        <div class="box-resize-handle handle-se" data-handle="se"></div>
        <div class="box-resize-handle handle-sw" data-handle="sw"></div>
        <div class="box-resize-handle handle-ne" data-handle="ne"></div>
        <div class="box-resize-handle handle-nw" data-handle="nw"></div>
      `;

      // Enable ultra-smooth draggable and resizable interaction
      enableBoxInteraction(boxEl, q, imgWidth, imgHeight);

      elements.boxOverlay.appendChild(boxEl);
    });
  }

  function enableBoxInteraction(boxEl, questionObj, imgWidth, imgHeight) {
    boxEl.addEventListener('mousedown', (e) => {
      // Direct fast selection without re-creating DOM
      highlightQuestion(questionObj.question_number);

      const handle = e.target.dataset.handle;
      const isResizing = Boolean(handle);
      const isDragging = !isResizing;

      const startX = e.clientX;
      const startY = e.clientY;
      const startLeft = parseFloat(boxEl.style.left);
      const startTop = parseFloat(boxEl.style.top);
      const startWidth = parseFloat(boxEl.style.width);
      const startHeight = parseFloat(boxEl.style.height);

      e.stopPropagation();
      e.preventDefault();

      boxEl.classList.add('is-dragging');
      document.body.style.userSelect = 'none';

      let rafId = null;

      const onMouseMove = (moveEvent) => {
        moveEvent.preventDefault();
        const dx = moveEvent.clientX - startX;
        const dy = moveEvent.clientY - startY;

        if (rafId) cancelAnimationFrame(rafId);

        rafId = requestAnimationFrame(() => {
          let curLeft = startLeft;
          let curTop = startTop;
          let curWidth = startWidth;
          let curHeight = startHeight;

          if (isDragging) {
            curLeft = Math.max(0, Math.min(imgWidth - startWidth, startLeft + dx));
            curTop = Math.max(0, Math.min(imgHeight - startHeight, startTop + dy));
          } else if (isResizing) {
            if (handle.includes('e')) {
              curWidth = Math.max(30, Math.min(imgWidth - startLeft, startWidth + dx));
            }
            if (handle.includes('s')) {
              curHeight = Math.max(20, Math.min(imgHeight - startTop, startHeight + dy));
            }
            if (handle.includes('w')) {
              const newWidth = startWidth - dx;
              if (newWidth >= 30 && startLeft + dx >= 0) {
                curLeft = startLeft + dx;
                curWidth = newWidth;
              }
            }
            if (handle.includes('n')) {
              const newHeight = startHeight - dy;
              if (newHeight >= 20 && startTop + dy >= 0) {
                curTop = startTop + dy;
                curHeight = newHeight;
              }
            }
          }

          boxEl.style.left = `${curLeft}px`;
          boxEl.style.top = `${curTop}px`;
          boxEl.style.width = `${curWidth}px`;
          boxEl.style.height = `${curHeight}px`;

          // Sync normalized 0~1000 coordinates
          questionObj.box_2d = [
            Math.max(0, Math.min(1000, Math.round((curTop / imgHeight) * 1000))),
            Math.max(0, Math.min(1000, Math.round((curLeft / imgWidth) * 1000))),
            Math.max(0, Math.min(1000, Math.round(((curTop + curHeight) / imgHeight) * 1000))),
            Math.max(0, Math.min(1000, Math.round(((curLeft + curWidth) / imgWidth) * 1000))),
          ];
        });
      };

      const onMouseUp = () => {
        if (rafId) cancelAnimationFrame(rafId);
        boxEl.classList.remove('is-dragging');
        document.body.style.userSelect = '';
        window.removeEventListener('mousemove', onMouseMove);
        window.removeEventListener('mouseup', onMouseUp);
      };

      window.addEventListener('mousemove', onMouseMove);
      window.addEventListener('mouseup', onMouseUp);
    });
  }

  // ==========================================
  // Step 3: Cropping & 20-Question Results
  // ==========================================
  async function executeCrop() {
    if (state.questions.length === 0) {
      showToast('검출된 문제가 없습니다.', 'error');
      return;
    }

    const zoomPercent = Math.round(state.zoomRatio * 100);
    showLoading(
      `${zoomPercent}% 확대 해상도로 크롭 중...`,
      `총 ${state.questions.length}개의 문제를 고화질로 잘라내고 ZIP 패키지를 생성하고 있습니다.`,
      40
    );

    try {
      const payload = {
        session_id: state.sessionId,
        questions: state.questions,
        zoom_ratio: state.zoomRatio,
        padding: state.padding,
      };

      const res = await fetch('/api/crop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || '이미지 크롭 실패');
      }

      const resultData = await res.json();
      state.croppedResults = resultData.questions;

      // Update download zip buttons
      elements.btnDownloadZip.href = resultData.zip_url;
      elements.btnDownloadZip.setAttribute('download', `모의고사_20문제_130프로_추출_${state.sessionId}.zip`);
      if (elements.btnBottomDownloadZip) {
        elements.btnBottomDownloadZip.href = resultData.zip_url;
        elements.btnBottomDownloadZip.setAttribute('download', `모의고사_20문제_130프로_추출_${state.sessionId}.zip`);
      }
      elements.resultTotalBadge.textContent = `${resultData.total_questions} / 20 문제 완료 (${zoomPercent}% 확대 해상도)`;

      renderResultsGallery();

      hideLoading();
      setStep(3);
      showToast(`20문제 이미지가 ${zoomPercent}% 확대 해상도로 완벽하게 추출되었습니다!`, 'success');

    } catch (err) {
      hideLoading();
      showToast(`오류 발생: ${err.message}`, 'error');
    }
  }

  function renderResultsGallery() {
    elements.galleryGrid.innerHTML = '';

    state.croppedResults.forEach(item => {
      const card = document.createElement('div');
      card.className = 'q-card';

      card.innerHTML = `
        <div class="q-card-header">
          <span class="q-num-tag"><i class="fa-solid fa-circle-question"></i> 문제 ${item.question_number}번</span>
          <span class="q-page-tag">${item.page_num}페이지 (${item.width}×${item.height}px)</span>
        </div>
        <div class="q-image-wrap">
          <img src="${item.image_url}" alt="문제 ${item.question_number}번" loading="lazy">
          <div class="q-hover-zoom">
            <i class="fa-solid fa-magnifying-glass-plus"></i>
          </div>
        </div>
        <div class="q-card-actions">
          <button class="btn btn-glass btn-sm btn-card-copy"><i class="fa-regular fa-copy"></i> 복사</button>
          <a href="${item.image_url}" download="문제_${String(item.question_number).padStart(2, '0')}.png" class="btn btn-primary btn-sm"><i class="fa-solid fa-download"></i> 저장</a>
        </div>
      `;

      // Lightbox on image click
      const imgWrap = card.querySelector('.q-image-wrap');
      imgWrap.addEventListener('click', () => openLightbox(item));

      // Copy to clipboard
      const copyBtn = card.querySelector('.btn-card-copy');
      copyBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        copyImageToClipboard(item.image_url, item.question_number);
      });

      elements.galleryGrid.appendChild(card);
    });
  }

  // ==========================================
  // Clipboard Copy & Lightbox
  // ==========================================
  async function copyImageToClipboard(imageUrl, qNum) {
    try {
      const response = await fetch(imageUrl);
      const blob = await response.blob();

      // Ensure PNG blob for clipboard
      const pngBlob = blob.type === 'image/png' ? blob : new Blob([blob], { type: 'image/png' });

      await navigator.clipboard.write([
        new ClipboardItem({ 'image/png': pngBlob })
      ]);
      showToast(`문제 ${qNum}번 이미지가 클립보드에 복사되었습니다! (Ctrl+V로 붙여넣기 가능)`, 'success');
    } catch (err) {
      showToast(`클립보드 복사 실패 (브라우저 권한 필요): ${err.message}`, 'error');
    }
  }

  function openLightbox(item) {
    elements.lightboxTitle.textContent = `문제 ${item.question_number}번 (${Math.round(state.zoomRatio * 100)}% 확대 고화질)`;
    elements.lightboxImg.src = item.image_url;
    elements.btnLightboxDownload.href = item.image_url;
    elements.btnLightboxDownload.setAttribute('download', `문제_${String(item.question_number).padStart(2, '0')}.png`);

    elements.btnLightboxCopy.onclick = () => {
      copyImageToClipboard(item.image_url, item.question_number);
    };

    elements.lightboxModal.classList.add('active');
  }

  // ==========================================
  // Gemini API Key Management
  // ==========================================
  async function testApiKey() {
    const key = elements.inputGeminiApiKey.value.trim();
    if (!key) {
      showApiKeyMsg('API 키를 입력해주세요.', 'error');
      return;
    }

    elements.btnTestApiKey.disabled = true;
    elements.btnTestApiKey.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 테스트 중...';

    try {
      const res = await fetch('/api/verify-gemini-key', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: key }),
      });
      const data = await res.json();

      if (data.success) {
        showApiKeyMsg('✓ Google Gemini API 키가 정상적으로 확인되었습니다!', 'success');
      } else {
        showApiKeyMsg(`✕ 인증 실패: ${data.message}`, 'error');
      }
    } catch (e) {
      showApiKeyMsg(`✕ 테스트 오류: ${e.message}`, 'error');
    } finally {
      elements.btnTestApiKey.disabled = false;
      elements.btnTestApiKey.innerHTML = '<i class="fa-solid fa-circle-check"></i> 연결 테스트';
    }
  }

  function saveApiKey() {
    const key = elements.inputGeminiApiKey.value.trim();
    state.apiKey = key;
    if (key) {
      localStorage.setItem('gemini_api_key', key);
      showToast('Gemini API 키가 안전하게 저장되었습니다.', 'success');
    } else {
      localStorage.removeItem('gemini_api_key');
      showToast('Gemini API 키가 제거되었습니다.', 'info');
    }
    initApiKeyStatus();
    elements.apiKeyModal.classList.remove('active');
  }

  function showApiKeyMsg(msg, type) {
    elements.apiKeyTestResult.textContent = msg;
    elements.apiKeyTestResult.className = `test-result-msg ${type}`;
  }

  // ==========================================
  // Loading & Toast Helpers
  // ==========================================
  function showLoading(title, desc, percent = 50) {
    elements.loadingTitle.textContent = title;
    elements.loadingDesc.textContent = desc;
    elements.progressBarFill.style.width = `${percent}%`;
    elements.loadingOverlay.classList.add('active');
  }

  function updateLoading(title, desc, percent) {
    elements.loadingTitle.textContent = title;
    elements.loadingDesc.textContent = desc;
    elements.progressBarFill.style.width = `${percent}%`;
  }

  function hideLoading() {
    elements.loadingOverlay.classList.remove('active');
  }

  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    let icon = 'fa-info-circle';
    if (type === 'success') icon = 'fa-check-circle';
    if (type === 'error') icon = 'fa-triangle-exclamation';

    toast.innerHTML = `<i class="fa-solid ${icon}"></i> <span>${message}</span>`;
    elements.toastContainer.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  }
});
