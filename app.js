const API_BASE = "http://127.0.0.1:8000";
let allDeals = [];
let activeTab = "all";

document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    document.getElementById("searchInput").focus();
  }
  if (e.key === "Escape") closeModal();
});

function toggleRealmTheme() {
  document.body.classList.toggle("daylight-theme");
  const btn = document.getElementById("themeToggleBtn");
  btn.textContent = document.body.classList.contains("daylight-theme")
    ? "🔥 Campfire Night"
    : "☀ Sunlit Trail";
}

function setTab(tab, btn) {
  activeTab = tab;
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  renderStorefront();
}

async function loadDeals() {
  const statusEl = document.getElementById("statusText");
  try {
    const res = await fetch(`${API_BASE}/api/deals`);
    allDeals = await res.json();
    statusEl.textContent = `Realm Online: Tracking ${allDeals.length} games across Official Stores & Key Resellers.`;
    renderStorefront();
  } catch {
    statusEl.textContent = "Backend offline — Run `python -m uvicorn sidequest_backend:app --reload` in PowerShell.";
  }
}

async function trackGame() {
  const input = document.getElementById("appIdInput");
  const appId = input.value.trim();
  if (!appId) return;

  const statusEl = document.getElementById("statusText");
  statusEl.textContent = `Scouting Steam & CheapShark merchants for App ID ${appId}...`;

  try {
    const res = await fetch(`${API_BASE}/api/track/${appId}`, { method: "POST" });
    if (!res.ok) {
      const err = await res.json();
      statusEl.textContent = err.detail || "Could not find paid Steam game.";
      return;
    }
    input.value = "";
    await loadDeals();
  } catch {
    statusEl.textContent = "Error connecting to backend.";
  }
}

async function syncDiscover() {
  const statusEl = document.getElementById("statusText");
  statusEl.textContent = "Syncing Steam Top Sellers, Specials & CheapShark stores (~8 seconds)...";
  try {
    const res = await fetch(`${API_BASE}/api/discover`, { method: "POST" });
    const data = await res.json();
    statusEl.textContent = `Discovered ${data.discovered_count} trending games!`;
    await loadDeals();
  } catch {
    statusEl.textContent = "Discovery sync failed.";
  }
}

async function uploadResellerFeed(event) {
  const file = event.target.files[0];
  if (!file) return;

  const statusEl = document.getElementById("statusText");
  statusEl.textContent = `Importing ${file.name} (filtering out account listings)...`;

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch(`${API_BASE}/api/resellers/import-feed`, {
      method: "POST",
      body: formData,
    });
    const result = await res.json();
    statusEl.textContent = `Feed Imported: ${result.accepted_offers} valid keys/gifts added, ${result.blocked_or_invalid} accounts blocked.`;
    await loadDeals();
  } catch {
    statusEl.textContent = "Failed to import reseller feed.";
  }
  event.target.value = "";
}

function getFilteredOfferForDeal(deal, sellerFilter) {
  const offers = deal.active_offers || [];
  if (sellerFilter === "all") return offers[0] || deal.cheapest_current;
  return offers.find(o => o.store_type === sellerFilter) || null;
}

function renderStorefront() {
  const query = document.getElementById("searchInput").value.trim().toLowerCase();
  const sellerFilter = document.getElementById("sellerFilter").value;
  const heroContainer = document.getElementById("heroContainer");
  const dealsContainer = document.getElementById("dealsContainer");
  const sectionHeading = document.getElementById("sectionHeading");

  const filtered = allDeals
    .map(deal => ({ deal, bestOffer: getFilteredOfferForDeal(deal, sellerFilter) }))
    .filter(({ deal, bestOffer }) => {
      if (!bestOffer) return false;
      if (query && !deal.title.toLowerCase().includes(query)) return false;
      if (activeTab === "sale" && bestOffer.discount_percent <= 0) return false;
      if (activeTab === "under20" && bestOffer.price > 20) return false;
      return true;
    });

  if (query.length > 0) {
    heroContainer.innerHTML = "";
    sectionHeading.textContent = `🧭 SEARCH TRAIL RESULTS (${filtered.length})`;
    dealsContainer.className = "aks-list";
    dealsContainer.innerHTML = filtered.map(({ deal, bestOffer }) => {
      const typeClass = bestOffer.store_type === "Key Reseller" ? "pill-reseller" : "pill-official";
      const couponHtml = bestOffer.coupon_code ? `<span class="pill pill-coupon">CODE: ${bestOffer.coupon_code}</span>` : "";
      const discountHtml = bestOffer.discount_percent > 0 ? `<span class="discount-badge">-${bestOffer.discount_percent}%</span>` : "";

      return `
        <div class="aks-row carved-stone" onclick="openDealModal(${deal.app_id})">
          <img src="${deal.header_image}" alt="${deal.title}" onerror="this.style.display='none'" />
          <div>
            <div style="font-size:17px; font-weight:700; color:#fff; margin-bottom:6px;">${deal.title}</div>
            <div class="badge-row" style="margin-bottom:0;">
              <span class="pill ${typeClass}">${bestOffer.store} (${bestOffer.store_type})</span>
              <span class="pill pill-format">${bestOffer.delivery_type} • ${bestOffer.region}</span>
              ${couponHtml}
            </div>
          </div>
          <div style="display:flex; align-items:center; gap:12px;">
            ${discountHtml}
            <div style="text-align:right;">
              ${bestOffer.coupon_code ? `<div class="strike-price">$${bestOffer.base_price.toFixed(2)}</div>` : ""}
              <div class="final-price">$${bestOffer.price.toFixed(2)}</div>
            </div>
            <button class="btn-pixel btn-ember">Compare (${deal.active_offers.length})</button>
          </div>
        </div>
      `;
    }).join("");
    return;
  }

  sectionHeading.textContent = "🌲 FEATURED WOODLAND DEALS";
  if (filtered.length > 0) {
    const { deal: heroDeal, bestOffer: heroOffer } = filtered[0];
    const heroTypeClass = heroOffer.store_type === "Key Reseller" ? "pill-reseller" : "pill-official";
    heroContainer.innerHTML = `
      <div class="hero-spotlight carved-stone" onclick="openDealModal(${heroDeal.app_id})">
        <div class="hero-img-wrap">
          <div class="quest-ribbon">★ FEATURED QUEST LOOT</div>
          <img src="${heroDeal.header_image}" alt="${heroDeal.title}" />
        </div>
        <div class="hero-info">
          <div>
            <div class="hero-title">${heroDeal.title}</div>
            <div class="badge-row">
              <span class="pill ${heroTypeClass}">${heroOffer.store}</span>
              <span class="pill pill-format">${heroOffer.delivery_type} • ${heroOffer.region}</span>
              ${heroOffer.coupon_code ? `<span class="pill pill-coupon">CODE: ${heroOffer.coupon_code}</span>` : ""}
            </div>
            <div style="font-size:13px; color:var(--text-muted); line-height:1.6;">
              <div>Historical Low: <strong style="color:#fff;">$${heroDeal.historical_low?.price?.toFixed(2) ?? "N/A"}</strong> (${heroDeal.historical_low?.date_hit || "Today"})</div>
              <div>Next Sale Window: <strong style="color:var(--leaf-bright);">${heroDeal.next_sale_prediction?.estimated_date}</strong></div>
            </div>
          </div>
          <div class="price-display">
            ${heroOffer.discount_percent > 0 ? `<span class="discount-badge">-${heroOffer.discount_percent}%</span>` : ""}
            <div>
              ${heroOffer.coupon_code ? `<div class="strike-price">$${heroOffer.base_price.toFixed(2)}</div>` : ""}
              <div class="final-price">$${heroOffer.price.toFixed(2)}</div>
            </div>
          </div>
        </div>
      </div>
    `;
  } else {
    heroContainer.innerHTML = "";
  }

  dealsContainer.className = "deals-grid";
  dealsContainer.innerHTML = filtered.slice(1).map(({ deal, bestOffer }) => {
    const typeClass = bestOffer.store_type === "Key Reseller" ? "pill-reseller" : "pill-official";
    return `
      <div class="game-card carved-stone" onclick="openDealModal(${deal.app_id})">
        <img src="${deal.header_image}" alt="${deal.title}" onerror="this.style.display='none'" />
        <div class="card-content">
          <div>
            <div class="card-title">${deal.title}</div>
            <div class="badge-row">
              <span class="pill ${typeClass}">${bestOffer.store}</span>
              <span class="pill pill-format">${bestOffer.delivery_type}</span>
              ${bestOffer.coupon_code ? `<span class="pill pill-coupon">${bestOffer.coupon_code}</span>` : ""}
            </div>
          </div>
          <div class="card-footer">
            <span style="font-size:12px; color:var(--text-muted);">${deal.active_offers.length} merchant(s)</span>
            <div style="display:flex; align-items:center; gap:8px;">
              ${bestOffer.discount_percent > 0 ? `<span class="discount-badge" style="font-size:18px;">-${bestOffer.discount_percent}%</span>` : ""}
              <span style="font-size:18px; font-weight:800; color:#fff;">$${bestOffer.price.toFixed(2)}</span>
            </div>
          </div>
        </div>
      </div>
    `;
  }).join("");
}
function buildPriceHistorySvg(points) {
  if (!points || points.length === 0) {
    return `<div style="font-size:13px; color:var(--text-muted); padding:16px 0;">No historical trail points logged yet.</div>`;
  }

  const width = 780, height = 165, padLeft = 48, padRight = 24, padTop = 20, padBottom = 28;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;

  const prices = points.map(p => p.price);
  const rawMin = Math.min(...prices);
  const rawMax = Math.max(...prices);
  const minP = Math.max(0, rawMin * 0.85);
  const maxP = rawMax === rawMin ? rawMax * 1.2 + 5 : rawMax * 1.1;

  const coords = points.map((pt, idx) => {
    const x = points.length === 1 ? padLeft + plotW / 2 : padLeft + (idx / (points.length - 1)) * plotW;
    const ratio = (pt.price - minP) / (maxP - minP || 1);
    const y = padTop + plotH - ratio * plotH;
    return { ...pt, x: Math.round(x), y: Math.round(y) };
  });

  const polylinePoints = coords.map(c => `${c.x},${c.y}`).join(" ");
  const areaPoints = `${coords[0].x},${padTop + plotH} ${polylinePoints} ${coords[coords.length - 1].x},${padTop + plotH}`;

  const midP = (minP + maxP) / 2;
  const gridLines = [maxP, midP, minP].map((val, idx) => {
    const y = padTop + (idx / 2) * plotH;
    return `
      <line x1="${padLeft}" y1="${y}" x2="${width - padRight}" y2="${y}" stroke="#233d2c" stroke-dasharray="4 4" />
      <text x="${padLeft - 6}" y="${y + 4}" fill="#9eb8a4" font-size="11" text-anchor="end">$${val.toFixed(0)}</text>
    `;
  }).join("");

  const dots = coords.map((c, idx) => {
    const label = `${c.date || "Today"} • ${c.store || "Store"} (${(c.delivery_type || "key").toUpperCase()}): $${Number(c.price || 0).toFixed(2)}`;

    return `
      <g style="cursor:pointer;"
         onmouseenter="document.getElementById('chartTooltip').textContent='${label.replace(/'/g, "\\'")}'"
         onmouseleave="document.getElementById('chartTooltip').textContent='Hover over any trail waypoint to inspect price & merchant'">
        <circle cx="${c.x}" cy="${c.y}" r="8" fill="transparent" />
        <rect x="${c.x - 4}" y="${c.y - 4}" width="8" height="8" fill="${idx === coords.length - 1 ? '#f4c430' : '#7ae582'}" stroke="#0b1610" stroke-width="2" />
      </g>
    `;
  }).join("");

  return `
    <svg viewBox="0 0 ${width} ${height}" style="width:100%; height:165px; display:block;">
      ${gridLines}
      ${coords.length > 1 ? `<polygon points="${areaPoints}" fill="rgba(122, 229, 130, 0.12)" />` : ""}
      ${coords.length > 1 ? `<polyline points="${polylinePoints}" fill="none" stroke="#c29b61" stroke-width="3" />` : ""}
      ${dots}
      <text x="${padLeft}" y="${height - 6}" fill="#9eb8a4" font-size="11">${coords[0].date}</text>
      <text x="${width - padRight}" y="${height - 6}" fill="#9eb8a4" font-size="11" text-anchor="end">${coords[coords.length - 1].date}</text>
    </svg>
  `;
}

async function openDealModal(appId) {
  const deal = allDeals.find(d => d.app_id === appId);
  if (!deal) return;

  let historyPoints = [];
  try {
    const histRes = await fetch(`${API_BASE}/api/deals/${appId}/history`);
    if (histRes.ok) historyPoints = await histRes.json();
  } catch { historyPoints = []; }

  if (historyPoints.length === 0 && deal.cheapest_current) {
    historyPoints = [{
      date: deal.cheapest_current.last_checked || "Today",
      store: deal.cheapest_current.store,
      price: deal.cheapest_current.price,
      delivery_type: deal.cheapest_current.delivery_type || "key",
    }];
  }

  const rowsHtml = (deal.active_offers || []).map((offer, idx) => {
    const typeClass = offer.store_type === "Key Reseller" ? "pill-reseller" : "pill-official";
    const couponCell = offer.coupon_code
      ? `<span class="pill pill-coupon">${offer.coupon_code}</span>
         <button class="copy-code-btn" onclick="copyVoucher('${offer.coupon_code}', this)">Copy</button>`
      : `<span style="color:var(--text-muted); font-size:12px;">—</span>`;

    return `
      <tr>
        <td>
          <strong style="color:#fff;">${idx === 0 ? "★ " : ""}${offer.store}</strong><br/>
          <span class="pill ${typeClass}" style="font-size:10px;">${offer.store_type}</span>
        </td>
        <td><span class="pill pill-format">${offer.delivery_type}</span></td>
        <td>${offer.region}</td>
        <td>${couponCell}</td>
        <td>
          ${offer.coupon_code ? `<span class="strike-price">$${offer.base_price.toFixed(2)}</span> ` : ""}
          <strong style="font-size:16px; color:var(--leaf-bright);">$${offer.price.toFixed(2)}</strong>
        </td>
        <td><a class="store-link" href="${offer.url}" target="_blank" rel="noopener noreferrer">Go to Store ↗</a></td>
      </tr>
    `;
  }).join("");

  document.getElementById("modalBody").innerHTML = `
    <div style="display:flex; flex-wrap:wrap; gap:18px; align-items:center; margin-bottom:14px;">
      <img src="${deal.header_image}" style="width:230px; border:2px solid var(--stone-outer);" />
      <div>
        <h2 style="font-size:24px; color:#fff; margin-bottom:8px;">${deal.title}</h2>
        <div style="font-size:13px; color:var(--text-muted); line-height:1.7;">
          <div>All-Time Tracked Low: <strong style="color:var(--gold-loot);">$${deal.historical_low?.price?.toFixed(2) ?? "N/A"}</strong> on ${deal.historical_low?.store || "Steam"} (${deal.historical_low?.date_hit || "Today"})</div>
          <div>Next Predicted Sale: <strong style="color:var(--leaf-bright);">${deal.next_sale_prediction?.estimated_date}</strong> (${deal.next_sale_prediction?.method})</div>
        </div>
      </div>
    </div>

    <div class="chart-box">
      <div class="chart-header">
        <div class="section-heading" style="margin-bottom:0;">📈 PRICE HISTORY TRAIL</div>
        <div class="chart-tooltip" id="chartTooltip">Hover over any trail waypoint to inspect price &amp; merchant</div>
      </div>
      ${buildPriceHistorySvg(historyPoints)}
    </div>

    <div class="section-heading" style="margin-top:10px;">⚔️ MERCHANT PRICE COMPARISON (KEYS &amp; GIFTS ONLY)</div>
    <table class="offer-table">
      <thead>
        <tr><th>Merchant</th><th>Format</th><th>Region</th><th>Voucher</th><th>Final Price</th><th>Action</th></tr>
      </thead>
      <tbody>${rowsHtml}</tbody>
    </table>

    <form class="voucher-form" onsubmit="submitVoucher(event, ${deal.app_id})">
      <strong style="font-size:13px; color:var(--gold-loot);">+ Found a Working Checkout Code?</strong>
      <input type="text" id="vStore" placeholder="Store (e.g. Fanatical)" required style="width:160px;" />
      <input type="text" id="vCode" placeholder="Code (e.g. SAVE10)" required style="width:140px;" />
      <input type="number" id="vPct" placeholder="% Off (e.g. 10)" step="0.5" min="1" max="90" required style="width:120px;" />
      <button type="submit" class="btn-pixel btn-ember">Apply &amp; Recalculate</button>
    </form>
  `;

  document.getElementById("dealModal").classList.add("open");
}

function copyVoucher(code, btn) {
  navigator.clipboard.writeText(code);
  btn.textContent = "Copied!";
  setTimeout(() => { btn.textContent = "Copy"; }, 1500);
}

async function submitVoucher(event, appId) {
  event.preventDefault();
  const store = document.getElementById("vStore").value;
  const code = document.getElementById("vCode").value;
  const discount_percent = parseFloat(document.getElementById("vPct").value);

  await fetch(`${API_BASE}/api/vouchers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ store, code, discount_percent, min_spend: 0 }),
  });

  await loadDeals();
  openDealModal(appId);
}

function closeModal() { document.getElementById("dealModal").classList.remove("open"); }
function closeModalOnBackdrop(event) { if (event.target.id === "dealModal") closeModal(); }

loadDeals();