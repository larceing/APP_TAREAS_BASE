/* Conversacion de un muro -- comun a templates/muro.html (pagina central
 * /muro/) y templates/muro_proyecto.html (pestana Muro). Pinta los mensajes en
 * el navegador (siempre con textContent: nunca HTML que venga del servidor),
 * pregunta cada pocos segundos si hay novedades (GET <base>mensajes) y
 * escribe/borra/deshace/silencia con fetch + JSON y la cabecera X-CSRFToken.
 *
 * Las rutas son las mismas en los dos routers, solo cambia la base:
 *   /espacio/<id>/muro/    muro de todo el espacio
 *   /proyecto/<id>/muro/   solo lo de un proyecto
 *
 * Uso: SalaChat.iniciar({ base, yo, esIT, iconos, ... }) -- ver muro.html.
 */
(function () {
  'use strict';

  function csrf() { return (typeof getCookie === 'function') ? getCookie('gestor_csrftoken') : ''; }

  function post(url, cuerpo) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
      body: JSON.stringify(cuerpo || {})
    }).then(function (r) { return r.json(); });
  }

  function isoDia(d) {
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  function etiquetaDia(dt) {
    var dia = dt.slice(0, 10), hoy = new Date(), ayer = new Date();
    ayer.setDate(hoy.getDate() - 1);
    if (dia === isoDia(hoy)) return 'Hoy';
    if (dia === isoDia(ayer)) return 'Ayer';
    return dia.slice(8, 10) + '/' + dia.slice(5, 7) + '/' + dia.slice(0, 4);
  }

  function avatar(nombre, uid) {
    var s = document.createElement('span');
    s.className = 'mu-avatar';
    s.style.background = 'hsl(' + ((uid || 0) * 67 % 360) + ',55%,46%)';
    var partes = (nombre || '?').replace(/_/g, ' ').split(/\s+/).filter(Boolean);
    s.textContent = ((partes[0] || '?')[0] + (partes[1] ? partes[1][0] : '')).toUpperCase();
    return s;
  }

  function el(tag, clase, texto) {
    var e = document.createElement(tag);
    if (clase) e.className = clase;
    if (texto !== undefined) e.textContent = texto;
    return e;
  }

  // etiqueta con el proyecto del mensaje (solo en el muro del espacio: en la
  // pestana Muro de un proyecto todos son del mismo, sobra)
  function etiquetaProyecto(m, cfg) {
    if (!cfg.mostrarProyecto || !m.proyecto) return null;
    var a = el('a', 'mu-proy', m.proyecto);
    a.href = '/proyecto/' + encodeURIComponent(m.proyecto_id) + '/muro/';
    a.title = 'Ver el muro de ' + m.proyecto;
    if (m.proyecto_color) a.style.setProperty('--mu-proy-color', m.proyecto_color);
    return a;
  }

  function iniciar(cfg) {
    var feed = document.getElementById(cfg.feedId || 'muFeed');
    var ta = document.getElementById(cfg.textareaId || 'muTexto');
    var btn = document.getElementById(cfg.enviarId || 'muEnviar');
    var ultimaFirma = '';
    var activo = true;

    function iconoSistema(texto) {
      var palabras = texto.split(' ');
      for (var i = 0; i < Math.min(palabras.length, 6); i++) {
        if (cfg.iconos && cfg.iconos[palabras[i]]) return cfg.iconos[palabras[i]];
      }
      return cfg.iconoDefecto || '';
    }

    function pintar(mensajes) {
      var abajo = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 80;
      feed.innerHTML = '';
      if (!mensajes.length) {
        feed.innerHTML = cfg.vacioHtml || '';
        return;
      }
      var diaActual = '';
      mensajes.forEach(function (m) {
        var dia = m.creado_en.slice(0, 10);
        if (dia !== diaActual) {
          diaActual = dia;
          feed.appendChild(el('div', 'mu-dia', etiquetaDia(m.creado_en)));
        }
        var hora = m.creado_en.slice(11, 16);

        if (m.borrado) {
          var b = el('div', 'mu-borrado');
          b.appendChild(document.createTextNode('Has borrado este mensaje · '));
          var undo = el('button', '', 'Deshacer (' + m.deshacer_quedan + ' s)');
          undo.type = 'button';
          undo.onclick = function () { post(cfg.base + 'mensaje/' + m.id + '/deshacer/').then(cargar); };
          b.appendChild(undo);
          feed.appendChild(b);
          return;
        }

        if (m.es_aviso) {
          var av = el('div', 'mu-aviso');
          var cab = el('div', 'mu-aviso-cab');
          var ic = el('span', 'mu-aviso-icono'); ic.innerHTML = cfg.iconoAviso || '';
          cab.appendChild(ic);
          cab.appendChild(el('strong', '', 'Aviso'));
          cab.appendChild(el('span', 'mu-hora', (m.autor || '') + ' · ' + hora));
          if (cfg.esIT && cfg.borrarAvisoUrl) {
            var quitar = el('button', 'mu-aviso-quitar', 'Quitar');
            quitar.type = 'button';
            quitar.onclick = function () {
              if (confirm('¿Quitar este aviso de todas las salas donde se difundió? Solo se quita este.')) {
                post(cfg.borrarAvisoUrl(m.id)).then(cargar);
              }
            };
            cab.appendChild(quitar);
          }
          av.appendChild(cab);
          av.appendChild(el('div', 'mu-texto', m.contenido));
          feed.appendChild(av);
          return;
        }

        if (m.es_sistema) {
          var s = el('div', 'mu-sistema');
          var dot = el('span', 'mu-sistema-dot'); dot.innerHTML = iconoSistema(m.contenido);
          var t = el('span', 'mu-sistema-texto');
          var chipS = etiquetaProyecto(m, cfg);
          if (chipS) t.appendChild(chipS);
          t.appendChild(document.createTextNode(m.contenido));
          if (m.url && m.url.charAt(0) === '/') {
            var a = el('a', '', 'Ver →'); a.href = m.url; t.appendChild(a);
          }
          s.appendChild(dot); s.appendChild(t); s.appendChild(el('span', 'mu-hora', hora));
          feed.appendChild(s);
          return;
        }

        var mio = m.user_id === cfg.yo;
        var fila = el('div', 'mu-msg' + (mio ? ' mu-mio' : ''));
        var burbuja = el('div', 'mu-burbuja');
        var autor = el('div', 'mu-autor');
        autor.appendChild(el('span', '', mio ? 'Tú' : (m.autor || 'Usuario eliminado')));
        autor.appendChild(el('span', 'mu-hora', hora));
        var chipM = etiquetaProyecto(m, cfg);
        if (chipM) autor.appendChild(chipM);
        burbuja.appendChild(autor);
        burbuja.appendChild(el('div', 'mu-texto', m.contenido));
        if (mio) {
          var del = el('button', 'mu-borrar'); del.type = 'button'; del.title = 'Borrar mensaje';
          del.innerHTML = cfg.iconoBorrar || '×';
          del.onclick = function () { post(cfg.base + 'mensaje/' + m.id + '/borrar/').then(cargar); };
          burbuja.appendChild(del);
        }
        fila.appendChild(avatar(m.autor, m.user_id));
        fila.appendChild(burbuja);
        feed.appendChild(fila);
      });
      if (abajo || !feed.dataset.pintado) feed.scrollTop = feed.scrollHeight;
      feed.dataset.pintado = '1';
    }

    function cargar() {
      return fetch(cfg.base + 'mensajes', { headers: { 'Accept': 'application/json' } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (!d) return;
          var firma = JSON.stringify(d.mensajes);
          if (firma !== ultimaFirma) { ultimaFirma = firma; pintar(d.mensajes); }
          if (cfg.alCargar) cfg.alCargar(d);
        }).catch(function () {});
    }

    function enviar() {
      var texto = ta.value.trim();
      if (!texto) return;
      btn.disabled = true;
      var cuerpo = { contenido: texto };
      var selProy = cfg.proyectoSelectId && document.getElementById(cfg.proyectoSelectId);
      if (selProy && selProy.value) cuerpo.proyecto_id = selProy.value;
      post(cfg.base + 'escribir/', cuerpo).then(function (r) {
        btn.disabled = false;
        if (r.ok) { ta.value = ''; ta.style.height = ''; delete feed.dataset.pintado; cargar(); }
        else if (r.error) { alert(r.error); }
      }).catch(function () { btn.disabled = false; });
    }

    if (ta && btn) {
      btn.onclick = enviar;
      ta.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); enviar(); }
      });
      ta.addEventListener('input', function () {
        ta.style.height = 'auto';
        ta.style.height = Math.min(ta.scrollHeight, 140) + 'px';
      });
    }

    cargar();
    // con un mensaje borrado en cuenta atras, refrescar cada segundo; si no,
    // cada 'intervalo' (y nada mientras la pestaña esta oculta)
    (function bucle() {
      if (!activo) return;
      var hayCuenta = ultimaFirma.indexOf('"borrado":true') !== -1;
      setTimeout(function () {
        (document.hidden && !hayCuenta ? Promise.resolve() : cargar()).then(bucle);
      }, hayCuenta ? 1000 : (cfg.intervalo || 4000));
    })();

    return {
      recargar: cargar,
      silenciar: function () { return post(cfg.base + 'silenciar/'); },
      parar: function () { activo = false; }
    };
  }

  window.SalaChat = { iniciar: iniciar, post: post };
})();
