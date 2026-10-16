/* ── whiteboard: pizarra tipo Paint, reeditable ──────────────────────────────
   Modelo en memoria (runtime, "legible"): array `objects` de {id, type, ...}.
   Modelo guardado en BD (compacto, claves cortas -- ver expand()/compact()):
   {"t":"r","x":..,"y":..,"w":..,"h":..,"c":"#color","s":grosor}, etc.
   El PNG (canvas.toBlob) es solo una miniatura derivada, nunca la fuente. */

var canvas, ctx, el;
var whiteboardId, saveUrl, csrfCookieName, reunionIdNueva, agendaFechaNueva;
var tituloInput, versionInfo;

var objects      = [];
var selectedId   = null;
var currentTool  = 'select';
var currentColor = '#111827';
var currentWidth = 4;
var idCounter    = 1;

var undoStack = [];
var UNDO_MAX  = 30;

var dragMode        = null;   // null | 'move' | 'resize' | 'draw'
var dragStart        = null;
var dragOrigObj      = null;
var dragHandleIndex  = -1;
var drawingObj       = null;
var preChangeSnapshot = null;

var draftTimer = null;
var DRAFT_KEY  = '';


document.addEventListener('DOMContentLoaded', function () {
    el = document.getElementById('wbEditor');
    canvas = document.getElementById('wbCanvas');
    ctx = canvas.getContext('2d');

    whiteboardId   = el.dataset.whiteboardId || '';
    saveUrl        = el.dataset.saveUrl;
    csrfCookieName = el.dataset.csrfCookie;
    reunionIdNueva = el.dataset.reunionIdNueva || '';
    agendaFechaNueva = el.dataset.agendaFechaNueva || '';
    DRAFT_KEY = 'wb_draft_' + (whiteboardId || 'nuevo');

    tituloInput = document.getElementById('wbTitulo');
    versionInfo = document.getElementById('wbVersionInfo');

    var initialColorSwatch = document.querySelector('.wb-color-swatch.active');
    if (initialColorSwatch) currentColor = initialColorSwatch.dataset.color;

    var contenidoEl = document.getElementById('wb-contenido-inicial');
    objects = expandAll(contenidoEl ? JSON.parse(contenidoEl.textContent) : []);

    if (el.dataset.versionHash) {
        versionInfo.textContent = 'Guardado · ' + el.dataset.versionHash;
    }

    bindUI();
    render();
    checkDraftOnLoad();
});


/* ── util ────────────────────────────────────────────────────────────────── */

function getCookie(name) {
    var value = '; ' + document.cookie;
    var parts = value.split('; ' + name + '=');
    if (parts.length === 2) return parts.pop().split(';').shift();
    return '';
}

function clone(x) { return JSON.parse(JSON.stringify(x)); }

function snapshot() { return clone(objects); }

function pushUndo(snap) {
    undoStack.push(snap);
    if (undoStack.length > UNDO_MAX) undoStack.shift();
}

function getObjectById(id) {
    for (var i = 0; i < objects.length; i++) if (objects[i].id === id) return objects[i];
    return null;
}

function getPos(e) {
    var rect = canvas.getBoundingClientRect();
    var scaleX = canvas.width / rect.width;
    var scaleY = canvas.height / rect.height;
    return { x: (e.clientX - rect.left) * scaleX, y: (e.clientY - rect.top) * scaleY };
}


/* ── compacto (guardado) <-> legible (runtime) ──────────────────────────── */

function r(n) { return Math.round(n * 10) / 10; }

function compact(o) {
    switch (o.type) {
        case 'stroke': return { t: 's', p: o.points.map(function (pt) { return [r(pt[0]), r(pt[1])]; }), c: o.color, s: o.width };
        case 'rect':   return { t: 'r', x: r(o.x), y: r(o.y), w: r(o.w), h: r(o.h), c: o.color, s: o.width };
        case 'circle': return { t: 'c', x: r(o.x), y: r(o.y), w: r(o.w), h: r(o.h), c: o.color, s: o.width };
        case 'line':   return { t: 'l', x1: r(o.x1), y1: r(o.y1), x2: r(o.x2), y2: r(o.y2), c: o.color, s: o.width };
        case 'arrow':  return { t: 'a', x1: r(o.x1), y1: r(o.y1), x2: r(o.x2), y2: r(o.y2), c: o.color, s: o.width };
        case 'text':
            return {
                t: 'x', x: r(o.x), y: r(o.y), c: o.color, fs: o.fontSize,
                ln: o.lines.map(function (l) { return { m: l.marker === 'bullet' ? 'b' : (l.marker === 'number' ? 'n' : 0), v: l.text }; }),
            };
    }
}

function expand(c) {
    var id = 'o' + (idCounter++);
    switch (c.t) {
        case 's': return { id: id, type: 'stroke', points: c.p, color: c.c, width: c.s };
        case 'r': return { id: id, type: 'rect',   x: c.x, y: c.y, w: c.w, h: c.h, color: c.c, width: c.s };
        case 'c': return { id: id, type: 'circle', x: c.x, y: c.y, w: c.w, h: c.h, color: c.c, width: c.s };
        case 'l': return { id: id, type: 'line',   x1: c.x1, y1: c.y1, x2: c.x2, y2: c.y2, color: c.c, width: c.s };
        case 'a': return { id: id, type: 'arrow',  x1: c.x1, y1: c.y1, x2: c.x2, y2: c.y2, color: c.c, width: c.s };
        case 'x': {
            // 'ln' es el formato nuevo (multi-linea, con viñetas/numeracion);
            // 'v' es compat con pizarras guardadas antes de añadir listas --
            // una sola linea sin marca, se comporta igual que siempre.
            var lines = c.ln
                ? c.ln.map(function (l) { return { marker: l.m === 'b' ? 'bullet' : (l.m === 'n' ? 'number' : null), text: l.v }; })
                : [{ marker: null, text: c.v || '' }];
            return { id: id, type: 'text', x: c.x, y: c.y, color: c.c, fontSize: c.fs, lines: lines };
        }
    }
}

function expandAll(arr) { return (arr || []).map(expand); }


/* ── geometria / bbox ────────────────────────────────────────────────────── */

function getBBox(o) {
    switch (o.type) {
        case 'rect':
        case 'circle':
            return { x: o.x, y: o.y, w: o.w, h: o.h };
        case 'line':
        case 'arrow':
            return { x: Math.min(o.x1, o.x2), y: Math.min(o.y1, o.y2), w: Math.abs(o.x2 - o.x1), h: Math.abs(o.y2 - o.y1) };
        case 'stroke': {
            var xs = o.points.map(function (p) { return p[0]; });
            var ys = o.points.map(function (p) { return p[1]; });
            var minX = Math.min.apply(null, xs), maxX = Math.max.apply(null, xs);
            var minY = Math.min.apply(null, ys), maxY = Math.max.apply(null, ys);
            return { x: minX, y: minY, w: maxX - minX, h: maxY - minY };
        }
        case 'text': {
            ctx.font = o.fontSize + 'px sans-serif';
            var m = textMetrics(o);
            var maxW = 20;
            o.lines.forEach(function (line) {
                var w = (line.marker ? m.indent : 0) + ctx.measureText(line.text || '').width;
                if (w > maxW) maxW = w;
            });
            return { x: o.x, y: o.y, w: maxW, h: Math.max(m.lineHeight, o.lines.length * m.lineHeight) };
        }
    }
}

// grosor de linea e indentacion de la marca (viñeta/numero) para texto
// multi-linea -- se comparte entre getBBox y drawObject para que la caja de
// seleccion y el dibujo real midan exactamente lo mismo.
function textMetrics(o) {
    return { lineHeight: o.fontSize * 1.3, indent: o.fontSize * 1.1 };
}

function mapPoint(px, py, ob, nb) {
    var sx = ob.w ? (px - ob.x) / ob.w : 0;
    var sy = ob.h ? (py - ob.y) / ob.h : 0;
    return [nb.x + sx * nb.w, nb.y + sy * nb.h];
}

function applyBBoxToObject(obj, ob, nb) {
    if (obj.type === 'rect' || obj.type === 'circle') {
        obj.x = nb.x; obj.y = nb.y; obj.w = nb.w; obj.h = nb.h;
        return;
    }
    if (obj.type === 'text') {
        obj.x = nb.x; obj.y = nb.y;
        if (ob.h) obj.fontSize = Math.max(8, Math.round(obj.fontSize * (nb.h / ob.h)));
        return;
    }
    if (obj.type === 'line' || obj.type === 'arrow') {
        var p1 = mapPoint(obj.x1, obj.y1, ob, nb), p2 = mapPoint(obj.x2, obj.y2, ob, nb);
        obj.x1 = p1[0]; obj.y1 = p1[1]; obj.x2 = p2[0]; obj.y2 = p2[1];
        return;
    }
    if (obj.type === 'stroke') {
        obj.points = obj.points.map(function (pt) { return mapPoint(pt[0], pt[1], ob, nb); });
    }
}

function moveGeometry(obj, dx, dy) {
    switch (obj.type) {
        case 'stroke':
            obj.points = obj.points.map(function (pt) { return [pt[0] + dx, pt[1] + dy]; });
            break;
        case 'rect':
        case 'circle':
        case 'text':
            obj.x += dx; obj.y += dy;
            break;
        case 'line':
        case 'arrow':
            obj.x1 += dx; obj.y1 += dy; obj.x2 += dx; obj.y2 += dy;
            break;
    }
}


/* ── dibujo ──────────────────────────────────────────────────────────────── */

function drawArrowHead(x1, y1, x2, y2, color, width) {
    var angle = Math.atan2(y2 - y1, x2 - x1);
    var headLen = Math.max(10, width * 3);
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(x2, y2);
    ctx.lineTo(x2 - headLen * Math.cos(angle - Math.PI / 6), y2 - headLen * Math.sin(angle - Math.PI / 6));
    ctx.lineTo(x2 - headLen * Math.cos(angle + Math.PI / 6), y2 - headLen * Math.sin(angle + Math.PI / 6));
    ctx.closePath();
    ctx.fill();
}

function drawObject(o) {
    ctx.lineJoin = 'round'; ctx.lineCap = 'round';
    switch (o.type) {
        case 'stroke':
            if (o.points.length < 2) return;
            ctx.strokeStyle = o.color; ctx.lineWidth = o.width;
            ctx.beginPath();
            ctx.moveTo(o.points[0][0], o.points[0][1]);
            for (var i = 1; i < o.points.length; i++) ctx.lineTo(o.points[i][0], o.points[i][1]);
            ctx.stroke();
            break;
        case 'rect':
            ctx.strokeStyle = o.color; ctx.lineWidth = o.width;
            ctx.strokeRect(o.x, o.y, o.w, o.h);
            break;
        case 'circle':
            ctx.strokeStyle = o.color; ctx.lineWidth = o.width;
            ctx.beginPath();
            ctx.ellipse(o.x + o.w / 2, o.y + o.h / 2, Math.abs(o.w) / 2, Math.abs(o.h) / 2, 0, 0, Math.PI * 2);
            ctx.stroke();
            break;
        case 'line':
            ctx.strokeStyle = o.color; ctx.lineWidth = o.width;
            ctx.beginPath(); ctx.moveTo(o.x1, o.y1); ctx.lineTo(o.x2, o.y2); ctx.stroke();
            break;
        case 'arrow':
            ctx.strokeStyle = o.color; ctx.lineWidth = o.width;
            ctx.beginPath(); ctx.moveTo(o.x1, o.y1); ctx.lineTo(o.x2, o.y2); ctx.stroke();
            drawArrowHead(o.x1, o.y1, o.x2, o.y2, o.color, o.width);
            break;
        case 'text': {
            ctx.font = o.fontSize + 'px sans-serif';
            ctx.fillStyle = o.color;
            ctx.textBaseline = 'top';
            var m = textMetrics(o);
            var numCounter = 0;
            o.lines.forEach(function (line, i) {
                var yy = o.y + i * m.lineHeight;
                if (line.marker === 'bullet') {
                    numCounter = 0;
                    ctx.fillText('•', o.x, yy);
                    ctx.fillText(line.text, o.x + m.indent, yy);
                } else if (line.marker === 'number') {
                    numCounter++;
                    ctx.fillText(numCounter + '.', o.x, yy);
                    ctx.fillText(line.text, o.x + m.indent, yy);
                } else {
                    numCounter = 0;
                    ctx.fillText(line.text, o.x, yy);
                }
            });
            break;
        }
    }
}

function drawSelection(o) {
    var b = getBBox(o);
    ctx.save();
    ctx.strokeStyle = '#7c3aed';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([6, 4]);
    ctx.strokeRect(b.x - 4, b.y - 4, b.w + 8, b.h + 8);
    ctx.setLineDash([]);
    var corners = [[b.x, b.y], [b.x + b.w, b.y], [b.x + b.w, b.y + b.h], [b.x, b.y + b.h]];
    corners.forEach(function (c) {
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(c[0] - 6, c[1] - 6, 12, 12);
        ctx.strokeRect(c[0] - 6, c[1] - 6, 12, 12);
    });
    ctx.restore();
}

function render() {
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    objects.forEach(drawObject);
    if (selectedId) {
        var sel = getObjectById(selectedId);
        if (sel) drawSelection(sel);
    }
    updateContextBar();
}

// Barra contextual bajo la cabecera: hoy solo el tamano de letra de un texto
// seleccionado (no tiene sentido para el resto de tipos, que ya se editan
// con el color/grosor globales -- ver applyColorToSelection/wbWidth).
function updateContextBar() {
    var bar = document.getElementById('wbContextBar');
    if (!bar) return;
    var sel = selectedId ? getObjectById(selectedId) : null;
    if (!sel || sel.type !== 'text') { bar.hidden = true; return; }
    bar.hidden = false;
    var fontInput = document.getElementById('wbFontSize');
    var fontVal = document.getElementById('wbFontSizeValue');
    if (document.activeElement !== fontInput) fontInput.value = sel.fontSize;
    fontVal.textContent = Math.round(sel.fontSize) + 'px';
}


/* ── hit-test / handles ─────────────────────────────────────────────────── */

function hitTest(x, y) {
    for (var i = objects.length - 1; i >= 0; i--) {
        var o = objects[i];
        var b = getBBox(o);
        var pad = Math.max(o.width || 0, 8) + 6;
        if (x >= b.x - pad && x <= b.x + b.w + pad && y >= b.y - pad && y <= b.y + b.h + pad) return o;
    }
    return null;
}

function getHandleAt(p, o) {
    var b = getBBox(o);
    var corners = [[b.x, b.y], [b.x + b.w, b.y], [b.x + b.w, b.y + b.h], [b.x, b.y + b.h]];
    var rad = 16;
    for (var i = 0; i < 4; i++) {
        if (Math.abs(p.x - corners[i][0]) <= rad && Math.abs(p.y - corners[i][1]) <= rad) return i;
    }
    return -1;
}


/* ── crear/actualizar objetos mientras se dibuja ───────────────────────── */

function createDraftObject(tool, p) {
    var base = { id: 'o' + (idCounter++), color: currentColor, width: currentWidth };
    switch (tool) {
        case 'pencil': return Object.assign(base, { type: 'stroke', points: [[p.x, p.y]] });
        case 'line':   return Object.assign(base, { type: 'line', x1: p.x, y1: p.y, x2: p.x, y2: p.y });
        case 'rect':   return Object.assign(base, { type: 'rect', x: p.x, y: p.y, w: 0, h: 0 });
        case 'circle': return Object.assign(base, { type: 'circle', x: p.x, y: p.y, w: 0, h: 0 });
        case 'arrow':  return Object.assign(base, { type: 'arrow', x1: p.x, y1: p.y, x2: p.x, y2: p.y });
    }
}

function updateDraftObject(obj, tool, start, p) {
    switch (tool) {
        case 'pencil': obj.points.push([p.x, p.y]); break;
        case 'line':
        case 'arrow': obj.x2 = p.x; obj.y2 = p.y; break;
        case 'rect':
        case 'circle': obj.w = p.x - start.x; obj.h = p.y - start.y; break;
    }
}

function normalizeObject(obj) {
    if (obj.type === 'rect' || obj.type === 'circle') {
        if (obj.w < 0) { obj.x += obj.w; obj.w = -obj.w; }
        if (obj.h < 0) { obj.y += obj.h; obj.h = -obj.h; }
    }
}

function isDegenerate(obj) {
    if (obj.type === 'stroke') return obj.points.length < 2;
    if (obj.type === 'rect' || obj.type === 'circle') return Math.abs(obj.w) < 3 || Math.abs(obj.h) < 3;
    if (obj.type === 'line' || obj.type === 'arrow') return Math.hypot(obj.x2 - obj.x1, obj.y2 - obj.y1) < 3;
    return false;
}


/* ── texto (multi-linea, con viñetas/numeracion tipo docx) ──────────────── */

// Atajos "docx-like" al escribir: "- "/"* " al principio de una linea = punto,
// "1. " (cualquier numero) = numerada -- el numero real se recalcula siempre
// al dibujar (ver drawObject), asi que basta con escribir cualquier digito.
var LINE_BULLET_RE = /^(?:-|\*)\s+(.*)$/;
var LINE_NUMBER_RE = /^\d+\.\s+(.*)$/;
var LINE_MARKED_RE = /^(?:-|\*|\d+\.)\s/;

function parseTextLines(raw) {
    return raw.split('\n').map(function (line) {
        var mb = line.match(LINE_BULLET_RE);
        if (mb) return { marker: 'bullet', text: mb[1] };
        var mn = line.match(LINE_NUMBER_RE);
        if (mn) return { marker: 'number', text: mn[1] };
        return { marker: null, text: line };
    });
}

function linesToRaw(lines) {
    return lines.map(function (l) {
        if (l.marker === 'bullet') return '- ' + l.text;
        if (l.marker === 'number') return '1. ' + l.text;
        return l.text;
    }).join('\n');
}

function placeTextInput(p) {
    openTextEditor(p, null, '', 10 + currentWidth * 3, currentColor);
}

function editTextObject(obj) {
    openTextEditor({ x: obj.x, y: obj.y }, obj, linesToRaw(obj.lines), obj.fontSize, obj.color);
}

function openTextEditor(p, existingObj, initialRaw, fontSize, color) {
    var scale = canvas.clientWidth / canvas.width;

    var wrap = document.createElement('div');
    wrap.className = 'wb-text-editor';
    wrap.style.left = (canvas.offsetLeft + p.x * scale) + 'px';
    wrap.style.top = (canvas.offsetTop + p.y * scale) + 'px';

    var toolbar = document.createElement('div');
    toolbar.className = 'wb-text-editor-toolbar';
    var bulletBtn = document.createElement('button');
    bulletBtn.type = 'button'; bulletBtn.textContent = '•';
    bulletBtn.title = (window.WB_I18N && window.WB_I18N.vinetas) || 'Lista con viñetas';
    var numberBtn = document.createElement('button');
    numberBtn.type = 'button'; numberBtn.textContent = '1.';
    numberBtn.title = (window.WB_I18N && window.WB_I18N.numerada) || 'Lista numerada';
    toolbar.appendChild(bulletBtn);
    toolbar.appendChild(numberBtn);

    var textarea = document.createElement('textarea');
    textarea.className = 'wb-text-input';
    textarea.value = initialRaw;
    textarea.rows = Math.max(1, initialRaw.split('\n').length);
    textarea.style.color = color;
    textarea.style.fontSize = (fontSize * scale) + 'px';

    wrap.appendChild(toolbar);
    wrap.appendChild(textarea);
    canvas.parentElement.appendChild(wrap);
    textarea.focus();
    if (existingObj) textarea.select();

    // preventDefault en el mousedown del boton evita que el textarea pierda
    // el foco al pulsarlo (mismo truco que el preventDefault del canvas,
    // ver onPointerDown) -- si no, el blur del textarea cerraria el editor
    // justo antes de que el click del boton llegara a insertar la marca.
    function insertMarker(prefix) {
        var start = textarea.selectionStart;
        var value = textarea.value;
        var lineStart = value.lastIndexOf('\n', start - 1) + 1;
        var lineEnd = value.indexOf('\n', start);
        if (lineEnd === -1) lineEnd = value.length;
        if (LINE_MARKED_RE.test(value.slice(lineStart, lineEnd))) return;
        textarea.value = value.slice(0, lineStart) + prefix + value.slice(lineStart);
        textarea.setSelectionRange(start + prefix.length, start + prefix.length);
        textarea.rows = Math.max(1, textarea.value.split('\n').length);
    }
    bulletBtn.addEventListener('mousedown', function (e) { e.preventDefault(); insertMarker('- '); });
    numberBtn.addEventListener('mousedown', function (e) { e.preventDefault(); insertMarker('1. '); });

    textarea.addEventListener('input', function () {
        textarea.rows = Math.max(1, textarea.value.split('\n').length);
    });

    var done = false;
    function commit() {
        if (done) return;
        done = true;
        var raw = textarea.value;
        wrap.remove();
        var snap = snapshot();
        if (!raw.trim()) {
            if (existingObj) {
                objects = objects.filter(function (o) { return o.id !== existingObj.id; });
                if (selectedId === existingObj.id) selectedId = null;
            } else {
                render();
                return; // nada que crear ni que deshacer
            }
        } else if (existingObj) {
            existingObj.lines = parseTextLines(raw);
        } else {
            objects.push({ id: 'o' + (idCounter++), type: 'text', x: p.x, y: p.y, color: color, fontSize: fontSize, lines: parseTextLines(raw) });
        }
        pushUndo(snap);
        render();
        scheduleDraftSave();
    }
    textarea.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') { done = true; wrap.remove(); render(); }
    });
    textarea.addEventListener('blur', commit);
}


/* ── seleccion: mover / borrar / goma ────────────────────────────────────── */

function deleteSelected() {
    if (!selectedId) return;
    var snap = snapshot();
    objects = objects.filter(function (o) { return o.id !== selectedId; });
    selectedId = null;
    pushUndo(snap);
    render();
    scheduleDraftSave();
}

// Cambiar de color con algo seleccionado lo recolorea a el, no solo afecta a
// lo que se dibuje despues -- coherente con "segun la seleccion, editar".
function applyColorToSelection(color) {
    var sel = selectedId ? getObjectById(selectedId) : null;
    if (!sel) return;
    var snap = snapshot();
    sel.color = color;
    pushUndo(snap);
    render();
    scheduleDraftSave();
}

// Goma: borra objetos ENTEROS que toque el arrastre (como el borrador de
// Excalidraw), no borrado parcial pixel a pixel -- asi los objetos que
// sobreviven siguen siendo un unico bloque reeditable.
function eraseAt(p) {
    objects = objects.filter(function (o) {
        var b = getBBox(o);
        var pad = Math.max(o.width || 0, 8) + 10;
        var hit = p.x >= b.x - pad && p.x <= b.x + b.w + pad && p.y >= b.y - pad && p.y <= b.y + b.h + pad;
        if (hit && selectedId === o.id) selectedId = null;
        return !hit;
    });
}

// Doble clic sobre un texto ya colocado reabre el input para editarlo --
// mover/redimensionar se hace con la herramienta Seleccionar, pero cambiar
// las palabras en si necesita este atajo aparte.
function onDblClick(e) {
    if (currentTool !== 'select') return;
    var p = getPos(e);
    var hit = hitTest(p.x, p.y);
    if (hit && hit.type === 'text') editTextObject(hit);
}

/* ── copia de seguridad local (borrador, "bajo mangas") ─────────────────── */

function scheduleDraftSave() {
    clearTimeout(draftTimer);
    draftTimer = setTimeout(saveDraftNow, 3000);
}

function saveDraftNow() {
    try {
        localStorage.setItem(DRAFT_KEY, JSON.stringify({
            contenido: objects.map(compact),
            titulo: tituloInput.value.trim(),
            ts: Date.now(),
        }));
    } catch (e) { /* localStorage lleno/bloqueado -- no es critico, se ignora */ }
}

function clearDraft() {
    try { localStorage.removeItem(DRAFT_KEY); } catch (e) { /* ignorar */ }
}

// El borrador local NUNCA se ofrece solo al abrir una pizarra (eso resultaba
// muy intrusivo -- aparecia en cualquier apertura normal sin guardar antes).
// Solo se aplica cuando llega ?restaurar_borrador=1 en la URL, que es el
// enlace "Restaurar" de Configuracion -> Sistema -- ahi el usuario ya eligio
// explicitamente recuperar ESE borrador, asi que se aplica sin preguntar mas.
function checkDraftOnLoad() {
    var params = new URLSearchParams(window.location.search);
    if (params.get('restaurar_borrador') !== '1') return;

    var raw;
    try { raw = localStorage.getItem(DRAFT_KEY); } catch (e) { return; }
    if (!raw) return;
    var draft;
    try { draft = JSON.parse(raw); } catch (e) { return; }

    objects = expandAll(draft.contenido);
    selectedId = null;
    if (draft.titulo) tituloInput.value = draft.titulo;
    render();

    if (window.history && window.history.replaceState) {
        window.history.replaceState(null, '', window.location.pathname);
    }
}


/* ── guardar / descargar ────────────────────────────────────────────────── */

function doSave() {
    var payload = new FormData();
    payload.append('whiteboard_id', whiteboardId || '');
    payload.append('titulo', tituloInput.value.trim());
    payload.append('contenido', JSON.stringify(objects.map(compact)));
    // solo relevante la PRIMERA vez (pizarra nueva llegada desde "+ Crear
    // whiteboard para esta reunion"); el servidor tambien lo ignora si ya existe.
    if (!whiteboardId && reunionIdNueva) payload.append('reunion_id', reunionIdNueva);
    if (!whiteboardId && agendaFechaNueva) payload.append('agenda_fecha', agendaFechaNueva);

    canvas.toBlob(function (blob) {
        if (blob) payload.append('thumbnail', blob, 'whiteboard.png');
        fetch(saveUrl, {
            method: 'POST',
            headers: { 'X-CSRFToken': getCookie(csrfCookieName) },
            body: payload,
        })
            .then(function (resp) { return resp.json(); })
            .then(function (data) {
                if (!data.ok) { alert(data.error || 'No se pudo guardar la pizarra'); return; }
                whiteboardId = data.whiteboard_id;
                el.dataset.whiteboardId = data.whiteboard_id;
                DRAFT_KEY = 'wb_draft_' + whiteboardId;
                versionInfo.textContent = 'Guardado · ' + data.version_hash;
                clearDraft();
                if (window.history && window.history.replaceState) {
                    window.history.replaceState(null, '', '/whiteboard/' + whiteboardId + '/editar/');
                }
            })
            .catch(function (err) {
                console.error('Error al guardar whiteboard:', err);
                alert('No se pudo guardar la pizarra');
            });
    }, 'image/png');
}

function doDownload() {
    canvas.toBlob(function (blob) {
        if (!blob) return;
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = (tituloInput.value.trim() || 'whiteboard') + '.png';
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    }, 'image/png');
}


/* ── eventos de puntero sobre el canvas ─────────────────────────────────── */

function onPointerDown(e) {
    // sin esto, el navegador intenta enfocar el elemento bajo el puntero tras
    // el mousedown y, como <canvas> no es enfocable, eso desenfoca cualquier
    // <input> que hayamos creado y enfocado nosotros mismos (herramienta Texto)
    e.preventDefault();
    canvas.setPointerCapture(e.pointerId);
    var p = getPos(e);

    if (currentTool === 'select') {
        var sel = selectedId ? getObjectById(selectedId) : null;
        if (sel) {
            var hIdx = getHandleAt(p, sel);
            if (hIdx !== -1) {
                dragMode = 'resize';
                dragHandleIndex = hIdx;
                preChangeSnapshot = snapshot();
                dragOrigObj = clone(sel);
                dragStart = p;
                return;
            }
        }
        var hit = hitTest(p.x, p.y);
        if (hit) {
            selectedId = hit.id;
            dragMode = 'move';
            preChangeSnapshot = snapshot();
            dragOrigObj = clone(hit);
            dragStart = p;
        } else {
            selectedId = null;
            dragMode = null;
        }
        render();
        return;
    }

    if (currentTool === 'text') {
        placeTextInput(p);
        return;
    }

    if (currentTool === 'goma') {
        dragMode = 'erase';
        preChangeSnapshot = snapshot();
        eraseAt(p);
        render();
        return;
    }

    dragMode = 'draw';
    dragStart = p;
    preChangeSnapshot = snapshot();
    drawingObj = createDraftObject(currentTool, p);
    objects.push(drawingObj);
    render();
}

function onPointerMove(e) {
    if (!dragMode) return;
    var p = getPos(e);

    if (dragMode === 'move') {
        var dx = p.x - dragStart.x, dy = p.y - dragStart.y;
        var live = getObjectById(selectedId);
        var fresh = clone(dragOrigObj);
        moveGeometry(fresh, dx, dy);
        Object.assign(live, fresh);
        render();
    } else if (dragMode === 'resize') {
        var live2 = getObjectById(selectedId);
        var ob = getBBox(dragOrigObj);
        var x0 = ob.x, y0 = ob.y, x1 = ob.x + ob.w, y1 = ob.y + ob.h;
        if (dragHandleIndex === 0) { x0 = p.x; y0 = p.y; }
        else if (dragHandleIndex === 1) { x1 = p.x; y0 = p.y; }
        else if (dragHandleIndex === 2) { x1 = p.x; y1 = p.y; }
        else if (dragHandleIndex === 3) { x0 = p.x; y1 = p.y; }
        var nb = { x: Math.min(x0, x1), y: Math.min(y0, y1), w: Math.abs(x1 - x0), h: Math.abs(y1 - y0) };
        var fresh2 = clone(dragOrigObj);
        applyBBoxToObject(fresh2, ob, nb);
        Object.assign(live2, fresh2);
        render();
    } else if (dragMode === 'draw') {
        updateDraftObject(drawingObj, currentTool, dragStart, p);
        render();
    } else if (dragMode === 'erase') {
        eraseAt(p);
        render();
    }
}

function onPointerUp() {
    if (dragMode === 'draw') {
        if (isDegenerate(drawingObj)) {
            objects.pop();
        } else {
            normalizeObject(drawingObj);
            pushUndo(preChangeSnapshot);
            scheduleDraftSave();
        }
        drawingObj = null;
    } else if (dragMode === 'move' || dragMode === 'resize') {
        var live = getObjectById(selectedId);
        if (live && JSON.stringify(live) !== JSON.stringify(dragOrigObj)) {
            pushUndo(preChangeSnapshot);
            scheduleDraftSave();
        }
        dragOrigObj = null;
    } else if (dragMode === 'erase') {
        if (JSON.stringify(objects) !== JSON.stringify(preChangeSnapshot)) {
            pushUndo(preChangeSnapshot);
            scheduleDraftSave();
        }
    }
    preChangeSnapshot = null;
    dragMode = null;
    render();
}


/* ── wiring de la interfaz ──────────────────────────────────────────────── */

function bindUI() {
    canvas.addEventListener('pointerdown', onPointerDown);
    canvas.addEventListener('pointermove', onPointerMove);
    canvas.addEventListener('pointerup', onPointerUp);
    canvas.addEventListener('pointercancel', onPointerUp);
    canvas.addEventListener('dblclick', onDblClick);

    document.querySelectorAll('.wb-tool-btn[data-tool]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            document.querySelectorAll('.wb-tool-btn[data-tool]').forEach(function (b) { b.classList.remove('active'); });
            btn.classList.add('active');
            currentTool = btn.dataset.tool;
            if (currentTool !== 'select') { selectedId = null; render(); }
        });
    });

    document.querySelectorAll('.wb-color-swatch').forEach(function (sw) {
        sw.addEventListener('click', function () {
            document.querySelectorAll('.wb-color-swatch').forEach(function (s) { s.classList.remove('active'); });
            sw.classList.add('active');
            currentColor = sw.dataset.color;
            applyColorToSelection(currentColor);
        });
    });
    document.getElementById('wbColorPicker').addEventListener('input', function () {
        currentColor = this.value;
        document.querySelectorAll('.wb-color-swatch').forEach(function (s) { s.classList.remove('active'); });
        applyColorToSelection(currentColor);
    });

    // grosor: si hay algo seleccionado (que no sea texto) el slider edita SU
    // grosor en vivo; si no, solo ajusta lo que se dibuje a partir de ahora.
    // 'input' = feedback en vivo mientras se arrastra, 'change' (al soltar)
    // es el unico momento en que se apila en Deshacer -- si no, un arrastre
    // largo del slider generaria decenas de pasos de deshacer inutiles.
    var widthUndoSnap = null;
    document.getElementById('wbWidth').addEventListener('input', function () {
        currentWidth = parseInt(this.value, 10) || 4;
        var sel = selectedId ? getObjectById(selectedId) : null;
        if (sel && sel.type !== 'text') {
            if (widthUndoSnap === null) widthUndoSnap = snapshot();
            sel.width = currentWidth;
            render();
        }
    });
    document.getElementById('wbWidth').addEventListener('change', function () {
        if (widthUndoSnap !== null) {
            pushUndo(widthUndoSnap);
            widthUndoSnap = null;
            scheduleDraftSave();
        }
    });

    var fontSizeUndoSnap = null;
    document.getElementById('wbFontSize').addEventListener('input', function () {
        var sel = selectedId ? getObjectById(selectedId) : null;
        if (!sel || sel.type !== 'text') return;
        if (fontSizeUndoSnap === null) fontSizeUndoSnap = snapshot();
        sel.fontSize = parseInt(this.value, 10) || sel.fontSize;
        document.getElementById('wbFontSizeValue').textContent = sel.fontSize + 'px';
        render();
    });
    document.getElementById('wbFontSize').addEventListener('change', function () {
        if (fontSizeUndoSnap !== null) {
            pushUndo(fontSizeUndoSnap);
            fontSizeUndoSnap = null;
            scheduleDraftSave();
        }
    });

    document.getElementById('wbUndoBtn').addEventListener('click', function () {
        if (!undoStack.length) return;
        objects = undoStack.pop();
        selectedId = null;
        render();
        scheduleDraftSave();
    });

    document.getElementById('wbDeleteSelBtn').addEventListener('click', deleteSelected);
    document.getElementById('wbSaveBtn').addEventListener('click', doSave);
    document.getElementById('wbDownloadBtn').addEventListener('click', doDownload);

    // salir por "Volver" es una decision deliberada de no guardar -- no debe
    // quedar como "recuperable" luego (eso es solo para un cierre brusco).
    var backLink = document.getElementById('wbBackLink');
    if (backLink) backLink.addEventListener('click', clearDraft);

    tituloInput.addEventListener('input', scheduleDraftSave);

    document.addEventListener('keydown', function (e) {
        if (!selectedId) return;
        // si se esta escribiendo en el textarea del editor de texto (o en
        // cualquier input), Backspace/Delete es para borrar letras, no el
        // objeto -- antes solo miraba 'INPUT' y con el editor multi-linea
        // (ahora un <textarea>) se colaba y borraba el objeto por detras.
        var tag = document.activeElement && document.activeElement.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA') return;
        if (e.key === 'Delete' || e.key === 'Backspace') {
            e.preventDefault();
            deleteSelected();
        }
    });
}
