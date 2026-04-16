/**
 * PDFViewer — lecteur PDF embarquable dans un div
 *
 * Dépendance : pdf.js 3.11.174
 *   <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
 *
 * Usage :
 *   const viewer = PDFViewer('mon-div-id', { onZoomChange: z => console.log(z) });
 *   viewer.load('fichier.pdf');
 *   // ou
 *   viewer.loadBlob(fileInputEvent.target.files[0]);
 *
 * CSS minimale requise sur le div conteneur :
 *   #mon-div { width: 800px; height: 600px; overflow: auto; }
 *
 * API publique :
 *   viewer.load(url)
 *   viewer.loadBlob(blob)
 *   viewer.zoomIn()
 *   viewer.zoomOut()
 *   viewer.fitWidth()
 *   viewer.setZoom(scale)          — scale absolu, ex: 1.5
 *   viewer.setMode('pan' | 'highlight' | 'select')
 *   viewer.addHighlight(page, rx, ry, rw, rh)   — coordonnées en unités PDF (indépendantes du zoom)
 *   viewer.clearHighlights()
 *   viewer.scrollToRegion(page, rx, ry, rw, rh) — scroll vers la zone + surligne
 */
function PDFViewer(containerId, options = {}) {

  /* ── Worker pdf.js ── */
  pdfjsLib.GlobalWorkerOptions.workerSrc =
    'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

  /* ── Éléments DOM ── */
  const container = document.getElementById(containerId);
  if (!container) throw new Error('Div introuvable : #' + containerId);

  // Le conteneur doit avoir overflow:auto pour que le scroll natif fonctionne.
  // On le force ici si ce n'est pas déjà fait.
  if (getComputedStyle(container).overflow === 'visible') {
    container.style.overflow = 'auto';
  }

  const pagesDiv = document.createElement('div');
  // align-items:flex-start + min-width dynamique + margin:auto sur chaque page
  // évite que le PDF soit coupé à gauche quand il est plus large que le conteneur
  pagesDiv.style.cssText = 'display:flex;flex-direction:column;align-items:flex-start;gap:12px;padding:16px;box-sizing:border-box;min-width:100%;';
  container.innerHTML = '';
  container.appendChild(pagesDiv);

  /* ── État interne ── */
  let pdf        = null;
  let scale      = 1.0;
  let mode       = options.mode || 'pan';
  let highlights = [];           // { page, rx, ry, rw, rh }  — coords PDF, indépendantes du zoom
  let pages      = {};           // { wrap, canvas, hlLayer, page, vp }

  const DPR = window.devicePixelRatio || 1;  // ratio HiDPI pour la qualité

  // Verrou anti-rebuild concurrent
  let rebuilding   = false;
  let pendingScale = null;

  /* ────────────────────────────────────────────
     PAN (drag to scroll)
  ──────────────────────────────────────────── */
  let panning = false, panX, panY, sLeft, sTop;

  container.addEventListener('mousedown', e => {
    if (mode !== 'pan') return;
    if (e.target.classList.contains('pdfv-hl-rect')) return;
    panning = true;
    panX = e.clientX; panY = e.clientY;
    sLeft = container.scrollLeft; sTop = container.scrollTop;
    container.style.cursor = 'grabbing';
    e.preventDefault();
  });

  window.addEventListener('mousemove', e => {
    if (!panning) return;
    container.scrollLeft = sLeft - (e.clientX - panX);
    container.scrollTop  = sTop  - (e.clientY - panY);
  });

  window.addEventListener('mouseup', () => {
    if (!panning) return;
    panning = false;
    container.style.cursor = mode === 'pan' ? 'grab' : 'default';
  });

  /* ────────────────────────────────────────────
     ZOOM Ctrl+molette (centré sur la souris)
  ──────────────────────────────────────────── */
  container.addEventListener('wheel', e => {
    if (!e.ctrlKey) return;
    e.preventDefault();

    // Position de la souris dans le scroll-space avant le zoom
    const rect   = container.getBoundingClientRect();
    const mouseX = e.clientX - rect.left + container.scrollLeft;
    const mouseY = e.clientY - rect.top  + container.scrollTop;

    const factor   = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    const newScale = Math.min(Math.max(0.2, scale * factor), 6);
    const ratio    = newScale / scale;
    scale = newScale;

    if (options.onZoomChange) options.onZoomChange(scale);
    if (!pdf) return;

    if (rebuilding) { pendingScale = scale; return; }

    // Après rebuild, on repositionne le scroll pour garder le point sous la souris
    rebuild().then(() => {
      container.scrollLeft = mouseX * ratio - (e.clientX - rect.left);
      container.scrollTop  = mouseY * ratio - (e.clientY - rect.top);
    });
  }, { passive: false });

  /* ────────────────────────────────────────────
     CHARGEMENT
  ──────────────────────────────────────────── */
  async function load(src) {
    pdf = await pdfjsLib.getDocument(src).promise;

    // Calcul du scale initial pour que la page 1 tienne en largeur dans le conteneur
    const firstPage     = await pdf.getPage(1);
    const vpNatural     = firstPage.getViewport({ scale: 1.0 });
    const availableWidth = container.clientWidth - 48; // 2×padding
    scale = availableWidth / vpNatural.width;

    if (options.onZoomChange) options.onZoomChange(scale);
    await rebuild();
  }

  /* ────────────────────────────────────────────
     REBUILD (avec verrou)
  ──────────────────────────────────────────── */
  async function rebuild() {
    if (rebuilding) { pendingScale = scale; return; }
    rebuilding = true;

    try {
      pagesDiv.innerHTML = '';
      pages = {};

      // 1. Créer les wrappers DOM pour toutes les pages
      for (let i = 1; i <= pdf.numPages; i++) buildPage(i);

      // 2. Récupérer les objets page + dimensionner les canvas
      for (let i = 1; i <= pdf.numPages; i++) {
        const page = await pdf.getPage(i);
        const vp   = page.getViewport({ scale });
        const p    = pages[i];
        p.page = page;
        p.vp   = vp;

        // Taille CSS (affichage)
        p.canvas.style.width  = vp.width  + 'px';
        p.canvas.style.height = vp.height + 'px';

        // Taille physique × DPR pour la qualité HiDPI
        p.canvas.width  = Math.round(vp.width  * DPR);
        p.canvas.height = Math.round(vp.height * DPR);

        // Dimensionner le wrapper et la couche de surlignage
        p.wrap.style.width    = vp.width  + 'px';
        p.wrap.style.height   = vp.height + 'px';
        p.hlLayer.style.width  = vp.width  + 'px';
        p.hlLayer.style.height = vp.height + 'px';
      }

      // S'assurer que pagesDiv est au moins aussi large que la page la plus large
      // + padding, pour que margin:auto sur les wraps centre correctement
      const maxPageWidth = Math.max(...Object.values(pages).map(p => p.vp ? p.vp.width : 0));
      pagesDiv.style.minWidth = (maxPageWidth + 32) + 'px';

      // 3. Rendre les pages (séquentiel pour éviter les conflits de canvas)
      for (let i = 1; i <= pdf.numPages; i++) {
        if (pendingScale !== null) break; // un nouveau zoom est arrivé → on abandonne
        await renderPage(i);
      }

      // 4. Redessiner les surlignages
      Object.keys(pages).forEach(n => drawHighlights(+n));

      applyMode();

    } finally {
      rebuilding = false;

      // Si un zoom a été demandé pendant ce rebuild, on le lance maintenant
      if (pendingScale !== null) {
        scale = pendingScale;
        pendingScale = null;
        if (options.onZoomChange) options.onZoomChange(scale);
        rebuild();
      }
    }
  }

  /* ────────────────────────────────────────────
     CONSTRUCTION D'UNE PAGE (DOM uniquement)
  ──────────────────────────────────────────── */
  function buildPage(num) {
    const wrap = document.createElement('div');
    wrap.className = 'pdfv-page';
    wrap.dataset.page = num;
    wrap.style.cssText = 'position:relative;flex-shrink:0;margin:0 auto;';

    const canvas  = document.createElement('canvas');
    canvas.style.cssText = 'display:block;';

    const hlLayer = document.createElement('div');
    hlLayer.style.cssText = 'position:absolute;inset:0;pointer-events:none;';

    // Couche de dessin (rectangle temporaire pendant le tracé)
    const drawLayer = document.createElement('div');
    drawLayer.style.cssText = 'position:absolute;inset:0;pointer-events:none;';
    const drawBox = document.createElement('div');
    drawBox.style.cssText = 'position:absolute;display:none;box-sizing:border-box;background:rgba(255,220,0,.25);border:1.5px dashed rgba(180,160,0,.7);pointer-events:none;';
    drawLayer.appendChild(drawBox);

    wrap.append(canvas, hlLayer, drawLayer);
    pagesDiv.appendChild(wrap);

    pages[num] = { wrap, canvas, hlLayer, drawBox, page: null, vp: null };

    /* ── Tracé de surlignage manuel ── */
    let drawing = false, sx, sy;

    wrap.addEventListener('mousedown', e => {
      if (mode !== 'highlight') return;
      if (e.target.classList.contains('pdfv-hl-rect')) return;
      drawing = true;
      const r = wrap.getBoundingClientRect();
      sx = e.clientX - r.left;
      sy = e.clientY - r.top;
      Object.assign(drawBox.style, { left: sx+'px', top: sy+'px', width:'0', height:'0', display:'block' });
      e.stopPropagation();
    });

    wrap.addEventListener('mousemove', e => {
      if (!drawing) return;
      const r  = wrap.getBoundingClientRect();
      const cx = e.clientX - r.left, cy = e.clientY - r.top;
      Object.assign(drawBox.style, {
        left:   Math.min(cx, sx) + 'px',
        top:    Math.min(cy, sy) + 'px',
        width:  Math.abs(cx - sx) + 'px',
        height: Math.abs(cy - sy) + 'px',
      });
    });

    wrap.addEventListener('mouseup', e => {
      if (!drawing) return;
      drawing = false;
      drawBox.style.display = 'none';
      const r  = wrap.getBoundingClientRect();
      const cx = e.clientX - r.left, cy = e.clientY - r.top;
      const x  = Math.min(cx, sx), y = Math.min(cy, sy);
      const w  = Math.abs(cx - sx), h = Math.abs(cy - sy);
      if (w > 4 && h > 4) {
        // Stocker en unités PDF (÷ scale) pour être indépendant du zoom
        highlights.push({ page: num, rx: x/scale, ry: y/scale, rw: w/scale, rh: h/scale });
        drawHighlights(num);
      }
      e.stopPropagation();
    });
  }

  /* ────────────────────────────────────────────
     RENDU D'UNE PAGE
  ──────────────────────────────────────────── */
  async function renderPage(num) {
    const p = pages[num];
    if (!p || !p.page) return;

    // Viewport HiDPI : scale × DPR pour le rendu interne
    const hiVp = p.page.getViewport({ scale: scale * DPR });
    const ctx  = p.canvas.getContext('2d');
    ctx.clearRect(0, 0, p.canvas.width, p.canvas.height);

    try {
      await p.page.render({ canvasContext: ctx, viewport: hiVp }).promise;
    } catch (e) {
      if (e.name !== 'RenderingCancelledException') console.warn('render p' + num, e);
    }
  }

  /* ────────────────────────────────────────────
     SURLIGNAGES
  ──────────────────────────────────────────── */
  function drawHighlights(num) {
    const p = pages[num];
    if (!p) return;
    p.hlLayer.innerHTML = '';

    highlights
      .filter(h => h.page === num)
      .forEach(h => {
        const div = document.createElement('div');
        div.className = 'pdfv-hl-rect';
        // Convertir les unités PDF → pixels écran (× scale)
        div.style.cssText = [
          'position:absolute',
          'box-sizing:border-box',
          'pointer-events:all',
          'cursor:pointer',
          'background:rgba(255,220,0,.35)',
          'border:1px solid rgba(180,160,0,.5)',
          `left:${h.rx * scale}px`,
          `top:${h.ry * scale}px`,
          `width:${h.rw * scale}px`,
          `height:${h.rh * scale}px`,
        ].join(';');
        div.title = 'Clic droit pour supprimer';
        div.addEventListener('contextmenu', e => {
          e.preventDefault();
          highlights = highlights.filter(i => i !== h);
          drawHighlights(num);
        });
        p.hlLayer.appendChild(div);
      });
  }

  /* ────────────────────────────────────────────
     MODE (pan / highlight)
  ──────────────────────────────────────────── */
  function applyMode() {
    container.style.cursor = mode === 'pan' ? 'grab' : 'default';
    Object.values(pages).forEach(({ wrap }) => {
      wrap.style.cursor = mode === 'highlight' ? 'crosshair'
                        : mode === 'pan'       ? 'grab'
                        :                        'default';
    });
  }

  /* ────────────────────────────────────────────
     API PUBLIQUE
  ──────────────────────────────────────────── */
  const api = {

    /** Charge un PDF depuis une URL */
    load(url) { return load(url); },

    /** Charge un PDF depuis un objet File / Blob */
    loadBlob(blob) { return load(URL.createObjectURL(blob)); },

    /** Zoom +20 % */
    zoomIn()  { return api.setZoom(scale * 1.2); },

    /** Zoom −20 % */
    zoomOut() { return api.setZoom(scale / 1.2); },

    /** Ajuste le zoom pour que la page 1 tienne en largeur */
    fitWidth() {
      if (!pdf || !pages[1] || !pages[1].vp) return;
      const naturalW      = pages[1].vp.width / scale;
      const availableWidth = container.clientWidth - 48;
      return api.setZoom(availableWidth / naturalW);
    },

    /** Définit le zoom à une valeur absolue (ex: 1.5 = 150 %) */
    setZoom(s) {
      scale = Math.min(Math.max(0.2, s), 6);
      if (options.onZoomChange) options.onZoomChange(scale);
      if (pdf) return rebuild();
    },

    /** Change le mode : 'pan' | 'highlight' */
    setMode(m) { mode = m; applyMode(); },

    /**
     * Ajoute un surlignage.
     * @param {number} page   Numéro de page (1-based)
     * @param {number} rx     X en unités PDF (indépendant du zoom)
     * @param {number} ry     Y en unités PDF
     * @param {number} rw     Largeur en unités PDF
     * @param {number} rh     Hauteur en unités PDF
     */
    addHighlight(page, rx, ry, rw, rh) {
      highlights.push({ page, rx, ry, rw, rh });
      if (pages[page]) drawHighlights(page);
    },

    /** Supprime tous les surlignages */
    clearHighlights() {
      highlights = [];
      Object.keys(pages).forEach(n => drawHighlights(+n));
    },

    /**
     * Scrolle vers une zone et la surligne.
     * Mêmes paramètres que addHighlight.
     */
    scrollToRegion(page, rx, ry, rw, rh) {
      api.addHighlight(page, rx, ry, rw, rh);
      if (!pages[page]) return;
      const pageTop = pages[page].wrap.offsetTop;
      container.scrollTo({ top: pageTop + ry * scale - 40, behavior: 'smooth' });
    },

    /** Retourne le scale courant */
    get scale() { return scale; },
  };

  return api;
}