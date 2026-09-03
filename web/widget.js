/*
 * Widget Aguas Brasil - assistente virtual embutivel.
 *
 * Uso na pagina:
 *   <link rel="stylesheet" href="URL/web/widget.css">
 *   <script src="URL/web/widget.js" data-api="URL"></script>
 *
 * data-api: base da API (onde roda o backend). Se ausente, usa a mesma origem.
 */
(function () {
  "use strict";

  var script = document.currentScript;
  var API = (script && script.getAttribute("data-api")) || "";
  API = API.replace(/\/$/, "");

  var STORAGE_KEY = "abw_session_id";

  function el(tag, cls, txt) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }

  // Renderiza texto com quebras de linha e links (sem innerHTML, seguro).
  function renderText(container, text) {
    var linkRe = /(https?:\/\/[^\s]+)/g;
    text.split("\n").forEach(function (line, i) {
      if (i > 0) container.appendChild(document.createElement("br"));
      var last = 0, m;
      linkRe.lastIndex = 0;
      while ((m = linkRe.exec(line)) !== null) {
        if (m.index > last) container.appendChild(document.createTextNode(line.slice(last, m.index)));
        var a = el("a", null, m[0]);
        a.href = m[0]; a.target = "_blank"; a.rel = "noopener noreferrer";
        container.appendChild(a);
        last = m.index + m[0].length;
      }
      if (last < line.length) container.appendChild(document.createTextNode(line.slice(last)));
    });
  }

  // Icones (SVG inline, sem dependencia externa). Tracos em currentColor.
  var ICONS = {
    user: '<circle cx="12" cy="8" r="3.2"/><path d="M5.5 19a6.5 6.5 0 0 1 13 0"/>',
    doc: '<path d="M6 3h7l5 5v13H6z"/><path d="M13 3v5h5"/>',
    coin: '<circle cx="12" cy="12" r="8"/><path d="M12 7v10M14.5 9.5h-4a1.8 1.8 0 0 0 0 3.6h3a1.8 1.8 0 0 1 0 3.6h-4"/>',
    drop: '<path d="M12 3s6 6.5 6 10.5a6 6 0 0 1-12 0C6 9.5 12 3 12 3z"/>',
    receipt: '<path d="M6 3h12v18l-2-1.5L14 21l-2-1.5L10 21l-2-1.5L6 21z"/><path d="M9 8h6M9 12h6"/>',
    shield: '<path d="M12 3l7 3v5c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/>',
    globe: '<circle cx="12" cy="12" r="8"/><path d="M4 12h16M12 4c2.5 2.5 2.5 13 0 16M12 4c-2.5 2.5-2.5 13 0 16"/>',
    info: '<circle cx="12" cy="12" r="8"/><path d="M12 11v5M12 8h.01"/>',
    ticket: '<path d="M4 9a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2 2 2 0 0 0 0 4 2 2 0 0 1-2 2H6a2 2 0 0 1-2-2 2 2 0 0 0 0-4z"/>',
    edit: '<path d="M4 20h4L18 10l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
    back: '<path d="M15 6l-6 6 6 6"/>',
    home: '<path d="M4 11l8-7 8 7"/><path d="M6 10v9h12v-9"/>',
    check: '<path d="M5 12l5 5 9-10"/>',
    refresh: '<path d="M20 11a8 8 0 0 0-14-4M4 5v4h4M4 13a8 8 0 0 0 14 4M20 19v-4h-4"/>',
    flag: '<path d="M6 3v18"/><path d="M6 4h11l-2 4 2 4H6"/>'
  };

  function iconEl(name) {
    var span = el("span", "abw-ic");
    if (ICONS[name]) {
      span.innerHTML = '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" ' +
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
        'stroke-linejoin="round">' + ICONS[name] + '</svg>';
    }
    return span;
  }

  // Remove as linhas de opcao numeradas e a dica "Digite 0" quando os botoes
  // (chips) ja mostram as opcoes - evita redundancia visual.
  function cleanReply(text, hasOptions) {
    if (!hasOptions) return text;
    return text.split("\n").filter(function (line) {
      var t = line.trim();
      if (/^\d+\)\s/.test(t)) return false;
      if (/^digite 0/i.test(t)) return false;
      return true;
    }).join("\n").replace(/\n{3,}/g, "\n\n").trim();
  }

  function clearChips() {
    var c = body.querySelector(".abw-chips");
    if (c) c.remove();
  }

  function renderOptions(options) {
    clearChips();
    if (!options || !options.length) return;
    var wrap = el("div", "abw-chips");
    options.forEach(function (o) {
      var chip = el("button", "abw-chip");
      if (o.icon) chip.appendChild(iconEl(o.icon));
      chip.appendChild(el("span", null, o.label));
      chip.onclick = function () { sendValue(o.value, o.label); };
      wrap.appendChild(chip);
    });
    body.appendChild(wrap);
  }

  // Rola para o INICIO da mensagem (topo alinhado ao topo do corpo), para o
  // usuario ler a resposta desde o comeco - respostas longas nao "correm" ate o
  // fim. O navegador limita o scroll, entao mensagens curtas ficam inteiras.
  function scrollMsgTop(m) {
    if (!m) return;
    body.scrollTop += m.getBoundingClientRect().top - body.getBoundingClientRect().top;
  }

  var root, body, input, sendBtn, sessionId = null, busy = false;

  function build() {
    root = el("div", "abw-root");

    var launcher = el("div", "abw-launcher");
    launcher.setAttribute("role", "button");
    launcher.setAttribute("aria-label", "Abrir assistente virtual");
    launcher.tabIndex = 0;
    var logo = el("img");
    logo.src = API + "/web/logo-sm.png";
    logo.alt = "Assistente Aguas Brasil";
    launcher.appendChild(logo);
    launcher.appendChild(el("span", "abw-caption", "Posso Ajudar?"));
    launcher.onclick = toggle;
    launcher.onkeydown = function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
    };

    var panel = el("div", "abw-panel");

    var header = el("div", "abw-header");
    var brand = el("div", "abw-brand");
    var headLogo = el("img", "abw-headlogo");
    headLogo.src = API + "/web/logo-sm.png";
    headLogo.alt = "";
    var brandText = el("div", "abw-brandtext");
    brandText.appendChild(el("h3", null, "Assistente Virtual"));
    brandText.appendChild(el("p", null, "Plataforma Aguas Brasil - ANA"));
    brand.appendChild(headLogo); brand.appendChild(brandText);
    var maxBtn = el("button", "abw-max");
    maxBtn.setAttribute("aria-label", "Maximizar janela");
    maxBtn.title = "Maximizar";
    maxBtn.appendChild(el("i"));
    maxBtn.onclick = toggleMax;
    var close = el("button", "abw-close", "x");
    close.setAttribute("aria-label", "Fechar");
    close.onclick = toggle;
    header.appendChild(brand);
    header.appendChild(maxBtn); header.appendChild(close);

    body = el("div", "abw-body");

    var footer = el("div", "abw-footer");
    input = el("input");
    input.type = "text";
    input.placeholder = "Digite sua mensagem...";
    input.onkeydown = function (e) { if (e.key === "Enter") send(); };
    sendBtn = el("button", null, "Enviar");
    sendBtn.onclick = send;
    footer.appendChild(input); footer.appendChild(sendBtn);

    panel.appendChild(header); panel.appendChild(body); panel.appendChild(footer);
    root.appendChild(panel); root.appendChild(launcher);
    document.body.appendChild(root);
  }

  function toggle() {
    var opening = !root.classList.contains("abw-open");
    root.classList.toggle("abw-open");
    if (!opening) root.classList.remove("abw-maximized");
    if (opening && body.childElementCount === 0) start();
    if (opening) setTimeout(function () { input.focus(); }, 50);
  }

  function toggleMax() {
    var maxed = root.classList.toggle("abw-maximized");
    var btn = root.querySelector(".abw-max");
    if (btn) {
      btn.title = maxed ? "Restaurar" : "Maximizar";
      btn.setAttribute("aria-label", maxed ? "Restaurar janela" : "Maximizar janela");
    }
    input.focus();
  }

  function addMsg(text, who) {
    var m = el("div", "abw-msg " + who);
    renderText(m, text);
    body.appendChild(m);
    body.scrollTop = body.scrollHeight;
    return m;
  }

  function setTyping(on) {
    var t = document.getElementById("abw-typing");
    if (on && !t) {
      t = el("div", "abw-typing", "digitando...");
      t.id = "abw-typing";
      body.appendChild(t); body.scrollTop = body.scrollHeight;
    } else if (!on && t) {
      t.remove();
    }
  }

  function post(message) {
    busy = true; sendBtn.disabled = true; setTyping(true);
    return fetch(API + "/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: message, session_id: sessionId })
    }).then(function (r) {
        return r.json().then(function (body) { return { status: r.status, body: body }; });
      })
      .then(function (res) {
        setTyping(false);
        if (res.status === 429) {
          addMsg((res.body && res.body.detail) || "Aguarde um momento e tente novamente.", "bot");
          return;
        }
        if (res.status >= 400) {
          addMsg("Ocorreu um erro. Tente novamente em instantes.", "bot");
          return;
        }
        sessionId = res.body.session_id;
        try { localStorage.setItem(STORAGE_KEY, sessionId); } catch (e) {}
        var opts = res.body.options || [];
        var m = addMsg(cleanReply(res.body.reply, opts.length > 0), "bot");
        renderOptions(opts);
        scrollMsgTop(m);   // mostra o inicio da resposta, nao o fim
      })
      .catch(function () {
        setTyping(false);
        addMsg("Nao foi possivel conectar ao assistente. Tente novamente.", "bot");
      })
      .finally(function () { busy = false; sendBtn.disabled = false; });
  }

  function start() {
    try { sessionId = localStorage.getItem(STORAGE_KEY); } catch (e) {}
    post("__start__");
  }

  function send() {
    if (busy) return;
    var text = input.value.trim();
    if (!text) return;
    clearChips();
    addMsg(text, "user");
    input.value = "";
    post(text);
  }

  // Clique num chip: mostra o rotulo como mensagem do usuario e envia o valor.
  function sendValue(value, label) {
    if (busy) return;
    clearChips();
    addMsg(label, "user");
    post(value);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", build);
  } else {
    build();
  }
})();
