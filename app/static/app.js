/* ── Audiolivro – frontend ─────────────────────────────────────────────── */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// State
let chapters = [];
let currentChapter = null;   // { index, title, body, sentences, speakers, page_start, page_end, total_chapters }
let currentSentenceIdx = -1;
let audio = null;
let isPlaying = false;
let playSessionId = 0;          // incremented on every new play; stops stale sessions
let resolveCurrentAudio = null; // called by stopPlayback to unblock the current Promise

// Azure: slow → fast. ElevenLabs: 0.70–1.20×.
const SPEED_STEPS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.75, 1.00];
const SPEED_STEPS_ELEVENLABS = [0.70, 0.80, 0.90, 1.00, 1.10, 1.20];
let activeSpeedSteps = SPEED_STEPS;
let speedIdx = SPEED_STEPS.indexOf(0.25);
let speed = SPEED_STEPS[speedIdx];

const REWIND_SENTENCES = 5;

// DOM refs
const menuBtn = $("#menuBtn");
const drawer = $("#drawer");
const drawerOverlay = $("#drawerOverlay");
const drawerClose = $("#drawerClose");
const chapterList = $("#chapterList");
const bookmarkList = $("#bookmarkList");
const bookmarkSectionTitle = $("#bookmarkSectionTitle");
const chapterHeader = $("#chapterHeader");
const chapterTitle = $("#chapterTitle");
const chapterInfo = $("#chapterInfo");
const chapterText = $("#chapterText");
const progressContainer = $("#progressContainer");
const progressBar = $("#progressBar");
const playBtn = $("#playBtn");
const prevBtn = $("#prevBtn");
const nextBtn = $("#nextBtn");
const rewindBtn = $("#rewindBtn");
const forwardBtn = $("#forwardBtn");
const speedSlider = $("#speedSlider");
const speedLabel = $("#speedLabel");
const posSlider = $("#posSlider");
const posLabel = $("#posLabel");
const bookmarkBtn = $("#bookmarkBtn");
const playerProgress = $("#playerProgress");
const continueBanner = $("#continueBanner");
const loading = $("#loading");
const homeScreen = $("#homeScreen");
const chapterView = $("#chapterView");
const chapterGrid = $("#chapterGrid");
const backBtn = $("#backBtn");

// ── Home / Chapter view toggle ──────────────────────────────────────────

function showHome() {
  stopPlayback();
  currentChapter = null;
  homeScreen.style.display = "";
  chapterView.style.display = "none";
  renderChapterGrid();
}

function showChapterView() {
  homeScreen.style.display = "none";
  chapterView.style.display = "";
}

backBtn.addEventListener("click", showHome);

function renderChapterGrid() {
  chapterGrid.innerHTML = "";
  chapters.forEach((ch) => {
    const card = document.createElement("button");
    card.className = "chapter-card";
    if (currentChapter && currentChapter.index === ch.index) card.classList.add("active");
    const isPreface = ch.title.toLowerCase().includes("prefácio") || ch.title.toLowerCase().includes("prefacio");
    const label = isPreface ? ch.title : ch.title;
    const pages = `p. ${ch.page_start}–${ch.page_end}`;
    card.innerHTML = `<span class="card-title">${label}</span><span class="card-pages">${pages}</span>`;
    card.addEventListener("click", () => loadChapter(ch.index, true));
    chapterGrid.appendChild(card);
  });
}

// ── Drawer ──────────────────────────────────────────────────────────────

function openDrawer() {
  drawer.classList.add("open");
  drawerOverlay.classList.add("open");
}
function closeDrawer() {
  drawer.classList.remove("open");
  drawerOverlay.classList.remove("open");
}

menuBtn.addEventListener("click", openDrawer);
drawerOverlay.addEventListener("click", closeDrawer);
drawerClose.addEventListener("click", closeDrawer);

// ── Load chapters ───────────────────────────────────────────────────────

async function loadChapters() {
  const res = await fetch("/api/chapters");
  chapters = await res.json();
  renderChapterList();
}

function renderChapterList() {
  chapterList.innerHTML = "";
  chapters.forEach((ch) => {
    const li = document.createElement("li");
    li.innerHTML = `${ch.title}<span class="page-range">p. ${ch.page_start} a ${ch.page_end}</span>`;
    if (currentChapter && currentChapter.index === ch.index) li.classList.add("active");
    li.addEventListener("click", () => {
      closeDrawer();
      loadChapter(ch.index, true);
    });
    chapterList.appendChild(li);
  });
}

// ── Load bookmarks ──────────────────────────────────────────────────────

async function loadBookmarks() {
  const res = await fetch("/api/bookmarks");
  const bookmarks = await res.json();
  bookmarkList.innerHTML = "";
  if (bookmarks.length === 0) {
    bookmarkSectionTitle.style.display = "none";
    return;
  }
  bookmarkSectionTitle.style.display = "";
  bookmarks.forEach((bm) => {
    const li = document.createElement("li");
    li.className = "bookmark-item";
    li.innerHTML = `${bm.chapter_title}<span class="bm-sentence">${bm.sentence_text}</span>`;
    li.addEventListener("click", () => {
      closeDrawer();
      loadChapter(bm.chapter_index, true, bm.sentence_index);
    });
    bookmarkList.appendChild(li);
  });
}

// ── Load & display a chapter ────────────────────────────────────────────

async function loadChapter(index, autoPlay = false, startSentence = 0) {
  stopPlayback();
  showChapterView();
  const res = await fetch(`/api/chapters/${index}/text`);
  currentChapter = await res.json();
  currentSentenceIdx = startSentence;

  // Update UI
  chapterTitle.textContent = currentChapter.title;
  chapterInfo.textContent =
    `Capítulo ${currentChapter.index + 1} de ${currentChapter.total_chapters} — ` +
    `Páginas ${currentChapter.page_start} a ${currentChapter.page_end}`;

  renderText();
  updateProgress();
  renderChapterList();
  savePosition();
  hideContinueBanner();

  if (autoPlay) {
    playSentences(startSentence);
  }
}

function renderText() {
  if (!currentChapter) return;
  const sentences = currentChapter.sentences;

  // Rebuild body preserving paragraph structure
  const bodyParas = currentChapter.body.split("\n\n");
  let sentenceIdx = 0;
  let html = "";

  for (const para of bodyParas) {
    const trimmed = para.trim();
    if (!trimmed) continue;

    // Match sentences within this paragraph
    let paraHtml = "";
    let remaining = trimmed;
    while (remaining.length > 0 && sentenceIdx < sentences.length) {
      const sent = sentences[sentenceIdx];
      const pos = remaining.indexOf(sent);
      if (pos === -1) break;

      // Any text before the sentence (shouldn't happen normally)
      if (pos > 0) {
        paraHtml += escapeHtml(remaining.substring(0, pos));
      }

      const spk = currentChapter.speakers ? currentChapter.speakers[sentenceIdx] : "ilana";
      let cls = sentenceIdx === currentSentenceIdx ? "sentence active" : "sentence";
      if (spk === "et") cls += " et-speech";
      else if (spk === "baruck") cls += " baruck-speech";
      paraHtml += `<span class="${cls}" data-idx="${sentenceIdx}">${escapeHtml(sent)}</span> `;
      remaining = remaining.substring(pos + sent.length).trimStart();
      sentenceIdx++;
    }
    // Any leftover text in the paragraph
    if (remaining.length > 0) {
      paraHtml += escapeHtml(remaining);
    }

    html += `<p>${paraHtml}</p>`;
  }

  chapterText.innerHTML = html;
  scrollToActive();
}

function escapeHtml(str) {
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML;
}

function scrollToActive() {
  const el = chapterText.querySelector(".sentence.active");
  if (el) {
    el.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

function highlightSentence(idx) {
  const prev = chapterText.querySelector(".sentence.active");
  if (prev) prev.classList.remove("active");
  const el = chapterText.querySelector(`.sentence[data-idx="${idx}"]`);
  if (el) {
    el.classList.add("active");
    el.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  currentSentenceIdx = idx;
  if (!posDragging) updateProgress();
  savePosition();
}

function updateProgress() {
  if (!currentChapter) return;
  const total = currentChapter.sentences.length;
  const pct = total > 0 ? ((currentSentenceIdx + 1) / total) * 100 : 0;
  progressBar.style.width = pct + "%";

  // Sync position slider
  posSlider.max = Math.max(0, total - 1);
  posSlider.value = Math.max(0, currentSentenceIdx);
  posLabel.textContent = `${currentSentenceIdx + 1} / ${total}`;

  // Estimated current page
  const charsRead = currentChapter.sentences
    .slice(0, currentSentenceIdx + 1)
    .reduce((sum, s) => sum + s.length, 0);
  const totalChars = currentChapter.sentences.reduce((sum, s) => sum + s.length, 0);
  const pageRange = currentChapter.page_end - currentChapter.page_start + 1;
  const currentPage =
    totalChars > 0
      ? currentChapter.page_start + Math.floor((charsRead / totalChars) * pageRange)
      : currentChapter.page_start;

  playerProgress.innerHTML =
    `Capítulo ${currentChapter.index + 1} de ${currentChapter.total_chapters}<br>` +
    `Página ~${Math.min(currentPage, currentChapter.page_end)}`;
}

// ── TTS playback ────────────────────────────────────────────────────────

// Group sentences into chunks for TTS.
// Splits at speaker boundaries so narrator and ET never share a chunk.
function buildChunks(sentences, startIdx) {
  const CHUNK_SIZE = 5;
  const speakers = currentChapter && currentChapter.speakers ? currentChapter.speakers : [];
  const chunks = [];
  let i = startIdx;
  while (i < sentences.length) {
    const spk = speakers[i] || "narrator";
    const end = Math.min(i + CHUNK_SIZE, sentences.length);
    let j = i + 1;
    while (j < end) {
      if ((speakers[j] || "narrator") !== spk) break;
      j++;
    }
    chunks.push({
      startIdx: i,
      sentences: sentences.slice(i, j),
      speaker: spk,
    });
    i = j;
  }
  return chunks;
}

// Fetch TTS audio for a chunk, returns Blob or null
async function fetchChunkAudio(chunk, session) {
  const text = chunk.sentences.join("\n\n");
  try {
    const res = await fetch("/api/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, speed, speaker: chunk.speaker || "ilana" }),
    });
    if (playSessionId !== session) return null;
    if (!res.ok) return null;
    applyEffectiveTtsFromHeader(res.headers.get("X-Effective-TTS-Provider"));
    return await res.blob();
  } catch {
    return null;
  }
}

function playBlob(blob, chunk, mySession) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(blob);
    audio = new Audio(url);

    const sentLengths = chunk.sentences.map((s) => s.length);
    const totalLen = sentLengths.reduce((a, b) => a + b, 0);
    const scheduleHighlights = (duration) => {
      let elapsed = 0;
      for (let si = 1; si < chunk.sentences.length; si++) {
        elapsed += sentLengths[si - 1];
        const t = (elapsed / totalLen) * duration;
        const idx = chunk.startIdx + si;
        const sid = mySession;
        setTimeout(() => {
          if ((isPlaying || isPaused) && playSessionId === sid) highlightSentence(idx);
        }, t * 1000);
      }
    };

    resolveCurrentAudio = resolve;

    audio.addEventListener("loadedmetadata", () => scheduleHighlights(audio.duration));
    audio.addEventListener("ended", () => {
      URL.revokeObjectURL(url);
      resolveCurrentAudio = null;
      resolve();
    });
    audio.addEventListener("error", () => {
      URL.revokeObjectURL(url);
      resolveCurrentAudio = null;
      resolve();
    });

    audio.play().catch((e) => {
      console.error("Audio play error:", e);
      resolveCurrentAudio = null;
      resolve();
    });
  });
}

async function playSentences(startIdx = 0) {
  if (!currentChapter) return;

  playSessionId++;
  const mySession = playSessionId;
  isPaused = false;
  if (audio) { audio.pause(); audio.src = ""; audio = null; }
  if (resolveCurrentAudio) { resolveCurrentAudio(); resolveCurrentAudio = null; }

  isPlaying = true;
  playBtn.innerHTML = "&#10074;&#10074;";

  const sentences = currentChapter.sentences;
  const chunks = buildChunks(sentences, startIdx);

  // Read the chapter title with Ilana's voice before the first chunk
  if (startIdx === 0 && chunks.length > 0) {
    loading.classList.add("show");
    // Start prefetching the first real chunk while the title plays
    const firstChunkPromise = fetchChunkAudio(chunks[0], mySession);
    try {
      const titleRes = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: "", speed, chapter_title: currentChapter.title, speaker: "ilana" }),
      });
      if (playSessionId !== mySession) return;
      if (titleRes.ok) {
        const titleBlob = await titleRes.blob();
        if (playSessionId !== mySession) return;
        loading.classList.remove("show");
        const titleUrl = URL.createObjectURL(titleBlob);
        audio = new Audio(titleUrl);
        await new Promise((resolve) => {
          resolveCurrentAudio = resolve;
          audio.onended = resolve;
          audio.onerror = resolve;
          audio.play().catch(resolve);
        });
        resolveCurrentAudio = null;
        URL.revokeObjectURL(titleUrl);
        audio = null;
      }
    } catch { /* continue */ }
    loading.classList.remove("show");
    if (playSessionId !== mySession) return;

    // Wait for pause to be lifted if paused during title
    while (isPaused && playSessionId === mySession) {
      await new Promise(r => { pauseResolve = r; });
    }
    if (playSessionId !== mySession) return;

    // First chunk was prefetched — use it
    const prefetchedBlob = await firstChunkPromise;
    if (playSessionId !== mySession) return;
    if (prefetchedBlob) {
      highlightSentence(chunks[0].startIdx);
      // Start prefetching chunk 2 while chunk 1 plays
      const nextPromise = chunks.length > 1 ? fetchChunkAudio(chunks[1], mySession) : null;
      await playBlob(prefetchedBlob, chunks[0], mySession);
      while (isPaused && playSessionId === mySession) {
        await new Promise(r => { pauseResolve = r; });
      }
      if (playSessionId !== mySession) { if (playSessionId === mySession) { isPlaying = false; playBtn.innerHTML = "&#9654;"; } return; }

      // Continue from chunk index 1 with nextPromise already in flight
      let pendingBlob = nextPromise;
      for (let ci = 1; ci < chunks.length; ci++) {
        if (playSessionId !== mySession) break;
        const blob = pendingBlob ? await pendingBlob : await fetchChunkAudio(chunks[ci], mySession);
        pendingBlob = null;
        if (playSessionId !== mySession || !blob) break;

        highlightSentence(chunks[ci].startIdx);
        // Prefetch next chunk while this one plays
        if (ci + 1 < chunks.length) pendingBlob = fetchChunkAudio(chunks[ci + 1], mySession);
        await playBlob(blob, chunks[ci], mySession);
        while (isPaused && playSessionId === mySession) {
          await new Promise(r => { pauseResolve = r; });
        }
      }
      if (playSessionId === mySession) { isPlaying = false; isPaused = false; playBtn.innerHTML = "&#9654;"; }
      return;
    }
  }

  // Normal loop (non-first-start or title failed): prefetch pipeline
  let pendingBlob = chunks.length > 0 ? fetchChunkAudio(chunks[0], mySession) : null;

  for (let ci = 0; ci < chunks.length; ci++) {
    if (playSessionId !== mySession) break;

    loading.classList.add("show");
    const blob = pendingBlob ? await pendingBlob : await fetchChunkAudio(chunks[ci], mySession);
    pendingBlob = null;
    loading.classList.remove("show");

    if (playSessionId !== mySession || !blob) break;

    highlightSentence(chunks[ci].startIdx);
    if (ci + 1 < chunks.length) pendingBlob = fetchChunkAudio(chunks[ci + 1], mySession);
    await playBlob(blob, chunks[ci], mySession);

    while (isPaused && playSessionId === mySession) {
      await new Promise(r => { pauseResolve = r; });
    }
  }

  if (playSessionId === mySession) {
    isPlaying = false;
    isPaused = false;
    playBtn.innerHTML = "&#9654;";
  }
}

let isPaused = false;
let pauseResolve = null;

function stopPlayback() {
  isPlaying = false;
  isPaused = false;
  playSessionId++;
  playBtn.innerHTML = "&#9654;";
  loading.classList.remove("show");
  if (audio) {
    audio.pause();
    audio.src = "";
    audio = null;
  }
  if (resolveCurrentAudio) {
    resolveCurrentAudio();
    resolveCurrentAudio = null;
  }
  if (pauseResolve) {
    pauseResolve();
    pauseResolve = null;
  }
}

function pausePlayback() {
  isPaused = true;
  isPlaying = false;
  playBtn.innerHTML = "&#9654;";
  if (audio) audio.pause();
}

function resumePlayback() {
  isPaused = false;
  isPlaying = true;
  playBtn.innerHTML = "&#10074;&#10074;";
  if (audio) audio.play().catch(() => {});
  if (pauseResolve) {
    pauseResolve();
    pauseResolve = null;
  }
}

function togglePlay() {
  if (isPaused) {
    resumePlayback();
  } else if (isPlaying) {
    pausePlayback();
  } else if (currentChapter) {
    playSentences(currentSentenceIdx >= 0 ? currentSentenceIdx : 0);
  }
}

// ── Controls ────────────────────────────────────────────────────────────

playBtn.addEventListener("click", togglePlay);

prevBtn.addEventListener("click", () => {
  if (!currentChapter || currentChapter.index <= 0) return;
  loadChapter(currentChapter.index - 1, true);
});

nextBtn.addEventListener("click", () => {
  if (!currentChapter || currentChapter.index + 1 >= currentChapter.total_chapters) return;
  loadChapter(currentChapter.index + 1, true);
});

// Speed slider
function updateSpeedDisplay() {
  speedLabel.textContent = speed.toFixed(2).replace(/0$/, "") + "x";
}

speedSlider.addEventListener("input", () => {
  speedIdx = parseInt(speedSlider.value, 10);
  speed = activeSpeedSteps[speedIdx];
  updateSpeedDisplay();
  localStorage.setItem("audiolivro_speed", speed);
});

// Position slider — drag to jump within chapter
let posDragging = false;
posSlider.addEventListener("pointerdown", () => { posDragging = true; });
posSlider.addEventListener("change", () => {
  if (!currentChapter) return;
  posDragging = false;
  const target = parseInt(posSlider.value, 10);
  const wasPlaying = isPlaying;
  stopPlayback();
  highlightSentence(target);
  if (wasPlaying) playSentences(target);
});
posSlider.addEventListener("input", () => {
  if (!currentChapter) return;
  posLabel.textContent = `${parseInt(posSlider.value, 10) + 1} / ${currentChapter.sentences.length}`;
});

// Rewind / Forward within current chapter
rewindBtn.addEventListener("click", () => {
  if (!currentChapter) return;
  const target = Math.max(0, currentSentenceIdx - REWIND_SENTENCES);
  stopPlayback();
  highlightSentence(target);
  playSentences(target);
});

forwardBtn.addEventListener("click", () => {
  if (!currentChapter) return;
  const lastIdx = currentChapter.sentences.length - 1;
  const target = Math.min(lastIdx, currentSentenceIdx + REWIND_SENTENCES);
  stopPlayback();
  highlightSentence(target);
  playSentences(target);
});

// Bookmark
bookmarkBtn.addEventListener("click", async () => {
  if (!currentChapter) return;
  const sentText = currentChapter.sentences[currentSentenceIdx] || "";
  await fetch("/api/bookmarks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chapter_index: currentChapter.index,
      chapter_title: currentChapter.title,
      sentence_index: currentSentenceIdx,
      sentence_text: sentText,
    }),
  });
  bookmarkBtn.textContent = "Marcado!";
  setTimeout(() => {
    bookmarkBtn.innerHTML = "&#128278; Marcar";
  }, 1500);
  loadBookmarks();
});

// ── Persistence ─────────────────────────────────────────────────────────

function savePosition() {
  if (!currentChapter) return;
  localStorage.setItem(
    "audiolivro_pos",
    JSON.stringify({
      chapter: currentChapter.index,
      sentence: currentSentenceIdx,
    })
  );
}

function restorePosition() {
  const raw = localStorage.getItem("audiolivro_pos");
  if (!raw) return;
  try {
    const pos = JSON.parse(raw);
    const ch = chapters.find((c) => c.index === pos.chapter);
    if (ch) {
      continueBanner.textContent = `Continuar do ${ch.title}`;
      continueBanner.style.display = "";
      continueBanner.addEventListener(
        "click",
        () => {
          loadChapter(pos.chapter, true, pos.sentence);
        },
        { once: true }
      );
    }
  } catch {
    // ignore
  }
}

function hideContinueBanner() {
  continueBanner.style.display = "none";
}

function pickSpeedIndexForSaved(parsed) {
  let bestIdx = 0;
  let bestDist = Math.abs(activeSpeedSteps[0] - parsed);
  for (let i = 1; i < activeSpeedSteps.length; i++) {
    const d = Math.abs(activeSpeedSteps[i] - parsed);
    if (d < bestDist) { bestDist = d; bestIdx = i; }
  }
  return bestIdx;
}

function applySavedSpeed() {
  const savedSpeed = localStorage.getItem("audiolivro_speed");
  if (savedSpeed) {
    const parsed = parseFloat(savedSpeed);
    speedIdx = pickSpeedIndexForSaved(parsed);
    speed = activeSpeedSteps[speedIdx];
  } else {
    speedIdx = activeSpeedSteps === SPEED_STEPS_ELEVENLABS
      ? SPEED_STEPS_ELEVENLABS.indexOf(0.90)
      : SPEED_STEPS.indexOf(0.25);
    speed = activeSpeedSteps[speedIdx];
  }
  speedSlider.value = speedIdx;
  updateSpeedDisplay();
}

function setSpeedMode(mode) {
  activeSpeedSteps = mode === "elevenlabs" ? SPEED_STEPS_ELEVENLABS : SPEED_STEPS;
  speedSlider.max = activeSpeedSteps.length - 1;
  if (activeSpeedSteps.length <= 1) {
    speedSlider.style.display = "none";
  } else {
    speedSlider.style.display = "";
    speedSlider.disabled = false;
    speedSlider.removeAttribute("aria-disabled");
  }
  applySavedSpeed();
}

function applyEffectiveTtsFromHeader(header) {
  // Per-request provider (fallback) — não confundir com /api/config (provedor configurado).
  if (header === "azure") setSpeedMode("azure");
  else if (header === "elevenlabs") setSpeedMode("elevenlabs");
}

async function applyServerConfig() {
  try {
    const res = await fetch("/api/config");
    const cfg = await res.json();
    if (cfg.speed_step_mode === "elevenlabs") {
      setSpeedMode("elevenlabs");
    } else {
      setSpeedMode("azure");
    }
  } catch {
    setSpeedMode("azure");
  }
}

// ── Init ────────────────────────────────────────────────────────────────

(async function init() {
  await applyServerConfig();
  await loadChapters();
  await loadBookmarks();
  restorePosition();
  renderChapterGrid();
})();
