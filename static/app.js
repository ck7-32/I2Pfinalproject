// 前端互動邏輯：送出查詢 → 呼叫 /api/plan → 渲染方案清單與地圖。

const form = document.getElementById("search-form");
const statusEl = document.getElementById("status");
const plansEl = document.getElementById("plans");
const mapFrame = document.getElementById("map-frame");
const searchBtn = document.getElementById("search-btn");

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const origin = document.getElementById("origin").value.trim();
  const dest = document.getElementById("dest").value.trim();
  if (origin && dest) runSearch(origin, dest);
});

// 目前查詢結果：每個方案各一張地圖 HTML、方案資料、起訖點名稱（給詳細資訊用）
let mapsHtml = [];
let currentPlans = [];
let originName = "起點";
let destName = "終點";

// 執行一次查詢（可由表單送出或點歷史/最愛觸發）
function runSearch(origin, dest) {
  switchTab("plans-tab");
  setLoading(true);
  plansEl.innerHTML = "";
  statusEl.textContent = "準備查詢…";

  // 用 SSE 串流取得後台即時進度，最後拿到結果
  const url = `/api/plan/stream?origin=${encodeURIComponent(origin)}&dest=${encodeURIComponent(dest)}`;
  const source = new EventSource(url);

  source.addEventListener("progress", (e) => {
    const { message } = JSON.parse(e.data);
    statusEl.textContent = `⏳ ${message}`;
  });

  source.addEventListener("result", (e) => {
    const data = JSON.parse(e.data);
    source.close();
    setLoading(false);

    mapsHtml = data.maps_html || [];
    currentPlans = data.plans || [];
    originName = (data.origin && data.origin.keyword) || origin;
    destName = (data.destination && data.destination.keyword) || dest;

    if (data.error) {
      statusEl.textContent = `⚠️ ${data.error}`;
    } else {
      renderPlans(currentPlans);
    }
    if (mapsHtml.length > 0) {
      selectPlan(0);
    }
    loadHistory(); // 查詢成功後端已記錄，刷新歷史面板
  });

  source.addEventListener("error", (e) => {
    source.close();
    setLoading(false);
    let msg = "查詢失敗，請稍後再試。";
    try { if (e.data) msg = JSON.parse(e.data).message; } catch (_) {}
    statusEl.textContent = `❌ ${msg}`;
  });
}

function setLoading(isLoading) {
  searchBtn.disabled = isLoading;
  searchBtn.textContent = isLoading ? "查詢中…" : "查詢路線";
}

// 渲染前 N 名方案卡片，標示四段耗時
function renderPlans(plans) {
  plansEl.innerHTML = ""; // 先清空舊卡片，避免重查或切換模式時重複堆疊
  if (!plans || plans.length === 0) {
    statusEl.textContent =
      "目前查無可搭乘方案（可能是非營運時段，公車尚未發車或末班已過）。";
    return;
  }
  statusEl.textContent = `找到 ${plans.length} 個方案，依總耗時排序：`;

  plans.forEach((p, i) => {
    const s = p.segments;
    // 等待時間來源：班表推算時加註，讓使用者知道這是估算值
    const waitTag = s.wait_source === "schedule" ? "（班表）" : "";
    // 排程出門模式：你卡點出門、抵達站牌時只剩緩衝時間在等車，
    //   故顯示的等車＝緩衝（若實際等車本就更短則取較小值），總時長亦隨之重算。
    const waitShown = timeMode === "latest"
      ? Math.min(s.wait_min, DEPART_BUFFER_MIN)
      : s.wait_min;
    const totalShown = p.total_min - (s.wait_min - waitShown);
    // 依時間模式決定卡片右上角主要顯示：總時長 or 最晚出門時刻＋預估花費
    const primary = timeMode === "latest"
      ? `<span class="total total-latest">${latestDepartureText(p)} 出門` +
        `<small>預估 ${totalShown} 分</small></span>`
      : `<span class="total">${p.total_min} 分</span>`;
    const li = document.createElement("li");
    li.className = "plan-card";
    li.dataset.index = i; // 記錄方案序號，點選時據此切換地圖
    li.innerHTML = `
      <div>
        <span class="rank">#${i + 1}</span>
        <span class="route">${p.route_name}</span>
        ${primary}
      </div>
      <div class="stops">
        🚏 ${p.board_stop.stop_name} → ${p.alight_stop.stop_name}
        （乘車 ${p.ride_stop_count} 站）
      </div>
      <div class="segments">
        <span>步行 ${s.walk_to_board_min} 分</span>
        <span>等車 ${waitShown} 分${waitTag}</span>
        <span>乘車 ${s.ride_min} 分</span>
        <span>步行 ${s.walk_to_dest_min} 分</span>
      </div>
      ${buildDetail(p)}
    `;
    // 點方案卡片 → 地圖切換到該方案的路線、並展開詳細資訊
    li.addEventListener("click", () => selectPlan(i));
    plansEl.appendChild(li);
  });
}

// 出發時間模式："now"=現在出門總時長 / "latest"=最晚幾點出門
let timeMode = "now";
const DEPART_BUFFER_MIN = 5; // 推薦出門模式：在「最晚出門」再扣的等車保險（分鐘）

// 計算某方案「最晚幾點出門」（HH:MM 字串）。
// 邏輯：公車 wait 分鐘後進站；要在進站前 5 分鐘抵達站牌（保險），
//      故最晚出門 = 現在 +（等待 − 步行至上車站 − 5 分緩衝）。可能為負（代表現在就得走）。
function latestDepartureText(p) {
  const s = p.segments;
  const leaveInMin = s.wait_min - s.walk_to_board_min - DEPART_BUFFER_MIN;
  const t = new Date(Date.now() + leaveInMin * 60000);
  const hh = String(t.getHours()).padStart(2, "0");
  const mm = String(t.getMinutes()).padStart(2, "0");
  return leaveInMin <= 0 ? "立即" : `${hh}:${mm}`;
}

// 資料來源的中文標籤
function sourceLabel(source) {
  return source === "realtime" ? "即時動態" : "班表推算";
}

// 建立方案的「詳細資訊」展開區：逐段列出 預估時間 / 起訖 / 資料來源
function buildDetail(p) {
  const s = p.segments;
  const o = originName;
  const d = destName;
  // 排程出門模式：等車段以緩衝時間呈現，總計同步重算（與卡片摘要一致）
  const waitShown = timeMode === "latest"
    ? Math.min(s.wait_min, DEPART_BUFFER_MIN)
    : s.wait_min;
  const totalShown = p.total_min - (s.wait_min - waitShown);
  const rows = [
    {
      icon: "🚶",
      title: "步行至上車站",
      time: `${s.walk_to_board_min} 分`,
      from: o, to: p.board_stop.stop_name,
      src: `OSRM 路徑（約 ${s.walk_to_board_dist_m} 公尺）`,
    },
    {
      icon: "⏳",
      title: "等待公車",
      time: `${waitShown} 分`,
      from: p.board_stop.stop_name, to: `${p.route_name} 線進站`,
      src: `TDX ${sourceLabel(s.wait_source)}`,
    },
    {
      icon: "🚌",
      title: `乘車（${p.route_name} 線）`,
      time: `${s.ride_min} 分`,
      from: p.board_stop.stop_name, to: p.alight_stop.stop_name,
      src: s.ride_source === "s2s"
        ? `TDX 站間行駛時間（經 ${p.ride_stop_count} 站）`
        : `估算：${p.ride_stop_count} 站 × 每站時間`,
    },
    {
      icon: "🚶",
      title: "下車步行至終點",
      time: `${s.walk_to_dest_min} 分`,
      from: p.alight_stop.stop_name, to: d,
      src: `OSRM 路徑（約 ${s.walk_to_dest_dist_m} 公尺）`,
    },
  ];

  const items = rows.map((r) => `
    <div class="detail-row">
      <div class="detail-head">
        <span class="detail-icon">${r.icon}</span>
        <span class="detail-title">${r.title}</span>
        <span class="detail-time">${r.time}</span>
      </div>
      <div class="detail-path">${r.from} → ${r.to}</div>
      <div class="detail-src">資料來源：${r.src}</div>
    </div>
  `).join("");

  return `
    <div class="plan-detail">
      ${items}
      <div class="detail-total">總計 ${totalShown} 分鐘</div>
    </div>
  `;
}

// 選取某個方案：切換地圖、標為選中、並展開該卡片的詳細資訊（其餘收合）
function selectPlan(index) {
  if (index < 0 || index >= mapsHtml.length) return;
  renderMap(mapsHtml[index]);

  // 更新卡片選中＋展開狀態（同一時間只展開被選中的那張）
  document.querySelectorAll(".plan-card").forEach((card) => {
    const isThis = Number(card.dataset.index) === index;
    card.classList.toggle("selected", isThis);
    card.classList.toggle("expanded", isThis);
  });
}

// 把 Folium 產生的完整 HTML 寫進 iframe（用 srcdoc 隔離樣式與腳本）
function renderMap(mapHtml) {
  mapFrame.srcdoc = mapHtml;
}

// ---- 「點地圖選位」功能 ----

const pickHint = document.getElementById("pick-hint");

// 首頁載入時先放一張可點選的空白地圖
fetch("/api/blank-map")
  .then((r) => r.text())
  .then((html) => { mapFrame.srcdoc = html; })
  .catch(() => {});

const mapWrap = document.querySelector(".map-wrap");

// 告知地圖 iframe「現在要設哪個目標」（null 表示停止選位）
function setPickTarget(target) {
  if (mapFrame.contentWindow) {
    mapFrame.contentWindow.postMessage({ type: "set-pick-target", target }, "*");
  }
}

// 點「📍 點地圖」按鈕 → 進入選位模式（地圖框高亮提示正在等你點）
document.querySelectorAll(".pick-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const target = btn.dataset.target; // 'origin' | 'dest'
    setPickTarget(target);
    const label = target === "origin" ? "起點" : "終點";
    pickHint.textContent = `🖱️ 在右側地圖上點選${label}位置；圖釘可拖動微調`;
    pickHint.classList.add("active");
    mapWrap.classList.add("picking");
  });
});

// 接收地圖 iframe 傳回的座標（點擊或拖動圖釘），依訊息帶的 target 填對應輸入框。
// 不依賴外層狀態 → 拖動既有圖釘時也能正確更新（修正「拖曳起點沒變」的問題）。
window.addEventListener("message", (e) => {
  const d = e.data;
  if (!d || d.type !== "map-click" || !d.target) return;

  // 以「@緯度,經度」格式填入；後端會直接解析為座標、跳過地名查詢
  const coordText = `@${d.lat.toFixed(5)},${d.lon.toFixed(5)}`;
  const input = document.getElementById(d.target);
  if (input) input.value = coordText;

  const label = d.target === "origin" ? "起點" : "終點";
  pickHint.textContent = `✓ 已設定${label}：${coordText}（可繼續拖動圖釘微調）`;
});

// ---- 分頁切換（方案 / 歷史 / 最愛）----

function switchTab(tabId) {
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.tab === tabId));
  document.querySelectorAll(".tab-panel").forEach((p) =>
    p.classList.toggle("active", p.id === tabId));
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    switchTab(tab.dataset.tab);
    if (tab.dataset.tab === "history-tab") loadHistory();
    if (tab.dataset.tab === "favorites-tab") loadFavorites();
  });
});

// ---- 出發時間模式開關 ----

const modeNote = document.getElementById("mode-note");
document.querySelectorAll("input[name='time-mode']").forEach((radio) => {
  radio.addEventListener("change", (e) => {
    timeMode = e.target.value;
    modeNote.textContent = timeMode === "latest"
      ? `推薦出門：算「最晚幾點出門」還能搭上車（已預留 ${DEPART_BUFFER_MIN} 分等車保險）。`
      : "顯示從現在出發到抵達的總花費時間。";
    // 重新渲染目前方案以套用新模式（不需重查）
    if (currentPlans.length > 0) {
      renderPlans(currentPlans);
      selectPlan(0);
    }
  });
});

// ---- 歷史記錄與我的最愛 ----

const historyList = document.getElementById("history-list");
const favoritesList = document.getElementById("favorites-list");

// 把一筆配對的座標轉成查詢用的 @lat,lon 文字
function pairToCoordText(point) {
  return `@${point.lat.toFixed(5)},${point.lon.toFixed(5)}`;
}

// 一筆配對的顯示文字：起點名 → 終點名
// 優先序：使用者輸入的關鍵字（但若是 @座標 文字則略過）→ 地點名稱(display_name) → 座標
function pairName(pt) {
  const kw = (pt.keyword || "").trim();
  if (kw && !kw.startsWith("@")) return kw; // 使用者打的地名，最直覺
  if (pt.display_name) return pt.display_name; // geocode 回傳的可讀地點名
  return `(${pt.lat.toFixed(4)}, ${pt.lon.toFixed(4)})`;
}
function pairLabel(pair) {
  // 使用者自訂名稱優先（蒐藏改名後，歷史與蒐藏皆顯示此名）
  const custom = (pair.label || favoriteLabels.get(pairKey(pair)) || "").trim();
  if (custom) return custom;
  return `${pairName(pair.origin)} → ${pairName(pair.destination)}`;
}

// 與後端 _pair_key 一致：用起訖座標（取小數 5 位）當唯一鍵，供「是否已收藏」比對。
function pairKey(pair) {
  const r = (n) => (Number(n) || 0).toFixed(5);
  const o = pair.origin || {};
  const d = pair.destination || {};
  return `${r(o.lat)},${r(o.lon)}|${r(d.lat)},${r(d.lon)}`;
}

// 目前已收藏的配對鍵集合，供歷史頁判斷每筆是否已收藏（決定按鈕外觀）。
let favoriteKeys = new Set();
// 配對鍵 → 使用者自訂顯示名稱，供歷史頁套用蒐藏設定的名稱。
let favoriteLabels = new Map();

// 點配對 → 填回起訖點並自動查詢（用座標，跳過 geocode）
function usePair(pair) {
  document.getElementById("origin").value = pairToCoordText(pair.origin);
  document.getElementById("dest").value = pairToCoordText(pair.destination);
  runSearch(pairToCoordText(pair.origin), pairToCoordText(pair.destination));
}

// 行內改名：把名稱 span 換成輸入框，Enter/失焦儲存，Esc 取消
function startInlineRename(li, labelEl, pair) {
  if (li.querySelector(".pair-rename-input")) return; // 已在編輯
  const input = document.createElement("input");
  input.type = "text";
  input.className = "pair-rename-input";
  input.value = (pair.label || "").trim() || pairLabel(pair);
  labelEl.style.display = "none";
  li.insertBefore(input, labelEl.nextSibling);
  input.focus();
  input.select();

  let done = false;
  const finish = (save) => {
    if (done) return;
    done = true;
    if (save) {
      favoriteAction("rename", pair, input.value.trim()).then(() => {
        loadFavorites();
        loadHistory();
      });
    } else {
      input.remove();
      labelEl.style.display = "";
    }
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); finish(true); }
    else if (e.key === "Escape") { e.preventDefault(); finish(false); }
  });
  input.addEventListener("blur", () => finish(true));
}

// 渲染一個配對清單；showFav=true 時每筆右側顯示「收藏/取消收藏」按鈕
function renderPairList(listEl, pairs, options) {
  listEl.innerHTML = "";
  if (!pairs || pairs.length === 0) {
    const li = document.createElement("li");
    li.className = "pair-empty";
    li.textContent = options.emptyText;
    listEl.appendChild(li);
    return;
  }
  pairs.forEach((pair) => {
    const li = document.createElement("li");
    li.className = "pair-item";
    const label = document.createElement("span");
    label.className = "pair-label";
    label.textContent = pairLabel(pair);
    label.addEventListener("click", () => usePair(pair));
    li.appendChild(label);

    // 蒐藏清單：提供「改名」按鈕，讓使用者自訂顯示名稱（行內編輯）
    if (options.allowRename) {
      const renameBtn = document.createElement("button");
      renameBtn.className = "pair-rename";
      renameBtn.textContent = "✎";
      renameBtn.title = "自訂顯示名稱";
      renameBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        startInlineRename(li, label, pair);
      });
      li.appendChild(renameBtn);
    }

    const btn = document.createElement("button");
    btn.className = "pair-action";
    // 歷史頁：依該筆是否已收藏，決定按鈕為「已收藏（實心★、高亮）」或「☆ 收藏」
    const faved = options.markFavorited && favoriteKeys.has(pairKey(pair));
    btn.textContent = faved ? options.activeText : options.actionText;
    btn.title = faved ? options.activeTitle : options.actionTitle;
    btn.classList.toggle("is-faved", !!faved);
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      options.onAction(pair, faved);
    });
    li.appendChild(btn);
    listEl.appendChild(li);
  });
}

function loadHistory() {
  // 先確保最愛集合是最新的，才能正確標示每筆歷史是否已收藏
  refreshFavoriteKeys().then(() => {
    fetch("/api/history")
      .then((r) => r.json())
      .then((pairs) => renderPairList(historyList, pairs, {
        emptyText: "尚無歷史記錄，查詢後會自動記錄。",
        markFavorited: true,
        actionText: "☆ 收藏",
        actionTitle: "加入我的最愛",
        activeText: "★ 已收藏",
        activeTitle: "已在我的最愛（再按一次取消收藏）",
        // 已收藏→取消，未收藏→加入；完成後刷新歷史（更新按鈕）與最愛分頁
        onAction: (pair, faved) =>
          favoriteAction(faved ? "remove" : "add", pair).then(() => {
            loadHistory();
            loadFavorites();
          }),
      }))
      .catch(() => {});
  });
}

function loadFavorites() {
  fetch("/api/favorites")
    .then((r) => r.json())
    .then((pairs) => {
      favoriteKeys = new Set(pairs.map(pairKey));
      rebuildFavoriteLabels(pairs);
      renderPairList(favoritesList, pairs, {
        emptyText: "尚無收藏，可在「歷史」分頁點☆收藏。",
        allowRename: true,
        actionText: "✕ 移除",
        actionTitle: "從我的最愛移除",
        onAction: (pair) => favoriteAction("remove", pair).then(() => {
          loadFavorites();
          loadHistory(); // 取消收藏後，歷史頁的對應按鈕也要還原成 ☆
        }),
      });
    })
    .catch(() => {});
}

// 依目前最愛清單重建「配對鍵→自訂名稱」對照，供歷史頁套用
function rebuildFavoriteLabels(pairs) {
  favoriteLabels = new Map();
  pairs.forEach((p) => {
    const lbl = (p.label || "").trim();
    if (lbl) favoriteLabels.set(pairKey(p), lbl);
  });
}

// 只更新 favoriteKeys/Labels（不重繪最愛清單），供歷史頁標示與顯示用
function refreshFavoriteKeys() {
  return fetch("/api/favorites")
    .then((r) => r.json())
    .then((pairs) => {
      favoriteKeys = new Set(pairs.map(pairKey));
      rebuildFavoriteLabels(pairs);
    })
    .catch(() => {});
}

// 新增/移除/改名最愛；rename 時用 label 傳入自訂名稱
function favoriteAction(action, pair, label) {
  return fetch("/api/favorites", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, pair, label }),
  }).then((r) => r.json());
}

// 首頁載入時先抓一次歷史與最愛（讓分頁有內容）
loadHistory();
loadFavorites();
