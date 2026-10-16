// Bloque personalizado "Tareas del proyecto (en vivo)" -- no guarda una
// copia de las tareas, solo la preferencia de filtro (pendientes/todas).
// El contenido real se consulta a la BD cada vez que se VE la pagina (ver
// wiki_store.py::render_content, tipo "tareasVivas"), nunca al editar --
// aqui en el editor solo se muestra un marcador de posicion con el
// selector de filtro, no la lista real de tareas.
class TareasVivas {
  static get toolbox() {
    return {
      title: 'Tareas del proyecto (en vivo)',
      icon: '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>',
    };
  }

  constructor({ data }) {
    this.data = { filtro: (data && data.filtro) || 'pendientes' };
  }

  render() {
    this.wrapper = document.createElement('div');
    this.wrapper.style.cssText =
      'display:flex;align-items:center;gap:10px;border:1px dashed var(--border,#d7dde8);' +
      'border-radius:8px;padding:10px 14px;background:var(--bg-alt,#f8fafc);' +
      'font-size:13px;color:var(--text-muted,#6b7280);';

    const label = document.createElement('span');
    label.textContent = '📋 Tareas del proyecto, en vivo —';
    this.wrapper.appendChild(label);

    const select = document.createElement('select');
    select.innerHTML =
      '<option value="pendientes">Solo pendientes</option><option value="todas">Todas</option>';
    select.value = this.data.filtro;
    select.style.cssText =
      'font-size:12px;padding:3px 8px;border-radius:6px;border:1px solid var(--border,#d7dde8);' +
      'background:var(--bg,#fff);color:var(--text,#111827);';
    select.addEventListener('change', () => { this.data.filtro = select.value; });
    this.wrapper.appendChild(select);

    const hint = document.createElement('span');
    hint.textContent = '(se mostrará la lista real al ver la página)';
    hint.style.cssText = 'font-size:11.5px;color:#9ca3af;';
    this.wrapper.appendChild(hint);

    return this.wrapper;
  }

  save() {
    return this.data;
  }
}
