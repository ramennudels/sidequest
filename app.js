const API_BASE = "https://sidequest-0so9.onrender.com";
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
    ? "🌙 Dark Mode"
    : "☀️ Light Mode";
}

function setTab(tabName, btnEl) {
  activeTab = tabName;
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
  btnEl.classList.add("active");
  renderStorefront();
}

function handleCoverError(img, appId, title) {
  if (!img.dataset.triedCapsule) {
    img.dataset.triedCapsule = "1";
    img.src = `https://steamstatic.com{appId}/capsule_616x353.jpg`;
    return;
  }
  const safeTitle = (title || "Sidequest Deal").replace(/[<>&"']/g, "");
  const svg = `<svg xmlns="http://w3.org" width="460" height="215" viewBox="0 0 460 215">
    <defs>
      <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="#1a1d26"/>
        <stop offset="100%" stop-color="#090a0e"/>
      </linearGradient>
    </defs>
    <rect width="460" height="215" fill="url(#bg)"/>
    <rect x="1" y="1" width="458" height="213" fill="none" stroke="#ef4444" stroke-width="2" stroke-opacity="0.5"/>
    <text x="230" y="96" fill="#ef4444" font-family="Inter, sans-serif" font-size="14" font-weight="800" text-anchor="middle" letter-spacing="3">🔥 SIDEQUEST</text>
    <text x="230" y="128" fill="#f8fafc" font-family="Inter, sans-serif" font-size="18" font-weight="700" text-anchor="middle">${safeTitle.slice(0, 34)}</text>
  </svg>`;
  img.onerror = null;
  img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
}

function escapeAttr(str) {
  return (str || "").replace(/'/g, "").replace(/"/g, "");
}

function getFilteredOffer(deal, sellerType) {
  const offers = deal.active_offers || [];
  const matching = sellerType === "all"
    ? offers
    : offers.filter((o) => o.store_type === sellerType);
  if (matching.length === 0) return null;
  return matching.reduce((best, curr) => (curr.price < best.price ? curr : best), matching[0]);
}

async function loadDeals() {
  const statusEl = document.getElementById("statusText");
  try {
    const res = await fetch(`${API_BASE}/api/deals`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    allDeals = await res.json();
    statusEl.textContent = `Realm Online: Tracking ${allDeals.length} games across Steam & 25+ key stores`;
    renderStorefront();
  } catch (err) {
    statusEl.innerHTML = `<span style="color:#ef4444;font-weight:700;">Backend offline</span> — Check Render server status or refresh in 30 seconds.`;
  }
}

function renderStorefront() {
  const query = document.getElementById("searchInput").value.trim().toLowerCase();
  const sellerType = document.getElementById("sellerFilter").value;
  const heroEl = document.getElementById("heroContainer");
  const container = document.getElementById("dealsContainer");
  const heading = document.getElementById("sectionHeading");

  const filtered = allDeals
    .map((deal) => ({ deal, bestOffer: getFilteredOffer(deal, sellerType) }))
    .filter(({ deal, bestOffer }) => {
      if (!bestOffer) return false;
      if (query && !deal.title.toLowerCase().includes(query) && !bestOffer.store.toLowerCase().includes(query)) {
        return false;
      }
      if (activeTab === "sale" && bestOffer.discount_percent <= 0 && !bestOffer.coupon_code) return false;
      if (activeTab === "under20" && bestOffer.price >= 20) return false;
      return true;
    })
    .sort((a, b) => (b.bestOffer.discount_percent || 0) - (a.bestOffer.discount_percent || 0));

  if (filtered.length === 0) {
    heroEl.innerHTML = "";
    container.className = "deals-grid";
    container.innerHTML = `<div class="carved-stone" style="padding:24px;grid-column:1/-1;text-align:center;">
      No matching deals found. Click <b>Sync Top Deals</b> or adjust your filters.
    </div>`;
    return;
  }

  const showHero = !query && activeTab === "all";
  let gridItems = filtered;

  if (showHero) {
    const { deal, bestOffer } = filtered[0];
    const steamOffer = (deal.active_offers || []).find((o) => o.store === "Steam");
    const baseDisplay = steamOffer && steamOffer.base_price > bestOffer.price
      ? `$${steamOffer.base_price.toFixed(2)}`
      : bestOffer.base_price > bestOffer.price
        ? `$${bestOffer.base_price.toFixed(2)}`
        : "";

    heroEl.innerHTML = `
      <div class="carved-stone hero-spotlight" onclick="openDealModal(${deal.app_id})">
        <div class="hero-img-wrap">
          <span class="quest-ribbon">🔥 TOP FEATURED DEAL</span>
          <img src="${deal.header_image}" alt="${escapeAttr(deal.title)}" onerror="handleCoverError(this, ${deal.app_id}, '${escapeAttr(deal.title)}')" />
        </div>
        <div class="hero-info">
          <div>
            <h1 class="hero-title">${deal.title}</h1>
            <div class="badge-row">
              <span class="pill ${bestOffer.store_type === "Official Store" ? "pill-official" : "pill-reseller"}">${bestOffer.store}</span>
              <span class="pill pill-format">${bestOffer.delivery_type.toUpperCase()}</span>
              <span class="pill pill-format">${bestOffer.region}</span>
              ${bestOffer.coupon_code ? `<span class="pill pill-coupon">Code: ${bestOffer.coupon_code} (-${bestOffer.coupon_discount_percent}%)</span>` : ""}
            </div>
            <p style="font-size:13px;color:var(--text-secondary);">
              Historical Low: <b style="color:var(--gold-accent);">$${deal.historical_low.price.toFixed(2)}</b> (${deal.historical_low.store}) • Next Sale: <b>${deal.next_sale_prediction.estimated_date}</b>
            </p>
          </div>
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;">
            <div class="price-display">
              ${bestOffer.discount_percent > 0 ? `<span class="discount-badge">-${bestOffer.discount_percent}%</span>` : ""}
              <div>
                ${baseDisplay ? `<div class="strike-price">${baseDisplay}</div>` : ""}
                <div class="final-price">$${bestOffer.price.toFixed(2)}</div>
              </div>
            </div>
            <button class="btn btn-primary">Compare ${(deal.active_offers || []).length} Stores →</button>
          </div>
        </div>
      </div>
    `;
    gridItems = filtered.slice(1);
    heading.textContent = "FEATURED DEALS";
  } else {
    heroEl.innerHTML = "";
    heading.textContent = query ? `SEARCH RESULTS (${filtered.length})` : "FILTERED DEALS";
  }

  if (query) {
    container.className = "aks-list";
    container.innerHTML = gridItems.map(({ deal, bestOffer }) => `
      <div class="carved-stone aks-row" onclick="openDealModal(${deal.app_id})">
        <img src="${deal.header_image}" alt="${escapeAttr(deal.title)}" loading="lazy" onerror="handleCoverError(this, ${deal.app_id}, '${escapeAttr(deal.title)}')" />
        <div>
          <div style="font-weight:700;font-size:16px;margin-bottom:6px;">${deal.title}</div>
          <div class="badge-row" style="margin-bottom:0;">
            <span class="pill ${bestOffer.store_type === "Official Store" ? "pill-official" : "pill-reseller"}">${bestOffer.store}</span>
            <span class="pill pill-format">${bestOffer.delivery_type.toUpperCase()}</span>
            ${bestOffer.coupon_code ? `<span class="pill pill-coupon">${bestOffer.coupon_code}</span>` : ""}
          </div>
        </div>
        <div class="price-display">
          ${bestOffer.discount_percent > 0 ? `<span class="discount-badge">-${bestOffer.discount_percent}%</span>` : ""}
          <div class="final-price">$${bestOffer.price.toFixed(2)}</div>
        </div>
      </div>
    `).join("");
  } else {
    container.className = "deals-grid";
    container.innerHTML = gridItems.map(({ deal, bestOffer }) => `
      <div class="carved-stone game-card" onclick="openDealModal(${deal.app_id})">
        <img src="${deal.header_image}" alt="${escapeAttr(deal.title)}" loading="lazy" onerror="handleCoverError(this, ${deal.app_id}, '${escapeAttr(deal.title)}')" />
        <div class="card-content">
          <div>
            <div class="card-title">${deal.title}</div>
            <div class="badge-row">
              <span class="pill ${bestOffer.store_type === "Official Store" ? "pill-official" : "pill-reseller"}">${bestOffer.store}</span>
              <span class="pill pill-format">${bestOffer.delivery_type.toUpperCase()}</span>
              ${bestOffer.coupon_code ? `<span class="pill pill-coupon">${bestOffer.coupon_code}</span>` : ""}
            </div>
          </div>
          <div class="card-footer">
            <div class="price-display">
              ${bestOffer.discount_percent > 0 ? `<span class="discount-badge">-${bestOffer.discount_percent}%</span>` : ""}
              <div class="final-price">$${bestOffer.price.toFixed(2)}</div>
            </div>
            <span style="font-size:12px;color:var(--text-secondary);">Low: $${deal.historical_low.price.toFixed(2)}</span>
          </div>
        </div>
      </div>
    `).join("");
  }
}
function buildPriceTrailSvg(history) {
  if (!history || history.length === 0) {
    return `<p style="font-size:12px;color:var(--text-secondary);">No historical trail recorded yet.</p>`;
  }

  const points = history.slice(-15);
  const prices = points.map((p) => p.price);
  const minP = Math.min(...prices);
  const maxP = Math.max(...prices);
  const range = maxP - minP || 1;
  const w = 680;
  const h = 130;
  const pad = 20;

  const coords = points.map((p, idx) => {
    const x = points.length === 1
      ? w / 2
      : pad + (idx / (points.length - 1)) * (w - pad * 2);
    const y = h - pad - ((p.price - minP) / range) * (h - pad * 2);
    return { x, y, ...p };
  });

  const polyline = coords.map((c) => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ");
  const circles = coords.map((c) => `
    <circle cx="${c.x.toFixed(1)}" cy="${c.y.toFixed(1)}" r="4.5" fill="#ef4444" stroke="#ffffff" stroke-width="1.5"
      onmouseover="document.getElementById('chartTooltip').textContent='$${c.price.toFixed(2)} on ${c.store} (${c.date})'"
      style="cursor:pointer;" />
  `).join("");

  return `
    <div class="chart-box">
      <div class="chart-header">
        <strong style="font-size:13px;">PRICE HISTORY TRAIL</strong>
        <span id="chartTooltip" class="chart-tooltip">Hover any node to inspect date &amp; merchant</span>
      </div>
      <svg viewBox="0 0 ${w} ${h}" style="width:100%;height:130px;overflow:visible;">
        <polyline fill="none" stroke="#ef4444" stroke-width="2.5" points="${polyline}" />
        ${circles}
      </svg>
    </div>
  `;
}

async function openDealModal(appId) {
  const modal = document.getElementById("dealModal");
  const body = document.getElementById("modalBody");
  modal.classList.add("open");
  body.innerHTML = `<p>Loading live store comparison...</p>`;

  try {
    const [dealRes, histRes] = await Promise.all([
      fetch(`${API_BASE}/api/deals/${appId}`),
      fetch(`${API_BASE}/api/history/${appId}`),
    ]);
    const deal = await dealRes.json();
    const histData = await histRes.json();

    const rows = (deal.active_offers || []).map((o) => {
      const targetUrl = o.url || o.store_url || `https://steampowered.com{deal.app_id}/`;
      return `
        <tr>
          <td><strong>${o.store}</strong><br><span style="font-size:11px;color:var(--text-secondary);">${o.store_type}</span></td>
          <td>${o.delivery_type.toUpperCase()} (${o.region})</td>
          <td>${o.coupon_code ? `<code>${o.coupon_code}</code> <button class="copy-code-btn" onclick="copyCode('${o.coupon_code}', this)">Copy</button>` : "—"}</td>
          <td><strong>$${o.price.toFixed(2)}</strong> ${o.discount_percent > 0 ? `<span style="color:#4ade80;font-size:11px;">(-${o.discount_percent}%)</span>` : ""}</td>
          <td><a class="store-link" href="${targetUrl}" target="_blank" rel="noopener">Go to Store ↗</a></td>
        </tr>
      `;
    }).join("");

    body.innerHTML = `
      <div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-bottom:14px;">
        <img src="${deal.header_image}" alt="${escapeAttr(deal.title)}" style="width:180px;border-radius:8px;border:1px solid var(--border-subtle);" onerror="handleCoverError(this, ${deal.app_id}, '${escapeAttr(deal.title)}')" />
        <div>
          <h2 style="font-size:22px;font-weight:800;margin-bottom:6px;">${deal.title}</h2>
          <p style="font-size:13px;color:var(--text-secondary);">
            Historical Low: <b style="color:var(--gold-accent);">$${deal.historical_low.price.toFixed(2)}</b> (${deal.historical_low.store} on ${deal.historical_low.date_hit})<br>
            Next Steam Seasonal Sale Estimate: <b>${deal.next_sale_prediction.estimated_date}</b>
          </p>
        </div>
      </div>

      ${buildPriceTrailSvg(histData.history)}

      <table class="offer-table">
        <thead>
          <tr>
            <th>Store</th>
            <th>Format</th>
            <th>Voucher</th>
            <th>Final Price</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>

      <div class="voucher-form">
        <strong style="font-size:13px;">Add Promo Code:</strong>
        <input type="text" id="vStore" placeholder="Store (e.g. Fanatical)" style="width:160px;" />
        <input type="text" id="vCode" placeholder="Code (e.g. SAVE10)" style="width:140px;" />
        <input type="number" id="vPct" placeholder="% Off" style="width:90px;" />
        <button class="btn btn-primary" onclick="submitVoucher(${deal.app_id})">Save Code</button>
      </div>
    `;
  } catch (err) {
    body.innerHTML = `<p style="color:#ef4444;">Failed to load offer details.</p>`;
  }
}

function closeModal() {
  document.getElementById("dealModal").classList.remove("open");
}

function closeModalOnBackdrop(e) {
  if (e.target.id === "dealModal") closeModal();
}

function copyCode(code, btn) {
  navigator.clipboard.writeText(code);
  const orig = btn.textContent;
  btn.textContent = "Copied!";
  setTimeout(() => { btn.textContent = orig; }, 1500);
}

async function submitVoucher(appId) {
  const store = document.getElementById("vStore").value.trim();
  const code = document.getElementById("vCode").value.trim();
  const pct = parseInt(document.getElementById("vPct").value, 10);
  if (!store || !code || !pct) return alert("Enter store, code, and discount %.");

  await fetch(`${API_BASE}/api/vouchers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ store, code, discount_percent: pct, min_spend: 0 }),
  });
  await loadDeals();
  openDealModal(appId);
}

async function trackGame() {
  const input = document.getElementById("appIdInput");
  const appId = parseInt(input.value, 10);
  if (!appId) return alert("Enter a valid numeric Steam App ID.");

  const statusEl = document.getElementById("statusText");
  statusEl.textContent = `Fetching Steam & key store prices for App ID ${appId}...`;

  const res = await fetch(`${API_BASE}/api/track/${appId}`, { method: "POST" });
  if (!res.ok) {
    statusEl.textContent = `Could not track App ID ${appId} (may be free-to-play or invalid).`;
    return;
  }
  input.value = "";
  await loadDeals();
}

async function syncDiscover() {
  const statusEl = document.getElementById("statusText");
  statusEl.textContent = "Syncing Steam Top Sellers & CheapShark key deals...";
  await fetch(`${API_BASE}/api/discover`, { method: "POST" });
  await loadDeals();
}

async function uploadResellerFeed(event) {
  const file = event.target.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append("file", file);

  const statusEl = document.getElementById("statusText");
  statusEl.textContent = `Importing ${file.name}...`;

  const res = await fetch(`${API_BASE}/api/offers/upload`, {
    method: "POST",
    body: formData,
  });
  const data = await res.json();
  alert(`Imported ${data.imported} valid key/gift offers (blocked ${data.blocked_accounts} account listings).`);
  event.target.value = "";
  await loadDeals();
}

loadDeals();
