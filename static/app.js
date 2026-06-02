// 前端互動邏輯：送出查詢 → 呼叫 /api/plan → 渲染方案清單與地圖。

const form = document.getElementById("search-form");
const statusEl = document.getElementById("status");
const plansEl = document.getElementById("plans");
const mapFrame = document.getElementById("map-frame");
const searchBtn = document.getElementById("search-btn");

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const origin = document.getElementById("origin").value.trim();
  const dest = document.getElementById("dest").value.trim();
  if (!origin || !dest) return;

  setLoading(true);
  plansEl.innerHTML = "";
  statusEl.textContent = "查詢中…（地理編碼有每秒限制，請稍候）";

  try {
    const url = `/api/plan?origin=${encodeURIComponent(origin)}&dest=${encodeURIComponent(dest)}`;
    const res = await fetch(url);
    const data = await res.json();

    // 每個方案對應一張地圖 HTML，存起來供點選切換
    mapsHtml = data.maps_html || [];
    // 起訖點名稱：優先用使用者輸入的關鍵字（較簡潔），供詳細資訊顯示
    originName = (data.origin && data.origin.keyword) || origin;
    destName = (data.destination && data.destination.keyword) || dest;

    if (data.error) {
      statusEl.textContent = `⚠️ ${data.error}`;
    } else {
      renderPlans(data.plans);
    }
    // 預設選取第一個方案（selectPlan 會同時切換地圖與標示卡片）
    if (mapsHtml.length > 0) {
      selectPlan(0);
    }
  } catch (err) {
    statusEl.textContent = `❌ 查詢失敗：${err.message}`;
  } finally {
    setLoading(false);
  }
});

// 目前查詢結果：每個方案各一張地圖 HTML、起訖點名稱（給詳細資訊用）
let mapsHtml = [];
let originName = "起點";
let destName = "終點";

function setLoading(isLoading) {
  searchBtn.disabled = isLoading;
  searchBtn.textContent = isLoading ? "查詢中…" : "查詢路線";
}

// 渲染前 N 名方案卡片，標示四段耗時
function renderPlans(plans) {
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
    const li = document.createElement("li");
    li.className = "plan-card";
    li.dataset.index = i; // 記錄方案序號，點選時據此切換地圖
    li.innerHTML = `
      <div>
        <span class="rank">#${i + 1}</span>
        <span class="route">${p.route_name}</span>
        <span class="total">${p.total_min} 分</span>
      </div>
      <div class="stops">
        🚏 ${p.board_stop.stop_name} → ${p.alight_stop.stop_name}
        （乘車 ${p.ride_stop_count} 站）
      </div>
      <div class="segments">
        <span>步行 ${s.walk_to_board_min} 分</span>
        <span>等車 ${s.wait_min} 分${waitTag}</span>
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

// 資料來源的中文標籤
function sourceLabel(source) {
  return source === "realtime" ? "即時動態" : "班表推算";
}

// 建立方案的「詳細資訊」展開區：逐段列出 預估時間 / 起訖 / 資料來源
function buildDetail(p) {
  const s = p.segments;
  const o = originName;
  const d = destName;
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
      time: `${s.wait_min} 分`,
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
      <div class="detail-total">總計 ${p.total_min} 分鐘</div>
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
