/* SPA «Второе мнение»: vanilla JS, без фреймворков */
"use strict";

/* ---------- состояние ---------- */
var state = {
  token: sessionStorage.getItem("vo_token") || null,
  user: null,
  authMode: "login",
  file: null,
  result: null,
  historyItemId: null
};

/* ---------- утилиты ---------- */
function $(sel) { return document.querySelector(sel); }
function $$(sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); }

function esc(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
    var map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
    return map[ch];
  });
}

function show(id) { var el = document.getElementById(id); if (el) el.classList.remove("hidden"); }
function hide(id) { var el = document.getElementById(id); if (el) el.classList.add("hidden"); }

function showView(name) {
  ["view-login", "view-cabinet", "view-analyze"].forEach(function (v) {
    if (v === name) show(v); else hide(v);
  });
  var nav = $("#main-nav");
  nav.classList.toggle("hidden", name === "view-login");
}

function formatDate(iso) {
  if (!iso) return "—";
  var d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function fmtNum(n) {
  return Number(n == null ? 0 : n).toLocaleString("ru-RU", { maximumFractionDigits: 2 });
}

function yearsRu(value) {
  var v = Number(value == null ? 0 : value);
  if (isNaN(v)) return String(value);
  if (v !== Math.floor(v)) return String(v).replace(".", ",") + " года";
  var m10 = v % 10, m100 = v % 100;
  if (m10 === 1 && m100 !== 11) return v + " год";
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return v + " года";
  return v + " лет";
}

function monthsRu(value) {
  var v = Number(value == null ? 0 : value);
  if (isNaN(v)) return String(value);
  var m10 = v % 10, m100 = v % 100;
  if (m10 === 1 && m100 !== 11) return v + " месяц";
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return v + " месяца";
  return v + " месяцев";
}

/* ---------- русские подписи ---------- */
var MITIGATING_LABELS = {
  "явка_с_повинной": "Явка с повинной",
  "активное_способствование": "Активное способствование раскрытию преступления",
  "возмещение_ущерба": "Возмещение ущерба",
  "малолетние_дети": "Наличие малолетних детей",
  "беременность": "Беременность",
  "несовершеннолетний_виновный": "Несовершеннолетний виновный",
  "признание_вины": "Признание вины",
  "раскаяние": "Раскаяние",
  "аморальность_потерпевшего": "Аморальность поведения потерпевшего",
  "тяжелые_жизненные_обстоятельства": "Тяжёлые жизненные обстоятельства",
  "оказание_помощи_потерпевшему": "Оказание помощи потерпевшему",
  "состояние_здоровья": "Состояние здоровья"
};

var AGGRAVATING_LABELS = {
  "рецидив": "Рецидив преступлений",
  "особо_активная_роль": "Особо активная роль",
  "группа_лиц": "Совершение в группе лиц",
  "опьянение": "Совершение в состоянии опьянения",
  "в_отношении_малолетнего": "В отношении малолетнего",
  "особая_жестокость": "Особая жестокость",
  "использование_служебного_положения": "Использование служебного положения"
};

var PUNISHMENT_LABELS = {
  "лишение свободы": "Лишение свободы",
  "штраф": "Штраф",
  "обязательные работы": "Обязательные работы",
  "исправительные работы": "Исправительные работы",
  "принудительные работы": "Принудительные работы",
  "ограничение свободы": "Ограничение свободы",
  "ограничение по военной службе": "Ограничение по военной службе",
  "арест": "Арест",
  "лишение права занимать определённые должности": "Лишение права занимать должности"
};

var RECIDIVISM_LABELS = { "нет": "Отсутствует", "простой": "Простой", "опасный": "Опасный", "особо опасный": "Особо опасный" };
var STAGE_LABELS = { "оконченное": "Оконченное преступление", "приготовление": "Приготовление", "покушение": "Покушение" };
var LEVEL_LABELS = { "ошибка": "Ошибка", "предупреждение": "Предупреждение", "информация": "Информация" };
var LEVEL_CLASS = { "ошибка": "error", "предупреждение": "warn", "информация": "info" };

var STAT_LABELS = {
  "count": "Число похожих дел",
  "mean_years": "Средний срок (лет)",
  "median_years": "Медианный срок (лет)",
  "min_years": "Минимальный срок (лет)",
  "max_years": "Максимальный срок (лет)",
  "p25": "25-й процентиль (лет)",
  "p75": "75-й процентиль (лет)",
  "deviation_years": "Отклонение от медианы (лет)",
  "deviation_percent": "Отклонение от медианы (%)"
};

var DISCLAIMER = "Система является вспомогательным инструментом, не принимает судебных решений и не заменяет судью. Заключение носит справочный характер.";

/* ---------- запросы к API ---------- */
function authHeaders() {
  return state.token ? { "Authorization": "Bearer " + state.token } : {};
}

async function api(path, options) {
  options = options || {};
  var headers = options.headers ? Object.assign({}, options.headers) : {};
  var isForm = options.body instanceof FormData;
  if (state.token && !isForm) headers["Authorization"] = "Bearer " + state.token;
  var resp = await fetch(path, Object.assign({}, options, { headers: headers }));
  var data = null;
  try { data = await resp.json(); } catch (e) { data = null; }
  if (!resp.ok) {
    var detail = "Ошибка запроса";
    if (data && data.detail) {
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    }
    var err = new Error(detail);
    err.status = resp.status;
    throw err;
  }
  return data;
}

/* ---------- авторизация ---------- */
function setToken(token) {
  state.token = token;
  if (token) sessionStorage.setItem("vo_token", token);
  else sessionStorage.removeItem("vo_token");
}

function showLogin() {
  state.user = null;
  setAuthMode("login");
  showView("view-login");
  var errBox = $("#auth-error");
  errBox.classList.add("hidden");
  $("#auth-form").reset();
}

function setAuthMode(mode) {
  state.authMode = mode;
  $$("#auth-tabs .tab").forEach(function (t) {
    t.classList.toggle("active", t.getAttribute("data-mode") === mode);
  });
  $("#field-fullname").classList.toggle("hidden", mode !== "register");
  $("#auth-submit").textContent = mode === "register" ? "Зарегистрироваться" : "Войти";
}

async function submitAuth(event) {
  event.preventDefault();
  var username = $("#auth-username").value.trim();
  var password = $("#auth-password").value;
  var fullName = $("#auth-fullname").value.trim();
  var errBox = $("#auth-error");
  errBox.classList.add("hidden");
  try {
    if (state.authMode === "register") {
      await api("/api/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username, password: password, full_name: fullName })
      });
    }
    var data = await api("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: username, password: password })
    });
    setToken(data.token);
    state.user = await api("/api/me");
    showCabinet();
  } catch (e) {
    errBox.textContent = e.message;
    errBox.classList.remove("hidden");
  }
}

async function logout() {
  try {
    await api("/api/logout", { method: "POST", headers: authHeaders() });
  } catch (e) { /* токен всё равно удаляем */ }
  setToken(null);
  showLogin();
}

/* ---------- личный кабинет ---------- */
async function showCabinet() {
  showView("view-cabinet");
  $("#cabinet-greeting").textContent =
    "Здравствуйте, " + (state.user.full_name || state.user.username) + "! Ниже — ваши прошлые анализы.";
  await loadHistory();
}

async function loadHistory() {
  var tbody = $("#history-body");
  try {
    var rows = await api("/api/history");
    $("#history-empty").hidden = rows.length > 0;
    tbody.innerHTML = "";
    rows.forEach(function (row) {
      var tr = document.createElement("tr");
      var status = row.ok === null ? '<span class="badge badge-warn">Недостаточно данных</span>' : row.ok
        ? '<span class="badge badge-ok">Проверено частично</span>'
        : '<span class="badge badge-bad">Есть замечания</span>';
      tr.innerHTML =
        '<td class="cell-file">' + esc(row.filename) + "</td>" +
        "<td>" + esc(formatDate(row.created_at)) + "</td>" +
        "<td>" + esc(row.article ? "ст. " + row.article : "—") + "</td>" +
        "<td>" + status + "</td>" +
        '<td class="cell-actions">' +
        '<button class="btn btn-small btn-secondary" data-action="open" data-id="' + row.id + '">Открыть</button> ' +
        '<button class="btn btn-small btn-danger" data-action="delete" data-id="' + row.id + '">Удалить</button>' +
        "</td>";
      tbody.appendChild(tr);
    });
  } catch (e) {
    if (e.status === 401) { setToken(null); showLogin(); return; }
    var empty = $("#history-empty");
    empty.textContent = "Не удалось загрузить историю: " + e.message;
    empty.hidden = false;
  }
}

async function openHistoryItem(id) {
  try {
    var item = await api("/api/history/" + id);
    showAnalyzeView();
    $("#upload-card").classList.add("hidden");
    $("#analyze-subtitle").textContent =
      "Результат анализа файла «" + item.filename + "» от " + formatDate(item.created_at);
    state.result = item.result;
    state.historyItemId = id;
    renderResult(item.result);
  } catch (e) {
    alert("Не удалось открыть запись: " + e.message);
  }
}

async function deleteHistoryItem(id) {
  if (!window.confirm("Удалить запись об анализе?")) return;
  try {
    await api("/api/history/" + id, { method: "DELETE", headers: authHeaders() });
  } catch (e) {
    alert(e.message);
  }
  await loadHistory();
}

/* ---------- рабочая область анализа ---------- */
function showAnalyzeView() {
  showView("view-analyze");
  $("#upload-card").classList.remove("hidden");
  $("#result-block").classList.add("hidden");
  $("#analyze-subtitle").textContent =
    "Загрузите проект судебного акта — система извлечёт параметры дела, проверит наказание и покажет похожие дела.";
  $("#file-input").value = "";
  state.file = null;
  state.result = null;
  state.historyItemId = null;
  $("#file-name").textContent = "Файл не выбран";
  $("#analyze-error").classList.add("hidden");
  $("#consent-check").checked = false;
  updateAnalyzeButton();
}

function setFile(file) {
  if (!file) return;
  if (!/\.(pdf|docx|txt)$/i.test(file.name)) {
    showAnalyzeError("Неподдерживаемый формат файла. Допустимы: .pdf, .docx, .txt");
    return;
  }
  state.file = file;
  $("#file-name").textContent = file.name + " (" + (file.size / 1024 / 1024).toFixed(2) + " МБ)";
  updateAnalyzeButton();
}

function updateAnalyzeButton() {
  $("#btn-analyze").disabled = !(state.file && $("#consent-check").checked);
}

function showAnalyzeError(message) {
  var box = $("#analyze-error");
  box.textContent = message;
  box.classList.remove("hidden");
}

async function runAnalysis() {
  if (!state.file || !$("#consent-check").checked) return;
  $("#analyze-error").classList.add("hidden");
  var fd = new FormData();
  fd.append("file", state.file);
  fd.append("consent", "true");
  $("#progress").classList.remove("hidden");
  $("#btn-analyze").disabled = true;
  try {
    var resp = await fetch("/api/analyze", { method: "POST", headers: authHeaders(), body: fd });
    var data = null;
    try { data = await resp.json(); } catch (e) { data = null; }
    if (!resp.ok) {
      var detail = data && data.detail ? data.detail : "Ошибка запроса";
      if (typeof detail !== "string") detail = JSON.stringify(detail);
      throw new Error(detail);
    }
    state.result = data;
    $("#upload-card").classList.add("hidden");
    renderResult(data);
    $("#result-block").scrollIntoView({ behavior: "smooth" });
  } catch (e) {
    showAnalyzeError(e.message);
  } finally {
    $("#progress").classList.add("hidden");
    updateAnalyzeButton();
  }
}

/* ---------- отображение результата ---------- */
function switchTab(name) {
  $$("#result-tabs .tab").forEach(function (t) {
    t.classList.toggle("active", t.getAttribute("data-tab") === name);
  });
  ["parameters", "check", "similar", "conclusion", "masked"].forEach(function (n) {
    $("#pane-" + n).classList.toggle("hidden", n !== name);
  });
}

function labeledList(items, labels) {
  if (!items || !items.length) return "";
  return items.map(function (k) { return labels[k] || k; }).join("; ");
}

function formatPunishment(p) {
  var type = PUNISHMENT_LABELS[p.punishment_type] || p.punishment_type || "не определено";
  var parts = [type];
  if (p.punishment_years) parts.push(yearsRu(p.punishment_years));
  if (p.punishment_months) parts.push(monthsRu(p.punishment_months));
  if (p.fine_rub) parts.push(fmtNum(p.fine_rub) + " ₽");
  return parts.join(", ");
}

function renderParameters(p) {
  var person = p.person || {};
  var rows = [
    ["Статья УК РФ", p.article ? "ст. " + p.article + (p.part ? " ч. " + p.part : "") : "не определена"],
    ["Назначенное наказание", formatPunishment(p)],
    ["Смягчающие обстоятельства", labeledList(p.mitigating, MITIGATING_LABELS) || "не извлечены; нужна проверка"],
    ["Отягчающие обстоятельства", labeledList(p.aggravating, AGGRAVATING_LABELS) || "не извлечены; нужна проверка"]
  ];
  if (p.stage) rows.push(["Стадия преступления", STAGE_LABELS[p.stage] || p.stage]);
  if (p.probation) {
    var termText = "не извлечён";
    if (p.probation_years != null || p.probation_months != null) {
      termText = ((p.probation_years || 0) * 12 + (p.probation_months || 0)) + " мес.";
    }
    rows.push(["Условное осуждение", "применено (ст. 73 УК РФ); испытательный срок: " + termText]);
  }
  if (person.recidivism && person.recidivism !== "нет") {
    rows.push(["Рецидив", RECIDIVISM_LABELS[person.recidivism] || person.recidivism]);
  }
  rows.push(["Несовершеннолетний", person.is_minor === true ? "да" : person.is_minor === false ? "нет" : "не установлено"]);
  if (p.crime_date) rows.push(["Дата преступления", p.crime_date]);
  if (p.release_grounds && p.release_grounds.length) {
    rows.push(["Основания освобождения", p.release_grounds.join(", ")]);
  }
  var body = rows.map(function (pair) {
    return "<tr><th>" + esc(pair[0]) + "</th><td>" + esc(pair[1]) + "</td></tr>";
  }).join("");
  $("#pane-parameters").innerHTML =
    "<h3>Параметры дела</h3>" +
    '<p class="muted small">Идентификатор анализа: ' + esc(p.case_id || "—") + "</p>" +
    '<table class="table kv">' + body + "</table>";
}

function renderCheck(check) {
  var limitLabels = {sanction_min_years:"Минимум лишения свободы по справочнику, лет",sanction_max_years:"Максимум лишения свободы по справочнику, лет",sanction_fine_min:"Минимум штрафа, руб.",sanction_fine_max:"Максимум штрафа, руб.",cap_rules:"Учтённые правила",effective_max:"Расчётный максимум, лет",recidivism_min_1_3_max:"Одна треть максимума с учётом стадии, лет",probation_term_min_years:"Минимальный испытательный срок, лет",probation_term_max_years:"Максимальный испытательный срок, лет",probation_term_basis:"Основание предела испытательного срока"};
  check = check || {};
  var violations = check.violations || [];
  var html = "<h3>Проверка наказания</h3>";
  if (check.status === "incomplete" || check.ok === null) {
    html += '<div class="result-banner warn">Недостаточно данных для проверки. Результат требует ручного анализа.</div>';
  } else if (check.ok && violations.length === 0) {
    html += '<div class="result-banner ok">В проверенной части несоответствий не выявлено. Полная законность не подтверждена.</div>';
  } else if (check.ok) {
    html += '<div class="result-banner ok">Частичная проверка завершена. Проверьте замечания, извлечённые факты и применимую редакцию закона.</div>';
  } else {
    html += '<div class="result-banner bad">Обнаружены замечания. Ознакомьтесь со списком ниже — возможно, наказание требует корректировки.</div>';
  }
  if (violations.length) {
    html += '<ul class="violations">' + violations.map(function (v) {
      var cls = LEVEL_CLASS[v.level] || "info";
      return '<li class="violation ' + cls + '">' +
        '<span class="badge badge-' + cls + '">' + esc(LEVEL_LABELS[v.level] || v.level) + "</span>" +
        "<div>" +
        '<div class="violation-code">' + esc(v.code || "") + "</div>" +
        "<div>" + esc(v.message) + "</div>" +
        "</div></li>";
    }).join("") + "</ul>";
  }
  if (check.warnings && check.warnings.length) {
    html += "<h4>Дополнительные замечания</h4><ul>" +
      check.warnings.map(function (w) { return "<li>" + esc(w) + "</li>"; }).join("") + "</ul>";
  }
  if (check.limits && Object.keys(check.limits).length) {
    html += "<h4>Пределы, применённые при проверке</h4><table class='table kv'>" +
      Object.keys(check.limits).map(function (k) {
        return "<tr><th>" + esc(limitLabels[k] || ("Промежуточный предел «" + k + "», лет")) + "</th><td>" + esc(check.limits[k] == null ? "Не задан" : typeof check.limits[k] === "number" ? Number(check.limits[k].toFixed(6)).toLocaleString("ru-RU", {maximumFractionDigits:6}) : check.limits[k]) + "</td></tr>";
      }).join("") + "</table>";
  }
  if (check.trace && check.trace.length) {
    html += "<h4>Как получен расчётный максимум</h4><ol class='calculation'>" + check.trace.map(function (t) {
      return "<li><strong>" + esc(t.norm) + "</strong><br>" + esc(fmtNum(t.base_years)) + " × " + esc(Math.abs(t.factor-2/3)<0.00001 ? "2/3" : t.factor === 0.5 ? "1/2" : t.factor === 0.75 ? "3/4" : fmtNum(t.factor)) + " ≈ " + esc(fmtNum(t.cap_years)) + " лет. Точные значения сохранены в JSON.</li>";
    }).join("") + "</ol>";
  }
  html += recheckFormHtml(state.result ? state.result.parameters : null);
  $("#pane-check").innerHTML = html;
}

var CONTEXT_LABELS = {
  article_64: "Применение ст. 64 УК РФ",
  agreement: "Досудебное соглашение",
  special_order: "Особый порядок (гл. 40 УПК)",
  reduced_inquiry: "Сокращённое дознание",
  jury_leniency: "Снисхождение присяжных",
  aggregate: "Есть совокупность / несколько эпизодов",
  aggregate_crimes: "Именно совокупность преступлений"
};
function contextFormHtml(context) {
  context = context || {};
  return Object.keys(CONTEXT_LABELS).map(function(key) {
    var value = context[key];
    return '<label>' + esc(CONTEXT_LABELS[key]) + '<select name="ctx_' + key + '">' +
      '<option value=""' + (value == null ? ' selected' : '') + '>не установлено</option>' +
      '<option value="true"' + (value === true ? ' selected' : '') + '>да</option>' +
      '<option value="false"' + (value === false ? ' selected' : '') + '>нет</option></select></label>';
  }).join('');
}
function recheckFormHtml(p) {
  p = p || {};
  var person = p.person || {};
  function val(v) { return v == null ? "" : String(v); }
  function opts(obj, sel) {
    return Object.keys(obj).map(function (k) {
      return '<option value="' + esc(k) + '"' + (k === sel ? " selected" : "") + ">" + esc(obj[k]) + "</option>";
    }).join("");
  }
  function chks(name, labels, chosen) {
    return Object.keys(labels).map(function (k) {
      var on = (chosen || []).indexOf(k) >= 0;
      return '<label class="chk"><input type="checkbox" name="' + name + '" value="' + esc(k) + '"' + (on ? " checked" : "") + "> " + esc(labels[k]) + "</label>";
    }).join("");
  }
  return "<details class='recheck'><summary>Пересчитать с уточнёнными параметрами (без документа)</summary>" +
    '<form id="recheck-form">' +
    '<div class="grid2">' +
    '<label>Дата деяния <input name="crime_date" placeholder="ДД.ММ.ГГГГ" value="' + esc(val(p.crime_date)) + '"></label>' +
    '<label>Статья <input name="article" value="' + esc(val(p.article)) + '" placeholder="158"></label>' +
    '<label>Часть <input name="part" value="' + esc(val(p.part)) + '" placeholder="2"></label>' +
    '<label>Вид наказания <select name="punishment_type"><option value="">—</option>' + opts(PUNISHMENT_LABELS, p.punishment_type) + "</select></label>" +
    '<label>Стадия <select name="stage"><option value="">—</option>' + opts(STAGE_LABELS, p.stage) + "</select></label>" +
    '<label>Лет <input type="number" step="0.5" min="0" name="punishment_years" value="' + esc(val(p.punishment_years)) + '"></label>' +
    '<label>Месяцев <input type="number" step="1" min="0" name="punishment_months" value="' + esc(val(p.punishment_months)) + '"></label>' +
    '<label>Штраф, руб. <input type="number" step="1000" min="0" name="fine_rub" value="' + esc(val(p.fine_rub)) + '"></label>' +
    '<label>Рецидив <select name="recidivism"><option value="">не установлено</option>' + opts(RECIDIVISM_LABELS, person.recidivism) + "</select></label>" +
    '<label>Несовершеннолетний <select name="is_minor"><option value="">не установлено</option><option value="true"' + (person.is_minor === true ? " selected" : "") + '>да</option><option value="false"' + (person.is_minor === false ? " selected" : "") + '>нет</option></select></label>' +
    '<label class="chk-row"><input type="checkbox" name="probation"' + (p.probation ? " checked" : "") + "> условное осуждение (ст. 73)</label>" +
    '<label>Испытательный срок, лет <input type="number" step="0.5" min="0" name="probation_years" value="' + esc(val(p.probation_years)) + '"></label>' +
    '<label>Испытательный срок, мес. <input type="number" step="1" min="0" name="probation_months" value="' + esc(val(p.probation_months)) + '"></label>' +
    "</div>" +
    "<h4>Условия расчёта — проверьте по документу</h4><div class='grid2'>" + contextFormHtml(p.rule_context) + "</div>" +
    "<h4>Смягчающие обстоятельства</h4><div class='chk-group'>" + chks("mitigating", MITIGATING_LABELS, p.mitigating) + "</div>" +
    "<h4>Отягчающие обстоятельства</h4><div class='chk-group'>" + chks("aggravating", AGGRAVATING_LABELS, p.aggravating) + "</div>" +
    '<button type="submit" class="btn primary">Пересчитать</button>' +
    '<p class="muted small">Дата и условия расчёта передаются повторно. Сведения, требующие текста документа, проверяются только частично; результат не сохраняется в истории.</p>' +
    "</form></details>";
}

async function runRecheck() {
  var form = $("#recheck-form");
  function num(name) {
    var el = form.querySelector('[name="' + name + '"]');
    return el && el.value !== "" ? Number(el.value) : null;
  }
  var recidivism = form.querySelector('[name="recidivism"]').value;
  var minorVal = form.querySelector('[name="is_minor"]').value;
  var previous = (state.result || {}).parameters || {};
  var context = {};
  Object.keys(CONTEXT_LABELS).forEach(function(key) {
    var value = form.querySelector('[name="ctx_' + key + '"]').value;
    context[key] = value === '' ? null : value === 'true';
  });
  var body = {
    crime_date: form.querySelector('[name="crime_date"]').value.trim() || null,
    rule_context: context,
    review_flags: previous.review_flags || [],
    mentioned_articles: previous.mentioned_articles || [],
    release_grounds: previous.release_grounds || [],
    article: form.querySelector('[name="article"]').value.trim() || null,
    part: form.querySelector('[name="part"]').value.trim() || null,
    punishment_type: form.querySelector('[name="punishment_type"]').value || null,
    punishment_years: num("punishment_years"),
    punishment_months: num("punishment_months"),
    fine_rub: num("fine_rub"),
    probation: form.querySelector('[name="probation"]').checked,
    probation_years: num("probation_years"),
    probation_months: num("probation_months"),
    stage: form.querySelector('[name="stage"]').value || null,
    recidivism: recidivism || null,
    is_minor: minorVal === "" ? null : minorVal === "true",
    mitigating: $$('#recheck-form input[name="mitigating"]:checked').map(function (i) { return i.value; }),
    aggravating: $$('#recheck-form input[name="aggravating"]:checked').map(function (i) { return i.value; })
  };
  try {
    var data = await api("/api/recheck", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    renderResult(data);
  } catch (e) {
    alert("Пересчёт не выполнен: " + e.message);
  }
}

function formatSimilarPunishment(c) {
  var type = PUNISHMENT_LABELS[c.punishment_type] || c.punishment_type || "—";
  var parts = [type];
  if (c.years) parts.push(yearsRu(c.years));
  if (c.months) parts.push(monthsRu(c.months));
  if (c.fine_rub) parts.push(fmtNum(c.fine_rub) + " ₽");
  return parts.join(", ");
}

function renderSimilar(similar, stats) {
  var html = "<h3>Учебные аналоги</h3><p class='source-note'>Синтетические примеры. Поисковый балл показывает относительное ранжирование; это не вероятность сходства. Медиана не отражает реальную судебную практику.</p>";
  if (!similar || !similar.length) {
    html += '<p class="muted">Похожие дела не найдены.</p>';
  } else {
    var rows = similar.map(function (c) {
      var article = c.article ? "ст. " + c.article + (c.part ? " ч. " + c.part : "") : "—";
      return "<tr>" +
        "<td>" + esc(c.id) + "</td>" +
        "<td>" + esc(article) + "</td>" +
        "<td>" + esc(formatSimilarPunishment(c)) + "</td>" +
        "<td>" + esc(fmtNum(c.score == null ? 0 : c.score)) + "</td>" +
        '<td class="cell-summary">' + esc(c.summary || "") + "</td>" +
        "</tr>";
    }).join("");
    html += '<table class="table"><thead><tr>' +
      "<th>Дело</th><th>Статья</th><th>Наказание</th><th>Балл поиска</th><th>Краткое описание</th>" +
      "</tr></thead><tbody>" + rows + "</tbody></table>";
  }
  html += "<h4>Статистика по похожим делам</h4>";
  if (stats && Object.keys(stats).length) {
    var cards = Object.keys(stats).filter(function(k) { return typeof stats[k] === "number"; }).map(function (k) {
      var v = stats[k];
      var shown = typeof v === "number" && isFinite(v) ? fmtNum(v) : String(v == null ? "" : v);
      return '<div class="stat"><div class="stat-value">' + esc(shown) + "</div>" +
        '<div class="stat-label">' + esc(STAT_LABELS[k] || k) + "</div></div>";
    }).join("");
    html += '<div class="stats">' + cards + "</div>";
  } else {
    html += '<p class="muted">Статистика недоступна.</p>';
  }
  if (stats && stats.official && stats.official.data) {
    html += "<h4>Официальная структура наказаний · " + esc(stats.official.year) + "</h4><p>Форма № 10.3 Судебного департамента. Агрегат по статье; не распределение сроков.</p><table class='table'>";
    Object.keys(stats.official.shares || {}).forEach(function(k) { html += "<tr><th>" + esc(k.replace(/_/g," ")) + "</th><td>" + esc(stats.official.shares[k]) + "%</td></tr>"; });
    html += "</table>";
  }
  $("#pane-similar").innerHTML = html;
}

function renderConclusion(concl) {
  concl = concl || {};
  var html = "<h3>Заключение</h3>";
  html += '<div class="conclusion-annotation">' + esc(concl.annotation || "Заключение не сформировано.") + "</div>";
  if (concl.deeper_analysis && concl.deeper_analysis.length) {
    html += "<h4>Области для глубокого анализа</h4><ul>" +
      concl.deeper_analysis.map(function (s) { return "<li>" + esc(s) + "</li>"; }).join("") + "</ul>";
  }
  if (concl.generated_at) {
    html += '<p class="muted small">Сформировано: ' + esc(formatDate(concl.generated_at)) + "</p>";
  }
  html += '<div class="disclaimer">' + esc(DISCLAIMER) + "</div>";
  if (state.result && state.result.history_id) {
    html += '<p><a class="btn secondary" href="/api/history/' + esc(state.result.history_id) +
      '/export" download>Скачать заключение (.md)</a></p>';
  }
  $("#pane-conclusion").innerHTML = html;
}

function renderResult(data) {
  state.result = data;
  $("#upload-card").classList.add("hidden");
  var labels = { issues: "Есть замечания", incomplete: "Недостаточно данных", partial: "Частичная проверка" };
  $("#result-summary").innerHTML = "<strong>" + esc(labels[(data.check || {}).status] || "Требуется проверка") + "</strong><span>" + esc(data.case_id) + " · Демо-справочник · Синтетические аналоги</span>";
  renderParameters(data.parameters || {});
  renderCheck(data.check || {});
  renderSimilar(data.similar || [], data.stats || {});
  renderConclusion(data.conclusion || {});
  $("#pane-masked").innerHTML =
    "<h3>Текст после маскирования</h3>" +
    '<p class="muted small">Эвристическое маскирование может пропускать идентификаторы. В сохранённой истории полный текст отсутствует.</p>' +
    '<pre class="masked-text">' + esc(data.masked_text || "") + "</pre>";
  switchTab("parameters");
  $("#result-block").classList.remove("hidden");
  $("#result-summary").scrollIntoView({behavior:"smooth", block:"start"});
}

/* ---------- привязка событий и запуск ---------- */
async function runDemo(sample) {
  try {
    var result = await api("/api/demo/" + sample, {method:"POST", headers:authHeaders()});
    renderResult(result);
  } catch (e) { showAnalyzeError(e.message); }
}

function minimizedReport(payload) {
  var report = JSON.parse(JSON.stringify(payload));
  report.masked_text = "";
  report.parameters.masked_text = "";
  report.parameters.evidence = {};
  report.parameters.crime_date = null;
  [report.similar, report.conclusion.similar].forEach(function(rows) { (rows || []).forEach(function(row) {row.summary = "";}); });
  [report.stats, report.conclusion.stats].forEach(function(stats) {
    if (stats && stats.edition) stats.edition.crime_date = null;
  });
  report.conclusion.deeper_analysis = (report.conclusion.deeper_analysis || []).filter(function(line) {
    return typeof line !== 'string' || !line.startsWith('Дата преступления:');
  });
  report.privacy = report.privacy || {};
  report.privacy.projection = 'minimal_structured_report';
  return report;
}
function exportReport() {
  if (!state.result) return;
  var report = minimizedReport(state.result);
  var url = URL.createObjectURL(new Blob([JSON.stringify(report,null,2)], {type:"application/json"}));
  var link = document.createElement("a"); link.href = url; link.download = report.case_id + ".json"; link.click();
  setTimeout(function(){ URL.revokeObjectURL(url); },1000);
}

function wireEvents() {
  $("#demo-ok").addEventListener("click",function(){runDemo("ok");});
  $("#demo-error").addEventListener("click",function(){runDemo("error");});
  $("#demo-attempt").addEventListener("click",function(){runDemo("attempt");});
  $("#export-report").addEventListener("click",exportReport);
  $("#auth-form").addEventListener("submit", submitAuth);
  $$("#auth-tabs .tab").forEach(function (t) {
    t.addEventListener("click", function () { setAuthMode(t.getAttribute("data-mode")); });
  });
  $("#nav-logout").addEventListener("click", logout);
  $("#nav-cabinet").addEventListener("click", function () { showCabinet(); });
  $("#btn-new-analysis").addEventListener("click", showAnalyzeView);
  $("#btn-back-cabinet").addEventListener("click", function () { showCabinet(); });
  $("#file-input").addEventListener("change", function (e) { setFile(e.target.files[0]); });
  $("#consent-check").addEventListener("change", updateAnalyzeButton);
  $("#btn-analyze").addEventListener("click", runAnalysis);
  $("#pane-check").addEventListener("submit", function (e) {
    if (e.target && e.target.id === "recheck-form") { e.preventDefault(); runRecheck(); }
  });

  var dz = $("#dropzone");
  ["dragenter", "dragover"].forEach(function (ev) {
    dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.add("drag"); });
  });
  ["dragleave", "drop"].forEach(function (ev) {
    dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.remove("drag"); });
  });
  dz.addEventListener("drop", function (e) { setFile(e.dataTransfer.files[0]); });

  $("#history-body").addEventListener("click", function (e) {
    var btn = e.target.closest("button[data-action]");
    if (!btn) return;
    var id = btn.getAttribute("data-id");
    if (btn.getAttribute("data-action") === "open") openHistoryItem(id);
    if (btn.getAttribute("data-action") === "delete") deleteHistoryItem(id);
  });

  $$("#result-tabs .tab").forEach(function (t) {
    t.addEventListener("click", function () { switchTab(t.getAttribute("data-tab")); });
  });
}

async function boot() {
  wireEvents();
  if (state.token) {
    try {
      state.user = await api("/api/me");
      showCabinet();
      return;
    } catch (e) {
      if (e.status === 401) setToken(null);
    }
  }
  showLogin();
}

document.addEventListener("DOMContentLoaded", boot);
