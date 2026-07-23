const DATA_VERSION = "20260717a";
const ShipSorting = globalThis.MKShipSorting || {};
const {
  ADSENSE_CLIENT,
  ADSENSE_PREVIEW,
  ADSENSE_SLOTS,
  ADSENSE_TEST_MODE,
  BW_TO_METERS,
  CLASS_LABELS,
  CLASS_ORDER,
  CONSUMABLE_TYPE_LABELS,
  DEBUG_AVAILABILITY_GROUPS,
  DEFAULT_LANGUAGE,
  EXCLUDED_SHIP_CLASSES,
  GROUP_FILTERS,
  HIDDEN_SHIP_GROUPS,
  MODAL_COMPARE_EXTREME_EXCLUDED_LABELS,
  PARAMETER_EXTREME_EXCLUDED_LABELS,
  PARAMETER_LOW_IS_GOOD_LABELS,
  RANGE_DEFAULTS_KM,
  RANGE_SELECTABLE_GROUPS,
  SECONDARY_GROUP_COLORS,
  SELECT_CLASS_LABELS,
  SHELL_CHART_DEFAULT_MAX_KM,
  SHELL_CHART_SERIES_COLORS,
  SHELL_DISPERSION_MAX_SHOTS,
  SHELL_DISPERSION_MIN_SHOTS,
  SHELL_DISPERSION_SAMPLE_COUNT,
  SHIP_ANGLE_IMAGE_BOUNDS,
  SHIP_ANGLE_VIEWBOX,
  STATIC_MODAL_PROFILES_SCRIPT,
  SUPPORT_URL,
  TEST_AVAILABILITY_GROUPS,
  TORPEDO_REACTION_SPEED_FACTOR,
} = globalThis.MKShipConstants || {};
const {
  angleSweep,
  clamp,
  clamp01,
  clockwiseDelta,
  escapeHtml,
  finiteNumberOrNull,
  fireChanceDisplay,
  formatBytes,
  formatDistanceMeters,
  formatPercent,
  formatRangeDisplay,
  formatSigma,
  formatValue,
  formatYearLabel,
  friendlyFallbackName,
  highlightSearchMatch,
  normalizeAngle,
  normalizeClass,
  normalizeDataServer,
  normalizeRoleLabel,
  positiveRatioValue,
  rafThrottle,
  renderValueHtml,
  roundedInt,
  sortYearValue,
  svgNumber,
  titleizeFallbackLabel,
  toRomanTier,
} = globalThis.MKShipUtils || {};
const {
  hardpointLayoutBounds,
  normalizeHardpointLayoutPoint,
  normalizeHardpointPayload,
  withHardpointLayouts,
} = globalThis.MKShipHardpoints || {};
const {
  mirrorHorizontalSector,
  polarPoint,
  rotateSector,
  sectorContainsAngle,
  sectorCrossesForwardCenterline,
  sectorLabelAngles,
  sectorPath,
  sectorPieceLabelAngles,
  sectorSideSign,
  signedAngle,
  splitSectorByDeadZones,
  uniqueAngleValues,
} = globalThis.MKShipGeometry || {};
const {
  els,
  floatingTableHover,
  state,
  staticDataLoadPromises,
  staticModalProfilesLoadPromises,
} = globalThis.MKShipAppState || {};

const {
  fetchJsonWithLoadingProgress,
  hideLoading,
  setLoadingStatus,
  setLoadingTranslator,
  showLoading,
} = globalThis.MKShipLoading || {};
const {
  browserLanguage,
  browserTheme,
  initialTheme,
  normalizeLanguage,
  normalizeTheme,
  rememberLanguage,
  rememberTheme,
  storedLanguage,
  storedTheme,
} = globalThis.MKShipPreferences || {};
const {
  nationFromRouteCode,
  nationRouteCode,
  parameterFromRouteCode,
  parameterRouteCode,
  routeDataServerFromSearch,
  routeDebugShipsFromSearch,
  shipFromRouteSegment: routeShipFromSegment,
  shipRouteCode,
  shipsFromRouteValue: routeShipsFromValue,
} = globalThis.MKShipRoutes || {};
const {
  labelI18nKey,
} = globalThis.MKShipI18nLabels || {};

let shellChartTooltip = null;
const TIER_FILTER_MIN = 1;
const TIER_FILTER_MAX = 11;
const ADSENSE_SCRIPT_ID = "mktool-adsense-script";
const ADSENSE_CLIENT_PATTERN = /^ca-pub-\d+$/;
const ADSENSE_SLOT_PATTERN = /^\d+$/;

function clampTierFilterValue(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return TIER_FILTER_MIN;
  return Math.max(TIER_FILTER_MIN, Math.min(TIER_FILTER_MAX, Math.round(numeric)));
}

function updateTierMinFromInput(value) {
  const next = clampTierFilterValue(value);
  const wasCollapsed = state.filters.tierMin === state.filters.tierMax;
  if (next > state.filters.tierMax) {
    if (wasCollapsed) {
      state.filters.tierMax = next;
    } else {
      state.filters.tierMin = state.filters.tierMax;
    }
    return;
  }
  state.filters.tierMin = next;
}

function updateTierMaxFromInput(value) {
  const next = clampTierFilterValue(value);
  const wasCollapsed = state.filters.tierMin === state.filters.tierMax;
  if (next < state.filters.tierMin) {
    if (wasCollapsed) {
      state.filters.tierMin = next;
    } else {
      state.filters.tierMax = state.filters.tierMin;
    }
    return;
  }
  state.filters.tierMax = next;
}

function adjustTierMin(delta) {
  state.filters.tierMin = Math.min(
    state.filters.tierMax,
    clampTierFilterValue(state.filters.tierMin + delta),
  );
}

function adjustTierMax(delta) {
  state.filters.tierMax = Math.max(
    state.filters.tierMin,
    clampTierFilterValue(state.filters.tierMax + delta),
  );
}

function serverDisplayName(server = state.dataServer) {
  return normalizeDataServer(server) === "test" ? t("server.test", "Test") : t("server.live", "Live");
}

function applyTheme(theme, options = {}) {
  const next = normalizeTheme(theme);
  state.theme = next;
  document.documentElement.dataset.theme = next;
  document.documentElement.style.colorScheme = next;
  if (options.remember) rememberTheme(next);
  renderSettingsControls();
}

function renderThemeToggle() {
  if (!els.themeToggle) return;
  const isDark = state.theme === "dark";
  const label = isDark
    ? t("theme.switchLight", "Switch to light mode")
    : t("theme.switchDark", "Switch to dark mode");
  els.themeToggle.setAttribute("aria-pressed", isDark ? "true" : "false");
  els.themeToggle.setAttribute("aria-label", label);
  els.themeToggle.title = label;
}

function renderSettingsControls() {
  renderThemeToggle();
  if (els.parameterExtremeToggle) {
    const active = !!state.parameterExtremeHighlight;
    els.parameterExtremeToggle.setAttribute("aria-pressed", active ? "true" : "false");
    els.parameterExtremeToggle.title = t("settings.highlightBestWorst", "Mark highest / lowest");
  }
  if (els.debugShipsToggle) {
    const active = !!state.debugShips;
    els.debugShipsToggle.setAttribute("aria-pressed", active ? "true" : "false");
    els.debugShipsToggle.title = t("settings.debugShips", "Debug ships");
  }
  if (els.settingsToggle) {
    els.settingsToggle.textContent = t("settings.openShort", "Settings");
    els.settingsToggle.title = t("settings.open", "Settings");
  }
}

function setSettingsPanelOpen(open) {
  if (!els.settingsPanel || !els.settingsToggle) return;
  els.settingsPanel.classList.toggle("hidden", !open);
  els.settingsToggle.setAttribute("aria-expanded", open ? "true" : "false");
}

function settingsPanelIsOpen() {
  return !!els.settingsPanel && !els.settingsPanel.classList.contains("hidden");
}

function configuredSupportUrl() {
  const url = `${SUPPORT_URL || ""}`.trim();
  return /^https?:\/\//i.test(url) ? url : "";
}

function configureSupportLinks() {
  const supportUrl = configuredSupportUrl();
  document.querySelectorAll("[data-support-link]").forEach((link) => {
    if (!(link instanceof HTMLAnchorElement)) return;
    if (supportUrl) {
      link.href = supportUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    } else {
      link.href = "/support";
      link.removeAttribute("target");
      link.removeAttribute("rel");
    }
  });
}

function configuredAdSenseClient() {
  const client = `${ADSENSE_CLIENT || ""}`.trim();
  return ADSENSE_CLIENT_PATTERN.test(client) ? client : "";
}

function configuredAdSenseSlot(slotName) {
  const slot = `${ADSENSE_SLOTS?.[slotName] || ""}`.trim();
  return ADSENSE_SLOT_PATTERN.test(slot) ? slot : "";
}

function adSensePreviewEnabled() {
  if (!ADSENSE_PREVIEW || configuredAdSenseClient()) return false;
  const hostname = window.location.hostname.toLowerCase();
  return window.location.protocol === "file:" || hostname === "localhost" || hostname === "127.0.0.1";
}

function loadingOverlayIsVisible() {
  return !!els.loadingOverlay && !els.loadingOverlay.classList.contains("hidden");
}

function homeHasPublisherContent() {
  return !!document.querySelector("#home-view .home-guide p")
    && document.querySelectorAll("#home-view section h2").length >= 4;
}

function nationHasPublisherContent() {
  return !!state.activeNation && !!document.querySelector("#nation-view .ship-node");
}

function parametersHasPublisherContent() {
  return !!els.parameterOutput?.querySelector(".param-table tbody tr");
}

function adSensePlacementHasPublisherContent(node) {
  const view = node.dataset.adsenseView || "";
  if (view === "home") return homeHasPublisherContent();
  if (view === "nation") return nationHasPublisherContent();
  if (view === "parameters") return parametersHasPublisherContent();
  return false;
}

function adSensePlacementIsActive(node) {
  if (!state.routeReady || loadingOverlayIsVisible()) return false;
  const view = node.dataset.adsenseView || "";
  if (view && view !== state.activeMainTab) return false;
  if (!adSensePlacementHasPublisherContent(node)) return false;
  if (node.dataset.adsensePlacement === "rail") {
    return window.matchMedia && window.matchMedia("(min-width: 1500px)").matches;
  }
  return true;
}

function clearAdSenseSlot(node) {
  if (!node.innerHTML && !node.dataset.adsenseRenderedSlot && !node.dataset.adsensePreviewRendered) return;
  node.innerHTML = "";
  delete node.dataset.adsenseClient;
  delete node.dataset.adsenseRenderedSlot;
  delete node.dataset.adsensePreviewRendered;
}

function renderAdSenseSlot(node, client, slot) {
  if (node.dataset.adsenseClient === client && node.dataset.adsenseRenderedSlot === slot) return;
  node.dataset.adsenseClient = client;
  node.dataset.adsenseRenderedSlot = slot;
  node.innerHTML = `
    <div class="adsense-label">Advertisements</div>
    <ins class="adsbygoogle"
      style="display:block"
      data-ad-client="${escapeHtml(client)}"
      data-ad-slot="${escapeHtml(slot)}"
      data-ad-format="auto"
      data-full-width-responsive="true"${ADSENSE_TEST_MODE ? ' data-adtest="on"' : ""}></ins>
  `;
}

function renderAdSensePreviewSlot(node) {
  if (node.dataset.adsensePreviewRendered === "true") return;
  const placement = node.dataset.adsensePlacement === "rail" ? "300 x 600" : "970 x 250";
  node.dataset.adsensePreviewRendered = "true";
  node.innerHTML = `
    <div class="adsense-label">Advertisements</div>
    <div class="adsense-preview-card" aria-hidden="true">
      <strong>AdSense preview</strong>
      <span>${escapeHtml(placement)}</span>
      <small>Local placeholder only</small>
    </div>
  `;
}

function requestVisibleAdSenseAds() {
  if (!configuredAdSenseClient()) return;
  document.querySelectorAll("ins.adsbygoogle:not([data-mktool-adsense-pushed])").forEach((node) => {
    if (!(node instanceof HTMLElement)) return;
    if (node.offsetParent === null) return;
    node.dataset.mktoolAdsensePushed = "true";
    try {
      (window.adsbygoogle = window.adsbygoogle || []).push({});
    } catch (_) {
      node.removeAttribute("data-mktool-adsense-pushed");
    }
  });
}

function loadAdSenseScript(client) {
  if (!client) return Promise.resolve(false);
  const existing = document.getElementById(ADSENSE_SCRIPT_ID);
  if (existing) {
    if (existing.dataset.loaded === "true") return Promise.resolve(true);
    return new Promise((resolve) => {
      existing.addEventListener("load", () => resolve(true), { once: true });
      existing.addEventListener("error", () => resolve(false), { once: true });
    });
  }
  const script = document.createElement("script");
  script.id = ADSENSE_SCRIPT_ID;
  script.async = true;
  script.crossOrigin = "anonymous";
  script.src = `https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${encodeURIComponent(client)}`;
  script.addEventListener("load", () => {
    script.dataset.loaded = "true";
    requestVisibleAdSenseAds();
  }, { once: true });
  document.head.appendChild(script);
  return new Promise((resolve) => {
    script.addEventListener("load", () => resolve(true), { once: true });
    script.addEventListener("error", () => resolve(false), { once: true });
  });
}

function configureAdSensePlacements() {
  const client = configuredAdSenseClient();
  const preview = adSensePreviewEnabled();
  const nodes = document.querySelectorAll("[data-adsense-slot]");
  let hasVisibleSlot = false;
  document.documentElement.dataset.adsenseEnabled = client ? "true" : "false";
  document.documentElement.dataset.adsensePreview = preview ? "true" : "false";
  document.documentElement.dataset.activeTab = state.activeMainTab || "home";
  nodes.forEach((node) => {
    if (!(node instanceof HTMLElement)) return;
    const slot = configuredAdSenseSlot(node.dataset.adsenseSlot || "");
    const active = (!!client && !!slot || preview) && adSensePlacementIsActive(node);
    node.hidden = !active;
    if (!active) {
      clearAdSenseSlot(node);
      return;
    }
    if (preview) {
      renderAdSensePreviewSlot(node);
      return;
    }
    renderAdSenseSlot(node, client, slot);
    hasVisibleSlot = true;
  });
  if (hasVisibleSlot) {
    loadAdSenseScript(client).then((loaded) => {
      if (loaded) requestVisibleAdSenseAds();
    });
  }
}

function routeLanguage() {
  if (window.location.pathname.toLowerCase().replace(/\/+$/, "") === "/ru") return "ru";
  const params = new URLSearchParams(window.location.search);
  const explicitLanguage = params.get("lang");
  if (explicitLanguage) return normalizeLanguage(explicitLanguage);
  return storedLanguage() || browserLanguage();
}

function t(key, fallback = "", values = {}) {
  const template = state.uiText?.[key] ?? fallback ?? key;
  return `${template}`.replace(/\{(\w+)\}/g, (_, name) => values[name] ?? "");
}

setLoadingTranslator(t);

function uiLabel(label, fallback = label) {
  const text = `${label ?? ""}`;
  if (!text) return "";
  const altMatch = text.match(/^(.+?)\s+\(alt\)$/i);
  if (altMatch) return `${uiLabel(altMatch[1], altMatch[1])} ${t("label.altSuffix", "(alt)")}`;
  const key = labelI18nKey(text);
  return key ? t(key, fallback ?? text) : (fallback ?? text);
}

function uiLabelLower(label) {
  return uiLabel(label, label).toLocaleLowerCase(state.language === "ru" ? "ru-RU" : undefined);
}

async function loadUiLocale(language = state.language) {
  const lang = normalizeLanguage(language);
  async function fetchLocale(code) {
    const response = await fetch(`/locales/${encodeURIComponent(code)}.json?v=${DATA_VERSION}`, { cache: "no-cache" });
    if (!response.ok) throw new Error(`Failed to load locale: ${code}`);
    return response.json();
  }

  try {
    state.uiText = await fetchLocale(lang);
    state.language = lang;
  } catch (error) {
    const fallbackLanguages = [DEFAULT_LANGUAGE, "ru"].filter((code, index, values) => (
      code !== lang && values.indexOf(code) === index
    ));
    let lastError = error;
    for (const fallbackLanguage of fallbackLanguages) {
      try {
        state.uiText = await fetchLocale(fallbackLanguage);
        state.language = fallbackLanguage;
        lastError = null;
        break;
      } catch (fallbackError) {
        lastError = fallbackError;
      }
    }
    if (lastError) throw lastError;
  }
  if (els.uiLanguage) els.uiLanguage.value = state.language;
  applyStaticTranslations();
}

function applyStaticTranslations() {
  document.documentElement.lang = state.language;
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n, node.textContent);
  });
  document.querySelectorAll("[data-i18n-html]").forEach((node) => {
    node.innerHTML = t(node.dataset.i18nHtml, node.innerHTML);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
    node.setAttribute("placeholder", t(node.dataset.i18nPlaceholder, node.getAttribute("placeholder") || ""));
  });
  document.querySelectorAll("[data-i18n-alt]").forEach((node) => {
    node.setAttribute("alt", t(node.dataset.i18nAlt, node.getAttribute("alt") || ""));
  });
  document.querySelectorAll("[data-i18n-aria-label]").forEach((node) => {
    node.setAttribute("aria-label", t(node.dataset.i18nAriaLabel, node.getAttribute("aria-label") || ""));
  });
  renderTopbarControls();
  renderGameVersion();
}

function renderTopbarControls() {
  if (els.dataServer) {
    const liveOption = els.dataServer.querySelector("option[value='live']");
    const testOption = els.dataServer.querySelector("option[value='test']");
    if (liveOption) liveOption.textContent = t("server.live", "Live");
    if (testOption) testOption.textContent = t("server.test", "Test");
  }
  renderSettingsControls();
}

function localizedLoadingStatus(key, fallback, values = {}) {
  return t(key, fallback, values);
}

function gameVersionText(server = state.dataServer) {
  const normalized = normalizeDataServer(server);
  const value = state.gameVersions?.[normalized];
  if (value && typeof value === "object") {
    return `${value.version || value.label || ""}`.trim();
  }
  return `${value || ""}`.trim();
}

function renderGameVersion() {
  if (!els.gameVersion) return;
  els.gameVersion.textContent = gameVersionText() || "25.4";
}

async function loadVersionHighlights() {
  const server = normalizeDataServer(state.dataServer);
  const urls = [
    `/data/${encodeURIComponent(server)}/version-highlights.json?v=${DATA_VERSION}`,
    `/data/version-highlights.json?v=${DATA_VERSION}`,
  ];
  for (const url of urls) {
    try {
      const response = await fetch(url, { cache: "no-cache" });
      if (response.status === 404) continue;
      if (!response.ok) throw new Error(`Failed to load ${url}`);
      const payload = await response.json();
      state.versionHighlights = payload && typeof payload === "object" ? payload : null;
      return;
    } catch (error) {
      console.warn("Failed to load version highlights", error);
    }
  }
  state.versionHighlights = null;
}

function versionHighlightVersions() {
  const payload = state.versionHighlights;
  if (!payload || typeof payload !== "object") return [];
  if (Array.isArray(payload.versions)) return payload.versions;
  if (Array.isArray(payload.ships)) {
    return [{
      version: payload.version || gameVersionText() || "",
      ships: payload.ships,
    }];
  }
  return [];
}

function versionHighlightShip(entry) {
  const code = `${entry?.code || ""}`.trim();
  if (!code) return null;
  return state.ships.find((ship) => ship.identity.code === code) || null;
}

function versionHighlightTag(entry, ship) {
  const explicit = `${entry?.tag || ""}`.trim().toLowerCase();
  if (explicit) return explicit;
  if (ship?.identity?.parent_ship) return "replica";
  return ship?.availability || "";
}

function versionHighlightTagLabel(tag) {
  if (tag === "replica") return t("versionHighlights.tag.replica", "Clone");
  if (tag === "test") return t("availability.test", "Test");
  if (tag === "early") return t("availability.earlyAccess", "Early access");
  if (tag === "premium") return t("availability.premium", "Premium");
  if (tag === "tech") return t("availability.techTree", "Tech tree");
  return tag;
}

function versionHighlightTagRank(tag) {
  if (tag === "test") return 0;
  if (tag === "early") return 1;
  if (tag === "replica") return 2;
  if (tag === "premium") return 3;
  if (tag === "tech") return 4;
  return 5;
}

function sortedVersionHighlightShips(ships) {
  return [...(ships || [])].sort((left, right) => {
    const leftShip = versionHighlightShip(left);
    const rightShip = versionHighlightShip(right);
    const leftTier = Number(leftShip?.identity?.tier ?? left?.tier ?? 0);
    const rightTier = Number(rightShip?.identity?.tier ?? right?.tier ?? 0);
    if (leftTier !== rightTier) return rightTier - leftTier;
    const leftTag = versionHighlightTag(left, leftShip);
    const rightTag = versionHighlightTag(right, rightShip);
    const tagDelta = versionHighlightTagRank(leftTag) - versionHighlightTagRank(rightTag);
    if (tagDelta) return tagDelta;
    const leftName = leftShip?.fullDisplayName || leftShip?.displayName || left?.name || left?.code || "";
    const rightName = rightShip?.fullDisplayName || rightShip?.displayName || right?.name || right?.code || "";
    return leftName.localeCompare(rightName, state.language || "en", { sensitivity: "base" });
  });
}

function versionHighlightShipHtml(entry) {
  const ship = versionHighlightShip(entry);
  const code = ship?.identity?.code || entry?.code || "";
  const tier = ship?.identity?.tier ?? entry?.tier ?? "";
  const shipClass = ship ? uiLabelLower(displayClass(ship)) : uiLabelLower(entry?.class || t("versionHighlights.ship", "ship"));
  const name = ship?.fullDisplayName || ship?.displayName || entry?.name || code;
  const tag = versionHighlightTag(entry, ship);
  const tagLabel = versionHighlightTagLabel(tag);
  const prefix = t("versionHighlights.newShipPrefix", "New tier {tier} {class}", {
    tier,
    class: shipClass,
  });
  const buttonHtml = ship
    ? `<button type="button" class="version-highlight-ship-link" data-open-ship="${escapeHtml(code)}">${escapeHtml(name)}</button>`
    : `<strong>${escapeHtml(name)}</strong>`;
  return `
    <li class="version-highlight-item">
      <span class="version-highlight-prefix">${escapeHtml(prefix)}</span>
      ${buttonHtml}
      ${tagLabel ? `<span class="version-highlight-tag version-highlight-tag-${escapeHtml(tag)}">${escapeHtml(tagLabel)}</span>` : ""}
    </li>
  `;
}

function renderVersionHighlights() {
  if (!els.versionHighlights) return;
  const versions = versionHighlightVersions()
    .map((version) => ({
      ...version,
      ships: Array.isArray(version?.ships) ? version.ships : [],
    }))
    .filter((version) => version.ships.length);
  if (!versions.length) {
    els.versionHighlights.innerHTML = "";
    return;
  }
  els.versionHighlights.innerHTML = `
    <h2>${escapeHtml(t("versionHighlights.title", "Game versions"))}</h2>
    ${versions.map((version) => `
      <section class="version-highlight-version">
        <h3>${escapeHtml(version.label || version.version || gameVersionText() || t("versionHighlights.current", "Current update"))}</h3>
        <ul>${sortedVersionHighlightShips(version.ships).map(versionHighlightShipHtml).join("")}</ul>
      </section>
    `).join("")}
  `;
  els.versionHighlights.querySelectorAll("[data-open-ship]").forEach((button) => {
    button.addEventListener("click", () => handleShipCardOpen(button.dataset.openShip));
  });
}

function renderHomeView() {
  document.documentElement.dataset.dataServer = normalizeDataServer(state.dataServer);
  renderGameVersion();
  renderVersionHighlights();
  configureAdSensePlacements();
}

function staticDataKey(server = state.dataServer, language = state.language) {
  return `${normalizeDataServer(server)}-${normalizeLanguage(language)}`;
}

function staticDataRoot() {
  const data = window.MK_SHIPTOOL_STATIC_DATA;
  return data && typeof data === "object" ? data : null;
}

function staticCatalogRequiresAssembly(dataKey) {
  const root = staticDataRoot();
  const catalogSpec = root?.catalogChunks?.[dataKey]?.catalog;
  return !!(catalogSpec && typeof catalogSpec === "object" && catalogSpec.ships && typeof catalogSpec.ships === "object");
}

function hasStaticCatalogData(server = state.dataServer, language = state.language) {
  const root = staticDataRoot();
  const dataKey = staticDataKey(server, language);
  const catalog = root?.catalogs?.[dataKey];
  if (!catalog || typeof catalog !== "object") return false;
  if (staticCatalogRequiresAssembly(dataKey) && catalog.__staticShipChunksLoaded !== true) return false;
  return true;
}

function staticCatalogChunkSources(chunkSpec) {
  if (!chunkSpec) return [];
  if (typeof chunkSpec === "string") return [chunkSpec];
  if (typeof chunkSpec !== "object") return [];
  const catalogSpec = chunkSpec.catalog;
  if (typeof catalogSpec === "string") return [catalogSpec];
  if (!catalogSpec || typeof catalogSpec !== "object") return [];
  const sources = [];
  if (typeof catalogSpec.base === "string") sources.push(catalogSpec.base);
  const shipSources = Object.values(catalogSpec.ships || {})
    .filter((value) => typeof value === "string");
  sources.push(...shipSources);
  return sources;
}

function assembleStaticCatalogShipChunks(dataKey) {
  const root = staticDataRoot();
  const catalog = root?.catalogs?.[dataKey];
  if (!catalog || typeof catalog !== "object") return false;
  if (!staticCatalogRequiresAssembly(dataKey)) return true;
  if (catalog.__staticShipChunksLoaded === true) return true;
  const expected = Object.keys(root?.catalogChunks?.[dataKey]?.catalog?.ships || {});
  if (!expected.length) return false;
  const chunks = root?.catalogShipChunks?.[dataKey] || {};
  const ships = [];
  for (const index of expected) {
    const chunk = chunks[index];
    if (!Array.isArray(chunk)) return false;
    ships.push(...chunk);
  }
  catalog.ships = ships;
  Object.defineProperty(catalog, "__staticShipChunksLoaded", {
    value: true,
    enumerable: false,
    configurable: true,
  });
  return true;
}

async function loadStaticCatalogData(server = state.dataServer, language = state.language) {
  const normalizedServer = normalizeDataServer(server);
  const normalizedLanguage = normalizeLanguage(language);
  if (hasStaticCatalogData(normalizedServer, normalizedLanguage)) return true;
  const root = staticDataRoot();
  const dataKey = staticDataKey(normalizedServer, normalizedLanguage);
  const chunkSources = staticCatalogChunkSources(root?.catalogChunks?.[dataKey]);
  if (!chunkSources.length) return false;
  const promiseKey = `${dataKey}/catalog`;
  if (staticDataLoadPromises[promiseKey]) return staticDataLoadPromises[promiseKey];
  const loadOne = (chunkSrc) => new Promise((resolve) => {
    const script = document.createElement("script");
    script.src = `${chunkSrc}${chunkSrc.includes("?") ? "&" : "?"}v=${DATA_VERSION}`;
    script.async = true;
    script.onload = () => resolve(true);
    script.onerror = () => {
      console.warn("Failed to load static catalog chunk", dataKey, chunkSrc);
      resolve(false);
    };
    document.head.appendChild(script);
  });
  staticDataLoadPromises[promiseKey] = Promise.all(chunkSources.map(loadOne)).then((results) => {
    if (!results.every(Boolean)) {
      delete staticDataLoadPromises[promiseKey];
      return false;
    }
    assembleStaticCatalogShipChunks(dataKey);
    return hasStaticCatalogData(normalizedServer, normalizedLanguage);
  });
  return staticDataLoadPromises[promiseKey];
}

function hasStaticConfigProfilesData(server = state.dataServer, language = state.language, config = state.activeConfig) {
  return !!staticConfigProfilesPayload(server, language, config);
}

async function loadStaticConfigProfilesData(server = state.dataServer, language = state.language, config = state.activeConfig) {
  const normalizedServer = normalizeDataServer(server);
  const normalizedLanguage = normalizeLanguage(language);
  const normalizedConfig = config || state.activeConfig;
  if (hasStaticConfigProfilesData(normalizedServer, normalizedLanguage, normalizedConfig)) return true;
  const root = staticDataRoot();
  const dataKey = staticDataKey(normalizedServer, normalizedLanguage);
  const chunkSpec = root?.catalogChunks?.[dataKey];
  if (typeof chunkSpec === "string") return loadStaticCatalogData(normalizedServer, normalizedLanguage);
  const chunkSrc = chunkSpec?.profiles?.[normalizedConfig];
  if (!chunkSrc) return false;
  const promiseKey = `${dataKey}/profiles/${normalizedConfig}`;
  if (staticDataLoadPromises[promiseKey]) return staticDataLoadPromises[promiseKey];
  staticDataLoadPromises[promiseKey] = new Promise((resolve) => {
    const script = document.createElement("script");
    script.src = `${chunkSrc}${chunkSrc.includes("?") ? "&" : "?"}v=${DATA_VERSION}`;
    script.async = true;
    script.onload = () => resolve(hasStaticConfigProfilesData(normalizedServer, normalizedLanguage, normalizedConfig));
    script.onerror = () => {
      console.warn("Failed to load static config profile chunk", dataKey, normalizedConfig);
      delete staticDataLoadPromises[promiseKey];
      resolve(false);
    };
    document.head.appendChild(script);
  });
  return staticDataLoadPromises[promiseKey];
}

function staticCatalogPayload(server = state.dataServer, language = state.language) {
  const root = staticDataRoot();
  const payload = root?.catalogs?.[staticDataKey(server, language)];
  return payload && typeof payload === "object" ? payload : null;
}

function staticConfigProfilesPayload(server = state.dataServer, language = state.language, config = state.activeConfig) {
  const root = staticDataRoot();
  const payload = root?.catalogProfiles?.[staticDataKey(server, language)]?.[config];
  return payload && typeof payload === "object" ? payload : null;
}

function staticModalProfileShardKey(shipCode) {
  return `${shipCode || ""}`.slice(0, 3).replace(/[^a-z0-9]/gi, "").toLowerCase() || "misc";
}

function hasStaticModalProfiles(server = state.dataServer, language = state.language, config = null, shipCode = null) {
  const root = staticDataRoot();
  const payload = root?.modalProfiles?.[staticDataKey(server, language)];
  if (!payload || typeof payload !== "object") return false;
  if (!config) return Object.keys(payload).length > 0;
  const configPayload = payload[config];
  if (!configPayload || typeof configPayload !== "object") return false;
  if (!shipCode) return Object.keys(configPayload).length > 0;
  const profile = configPayload[shipCode];
  return profile && typeof profile === "object";
}

function staticModalProfileChunkSources(chunkSpec, shipCode = null) {
  if (!chunkSpec) return [];
  if (typeof chunkSpec === "string") return [chunkSpec];
  if (typeof chunkSpec !== "object") return [];
  if (shipCode) {
    const shard = staticModalProfileShardKey(shipCode);
    return chunkSpec[shard] ? [chunkSpec[shard]] : [];
  }
  return Object.values(chunkSpec).filter((value) => typeof value === "string");
}

async function loadStaticModalProfiles(server = state.dataServer, language = state.language, config = state.activeConfig, shipCode = null) {
  const normalizedServer = normalizeDataServer(server);
  const normalizedLanguage = normalizeLanguage(language);
  const normalizedConfig = config || state.activeConfig;
  if (hasStaticModalProfiles(normalizedServer, normalizedLanguage, normalizedConfig, shipCode)) return true;
  const root = staticDataRoot();
  const dataKey = staticDataKey(normalizedServer, normalizedLanguage);
  const chunkSpec = root?.modalProfileChunks?.[dataKey]?.[normalizedConfig];
  const chunkSources = staticModalProfileChunkSources(chunkSpec, shipCode);
  if (!chunkSources.length) return false;
  const loadOne = (chunkSrc) => {
    const promiseKey = `${dataKey}/${normalizedConfig}/${chunkSrc}`;
    if (staticModalProfilesLoadPromises[promiseKey]) return staticModalProfilesLoadPromises[promiseKey];
    staticModalProfilesLoadPromises[promiseKey] = new Promise((resolve) => {
      const script = document.createElement("script");
      script.src = `${chunkSrc}${chunkSrc.includes("?") ? "&" : "?"}v=${DATA_VERSION}`;
      script.async = true;
      script.onload = () => resolve(true);
      script.onerror = () => {
        console.warn("Failed to load static modal profile chunk", dataKey, normalizedConfig, chunkSrc);
        delete staticModalProfilesLoadPromises[promiseKey];
        resolve(false);
      };
      document.head.appendChild(script);
    });
    return staticModalProfilesLoadPromises[promiseKey];
  };
  const results = await Promise.all(chunkSources.map(loadOne));
  if (!results.some(Boolean)) return false;
  return hasStaticModalProfiles(normalizedServer, normalizedLanguage, normalizedConfig, shipCode);
}

function staticSelectedKey(selectedMap) {
  return Object.values(selectedMap || {})
    .filter(Boolean)
    .sort()
    .join(",");
}

function staticModalProfilePayload(shipCode, config, selectedMap, server = state.dataServer, language = state.language) {
  const root = staticDataRoot();
  const profile = root?.modalProfiles?.[staticDataKey(server, language)]?.[config]?.[shipCode]?.[staticSelectedKey(selectedMap)];
  return profile && typeof profile === "object" ? profile : null;
}

function applyStaticModalProfiles(ship, snapshots, config = state.activeConfig) {
  const applied = {};
  (snapshots || []).forEach((snapshot) => {
    const profile = staticModalProfilePayload(ship.identity.code, config, snapshot);
    if (!profile) return;
    setCachedModalProfile(ship.identity.code, config, snapshot, profile);
    applied[modalProfileCacheKey(ship.identity.code, config, snapshot)] = profile;
  });
  return applied;
}

async function loadGameVersions() {
  try {
    const response = await fetch(`/data/Version.json?v=${DATA_VERSION}`, { cache: "no-cache" });
    if (!response.ok) return;
    const payload = await response.json();
    if (!payload || typeof payload !== "object") return;
    state.gameVersions = {
      ...state.gameVersions,
      ...payload,
    };
  } catch (error) {
    console.warn("Failed to load Version.json", error);
  } finally {
    renderGameVersion();
  }
}

function modalYearLabel(ship) {
  const isPaperShip = ship?.identity?.is_paper_ship === true || ship?.identity?.isPaperShip === true;
  return isPaperShip ? t("label.yearOfDesign", "Year of Design") : t("label.year", "Year");
}

const MKBallistics = window.MKBallistics;

async function initShellWasm() {
  return MKBallistics?.initShellWasm?.() ?? null;
}

function clampShellDispersionShots(value) {
  const numeric = Math.round(Number(value));
  if (!Number.isFinite(numeric)) return state.shellDispersionShots || SHELL_DISPERSION_SAMPLE_COUNT;
  return clamp(numeric, SHELL_DISPERSION_MIN_SHOTS, SHELL_DISPERSION_MAX_SHOTS);
}

function getMaxSpeed(hull) {
  const maxSpeed = Number(hull?.maxSpeed);
  const speedCoef = hull?.speedCoef == null ? 1 : Number(hull.speedCoef);
  if (!Number.isFinite(maxSpeed) || maxSpeed <= 0 || !Number.isFinite(speedCoef)) return null;
  return maxSpeed * speedCoef;
}

function getEffectiveTonnage(hull) {
  const tonnage = Number(hull?.tonnage);
  if (Number.isFinite(tonnage) && tonnage > 0) {
    return tonnage;
  }

  const mass = Number(hull?.mass);
  if (Number.isFinite(mass) && mass > 0) {
    return mass / 1000;
  }

  return null;
}

function getEnginePower(hull, engine) {
  const enginePower = hull?.enginePower ?? engine?.histEnginePower;
  const numeric = Number(enginePower);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : null;
}

function estimatePropulsionFactor(hull, engine) {
  const maxSpeed = getMaxSpeed(hull);
  const tonnage = getEffectiveTonnage(hull);
  const enginePower = getEnginePower(hull, engine);

  if (!maxSpeed || maxSpeed <= 0 || !tonnage || !enginePower) {
    return null;
  }

  return 5 * Math.sqrt(enginePower / (tonnage * maxSpeed));
}

function getAccelerationTargetSpeed(maxSpeed, engine, targetRatio, targetMode) {
  const exactTargetSpeed = maxSpeed * targetRatio;

  if (targetMode === "exact90") {
    return exactTargetSpeed;
  }

  // Future alternative:
  // Use this if Acceleration should mean "time until the acceleration curve
  // becomes noticeably flatter" instead of strict 0-90%.
  const curveEndTargetSpeed = Math.max(
    exactTargetSpeed,
    Number(engine?.forwardEngineForsagMaxSpeed),
  );

  // Avoid exact max speed; the drag/thrust equilibrium makes it numerically awkward.
  return Math.min(maxSpeed * 0.999, curveEndTargetSpeed);
}

function createAccelerationState(hull, engine) {
  const maxSpeed = getMaxSpeed(hull);
  const propulsionFactor = estimatePropulsionFactor(hull, engine);
  const forwardEngineUpTime = Number(engine?.forwardEngineUpTime);
  const forsag = Number(engine?.forwardEngineForsag);
  const forsagMaxSpeed = Number(engine?.forwardEngineForsagMaxSpeed);

  if (!propulsionFactor || !maxSpeed || maxSpeed <= 0) {
    return null;
  }
  if (
    !Number.isFinite(forwardEngineUpTime)
    || forwardEngineUpTime <= 0
    || !Number.isFinite(forsag)
    || !Number.isFinite(forsagMaxSpeed)
  ) {
    return null;
  }

  return {
    maxSpeed,
    propulsionFactor,
    engineRampTime: forwardEngineUpTime / 2.8,
    forsag,
    forsagMaxSpeed,
  };
}

function stepForwardSpeed(time, speed, state, dt) {
  const {
    maxSpeed,
    propulsionFactor,
    engineRampTime,
    forsag,
    forsagMaxSpeed,
  } = state;

  const engineRatio = clamp01(time / engineRampTime);
  const normalThrust = propulsionFactor * engineRatio;
  const drag = propulsionFactor * Math.pow(speed / maxSpeed, 2);
  const isForsagZone = speed >= 0 && speed <= forsagMaxSpeed;
  const thrust = isForsagZone
    ? propulsionFactor * forsag
    : normalThrust;
  const acceleration = thrust - drag;
  const nextSpeed = speed + acceleration * dt;

  return clamp(nextSpeed, 0, maxSpeed);
}

function timeToReachAccelerationTarget(hull, engine, options = {}) {
  const targetRatio = options.targetRatio ?? 0.9;
  const targetMode = options.targetMode ?? "exact90";
  const dt = options.dt ?? 1 / 240;
  const maxTime = options.maxTime ?? 300;
  const state = createAccelerationState(hull, engine);

  if (!state) {
    return null;
  }

  const targetSpeed = getAccelerationTargetSpeed(
    state.maxSpeed,
    engine,
    targetRatio,
    targetMode,
  );

  let time = 0;
  let speed = 0;

  // Reverse-engineered approximation for forward acceleration only.
  // It intentionally models 0 kt -> target speed, not deceleration, reverse,
  // gear transitions, or the asymptotic tail after near-max speed.
  while (time <= maxTime) {
    const nextSpeed = stepForwardSpeed(time, speed, state, dt);

    if (speed < targetSpeed && nextSpeed >= targetSpeed) {
      const progress = (targetSpeed - speed) / Math.max(nextSpeed - speed, 1e-9);
      return time + dt * progress;
    }

    speed = nextSpeed;
    time += dt;
  }

  return null;
}

function accelerationInputsFromShip(ship) {
  const mobility = resolvedShipView(ship)?.mobility || {};
  return {
    hull: {
      maxSpeed: mobility.max_speed_kn,
      speedCoef: mobility.hull_speed_coef ?? 1,
      tonnage: mobility.tonnage_t,
      mass: mobility.mass_kg,
      enginePower: mobility.hull_engine_power,
    },
    engine: {
      histEnginePower: mobility.engine_power,
      forwardEngineUpTime: mobility.forward_engine_up_time,
      forwardEngineForsag: mobility.forward_engine_factor,
      forwardEngineForsagMaxSpeed: mobility.forward_engine_factor_max,
    },
  };
}

function shipAccelerationSeconds(ship) {
  const { hull, engine } = accelerationInputsFromShip(ship);
  return timeToReachAccelerationTarget(hull, engine, {
    targetRatio: 0.9,
    targetMode: "exact90",
  });
}

function accelerationDisplay(ship) {
  const seconds = shipAccelerationSeconds(ship);
  return seconds == null ? "N/A" : `${seconds.toFixed(1)} s`;
}

function secondaryBaseRangeMeters(ship) {
  return (secondaryGunModules(ship) || [])
    .reduce((max, module) => Math.max(max, module?.max_dist_m || module?.range_m || 0), 0) || null;
}

function secondaryCombatInstructionRangeMultiplier(ship) {
  const details = ship?.combat_instruction?.details;
  if (!Array.isArray(details)) return 1;
  const rangeDetail = details.find((item) => item?.label === "Secondary battery firing range");
  const value = Number(rangeDetail?.value);
  if (!Number.isFinite(value) || value <= 0) return 1;
  const delta = value / 100;
  return rangeDetail?.sign === "-" ? Math.max(0, 1 - delta) : 1 + delta;
}

function secondaryTheoreticalRangeMultiplier(ship) {
  const tier = Number(ship?.identity?.tier);
  const shipClass = normalizeClass(ship?.identity?.class);
  let multiplier = 1.2;
  if (tier >= 5 && (shipClass === "Battleship" || shipClass === "Cruiser")) {
    multiplier *= 1.26;
  }
  multiplier *= secondaryCombatInstructionRangeMultiplier(ship);
  return multiplier;
}

function secondaryTheoreticalRangeMeters(ship) {
  const baseRange = secondaryBaseRangeMeters(ship);
  if (!baseRange) return null;
  return baseRange * secondaryTheoreticalRangeMultiplier(ship);
}

function weaponRangeMetersForGroup(ship, groupLabel) {
  if (groupLabel === "Secondaries") {
    return secondaryTheoreticalRangeMeters(ship)
      ?? MKBallistics?.weaponRangeMetersForGroup?.(ship, groupLabel)
      ?? null;
  }
  return MKBallistics?.weaponRangeMetersForGroup?.(ship, groupLabel) ?? null;
}

function rangeOptionsKm(groupLabel, ships) {
  const maxRangeM = ships.reduce((max, ship) => Math.max(max, weaponRangeMetersForGroup(ship, groupLabel) || 0), 0);
  if (!maxRangeM) return [];
  const maxKm = maxSelectableRangeKm(maxRangeM);
  const options = [];
  for (let km = 1; km <= maxKm; km += 1) {
    options.push(km);
  }
  return options;
}

function maxSelectableRangeKm(maxRangeM) {
  const km = Number(maxRangeM) / 1000;
  if (!Number.isFinite(km) || km <= 0) return 0;
  const oneDecimalKm = Math.round((km + Number.EPSILON) * 10) / 10;
  return Math.max(1, Math.ceil(oneDecimalKm));
}

function getParameterRangeKm(groupLabel, ships) {
  if (!RANGE_SELECTABLE_GROUPS.has(groupLabel)) return null;
  const options = rangeOptionsKm(groupLabel, ships);
  if (!options.length) return null;
  const defaultKm = RANGE_DEFAULTS_KM[groupLabel] || options[0];
  const savedKm = state.parameterRanges[groupLabel];
  const resolvedKm = savedKm != null ? clamp(savedKm, options[0], options[options.length - 1]) : clamp(defaultKm, options[0], options[options.length - 1]);
  state.parameterRanges[groupLabel] = Number(resolvedKm.toFixed(1));
  return state.parameterRanges[groupLabel];
}

function getParameterRenderContext(groupLabel, ships) {
  const rangeKm = getParameterRangeKm(groupLabel, ships);
  return {
    groupLabel,
    ships,
    range_km: rangeKm,
    range_m: rangeKm == null ? null : rangeKm * 1000,
  };
}

function getDefaultRenderContext(groupLabel, ships) {
  if (!RANGE_SELECTABLE_GROUPS.has(groupLabel)) {
    return { groupLabel, ships, range_km: null, range_m: null };
  }
  const options = rangeOptionsKm(groupLabel, ships);
  if (!options.length) {
    return { groupLabel, ships, range_km: null, range_m: null };
  }
  const defaultKm = RANGE_DEFAULTS_KM[groupLabel] || options[0];
  const rangeKm = Number(clamp(defaultKm, options[0], options[options.length - 1]).toFixed(1));
  return {
    groupLabel,
    ships,
    range_km: rangeKm,
    range_m: rangeKm * 1000,
  };
}

function getModalRangeKm(groupLabel, ships) {
  if (!RANGE_SELECTABLE_GROUPS.has(groupLabel)) return null;
  const options = rangeOptionsKm(groupLabel, ships);
  if (!options.length) return null;
  const defaultKm = RANGE_DEFAULTS_KM[groupLabel] || options[0];
  const savedKm = state.modalParameterRanges[groupLabel];
  const resolvedKm = savedKm != null ? clamp(savedKm, options[0], options[options.length - 1]) : clamp(defaultKm, options[0], options[options.length - 1]);
  state.modalParameterRanges[groupLabel] = Number(resolvedKm.toFixed(1));
  return state.modalParameterRanges[groupLabel];
}

function getModalRenderContext(groupLabel, ships) {
  const rangeKm = getModalRangeKm(groupLabel, ships);
  return {
    groupLabel,
    ships,
    range_km: rangeKm,
    range_m: rangeKm == null ? null : rangeKm * 1000,
  };
}

function renderRangeSelect(groupLabel, ships) {
  if (!RANGE_SELECTABLE_GROUPS.has(groupLabel)) return "";
  const options = rangeOptionsKm(groupLabel, ships);
  if (!options.length) return "";
  const selectedKm = getParameterRangeKm(groupLabel, ships);
  const minKm = options[0];
  const maxKm = options[options.length - 1];
  return `
    <div class="parameter-range-control" data-range-group="${groupLabel}">
      <span>${uiLabel("Firing range")}:</span>
      <div class="parameter-range-spinner">
        <strong>${selectedKm}km</strong>
        <div class="parameter-range-buttons">
          <button type="button" class="parameter-range-button up" data-range-step="1" data-range-min="${minKm}" data-range-max="${maxKm}" data-range-group="${groupLabel}" aria-label="${escapeHtml(uiLabel("Increase firing range"))}"></button>
          <button type="button" class="parameter-range-button down" data-range-step="-1" data-range-min="${minKm}" data-range-max="${maxKm}" data-range-group="${groupLabel}" aria-label="${escapeHtml(uiLabel("Decrease firing range"))}"></button>
        </div>
      </div>
    </div>
  `;
}

function renderModalRangeControl(groupLabel, ships) {
  if (!RANGE_SELECTABLE_GROUPS.has(groupLabel)) return "";
  const options = rangeOptionsKm(groupLabel, ships);
  if (!options.length) return "";
  const selectedKm = getModalRangeKm(groupLabel, ships);
  const minKm = options[0];
  const maxKm = options[options.length - 1];
  return `
    <div class="parameter-range-control modal-range-control" data-modal-range-group="${groupLabel}">
      <span>${uiLabel("Firing range")}:</span>
      <div class="parameter-range-spinner">
        <strong>${selectedKm}km</strong>
        <div class="parameter-range-buttons">
          <button type="button" class="parameter-range-button modal-range-button up" data-modal-range-step="1" data-modal-range-min="${minKm}" data-modal-range-max="${maxKm}" data-modal-range-group="${groupLabel}" aria-label="${escapeHtml(uiLabel("Increase firing range"))}"></button>
          <button type="button" class="parameter-range-button modal-range-button down" data-modal-range-step="-1" data-modal-range-min="${minKm}" data-modal-range-max="${maxKm}" data-modal-range-group="${groupLabel}" aria-label="${escapeHtml(uiLabel("Decrease firing range"))}"></button>
        </div>
      </div>
    </div>
  `;
}

function mainBatteryModule(ship) {
  const module = mainBatteryModules(ship).find((item) => /_GM_1$/.test(item?.slot || "")) || mainBatteryModules(ship)[0];
  if (!module) return null;
  return {
    ...module,
    max_dist_m: module.max_dist_m ?? ship.artillery?.main_battery?.range_m ?? null,
  };
}

function secondaryModule(ship) {
  const modules = secondaryGunModules(ship);
  const module = modules.find((item) => /_GS_1$/.test(item?.slot || "")) || modules[0];
  if (!module) return null;
  const effectiveRangeM = (module.max_dist_m && module.max_dist_m > 0)
    ? module.max_dist_m
    : (module.range_m && module.range_m > 0 ? module.range_m : null);
  return {
    ...module,
    range_m: effectiveRangeM,
    max_dist_m: module.max_dist_m ?? effectiveRangeM ?? null,
  };
}

function metersToBw(value) {
  return value / BW_TO_METERS;
}

function horizontalDispersionMeters(module, rangeMeters) {
  if (!module || rangeMeters == null) return null;
  const distanceBw = metersToBw(rangeMeters);
  const idealDistanceBw = module.ideal_distance_bw;
  const idealRadiusBw = module.ideal_radius_bw;
  const minRadiusBw = module.min_radius_bw;
  const taperDistBw = metersToBw(module.taper_dist_m || 0);
  if ([idealDistanceBw, idealRadiusBw, minRadiusBw].some((value) => value == null)) return null;
  let radiusBw = distanceBw * (idealRadiusBw - minRadiusBw) / idealDistanceBw;
  if (taperDistBw > 0 && distanceBw <= taperDistBw) {
    radiusBw += minRadiusBw * (distanceBw / taperDistBw);
  } else {
    radiusBw += minRadiusBw;
  }
  return radiusBw * BW_TO_METERS;
}

function verticalDispersionMeters(module, rangeMeters) {
  if (!module || rangeMeters == null) return null;
  const horizontal = horizontalDispersionMeters(module, rangeMeters);
  if (horizontal == null) return null;
  const distanceBw = metersToBw(rangeMeters);
  const maxDistBw = metersToBw(module.max_dist_m || 0);
  const delimDistBw = maxDistBw * (module.delim ?? 0);
  const radiusOnZero = module.radius_on_zero;
  const radiusOnDelim = module.radius_on_delim;
  const radiusOnMax = module.radius_on_max;
  if ([radiusOnZero, radiusOnDelim, radiusOnMax].some((value) => value == null) || !maxDistBw) return null;
  let coeff;
  if (distanceBw < delimDistBw) {
    coeff = radiusOnZero + (radiusOnDelim - radiusOnZero) * (distanceBw / Math.max(delimDistBw, 1));
  } else {
    coeff = radiusOnDelim + (radiusOnMax - radiusOnDelim) * ((distanceBw - delimDistBw) / Math.max(maxDistBw - delimDistBw, 1));
  }
  return horizontal * coeff;
}

function shellResultAtRange(ship, projectile, context, groupLabel = context?.groupLabel) {
  return MKBallistics?.shellResultAtRange?.(ship, projectile, context, groupLabel) ?? null;
}

function isDisplayableShip(ship) {
  const group = ship?.identity?.group;
  const nation = ship?.identity?.nation;
  const shipClass = normalizeClass(ship?.identity?.class);
  if (EXCLUDED_SHIP_CLASSES.has(shipClass)) return false;
  if (state.debugShips) return true;
  return !HIDDEN_SHIP_GROUPS.has(group) && nation !== "Events";
}

function displayClass(ship) {
  return CLASS_LABELS[ship.shipClass] || ship.shipClass;
}

function localizedDisplayClass(ship) {
  return uiLabel(displayClass(ship));
}

function localizedNationLabel(ship) {
  return uiLabel(ship.nationLabel);
}

function displaySelectClass(ship) {
  return SELECT_CLASS_LABELS[ship.shipClass] || displayClass(ship);
}

function detectAvailability(ship) {
  const group = ship.identity?.group || ship.group || "";
  if (state.debugShips && DEBUG_AVAILABILITY_GROUPS.includes(group)) return group;
  if (TEST_AVAILABILITY_GROUPS.has(group)) return "test";
  if (group === "earlyAccess") return "early";
  if (group === "upgradeable" || group === "superShip" || group === "start") return "tech";
  return "premium";
}

function availabilityLabel(value) {
  if (value === "tech") return t("availability.techTree", "Tech tree");
  if (value === "premium") return t("availability.premium", "Premium");
  if (value === "early") return t("availability.earlyAccess", "Early access");
  if (value === "test") return t("availability.test", "Test");
  if (value === "event") return t("availability.event", "Event");
  if (value === "disabled") return t("availability.disabled", "Disabled");
  if (value === "preserved") return t("availability.preserved", "Preserved");
  if (value === "coopOnly") return t("availability.coopOnly", "Co-op only");
  if (value === "clan") return t("availability.clan", "Clan");
  if (value === "demoWithoutStats") return t("availability.demoWithoutStats", "Demo without stats");
  if (value === "demoWithoutStatsPrem") return t("availability.demoWithoutStatsPrem", "Demo without stats premium");
  return uiLabel(value);
}

function enrichShip(ship) {
  const displayName = ship.identity.display_name || friendlyFallbackName(ship.identity.name);
  const fullDisplayName = ship.identity.full_name || displayName;
  const nationLabel = ship.identity.nation_label || ship.identity.nation;
  const roleLabel = normalizeRoleLabel(ship.identity.role_label || ship.identity.role);
  const shipClass = normalizeClass(ship.identity.class);
  return {
    ...ship,
    displayName,
    fullDisplayName,
    nationLabel,
    roleLabel,
    shipClass,
    availability: detectAvailability(ship),
    techTree: {
      nextCodes: ship.tech_tree?.next_ship_codes || [],
    },
    searchable: [
      displayName,
      fullDisplayName,
      ship.identity.code,
      ship.identity.name,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase(),
  };
}

function shipViewWithProfile(ship, profile) {
  const resolvedProfile = profile || {};
  const mergeConsumableSlots = (baseSlots, profileSlots) => {
    const baseList = Array.isArray(baseSlots) ? baseSlots : [];
    const profileList = Array.isArray(profileSlots) ? profileSlots : [];
    if (!profileList.length) return baseList;
    return profileList.map((slot, slotIndex) => {
      const baseSlot = baseList.find((candidate) => (candidate?.slot ?? slotIndex) === (slot?.slot ?? slotIndex)) || baseList[slotIndex] || {};
      const baseChoices = Array.isArray(baseSlot?.choices) ? baseSlot.choices : [];
      const profileChoices = Array.isArray(slot?.choices) ? slot.choices : [];
      return {
        ...baseSlot,
        ...slot,
        choices: profileChoices.map((choice, choiceIndex) => {
          const baseChoice = baseChoices.find((candidate) => candidate?.id === choice?.id) || baseChoices[choiceIndex] || {};
          return { ...baseChoice, ...choice };
        }),
      };
    });
  };
  const mergeWeapons = (baseWeapons, profileWeapons) => {
    const baseList = Array.isArray(baseWeapons) ? baseWeapons : [];
    const profileList = Array.isArray(profileWeapons) ? profileWeapons : [];
    if (!profileList.length) return baseList;
    return profileList.map((weapon, weaponIndex) => {
      const baseWeapon = baseList[weaponIndex] || baseList.find((candidate) => candidate?.projectile?.id === weapon?.projectile?.id) || {};
      return {
        ...baseWeapon,
        ...weapon,
        projectile: {
          ...(baseWeapon?.projectile || {}),
          ...(weapon?.projectile || {}),
        },
      };
    });
  };
  const mergeAircraft = (baseAircraft, profileAircraft) => {
    const baseEntry = baseAircraft || {};
    const profileEntry = profileAircraft || {};
    if (!profileAircraft) return baseEntry;
    return {
      ...baseEntry,
      ...profileEntry,
      weapons: mergeWeapons(baseEntry?.weapons, profileEntry?.weapons),
      consumables: mergeConsumableSlots(baseEntry?.consumables, profileEntry?.consumables),
      variants: (() => {
        const baseVariants = Array.isArray(baseEntry?.variants) ? baseEntry.variants : [];
        const profileVariants = Array.isArray(profileEntry?.variants) ? profileEntry.variants : [];
        if (!profileVariants.length) return baseVariants;
        return profileVariants.map((variant, index) => mergeAircraft(baseVariants[index], variant));
      })(),
    };
  };
  const mergeAircraftSquadrons = (baseSquadrons, profileSquadrons) => {
    const baseMap = baseSquadrons || {};
    const profileMap = profileSquadrons || {};
    if (!profileSquadrons) return baseMap;
    const result = { ...baseMap };
    Object.entries(profileMap).forEach(([key, squadron]) => {
      result[key] = mergeAircraft(baseMap?.[key], squadron);
    });
    return result;
  };
  const mergeAirSupport = (baseAirSupport, profileAirSupport) => {
    const baseList = Array.isArray(baseAirSupport) ? baseAirSupport : [];
    const profileList = Array.isArray(profileAirSupport) ? profileAirSupport : [];
    if (!profileList.length) return baseList;
    return profileList.map((support, index) => {
      const baseSupport = baseList[index] || {};
      return {
        ...baseSupport,
        ...support,
        plane: mergeAircraft(baseSupport?.plane, support?.plane),
      };
    });
  };
  return {
    ...ship,
    __resolvedProfile: true,
    survivability: resolvedProfile.survivability || ship.survivability,
    mobility: resolvedProfile.mobility || ship.mobility,
    artillery: resolvedProfile.artillery || ship.artillery,
    torpedoes: resolvedProfile.torpedoes || ship.torpedoes,
    anti_air: resolvedProfile.anti_air || ship.anti_air,
    air_support: mergeAirSupport(ship.air_support, resolvedProfile.air_support),
    aircraft_squadrons: mergeAircraftSquadrons(ship.aircraft_squadrons, resolvedProfile.aircraft_squadrons),
    diving: resolvedProfile.diving || ship.diving,
    sonar: resolvedProfile.sonar || ship.sonar,
    combat_instruction: resolvedProfile.combat_instruction || ship.combat_instruction,
    active_components: resolvedProfile.active_components || ship.active_components,
  };
}

function shipConfigView(ship) {
  if (ship?.__resolvedProfile) return ship;
  const profile = state.activeConfig === "stock" ? ship?.profiles?.stock : null;
  return shipViewWithProfile(ship, profile || {});
}

function resolvedShipView(ship) {
  return ship?.__resolvedProfile ? ship : shipConfigView(ship);
}

function modalShipView(ship) {
  if (state.activeModalShipCode === ship?.identity?.code && state.modalProfileOverride) {
    return shipViewWithProfile(ship, state.modalProfileOverride);
  }
  return shipConfigView(ship);
}

function getNations() {
  const preferredOrder = [
    "Russia",
    "Japan",
    "USA",
    "Germany",
    "UnitedKingdom",
    "France",
    "Italy",
    "PanAsia",
    "Europe",
    "Netherlands",
    "PanAmerica",
    "Spain",
  ];
  const orderIndex = new Map(preferredOrder.map((value, index) => [value, index]));
  return [...new Set(state.ships.map((ship) => ship.identity.nation).filter(Boolean))]
    .sort((left, right) => {
      if (left === "Events" && right !== "Events") return 1;
      if (right === "Events" && left !== "Events") return -1;
      const leftRank = orderIndex.has(left) ? orderIndex.get(left) : Number.MAX_SAFE_INTEGER;
      const rightRank = orderIndex.has(right) ? orderIndex.get(right) : Number.MAX_SAFE_INTEGER;
      if (leftRank !== rightRank) return leftRank - rightRank;
      const a = uiLabel(state.ships.find((ship) => ship.identity.nation === left)?.nationLabel || left);
      const b = uiLabel(state.ships.find((ship) => ship.identity.nation === right)?.nationLabel || right);
      return a.localeCompare(b);
    });
}

function getClasses() {
  const found = [...new Set(state.ships.map((ship) => ship.shipClass).filter((value) => value && !EXCLUDED_SHIP_CLASSES.has(value)))];
  return [...CLASS_ORDER.filter((item) => found.includes(item)), ...found.filter((item) => !CLASS_ORDER.includes(item))];
}

function shipMatchesSearch(ship, search) {
  return !search || ship.searchable.includes(search);
}

function shipHardpointKeys(ship) {
  return [
    ship?.identity?.code,
    ship?.identity?.name,
    ship?.identity?.internal_name,
  ].filter(Boolean);
}

function externalHardpointFor(ship, kind, slot) {
  if (!slot) return null;
  const store = state.hardpoints?.[kind] || {};
  for (const key of shipHardpointKeys(ship)) {
    const record = store[key];
    if (record?.[slot]) return record[slot];
  }
  return null;
}

function withExternalHardpoints(ship, modules, kind) {
  const source = modules || [];
  const decorated = source.map((module) => {
    const hardpoint = externalHardpointFor(ship, kind, module?.slot);
    return hardpoint ? { ...module, hardpoint } : module;
  });
  const slottedCount = source.filter((module) => module?.slot).length;
  const hardpointCount = decorated.filter((module) => module?.hardpoint).length;
  if (hardpointCount > 0 && hardpointCount < slottedCount) {
    return source;
  }
  return decorated;
}

function allExternalHardpointsForShip(ship) {
  const points = [];
  const seen = new Set();
  const keys = shipHardpointKeys(ship);
  ["main", "secondary", "torpedo"].forEach((kind) => {
    const store = state.hardpoints?.[kind] || {};
    for (const key of keys) {
      const record = store[key];
      if (!record || typeof record !== "object") continue;
      Object.entries(record).forEach(([slot, point]) => {
        const x = Number(point?.x);
        const y = Number(point?.y);
        const z = Number(point?.z);
        if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) return;
        const id = `${kind}:${slot}`;
        if (seen.has(id)) return;
        seen.add(id);
        points.push({ kind, slot, x, y, z });
      });
      break;
    }
  });
  return points;
}

function routeDataServer() {
  return routeDataServerFromSearch(window.location.search);
}

function routeDebugShips() {
  return routeDebugShipsFromSearch(window.location.search);
}

function appendDataServerParam(query) {
  if (state.dataServer !== "live") query.set("server", state.dataServer);
}

function appendLanguageParam(query) {
  if (state.language !== DEFAULT_LANGUAGE) query.set("lang", state.language);
}

function appendDebugShipsParam(query) {
  if (state.debugShips) query.set("debugShips", "1");
}

function applyDataServerFromLocation() {
  state.dataServer = routeDataServer();
  if (els.dataServer) els.dataServer.value = state.dataServer;
}

function applyLanguageFromLocation() {
  state.language = routeLanguage();
  if (els.uiLanguage) els.uiLanguage.value = state.language;
}

function applyDebugShipsFromLocation() {
  state.debugShips = routeDebugShips();
  renderSettingsControls();
}

function selectedShipsRouteValue() {
  return selectedShips().map((ship) => shipRouteCode(ship)).join("");
}

function shipsFromRouteValue(value) {
  return routeShipsFromValue(state.ships, value);
}

function shipFromRouteSegment(value) {
  return routeShipFromSegment(state.ships, value);
}

function shipSharePath(shipOrCode, options = {}) {
  const code = typeof shipOrCode === "string" ? shipOrCode : shipOrCode?.identity?.code;
  const ship = state.ships.find((item) => item.identity.code === code) || null;
  const shareCode = ship?.identity?.code || code || "";
  const query = new URLSearchParams();
  appendDataServerParam(query);
  appendLanguageParam(query);
  appendDebugShipsParam(query);
  if (options.compareCode) query.set("compare", options.compareCode);
  if (options.compareMode) query.set("compareMode", "1");
  const suffix = query.toString();
  return `/ship/${encodeURIComponent(shareCode)}${suffix ? `?${suffix}` : ""}`;
}

function modalSharePath(primaryCode = state.activeModalShipCode) {
  const compareCode = state.modalCompare.enabled ? state.modalCompare.secondaryCode : null;
  return shipSharePath(primaryCode, {
    compareCode,
    compareMode: compareCode ? modalCompareMode() : null,
  });
}

function syncActiveModalShareRoute() {
  if (!state.routeReady || state.applyingRoute || !state.activeModalShipCode) return;
  if (!window.location.pathname.toLowerCase().startsWith("/ship/")) return;
  const next = modalSharePath(state.activeModalShipCode);
  const current = `${window.location.pathname}${window.location.search}`;
  if (next !== current) window.history.replaceState({}, "", next);
}

function currentRoutePath() {
  if (state.activeMainTab === "nation") {
    const query = new URLSearchParams();
    appendDataServerParam(query);
    appendLanguageParam(query);
    appendDebugShipsParam(query);
    query.set("N", nationRouteCode(state.activeNation));
    return `/nations?${query.toString()}`;
  }
  if (state.activeMainTab === "parameters") {
    const query = new URLSearchParams();
    appendDataServerParam(query);
    appendLanguageParam(query);
    appendDebugShipsParam(query);
    query.set("m", state.pickJoinMode === "and" ? "A" : state.activePickMode === "select" ? "L" : "F");
    if (state.pickJoinMode === "and" || state.activePickMode === "select") {
      const selected = selectedShipsRouteValue();
      if (selected) query.set("s", selected);
    }
    query.set("p", parameterRouteCode(state.activeParameterGroup));
    return `/params?${query.toString()}`;
  }
  const query = new URLSearchParams();
  appendDataServerParam(query);
  appendLanguageParam(query);
  appendDebugShipsParam(query);
  return query.toString() ? `/?${query.toString()}` : "/";
}

function syncRoute(options = {}) {
  if (!state.routeReady || state.applyingRoute) return;
  const next = currentRoutePath();
  const current = `${window.location.pathname}${window.location.search}`;
  if (next === current) return;
  const method = options.replace ? "replaceState" : "pushState";
  window.history[method]({}, "", next);
}

function renderActiveMainTab(options = {}) {
  if (state.activeMainTab === "home") {
    renderHomeView();
    return;
  }
  if (state.activeMainTab === "nation") {
    renderNationPicker();
    renderNationView({ syncRoute: options.syncRoute });
    return;
  }
  if (state.activeMainTab === "parameters") {
    renderPickMode();
    renderFilterPane();
    renderSelectPane();
    refreshParameterView({ syncRoute: options.syncRoute });
  }
}

function setMainTab(tab, options = {}) {
  const resolvedTab = els.views[tab] ? tab : "home";
  state.activeMainTab = resolvedTab;
  document.documentElement.dataset.activeTab = resolvedTab;
  els.tabButtons.forEach((button) => button.classList.toggle("active", button.dataset.tab === resolvedTab));
  Object.entries(els.views).forEach(([name, node]) => node.classList.toggle("active", name === resolvedTab));
  if (options.render !== false) {
    renderActiveMainTab({ syncRoute: false });
  }
  if (options.updateRoute !== false) {
    syncRoute({ replace: options.replace ?? false });
  }
  configureAdSensePlacements();
}

function applyRouteFromLocation() {
  const path = window.location.pathname.toLowerCase();
  const params = new URLSearchParams(window.location.search);
  const nations = getNations();
  state.sharedShipCode = null;
  state.sharedCompare = null;

  if (path.startsWith("/ship/")) {
    const segment = window.location.pathname.split("/").filter(Boolean)[1] || "";
    const ship = shipFromRouteSegment(segment);
    state.sharedShipCode = ship?.identity?.code || segment || null;
    const compareShip = shipFromRouteSegment(params.get("compare") || params.get("c") || "");
    if (compareShip && compareShip.identity.code !== state.sharedShipCode) {
      state.sharedCompare = {
        enabled: true,
        mode: "inline",
        secondaryCode: compareShip.identity.code,
      };
    }
    state.activeMainTab = "home";
    return;
  }

  if (path === "/nations") {
    state.activeMainTab = "nation";
    const routedNation = nationFromRouteCode(params.get("N"));
    state.activeNation = routedNation && nations.includes(routedNation)
      ? routedNation
      : state.activeNation || nations[0] || null;
    return;
  }

  if (path === "/params") {
    state.activeMainTab = "parameters";
    const mode = `${params.get("m") || ""}`.toUpperCase();
    state.pickJoinMode = mode === "A" ? "and" : "or";
    state.activePickMode = mode === "L" || (mode !== "A" && params.has("s")) ? "select" : "filter";
    if (mode === "A" || state.activePickMode === "select" || params.has("s")) {
      state.selectedCodes = new Set(shipsFromRouteValue(params.get("s")));
    }
    const parameterLabel = parameterFromRouteCode(params.get("p"));
    if (parameterLabel) state.activeParameterGroup = parameterLabel;
    return;
  }

  state.activeMainTab = "home";
}

function applySharedShipFromRoute() {
  if (!state.sharedShipCode) return;
  const ship = shipFromRouteSegment(state.sharedShipCode);
  if (!ship) return;
  openShipModal(ship.identity.code, { updateRoute: false, fromRoute: true, compareState: state.sharedCompare });
}

function renderAppState() {
  if (els.dataServer) els.dataServer.value = state.dataServer;
  if (els.uiLanguage) els.uiLanguage.value = state.language;
  applyStaticTranslations();
  renderHomeView();
  setMainTab(state.activeMainTab, { updateRoute: false });
  if (!state.sharedShipCode && state.activeModalShipCode && !window.location.pathname.toLowerCase().startsWith("/ship/")) {
    closeModal();
  }
  applySharedShipFromRoute();
}

function renderNationPicker() {
  els.nationPicker.innerHTML = "";
  getNations().forEach((nation) => {
    const wrap = document.createElement("label");
    wrap.className = "radio-pill";
    const ship = state.ships.find((item) => item.identity.nation === nation);
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "nation-picker";
    input.value = nation;
    input.checked = state.activeNation === nation;
    const label = document.createElement("span");
    label.textContent = uiLabel(ship?.nationLabel || nation);
    input.addEventListener("change", () => {
      state.activeNation = nation;
      renderNationPicker();
      renderNationView();
    });
    wrap.append(input, document.createTextNode(" "), label);
    els.nationPicker.appendChild(wrap);
  });
}

function modalComparePickState(slot) {
  return {
    kind: "compare",
    slot,
    primaryCode: state.activeModalShipCode,
    secondaryCode: state.modalCompare.secondaryCode,
    mode: modalCompareMode(),
  };
}

function beginModalComparePick(slot) {
  if (!state.activeModalShipCode) return;
  state.modalComparePick = modalComparePickState(slot === "primary" ? "primary" : "secondary");
  els.modal.classList.add("hidden");
  els.modal.classList.remove("modal-compare-active");
  els.modal.classList.remove("modal-compare-separate-active");
  state.activeModalShipCode = null;
  setMainTab("nation", { replace: true });
}

function beginShellChartComparePick(groupLabel) {
  if (!state.activeModalShipCode || !groupLabel) return;
  state.modalComparePick = {
    kind: "chart",
    groupLabel,
    primaryCode: state.activeModalShipCode,
    activeTab: state.activeModalTab,
    chartCompareCodes: [...state.modalChartCompareCodes],
  };
  els.modal.classList.add("hidden");
  els.modal.classList.remove("modal-compare-active");
  els.modal.classList.remove("modal-compare-separate-active");
  state.activeModalShipCode = null;
  setMainTab("nation", { replace: true });
}

function cancelModalComparePick() {
  const pick = state.modalComparePick;
  state.modalComparePick = null;
  renderComparePickBanner();
  if (!pick?.primaryCode) return;
  if (pick.kind === "chart") {
    openShipModal(pick.primaryCode, { activeTab: pick.activeTab, chartCompareCodes: pick.chartCompareCodes || [] });
    return;
  }
  openShipModal(pick.primaryCode, {
    compareState: {
      enabled: true,
      mode: pick.mode || "inline",
      secondaryCode: pick.secondaryCode || null,
    },
  });
}

function completeModalComparePick(code) {
  const pick = state.modalComparePick;
  if (!pick || !code) return false;
  if (pick.kind === "chart") {
    const primaryShip = state.ships.find((ship) => ship.identity.code === pick.primaryCode);
    const pickedShip = state.ships.find((ship) => ship.identity.code === code);
    const pickedView = pickedShip ? modalShipView(pickedShip) : null;
    state.modalComparePick = null;
    const nextChartCompareCodes = [...(pick.chartCompareCodes || [])];
    if (
      primaryShip
      && pickedShip
      && code !== pick.primaryCode
      && projectileForShellChart(pickedView, pick.groupLabel)
      && !nextChartCompareCodes.includes(code)
    ) {
      nextChartCompareCodes.push(code);
    }
    openShipModal(pick.primaryCode, { activeTab: pick.activeTab, chartCompareCodes: nextChartCompareCodes });
    return true;
  }
  let primaryCode = pick.primaryCode;
  let secondaryCode = pick.secondaryCode || null;
  if (pick.slot === "primary") {
    primaryCode = code;
    if (secondaryCode === primaryCode) secondaryCode = null;
  } else {
    secondaryCode = code === primaryCode ? null : code;
  }
  state.modalComparePick = null;
  openShipModal(primaryCode, {
    compareState: {
      enabled: true,
      mode: pick.mode || "inline",
      secondaryCode,
    },
  });
  return true;
}

function handleShipCardOpen(code) {
  if (state.modalComparePick && completeModalComparePick(code)) return;
  openShipModal(code);
}

function renderComparePickBanner() {
  let banner = document.getElementById("compare-pick-banner");
  if (!state.modalComparePick) {
    banner?.remove();
    document.body.classList.remove("compare-pick-active");
    return;
  }
  document.body.classList.add("compare-pick-active");
  if (!banner) {
    banner = document.createElement("div");
    banner.id = "compare-pick-banner";
    banner.className = "compare-pick-banner";
    els.views.nation.insertBefore(banner, els.views.nation.firstElementChild);
  }
  const pick = state.modalComparePick;
  const primaryShip = state.ships.find((ship) => ship.identity.code === pick.primaryCode);
  const isChartPick = pick.kind === "chart";
  const slotLabel = isChartPick
    ? t("modal.chartCompare", "Chart compare")
    : pick.slot === "primary"
    ? t("modal.comparePrimaryTarget", "Primary ship")
    : t("modal.compareTarget", "Compare with");
  banner.innerHTML = `
    <div>
      <strong>${escapeHtml(isChartPick ? t("modal.chartComparePickNotice", "Select a ship to add to the chart") : t("modal.comparePickNotice", "Select a ship for compare"))}</strong>
      <span>${escapeHtml(slotLabel)}${primaryShip ? `: ${shipModalDisplayName(primaryShip)}` : ""}</span>
    </div>
    <button type="button" data-modal-compare-pick-cancel>${escapeHtml(t("common.cancel", "Cancel"))}</button>
  `;
  banner.querySelector("[data-modal-compare-pick-cancel]")?.addEventListener("click", cancelModalComparePick);
}

function nationShips(nation, availability) {
  const nameComparator = ShipSorting.compareShipNames || ((a, b) => a.displayName.localeCompare(b.displayName));
  const premiumComparator = ShipSorting.comparePremiumShipCards || nameComparator;
  return state.ships
    .filter((ship) => ship.identity.nation === nation && ship.availability === availability)
    .sort((a, b) => (a.identity.tier - b.identity.tier) || (availability === "premium" ? premiumComparator(a, b) : nameComparator(a, b)));
}

function availabilityFilterValues() {
  if (!state.debugShips) return [...GROUP_FILTERS];
  const present = new Set(state.ships.map((ship) => ship.availability));
  return [
    ...GROUP_FILTERS,
    ...DEBUG_AVAILABILITY_GROUPS.filter((value) => present.has(value)),
  ];
}

function debugAvailabilityValuesForNation(nation) {
  if (!state.debugShips || !nation) return [];
  return DEBUG_AVAILABILITY_GROUPS.filter((value) => nationShips(nation, value).length > 0);
}

function slugForAvailability(value) {
  return `${value || ""}`
    .replace(/([a-z0-9])([A-Z])/g, "$1-$2")
    .replace(/[^A-Za-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .toLowerCase() || "group";
}

function nationSectionIdForJump(value) {
  const sectionIdByJump = {
    premium: "premium-section",
    early: "early-access-section",
    test: "test-section",
  };
  return sectionIdByJump[value] || `debug-${slugForAvailability(value)}-section`;
}

function shipModuleOptionsFlat(ship) {
  return (ship?.module_options || []).flatMap((group) => group?.options || []);
}

function shipResearchXp(ship) {
  const explicit = Number(ship?.tech_tree?.research_xp);
  if (Number.isFinite(explicit) && explicit > 0) return explicit;

  const hullOptions = shipModuleOptionsFlat(ship)
    .filter((option) => option?.category === "Hull")
    .sort((a, b) => (a.depth ?? 0) - (b.depth ?? 0));
  const stockHullCost = Number(hullOptions[0]?.cost_xp);
  if (Number.isFinite(stockHullCost) && stockHullCost > 0) return stockHullCost;

  const stockOptionCost = Number(shipModuleOptionsFlat(ship).find((option) => (option?.depth ?? 0) === 0)?.cost_xp);
  return Number.isFinite(stockOptionCost) && stockOptionCost > 0 ? stockOptionCost : 0;
}

function shipPurchaseCredits(ship) {
  const explicit = Number(ship?.tech_tree?.purchase_cr);
  if (Number.isFinite(explicit) && explicit > 0) return explicit;
  return null;
}

function moduleUpgradeCostTotal(ship, fieldName) {
  return shipModuleOptionsFlat(ship)
    .filter((option) => (option?.depth ?? 0) > 0)
    .map((option) => Number(option?.[fieldName]))
    .filter((value) => Number.isFinite(value) && value > 0)
    .reduce((sum, value) => sum + value, 0);
}

function shipFullyUpgradedResearchXp(ship) {
  return shipResearchXp(ship) + moduleUpgradeCostTotal(ship, "cost_xp");
}

function shipFullyUpgradedPurchaseCredits(ship) {
  const purchaseCredits = shipPurchaseCredits(ship);
  if (purchaseCredits == null) return null;
  return purchaseCredits + moduleUpgradeCostTotal(ship, "cost_cr");
}

function shipResearchTooltip(ship) {
  if (ship?.availability !== "tech") return "";
  const researchXp = shipResearchXp(ship);
  const fullResearchXp = shipFullyUpgradedResearchXp(ship);
  const purchaseCredits = shipPurchaseCredits(ship);
  const fullPurchaseCredits = shipFullyUpgradedPurchaseCredits(ship);
  const rows = [];
  let hasUpgradeCosts = false;
  if (researchXp > 0) {
    rows.push(`
      <div class="ship-research-tooltip-row">
        <span>${escapeHtml(t("research.tooltip.researchXp", "Research XP:"))}</span>
        <strong>${formatValue(researchXp, { digits: 0, grouping: true })}</strong>
      </div>
    `);
    if (fullResearchXp > researchXp) {
      hasUpgradeCosts = true;
      rows.push(`
      <div class="ship-research-tooltip-row is-sub">
        <span>&#9492; ${escapeHtml(t("research.tooltip.fullyUpgraded", "Fully upgraded:"))}</span>
        <strong>${formatValue(fullResearchXp, { digits: 0, grouping: true })}</strong>
      </div>
    `);
    }
  }
  if (purchaseCredits != null) {
    rows.push(`
      <div class="ship-research-tooltip-row">
        <span>${escapeHtml(t("research.tooltip.purchaseCredits", "Purchase credits:"))}</span>
        <strong>${formatValue(purchaseCredits, { digits: 0, grouping: true })}</strong>
      </div>
    `);
    if (fullPurchaseCredits != null && fullPurchaseCredits > purchaseCredits) {
      hasUpgradeCosts = true;
      rows.push(`
      <div class="ship-research-tooltip-row is-sub">
        <span>&#9492; ${escapeHtml(t("research.tooltip.fullyUpgraded", "Fully upgraded:"))}</span>
        <strong>${formatValue(fullPurchaseCredits, { digits: 0, grouping: true })}</strong>
      </div>
    `);
    }
  }
  if (rows.length && !hasUpgradeCosts) {
    rows.push(`
      <div class="ship-research-tooltip-row is-sub">
        <span>${escapeHtml(t("research.tooltip.noModuleUpgrades", "No module upgrades"))}</span>
      </div>
    `);
  }
  if (!rows.length) return "";
  return `
    <div class="ship-research-card">
      <div class="ship-research-tooltip-title">${escapeHtml(ship.displayName)}</div>
      <div class="ship-research-tooltip-divider"></div>
      <div class="ship-research-tooltip-body">${rows.join("")}</div>
    </div>
  `;
}

function shipRefCode(ref) {
  return typeof ref === "string" ? ref.split("_", 1)[0] : "";
}

function optionUnlocksShip(option, childCode) {
  return (option?.next_ship_refs || []).some((ref) => shipRefCode(ref) === childCode);
}

function unlockModuleXp(parent, childCode) {
  const unlockCosts = shipModuleOptionsFlat(parent)
    .filter((option) => optionUnlocksShip(option, childCode))
    .map((option) => Number(option.cost_xp))
    .filter((value) => Number.isFinite(value) && value > 0);
  return unlockCosts.length ? Math.min(...unlockCosts) : 0;
}

function researchEdgeXp(parent, child) {
  return unlockModuleXp(parent, child.identity.code) + shipResearchXp(child);
}

function buildResearchGraph(ships) {
  const shipMap = new Map(ships.map((ship) => [ship.identity.code, ship]));
  const adjacency = new Map(ships.map((ship) => [ship.identity.code, []]));
  ships.forEach((ship) => {
    (ship.techTree.nextCodes || []).forEach((childCode) => {
      const child = shipMap.get(childCode);
      if (!child) return;
      adjacency.get(ship.identity.code).push({
        code: childCode,
        xp: researchEdgeXp(ship, child),
      });
    });
  });
  return { shipMap, adjacency };
}

function findResearchRoute(ships, startCode, targetCode) {
  if (!startCode || !targetCode) return null;
  const { shipMap, adjacency } = buildResearchGraph(ships);
  if (!shipMap.has(startCode) || !shipMap.has(targetCode)) return null;
  if (startCode === targetCode) return { totalXp: 0, pathCodes: [startCode] };

  const distance = new Map();
  const previous = new Map();
  const pending = new Set(shipMap.keys());
  shipMap.forEach((_, code) => distance.set(code, Number.POSITIVE_INFINITY));
  distance.set(startCode, 0);

  while (pending.size) {
    let current = null;
    let best = Number.POSITIVE_INFINITY;
    pending.forEach((code) => {
      const value = distance.get(code);
      if (value < best) {
        best = value;
        current = code;
      }
    });
    if (current == null || best === Number.POSITIVE_INFINITY) break;
    pending.delete(current);
    if (current === targetCode) break;

    (adjacency.get(current) || []).forEach((edge) => {
      if (!pending.has(edge.code)) return;
      const nextDistance = best + edge.xp;
      if (nextDistance < distance.get(edge.code)) {
        distance.set(edge.code, nextDistance);
        previous.set(edge.code, current);
      }
    });
  }

  const totalXp = distance.get(targetCode);
  if (!Number.isFinite(totalXp)) return null;

  const pathCodes = [];
  let cursor = targetCode;
  while (cursor) {
    pathCodes.unshift(cursor);
    if (cursor === startCode) break;
    cursor = previous.get(cursor);
  }
  return pathCodes[0] === startCode ? { totalXp, pathCodes } : null;
}

function reachableResearchCodes(ships, startCode) {
  if (!startCode) return null;
  const { shipMap, adjacency } = buildResearchGraph(ships);
  if (!shipMap.has(startCode)) return new Set();
  const reachable = new Set();
  const pending = [startCode];

  while (pending.length) {
    const current = pending.shift();
    (adjacency.get(current) || []).forEach((edge) => {
      if (reachable.has(edge.code)) return;
      reachable.add(edge.code);
      pending.push(edge.code);
    });
  }

  return reachable;
}

function normalizeResearchSelection(ships) {
  const codes = new Set(ships.map((ship) => ship.identity.code));
  if (!codes.has(state.researchStartCode)) state.researchStartCode = null;
  if (!codes.has(state.researchTargetCode)) state.researchTargetCode = null;
  const reachableTargets = reachableResearchCodes(ships, state.researchStartCode);
  if (reachableTargets && state.researchTargetCode && !reachableTargets.has(state.researchTargetCode)) {
    state.researchTargetCode = null;
  }
}

function researchShipOptionLabel(ship) {
  return `${toRomanTier(ship.identity.tier)} ${ship.displayName}`;
}

function researchPathShipLink(ship) {
  if (!ship) return "";
  return `
    <button type="button" class="research-path-ship" data-open-ship="${escapeHtml(ship.identity.code)}">
      <span>${escapeHtml(ship.displayName)}</span>
      ${shipResearchTooltip(ship)}
    </button>
  `;
}

function renderResearchCalculator(ships) {
  if (!els.researchCalculator) return;
  normalizeResearchSelection(ships);
  if (!ships.length) {
    els.researchCalculator.innerHTML = "";
    return;
  }

  const orderedShips = [...ships].sort((a, b) => (a.identity.tier - b.identity.tier) || a.displayName.localeCompare(b.displayName));
  const startCode = state.researchStartCode || "";
  const reachableTargets = reachableResearchCodes(ships, startCode);
  const targetShips = reachableTargets
    ? orderedShips.filter((ship) => reachableTargets.has(ship.identity.code))
    : orderedShips;
  if (state.researchTargetCode && reachableTargets && !reachableTargets.has(state.researchTargetCode)) {
    state.researchTargetCode = null;
  }
  const targetCode = state.researchTargetCode || "";
  const route = findResearchRoute(ships, startCode, targetCode);
  const shipMap = new Map(ships.map((ship) => [ship.identity.code, ship]));
  const selectShipLabel = escapeHtml(t("research.selectShip", "Select ship"));
  const startOptionsHtml = [
    `<option value="">${selectShipLabel}</option>`,
    ...orderedShips.map((ship) => `<option value="${escapeHtml(ship.identity.code)}">${escapeHtml(researchShipOptionLabel(ship))}</option>`),
  ].join("");
  const targetOptionsHtml = [
    `<option value="">${selectShipLabel}</option>`,
    ...targetShips.map((ship) => `<option value="${escapeHtml(ship.identity.code)}">${escapeHtml(researchShipOptionLabel(ship))}</option>`),
  ].join("");
  let resultHtml = `<span class="research-calc-muted">${escapeHtml(t("research.selectHint", "Select two tech-tree ships, or Ctrl-click tree cards."))}</span>`;

  if (startCode && targetCode) {
    if (route) {
      const pathHtml = route.pathCodes
        .map((code) => researchPathShipLink(shipMap.get(code)))
        .filter(Boolean)
        .join(`<span class="research-path-arrow">&rarr;</span>`);
      resultHtml = `
        <strong>${formatValue(route.totalXp, { digits: 0, grouping: true })} XP</strong>
        <span class="research-path">${pathHtml}</span>
      `;
    } else {
      resultHtml = `<span class="research-calc-warning">${escapeHtml(t("research.noPath", "No research path between selected ships."))}</span>`;
    }
  }

  els.researchCalculator.innerHTML = `
    <div class="research-calc-card">
      <div class="research-calc-title">${escapeHtml(t("research.title", "Research XP calculator"))}</div>
      <label class="research-calc-field">
        <span>${escapeHtml(t("research.from", "From"))}</span>
        <select id="research-start-select">${startOptionsHtml}</select>
      </label>
      <label class="research-calc-field">
        <span>${escapeHtml(t("research.to", "To"))}</span>
        <select id="research-target-select">${targetOptionsHtml}</select>
      </label>
      <div class="research-calc-result">${resultHtml}</div>
    </div>
  `;

  const startSelect = document.getElementById("research-start-select");
  const targetSelect = document.getElementById("research-target-select");
  if (startSelect) {
    startSelect.value = startCode;
    startSelect.addEventListener("change", () => {
      state.researchStartCode = startSelect.value || null;
      renderNationView();
    });
  }
  if (targetSelect) {
    targetSelect.value = targetCode;
    targetSelect.addEventListener("change", () => {
      state.researchTargetCode = targetSelect.value || null;
      renderNationView();
    });
  }
  els.researchCalculator.querySelectorAll("[data-open-ship]").forEach((button) => {
    button.addEventListener("click", () => handleShipCardOpen(button.dataset.openShip));
  });
}

function currentResearchRoute(ships) {
  return findResearchRoute(ships, state.researchStartCode, state.researchTargetCode);
}

function shipCardImage(ship, className = "ship-preview") {
  const classAttr = escapeHtml(className);
  const src = escapeHtml(ship.assets?.preview || "");
  const alt = escapeHtml(ship.displayName);
  return ship.assets?.preview
    ? `<img class="${classAttr}" src="${src}" alt="${alt}" loading="lazy" decoding="async">`
    : `<div class="${classAttr} ship-preview-fallback">${escapeHtml(localizedDisplayClass(ship))}</div>`;
}

function createShipNode(ship) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "ship-node";
  const chartPickAllowed = state.modalComparePick?.kind === "chart"
    ? projectileForShellChart(modalShipView(ship), state.modalComparePick.groupLabel)
    : true;
  if (state.modalComparePick && ship.identity.code !== state.modalComparePick.primaryCode && chartPickAllowed) {
    button.classList.add("is-compare-pick-target");
  }
  button.dataset.openShip = ship.identity.code;
  button.dataset.shipName = ship.displayName;
  button.innerHTML = `
    ${shipCardImage(ship)}
    <div class="ship-name">${escapeHtml(ship.displayName)}</div>
    ${shipResearchTooltip(ship)}
  `;
  button.addEventListener("click", () => handleShipCardOpen(ship.identity.code));
  return button;
}

function renderShipBlock(host, ships, emptyText, orientation = "rows", shipComparator = null) {
  host.innerHTML = "";
  if (!ships.length) {
    host.innerHTML = `<div class="empty-panel">${escapeHtml(emptyText)}</div>`;
    return;
  }
  const comparator = shipComparator || ShipSorting.compareShipNames || ((a, b) => a.displayName.localeCompare(b.displayName));
  const byTier = new Map();
  ships.forEach((ship) => {
    const tier = ship.identity.tier || 0;
    if (!byTier.has(tier)) byTier.set(tier, []);
    byTier.get(tier).push(ship);
  });

  host.classList.toggle("tier-columns-layout", orientation === "columns");
  host.classList.toggle("tier-rows-layout", orientation === "rows");

  [...byTier.keys()].sort((a, b) => a - b).forEach((tier) => {
    const row = document.createElement("div");
    row.className = `tier-group ${orientation === "columns" ? "tier-group-column" : "tier-group-row"}`;
    const tierLabel = document.createElement("div");
    tierLabel.className = "tier-group-label";
    tierLabel.textContent = toRomanTier(tier);
    const grid = document.createElement("div");
    grid.className = `ship-grid ${orientation === "columns" ? "ship-grid-column" : "ship-grid-row"}`;
    byTier.get(tier)
      .sort(comparator)
      .forEach((ship) => grid.appendChild(createShipNode(ship)));
    row.append(tierLabel, grid);
    host.appendChild(row);
  });
}

function renderDebugNationJumps(values) {
  if (!els.debugJumpLinks) return;
  els.debugJumpLinks.innerHTML = "";
  values.forEach((value) => {
    const button = document.createElement("button");
    button.className = `inline-link jump-pill debug-jump debug-jump-${slugForAvailability(value)}`;
    button.type = "button";
    button.dataset.jump = value;
    button.textContent = availabilityLabel(value);
    els.debugJumpLinks.appendChild(button);
  });
}

function renderDebugNationSections(values) {
  if (!els.debugShipSections) return;
  els.debugShipSections.innerHTML = "";
  values.forEach((value) => {
    const section = document.createElement("section");
    section.className = `nation-block debug-block debug-block-${slugForAvailability(value)}`;
    section.id = nationSectionIdForJump(value);

    const title = document.createElement("h3");
    title.className = "section-headline debug-headline";
    title.textContent = availabilityLabel(value);

    const list = document.createElement("div");
    renderShipBlock(
      list,
      nationShips(state.activeNation, value),
      t("nation.noDebugGroup", "No {group} ships for this nation.", { group: availabilityLabel(value) }),
      "rows",
    );
    section.append(title, list);
    els.debugShipSections.appendChild(section);
  });
}

function buildTechTree(ships) {
  const shipMap = new Map(ships.map((ship) => [ship.identity.code, ship]));
  const edges = [];
  const parentMap = new Map();

  ships.forEach((ship) => parentMap.set(ship.identity.code, []));
  ships.forEach((ship) => {
    (ship.techTree.nextCodes || []).forEach((childCode) => {
      if (!shipMap.has(childCode)) return;
      edges.push([ship.identity.code, childCode]);
      parentMap.get(childCode).push(ship.identity.code);
    });
  });

  const groupedByClass = new Map();
  ships.forEach((ship) => {
    const key = ship.shipClass;
    if (!groupedByClass.has(key)) groupedByClass.set(key, []);
    groupedByClass.get(key).push(ship);
  });

  const positions = new Map();

  const laneOrder = [...new Set([
    ...CLASS_ORDER.filter((item) => groupedByClass.has(item)),
    ...ships.map((ship) => ship.shipClass),
  ])];

  const laneMeta = [];
  let laneOffset = 0;

  laneOrder.forEach((shipClass) => {
    const laneShips = ships
      .filter((ship) => ship.shipClass === shipClass)
      .sort((a, b) => (a.identity.tier - b.identity.tier) || a.displayName.localeCompare(b.displayName));
    if (!laneShips.length) return;

    const sameChildren = new Map();
    const sameIncoming = new Map();
    laneShips.forEach((ship) => {
      sameChildren.set(ship.identity.code, []);
      sameIncoming.set(ship.identity.code, 0);
    });

    edges.forEach(([parentCode, childCode]) => {
      const parent = shipMap.get(parentCode);
      const child = shipMap.get(childCode);
      if (!parent || !child) return;
      if (parent.shipClass !== shipClass || child.shipClass !== shipClass) return;
      sameChildren.get(parentCode).push(child);
      sameIncoming.set(childCode, (sameIncoming.get(childCode) || 0) + 1);
    });

    laneShips.forEach((ship) => {
      sameChildren.get(ship.identity.code).sort((a, b) => (a.identity.tier - b.identity.tier) || a.displayName.localeCompare(b.displayName));
    });

    const roots = laneShips
      .filter((ship) => ship.identity.group === "start" || (sameIncoming.get(ship.identity.code) || 0) === 0)
      .sort((a, b) => (a.identity.tier - b.identity.tier) || a.displayName.localeCompare(b.displayName));

    let nextColumn = 0;
    const assignedColumn = new Map();

    function assignBranch(ship, column) {
      if (assignedColumn.has(ship.identity.code)) return;
      assignedColumn.set(ship.identity.code, column);
      positions.set(ship.identity.code, { x: laneOffset + column, y: (ship.identity.tier || 1) - 1 });

      const children = sameChildren.get(ship.identity.code) || [];
      children.forEach((child, index) => {
        if (assignedColumn.has(child.identity.code)) return;
        if (index === 0) {
          assignBranch(child, column);
        } else {
          nextColumn += 1;
          assignBranch(child, nextColumn);
        }
      });
    }

    roots.forEach((ship) => {
      if (assignedColumn.has(ship.identity.code)) return;
      assignBranch(ship, nextColumn);
      nextColumn += 1;
    });

    laneShips
      .filter((ship) => ship.identity.group === "start" && !assignedColumn.has(ship.identity.code))
      .sort((a, b) => a.displayName.localeCompare(b.displayName))
      .forEach((ship) => {
        assignBranch(ship, nextColumn);
        nextColumn += 1;
      });

    laneShips.forEach((ship) => {
      if (!assignedColumn.has(ship.identity.code)) {
        assignBranch(ship, nextColumn);
        nextColumn += 1;
      }
    });

    const laneWidth = Math.max(nextColumn, 1);

    laneMeta.push({
      shipClass,
      start: laneOffset,
      width: laneWidth,
    });
    laneOffset += laneWidth + 1;
  });

  return { shipMap, edges, positions, laneMeta };
}

function renderNationTree(ships) {
  els.nationTree.innerHTML = "";
  if (!ships.length) {
    els.nationTree.innerHTML = `<div class="empty-panel">No ships for this nation in the current dataset.</div>`;
    return;
  }

  const { edges, positions, laneMeta } = buildTechTree(ships);
  const researchRoute = currentResearchRoute(ships);
  const researchPathCodes = new Set(researchRoute?.pathCodes || []);
  const researchPathEdges = new Set((researchRoute?.pathCodes || []).slice(1).map((code, index) => `${researchRoute.pathCodes[index]}:${code}`));
  const cardWidth = 144;
  const colGap = 40;
  const cardHeight = 102;
  const rowGap = 130;
  const padding = 12;
  const maxX = Math.max(...[...positions.values()].map((item) => item.x), 0);
  const maxTier = Math.max(...ships.map((ship) => ship.identity.tier || 1), 1);
  const width = Math.ceil((maxX + 1) * (cardWidth + colGap) + padding * 2);
  const laneHeaderHeight = 28;
  const height = maxTier * rowGap + cardHeight + 32 + laneHeaderHeight;
  const connectorInset = 10;

  const viewport = document.createElement("div");
  viewport.className = "tech-tree-viewport";

  const board = document.createElement("div");
  board.className = "tech-tree-board";
  board.style.width = `${width}px`;
  board.style.height = `${height}px`;

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "tech-tree-lines");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("width", `${width}`);
  svg.setAttribute("height", `${height}`);

  edges.forEach(([parentCode, childCode]) => {
    const parentPos = positions.get(parentCode);
    const childPos = positions.get(childCode);
    if (!parentPos || !childPos) return;
    const startX = padding + parentPos.x * (cardWidth + colGap) + cardWidth / 2;
    const startY = padding + laneHeaderHeight + parentPos.y * rowGap + cardHeight - connectorInset;
    const endX = padding + childPos.x * (cardWidth + colGap) + cardWidth / 2;
    const endY = padding + laneHeaderHeight + childPos.y * rowGap + connectorInset;
    const midY = startY + (endY - startY) / 2;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", `M ${startX} ${startY} V ${midY} H ${endX} V ${endY}`);
    path.setAttribute("class", researchPathEdges.has(`${parentCode}:${childCode}`) ? "tech-edge is-research-path" : "tech-edge");
    svg.appendChild(path);
  });

  board.appendChild(svg);

  laneMeta.forEach((lane) => {
    const header = document.createElement("div");
    header.className = "tree-lane-label";
    header.textContent = uiLabel(CLASS_LABELS[lane.shipClass] || lane.shipClass);
    header.style.left = `${padding + lane.start * (cardWidth + colGap)}px`;
    header.style.top = `${padding}px`;
    header.style.width = `${Math.max(lane.width * (cardWidth + colGap) - colGap, cardWidth)}px`;
    board.appendChild(header);
  });

  ships.forEach((ship) => {
    const pos = positions.get(ship.identity.code);
    const node = createShipNode(ship);
    node.classList.add("tree-node");
    node.addEventListener("click", (event) => {
      if (!event.ctrlKey && !event.shiftKey) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      if (!state.researchStartCode || state.researchTargetCode || state.researchStartCode === ship.identity.code) {
        state.researchStartCode = ship.identity.code;
        state.researchTargetCode = null;
      } else {
        state.researchTargetCode = ship.identity.code;
      }
      renderNationView();
    }, true);
    if (researchPathCodes.has(ship.identity.code)) node.classList.add("is-research-path");
    if (state.researchStartCode === ship.identity.code) node.classList.add("is-research-start");
    if (state.researchTargetCode === ship.identity.code) node.classList.add("is-research-target");
    node.style.left = `${padding + pos.x * (cardWidth + colGap)}px`;
    node.style.top = `${padding + laneHeaderHeight + pos.y * rowGap}px`;
    board.appendChild(node);
  });

  viewport.appendChild(board);
  els.nationTree.appendChild(viewport);
  applyTechTreeScale(viewport, board, width, height);
}

function applyTechTreeScale(viewport, board, width, height) {
  const available = viewport.clientWidth || els.nationTree.clientWidth || width;
  const scale = Math.min(1, available / width);
  board.style.transform = `scale(${scale})`;
  board.style.transformOrigin = "top left";
  viewport.style.height = `${height * scale}px`;
}

function renderNationView(options = {}) {
  const techShips = nationShips(state.activeNation, "tech");
  const nationLabel = state.ships.find((ship) => ship.identity.nation === state.activeNation)?.nationLabel || state.activeNation;
  els.techTreeTitle.textContent = t("nation.techTreeTitle", "{nation} tech tree", { nation: uiLabel(nationLabel) });
  renderResearchCalculator(techShips);
  renderNationTree(techShips);
  renderShipBlock(els.premiumList, nationShips(state.activeNation, "premium"), t("nation.noPremium", "No premium ships for this nation."), "rows", ShipSorting.comparePremiumShipCards);
  renderShipBlock(els.earlyAccessList, nationShips(state.activeNation, "early"), t("nation.noEarlyAccess", "No early access ships for this nation."), "rows");
  renderShipBlock(els.testList, nationShips(state.activeNation, "test"), t("nation.noTest", "No test ships for this nation."), "rows");
  const debugValues = debugAvailabilityValuesForNation(state.activeNation);
  renderDebugNationJumps(debugValues);
  renderDebugNationSections(debugValues);
  renderComparePickBanner();
  configureAdSensePlacements();
  if (state.activeMainTab === "nation" && options.syncRoute !== false) {
    syncRoute({ replace: true });
  }
}

function createFilterOption(item, active, onToggle) {
  const label = document.createElement("label");
  label.className = "check-pill";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = active;
  const text = document.createElement("span");
  text.textContent = uiLabel(item.label);
  input.addEventListener("change", onToggle);
  label.append(input, document.createTextNode(" "), text);
  return label;
}

function renderFilterRow(host, items, activeSet) {
  host.innerHTML = "";
  const row = document.createElement("div");
  row.className = "checkbox-row";
  items.forEach((item) => {
    row.appendChild(createFilterOption(item, activeSet.has(item.value), () => {
      if (activeSet.has(item.value)) activeSet.delete(item.value);
      else activeSet.add(item.value);
      renderFilterPane();
      refreshParameterView();
    }));
  });
  const controls = document.createElement("div");
  controls.className = "filter-inline-actions";
  const all = document.createElement("button");
  all.type = "button";
  all.className = "inline-link";
  all.textContent = t("common.all", "All");
  all.addEventListener("click", () => {
    activeSet.clear();
    items.forEach((item) => activeSet.add(item.value));
    renderFilterPane();
    refreshParameterView();
  });
  const none = document.createElement("button");
  none.type = "button";
  none.className = "inline-link";
  none.textContent = t("common.none", "None");
  none.addEventListener("click", () => {
    activeSet.clear();
    renderFilterPane();
    refreshParameterView();
  });
  controls.append(all, none);
  host.append(row, controls);
}

function renderFilterPane() {
  const availabilityValues = availabilityFilterValues();
  renderFilterRow(
    els.availabilityFilters,
    availabilityValues.map((value) => ({ value, label: availabilityLabel(value) })),
    state.filters.groups,
  );
  renderFilterRow(
    els.classFilters,
    getClasses().map((value) => ({ value, label: CLASS_LABELS[value] || value })),
    state.filters.classes,
  );
  renderFilterRow(
    els.nationFilters,
    getNations().map((value) => ({
      value,
      label: state.ships.find((ship) => ship.identity.nation === value)?.nationLabel || value,
    })),
    state.filters.nations,
  );

  els.tierMin.value = `${state.filters.tierMin}`;
  els.tierMax.value = `${state.filters.tierMax}`;
  els.tierLabel.textContent = `${state.filters.tierMin} - ${state.filters.tierMax}`;
  const left = ((state.filters.tierMin - 1) / 10) * 100;
  const right = ((state.filters.tierMax - 1) / 10) * 100;
  els.tierRange.style.setProperty("--range-left", `${left}%`);
  els.tierRange.style.setProperty("--range-right", `${right}%`);
  if (els.tierMinDown) {
    els.tierMinDown.disabled = state.filters.tierMin <= TIER_FILTER_MIN;
    els.tierMinDown.title = t("filters.lowerMinimumTier", "Lower minimum tier");
    els.tierMinDown.setAttribute("aria-label", t("filters.lowerMinimumTier", "Lower minimum tier"));
  }
  if (els.tierMaxUp) {
    els.tierMaxUp.disabled = state.filters.tierMax >= TIER_FILTER_MAX;
    els.tierMaxUp.title = t("filters.raiseMaximumTier", "Raise maximum tier");
    els.tierMaxUp.setAttribute("aria-label", t("filters.raiseMaximumTier", "Raise maximum tier"));
  }
  els.filterSummary.textContent = t("parameters.filterSummary", "{count} ships match the current filters.", { count: filteredShipsForParameters().length });
}

function matchesFilters(ship) {
  const { groups, classes, nations, tierMin, tierMax } = state.filters;
  if (!groups.has(ship.availability)) return false;
  if (!classes.has(ship.shipClass)) return false;
  if (!nations.has(ship.identity.nation)) return false;
  if (ship.identity.tier < tierMin || ship.identity.tier > tierMax) return false;
  return true;
}

function filteredShipsForParameters() {
  return state.ships
    .filter(matchesFilters)
    .sort((a, b) => (a.identity.tier - b.identity.tier) || a.displayName.localeCompare(b.displayName));
}

function shipNameSearchRank(ship, search) {
  const name = `${ship?.displayName || ""}`.toLowerCase();
  const query = `${search || ""}`.toLowerCase();
  const index = query ? name.indexOf(query) : -1;
  return index === -1 ? Number.MAX_SAFE_INTEGER : index;
}

function compareShipsByNameSearch(left, right, search) {
  const leftRank = shipNameSearchRank(left, search);
  const rightRank = shipNameSearchRank(right, search);
  if (leftRank !== rightRank) return leftRank - rightRank;
  return left.displayName.localeCompare(right.displayName);
}

function matchingSelectShips() {
  const search = state.selectSearch.trim().toLowerCase();
  if (!search) return [];
  return state.ships
    .filter((ship) => ship.searchable.includes(search))
    .filter((ship) => !state.selectedCodes.has(ship.identity.code))
    .sort((left, right) => compareShipsByNameSearch(left, right, search))
    .slice(0, 10);
}

function matchingGlobalSearchShips() {
  const search = state.globalSearch.trim().toLowerCase();
  if (!search) return [];
  return state.ships
    .filter((ship) => ship.searchable.includes(search))
    .sort((left, right) => {
      const leftName = left.displayName.toLowerCase();
      const rightName = right.displayName.toLowerCase();
      const leftExact = leftName === search ? 0 : 1;
      const rightExact = rightName === search ? 0 : 1;
      if (leftExact !== rightExact) return leftExact - rightExact;
      return compareShipsByNameSearch(left, right, search);
    });
}

function hideGlobalSearchResults() {
  if (els.globalSearchResults) els.globalSearchResults.innerHTML = "";
}

function openGlobalSearchShip(code) {
  if (!code) return;
  hideGlobalSearchResults();
  if (els.globalSearch) {
    els.globalSearch.value = "";
    state.globalSearch = "";
  }
  openShipModal(code);
}

function renderGlobalSearchResults() {
  if (!els.globalSearchResults) return;
  els.globalSearchResults.innerHTML = "";
  const query = state.globalSearch.trim();
  if (!query) return;

  const results = matchingGlobalSearchShips();
  if (!results.length) {
    const message = document.createElement("div");
    message.className = "empty-panel compact";
    message.textContent = t("search.noShipsMatch", "No ships match \"{query}\".", { query });
    els.globalSearchResults.appendChild(message);
    return;
  }

  results.forEach((ship) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "global-search-result";
    button.dataset.openShip = ship.identity.code;
    button.dataset.shipName = ship.displayName;
    button.innerHTML = `
      ${shipCardImage(ship, "tiny-preview")}
      <strong>${highlightSearchMatch(ship.displayName, query)}</strong>
    `;
    button.addEventListener("pointerdown", (event) => event.preventDefault());
    button.addEventListener("click", () => openGlobalSearchShip(ship.identity.code));
    els.globalSearchResults.appendChild(button);
  });
}

function openGlobalSearchMatch() {
  const match = matchingGlobalSearchShips()[0];
  if (!match) return false;
  openGlobalSearchShip(match.identity.code);
  return true;
}

function addShipToSelection(code) {
  state.selectedCodes.add(code);
  state.selectSearch = "";
  if (els.selectSearch) els.selectSearch.value = "";
  renderSelectPane();
  refreshParameterView();
}

function selectedShips() {
  return state.ships
    .filter((ship) => state.selectedCodes.has(ship.identity.code))
    .sort((a, b) => a.displayName.localeCompare(b.displayName));
}

function combinedFilterAndSelectionShips() {
  const shipsByCode = new Map();
  filteredShipsForParameters().forEach((ship) => {
    shipsByCode.set(ship.identity.code, ship);
  });
  selectedShips().forEach((ship) => {
    if (!shipsByCode.has(ship.identity.code)) {
      shipsByCode.set(ship.identity.code, ship);
    }
  });
  return [...shipsByCode.values()];
}

function comparisonShips() {
  const sourceShips = state.pickJoinMode === "and"
    ? combinedFilterAndSelectionShips()
    : state.activePickMode === "filter"
      ? filteredShipsForParameters()
      : selectedShips();
  return sourceShips.map(shipConfigView);
}

function renderSelectPane() {
  const results = matchingSelectShips();
  const selected = selectedShips();
  els.selectionSummary.textContent = "";
  els.searchResults.innerHTML = "";

  if (state.selectSearch.trim()) {
    if (!results.length) {
      const message = document.createElement("div");
      message.className = "empty-panel compact";
      message.textContent = t("search.noShipsMatch", "No ships match \"{query}\".", { query: state.selectSearch });
      els.searchResults.appendChild(message);
    } else {
      results.forEach((ship) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "search-result";
        button.innerHTML = `
          ${shipCardImage(ship, "tiny-preview")}
          <div class="search-result-copy">
            <strong>${highlightSearchMatch(ship.displayName, state.selectSearch)}</strong>
          </div>
        `;
        button.addEventListener("click", () => addShipToSelection(ship.identity.code));
        els.searchResults.appendChild(button);
      });
    }
  }

  els.selectionList.innerHTML = "";
  if (!selected.length) {
    return;
  }

  els.selectionList.innerHTML = `
    <div class="selected-ship-header">
      <span></span>
      <span>Ship</span>
      <span>Tier</span>
      <span>Class</span>
      <span>Nation</span>
      <span></span>
    </div>
  `;

  selected.forEach((ship) => {
    const row = document.createElement("div");
    row.className = "selected-ship-row";
    row.innerHTML = `
      ${shipCardImage(ship, "tiny-preview")}
      <button type="button" class="selected-ship-link" data-open-selected-ship="${escapeHtml(ship.identity.code)}">${escapeHtml(ship.displayName)}</button>
      <span class="selected-ship-meta">${escapeHtml(ship.identity.tier)}</span>
      <span class="selected-ship-meta">${escapeHtml(displaySelectClass(ship))}</span>
      <span class="selected-ship-meta">${escapeHtml(ship.nationLabel)}</span>
      <button class="remove-chip" type="button">x</button>
    `;
    row.querySelector(".selected-ship-link").addEventListener("click", () => openShipModal(ship.identity.code));
    row.querySelector(".remove-chip").addEventListener("click", () => {
      state.selectedCodes.delete(ship.identity.code);
      renderSelectPane();
      refreshParameterView();
    });
    els.selectionList.appendChild(row);
  });
}

function renderPickMode() {
  els.pickModeButtons.forEach((button) => button.classList.toggle("active", button.dataset.pickMode === state.activePickMode));
  els.filterPane.classList.toggle("active", state.activePickMode === "filter");
  els.selectPane.classList.toggle("active", state.activePickMode === "select");
  renderPickJoinMode();
}

function renderPickJoinMode() {
  if (!els.pickJoinToggle) return;
  const isAnd = state.pickJoinMode === "and";
  els.pickJoinToggle.textContent = t(isAnd ? "common.and" : "common.or", isAnd ? "and" : "or");
  els.pickJoinToggle.dataset.mode = state.pickJoinMode;
  els.pickJoinToggle.classList.toggle("active", isAnd);
  els.pickJoinToggle.setAttribute("aria-pressed", isAnd ? "true" : "false");
}

function firstProjectile(ship, type) {
  const resolved = resolvedShipView(ship);
  const acceptedTypes = type === "SAP" ? ["SAP", "CS"] : [type];
  return (resolved.artillery?.main_battery?.projectiles || []).find((projectile) => acceptedTypes.includes(projectile.ammo_type)) || null;
}

function hasMainBatteryAmmo(ship, type) {
  return firstProjectile(ship, type) != null;
}

function normalizeRows(rows) {
  return rows.map((row) => Array.isArray(row)
    ? { label: row[0], render: row[1], sortValue: row[1], sortType: "auto" }
    : row);
}

function visibleParameterRows(rows, ships) {
  return normalizeRows(rows).filter((row) => !row.visibleWhen || row.visibleWhen(ships));
}

function statHelpRangeText(context, fallbackKm = 12) {
  const contextKm = Number(context?.range_km);
  const contextMeters = Number(context?.range_m);
  const rangeKm = Number.isFinite(contextKm)
    ? contextKm
    : Number.isFinite(contextMeters)
      ? contextMeters / 1000
      : fallbackKm;
  return `${formatValue(rangeKm, { digits: Number.isInteger(rangeKm) ? 0 : 1 })}km`;
}

function statHelpText(label, groupLabel, context = null) {
  const text = `${label || ""}`.trim();
  const key = text.toLowerCase().replace(/\s+/g, " ").replace(/\s*\/\s*/g, "/");
  const group = `${groupLabel || ""}`.trim();
  const rangeFallback = group === "Secondaries" ? 6 : 12;
  const range = statHelpRangeText(context, rangeFallback);

  if (key === "hor. dispersion") return t("tooltip.horDispersion", "Horizontal dispersion at {range}", { range });
  if (key === "ver. dispersion") return t("tooltip.verDispersion", "Vertical dispersion at {range}", { range });
  if (key === "flight time") return t("tooltip.flightTime", "Shell flight time to {range}", { range });
  if (key === "impact speed") return t("tooltip.impactSpeed", "Shell impact speed at {range}", { range });
  if (key === "impact angle") return t("tooltip.impactAngle", "Shell impact angle at {range}", { range });

  const helpByKey = {
    "acceleration": ["tooltip.acceleration", "Acceleration time to 90% of the ship's maximum speed"],
    "repair %": ["tooltip.repairPercent", "Amount of damage that can be repaired"],
    "cit. repair %": ["tooltip.citadelRepairPercent", "Amount of citadel damage that can be repaired"],
    "citadel repair %": ["tooltip.citadelRepairPercent", "Amount of citadel damage that can be repaired"],
    "fire damage": ["tooltip.fireDamage", "Maximum damage of your HP per one fire"],
    "no of fires": ["tooltip.noOfFires", "Maximum number of fires"],
    "no of fire": ["tooltip.noOfFires", "Maximum number of fires"],
    "no of floodings": ["tooltip.noOfFloodings", "Maximum number of floodings"],
    "no of flooding": ["tooltip.noOfFloodings", "Maximum number of floodings"],
    "flooding damage": ["tooltip.floodingDamage", "Maximum damage of your HP per one flooding"],
    "he dpm": ["tooltip.heDpm", "Damage per minute that can be shot to each direction with HE shells"],
    "ap dpm": ["tooltip.apDpm", "Damage per minute that can be shot to each direction with AP shells"],
    "sap dpm": ["tooltip.sapDpm", "Damage per minute that can be shot to each direction with SAP shells"],
    "he salvo": ["tooltip.heSalvo", "Maximum single salvo damage with HE shells"],
    "ap salvo": ["tooltip.apSalvo", "Maximum single salvo damage with AP shells"],
    "sap salvo": ["tooltip.sapSalvo", "Maximum single salvo damage with SAP shells"],
    "shells/min": ["tooltip.shellsPerMinute", "Maximum number of shells that can be fired to each direction"],
    "weight": ["tooltip.weight", "Shell weight"],
    "fires/min": ["tooltip.firesPerMinute", "Fires that can be started per minute"],
    "secondary dpm": ["tooltip.secondaryDpm", "Damage per minute that can be shot to each direction with secondaries"],
    "hitting dpm": ["tooltip.hittingDpm", "Estimated secondary damage per minute after hit-rate adjustment"],
    "dpm contribution": ["tooltip.dpmContribution", "Share of secondary DPM provided by each gun group"],
    "on deck": ["tooltip.onDeck", "Number of planes on the deck"],
    "regeneration": ["tooltip.regeneration", "Aircraft restoration time"],
    "squadron": ["tooltip.squadron", "Planes in the squadron"],
    "firing delay": ["tooltip.firingDelay", "Machine gun phase action time"],
    "arming time": ["tooltip.armingTime", "Torpedo arming time"],
    "arming distance": ["tooltip.armingDistance", "Torpedo arming distance"],
    "spread": ["tooltip.spread", "Torpedo spread"],
  };

  const help = helpByKey[key];
  return help ? t(help[0], help[1]) : "";
}

function statHelpLabelHtml(label, groupLabel, context = null) {
  const text = `${label || ""}`;
  const displayText = uiLabel(text);
  const help = statHelpText(text, groupLabel, context);
  if (!help) return escapeHtml(displayText);
  return `
    <span class="detail-hover-wrap stat-help-wrap">
      <span class="detail-hover-trigger stat-help-trigger">${escapeHtml(displayText)}</span>
      <span class="detail-hover-card stat-help-card">
        <span class="stat-help-text">${escapeHtml(help)}</span>
      </span>
    </span>
  `;
}

function firstTorpedoProjectile(ship) {
  const resolved = resolvedShipView(ship);
  const module = firstTorpedoModule(resolved);
  const variant = selectedTorpedoVariant(resolved);
  return module?.shells?.[0]
    || variant?.projectile
    || resolved.torpedoes?.projectiles?.[0]
    || null;
}

function firstTorpedoModule(ship) {
  const modules = torpedoModules(ship);
  return modules.find((module) => /_GT_1$/i.test(module?.slot || "")) || modules[0] || null;
}

function allTorpedoModules(ship) {
  const resolved = resolvedShipView(ship);
  const modules = (resolved.torpedoes?.modules || []).filter((module) => weaponModuleMatches(module, "Torpedo", /_GT_\d+$/i));
  return modules.length ? modules : (resolved.torpedoes?.modules || []);
}

function cloneTorpedoModuleForProjectile(module, projectile, projectileIndex) {
  if (!projectile) return { ...module };
  const shellIds = Array.isArray(module?.shell_ids) ? module.shell_ids : [];
  return {
    ...module,
    shells: [projectile],
    shell_ids: [projectile.id || shellIds[projectileIndex] || ""],
    __torpedoProjectileIndex: projectileIndex,
  };
}

function torpedoModuleProjectileEntries(module) {
  const shells = Array.isArray(module?.shells) ? module.shells.filter(Boolean) : [];
  if (!shells.length) return [cloneTorpedoModuleForProjectile(module, null, 0)];
  return shells.map((projectile, index) => cloneTorpedoModuleForProjectile(module, projectile, index));
}

function torpedoVariantGroupingKey(module) {
  const projectile = module?.shells?.[0] || {};
  return [
    projectile.id || module?.shell_ids?.[0] || module?.index || module?.name || "",
    projectile.ammo_type || "",
    projectile.max_dist ?? "",
    projectile.speed ?? "",
    projectile.alpha_damage ?? "",
    projectile.damage ?? "",
    projectile.visibility_factor ?? "",
  ].join("|");
}

function allTorpedoVariantEntries(ship) {
  const modules = allTorpedoModules(ship);
  if (!modules.length) return [];
  const groups = new Map();
  modules.forEach((module) => {
    torpedoModuleProjectileEntries(module).forEach((projectileModule) => {
      const key = torpedoVariantGroupingKey(projectileModule);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(projectileModule);
    });
  });
  return [...groups.values()].map((groupModules, index) => ({
    index,
    isAlt: index > 0,
    modules: groupModules,
    projectile: groupModules[0]?.shells?.[0] || null,
  }));
}

function selectedTorpedoVariant(ship) {
  const entries = allTorpedoVariantEntries(ship);
  if (!entries.length) return null;
  const requestedIndex = Number(ship?.__torpedoVariantIndex ?? 0);
  return entries.find((entry) => entry.index === requestedIndex) || entries[0];
}

function torpedoVariantEntries(ship) {
  const entries = allTorpedoVariantEntries(ship);
  if (ship?.__torpedoVariantIndex == null) return entries;
  const selected = selectedTorpedoVariant(ship);
  return selected ? [selected] : [];
}

function withTorpedoVariant(ship, index) {
  return {
    ...ship,
    __torpedoVariantIndex: index,
    __torpedoVariantAlt: index > 0,
  };
}

function variantAltSuffix(index) {
  const numeric = Number(index);
  if (!Number.isFinite(numeric) || numeric <= 0) return "";
  return numeric === 1 ? " (alt)" : ` (alt ${numeric})`;
}

function torpedoModalTabKey(index) {
  return index > 0 ? `torpedoes-alt-${index}` : "torpedoes";
}

function torpedoModalTabIndex(tab) {
  if (tab === "torpedoes") return 0;
  const match = /^torpedoes-alt-(\d+)$/.exec(`${tab || ""}`);
  return match ? Number(match[1]) : null;
}

function torpedoModules(ship) {
  const variant = selectedTorpedoVariant(ship);
  return variant?.modules || allTorpedoModules(ship);
}

function airSupportEntries(ship) {
  const resolved = resolvedShipView(ship);
  return Array.isArray(resolved.air_support) ? resolved.air_support : [];
}

function firstAirSupport(ship) {
  return airSupportEntries(ship).find((support) => support?.air_support_type === "manual") || null;
}

function helperAirSupport(ship, uiType) {
  return airSupportEntries(ship).find((support) => support?.air_support_type === "helper" && `${support?.ui_type || ""}`.toLowerCase() === `${uiType}`.toLowerCase()) || null;
}

function planeConsumableById(aircraft, abilityId) {
  const slots = Array.isArray(aircraft?.consumables) ? aircraft.consumables : [];
  for (const slot of slots) {
    for (const choice of slot?.choices || []) {
      if (choice?.id === abilityId) return choice;
    }
  }
  return null;
}

function aircraftSquadron(ship, key) {
  const resolved = resolvedShipView(ship);
  const squadron = resolved.aircraft_squadrons?.[key] || null;
  if (!squadron) return null;
  if (ship?.__aircraftVariantKey === key) {
    const index = Number(ship.__aircraftVariantIndex || 0);
    if (index <= 0) return squadron;
    const variants = Array.isArray(squadron.variants) ? squadron.variants : [];
    return variants[index - 1] || null;
  }
  return squadron;
}

function aircraftSquadronEntries(ship, key) {
  const squadron = aircraftSquadron(ship, key);
  if (!squadron) return [];
  if (ship?.__aircraftVariantKey === key) {
    return [squadron].filter(Boolean);
  }
  return [squadron, ...(Array.isArray(squadron.variants) ? squadron.variants : [])].filter(Boolean);
}

function aircraftHangarSettings(squadron) {
  return squadron?.hangar_settings || squadron?.hangarSettings || null;
}

function isTacticalAircraftSquadron(squadron) {
  const hangar = aircraftHangarSettings(squadron);
  const maxValue = Number(hangar?.maxValue);
  const restoreAmount = Number(hangar?.restoreAmount);
  return Number.isFinite(maxValue)
    && Number.isFinite(restoreAmount)
    && maxValue > 0
    && restoreAmount > 0
    && Math.abs(maxValue - restoreAmount) < 1e-6;
}

function aircraftVariantSuffix(ship, key = ship?.__aircraftVariantKey) {
  if (!key) return "";
  const squadron = aircraftSquadron(ship, key);
  if (isTacticalAircraftSquadron(squadron)) return " (tact.)";
  if (ship?.__aircraftVariantAlt) return variantAltSuffix(ship.__aircraftVariantIndex);
  return "";
}

function aircraftWeaponEntries(ship, key) {
  return aircraftSquadronEntries(ship, key)
    .map((squadron) => ({
      squadron,
      weapon: (squadron?.weapons || [])[0] || null,
    }))
    .filter((entry) => entry.squadron);
}

function firstAircraftWeapon(ship, key) {
  return aircraftSquadron(ship, key)?.weapons?.[0] || null;
}

function aircraftDescription(ship, key) {
  const names = [...new Set(aircraftSquadronEntries(ship, key).map((squadron) => displayAircraftName(squadron)).filter(Boolean))];
  if (!names.length) return "N/A";
  return names.join("<br>");
}

function aircraftGroupKeyForTitle(title) {
  return {
    "Attack aircraft": "attack_aircraft",
    "Torpedo bombers": "torpedo_bombers",
    "Bombers": "bombers",
    "Skip bombers": "skip_bombers",
    "Mine bombers": "mine_bombers",
  }[title] || null;
}

function expandShipsForAircraftVariants(title, ships) {
  const key = aircraftGroupKeyForTitle(title);
  if (!key) return ships;
  return ships.flatMap((ship) => {
    const entries = aircraftSquadronEntries(ship, key);
    if (entries.length <= 1) return [ship];
    return entries.map((_, index) => ({
      ...ship,
      __aircraftVariantKey: key,
      __aircraftVariantIndex: index,
      __aircraftVariantAlt: index > 0,
    }));
  });
}

function expandShipsForTorpedoVariants(title, ships) {
  if (title !== "Torpedoes") return ships;
  return ships.flatMap((ship) => {
    const entries = allTorpedoVariantEntries(ship);
    if (entries.length <= 1) return [ship];
    return entries.map((entry) => withTorpedoVariant(ship, entry.index));
  });
}

function parameterShipVariantSuffix(ship) {
  if (ship?.__aircraftVariantKey) return aircraftVariantSuffix(ship).trim();
  if (ship?.__torpedoVariantAlt) return variantAltSuffix(ship.__torpedoVariantIndex).trim();
  return "";
}

function displayAircraftName(aircraft) {
  const value = aircraft?.display_name || aircraft?.translated_name || aircraft?.name || aircraft?.id;
  if (!value) return "N/A";
  if (/^[A-Z]{4}\d{3}_[A-Z0-9_]+$/.test(`${value}`)) {
    return titleizeFallbackLabel(friendlyFallbackName(`${value}`));
  }
  return value;
}

function displayProjectileName(projectile) {
  const value = projectile?.display_name || projectile?.translated_name || projectile?.name || projectile?.id;
  if (!value) return "N/A";
  if (/^[A-Z]{4}\d{3}_[A-Z0-9_]+$/.test(`${value}`)) {
    return titleizeFallbackLabel(friendlyFallbackName(`${value}`));
  }
  return value;
}

function aircraftVariantStatDisplay(ship, key, valueGetter, formatter, options = {}) {
  const entries = aircraftWeaponEntries(ship, key);
  if (!entries.length) return options.empty ?? "N/A";
  const values = entries
    .map((entry) => ({
      label: displayAircraftName(entry.squadron),
      raw: valueGetter(entry),
    }))
    .filter((item) => item.raw != null && item.raw !== "" && !(typeof item.raw === "number" && !Number.isFinite(item.raw)));
  if (!values.length) return options.empty ?? "N/A";
  const displayValues = values.map((item) => formatter(item.raw));
  const uniqueDisplays = [...new Set(displayValues)];
  if (uniqueDisplays.length === 1) {
    return uniqueDisplays[0];
  }
  const detailRows = values.map((item) => ({ label: item.label, value: formatter(item.raw) }));
  const numericValues = values
    .map((item) => Number(item.raw))
    .filter((value) => Number.isFinite(value));
  if (numericValues.length === values.length) {
    const min = Math.min(...numericValues);
    const max = Math.max(...numericValues);
    if (min === max) return formatter(min);
    return hoverStatDisplay(`${formatter(min)} - ${formatter(max)}`, detailRows);
  }
  return hoverStatDisplay(displayValues[0], detailRows);
}

function aircraftSquadronSize(ship, key) {
  return aircraftVariantStatDisplay(
    ship,
    key,
    ({ squadron }) => {
      const total = squadron?.num_planes_in_squadron;
      const wave = squadron?.attackers_per_wave;
      if (typeof total === "number" && typeof wave === "number" && wave > 0) {
        const groups = Math.max(1, Math.floor(total / wave));
        return `${groups}x${wave}`;
      }
      return squadron?.formation_size || squadron?.squadron_size || squadron?.attackers_per_wave || null;
    },
    (value) => `${value}`,
  );
}

function aircraftWeaponType(projectile) {
  if (!projectile) return "N/A";
  if (projectile.ammo_type === "CS") return "SAP";
  if (projectile.ammo_type === "HE") return "HE";
  if (projectile.ammo_type === "AP") return "AP";
  if (projectile.ammo_type === "torpedo") return uiLabel("Normal");
  if (projectile.ammo_type === "torpedo_alternative") return uiLabel("Alternative");
  if (projectile.ammo_type === "torpedo_deepwater") return uiLabel("Deepwater");
  return projectile.ammo_type || projectile.id || "N/A";
}

function aircraftSectionLabel(ship, key, baseLabel) {
  const projectile = firstAircraftWeapon(ship, key)?.projectile;
  const ammo = projectile?.ammo_type;
  if (ammo === "AP") return `AP ${baseLabel}`;
  if (ammo === "HE") return `HE ${baseLabel}`;
  if (ammo === "CS") return `SAP ${baseLabel}`;
  return baseLabel;
}

function airstrikeSupport(ship) {
  return firstAirSupport(ship);
}

function airstrikeWeapon(ship) {
  return airstrikeSupport(ship)?.plane?.weapons?.[0] || null;
}

function airstrikeProjectile(ship) {
  return airstrikeWeapon(ship)?.projectile || null;
}

function airstrikeSectionLabel(ship) {
  const support = airstrikeSupport(ship);
  if (support?.air_support_type === "helper") {
    const uiType = `${support?.ui_type || ""}`.toLowerCase();
    if (uiType === "spy") return "Scouts";
    if (uiType === "smoke") return "Smoke Screen Aircraft";
    if (uiType === "scout") return "Escort Spotters";
  }
  const ammo = airstrikeProjectile(ship)?.ammo_type;
  if (ammo === "depthcharge") return "ASW Airstrike";
  if (ammo === "HE") return "HE Airstrike";
  if (ammo === "CS") return "SAP Airstrike";
  if (ammo === "AP") return "AP Airstrike";
  return "Airstrike";
}

function helperSupportSectionLabel(uiType) {
  if (uiType === "spy") return "Scouts";
  if (uiType === "smoke") return "Smoke Screen Aircraft";
  if (uiType === "scout") return "Escort Spotters";
  return "Helper Air Support";
}

function helperSupportBuffPercent(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  return Math.abs(1 - numeric) * 100;
}

function airstrikeBombCount(ship) {
  const plane = airstrikeSupport(ship)?.plane;
  const attackers = Number(plane?.attackers_per_wave);
  const attackCount = Number(plane?.attack_count);
  if (!Number.isFinite(attackers) || !Number.isFinite(attackCount)) return null;
  return attackers * attackCount;
}

function airstrikePenetration(projectile) {
  if (!projectile) return null;
  if (projectile.ammo_type === "depthcharge") return null;
  if (projectile.ammo_type === "CS") return projectile.alpha_piercing_cs ?? null;
  return projectile.alpha_piercing_he ?? projectile.alpha_piercing_cs ?? null;
}

function innerBombsPercentageDisplay(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  const percent = numeric <= 1 ? numeric * 100 : numeric;
  return `${formatValue(percent, { digits: 1 })}%`;
}

function airstrikeReticleMetrics(ship, kind = "outer") {
  const support = airstrikeSupport(ship);
  const plane = support?.plane;
  const projectile = airstrikeProjectile(ship);
  if (!plane || projectile?.ammo_type === "depthcharge") return null;
  const salvo = kind === "inner" ? plane?.reticle_size : plane?.outer_reticle_size;
  const flightRadius = Number(plane?.flight_radius);
  const attackCount = Number(plane?.attack_count);
  const attackInterval = Number(plane?.attack_interval);
  const speedMoveWithBomb = Number(plane?.speed_move_with_bomb);
  if (!Array.isArray(salvo) || salvo.length < 2 || !Number.isFinite(flightRadius)) return null;
  const width = roundedInt(flightRadius * Number(salvo[0]) * 1.81818);
  const baseHeight = roundedInt(flightRadius * Number(salvo[1]) * 1.81818);
  const drop = Number.isFinite(attackCount) && Number.isFinite(attackInterval) && Number.isFinite(speedMoveWithBomb)
    ? roundedInt((attackCount - 1) * attackInterval * speedMoveWithBomb * 2.6867)
    : null;
  if (width == null || baseHeight == null) return null;
  return {
    width,
    height: baseHeight + (drop || 0),
    baseHeight,
    drop,
  };
}

function airstrikeReticleDisplay(ship) {
  const outer = airstrikeReticleMetrics(ship, "outer");
  if (!outer) return "N/A";
  const inner = airstrikeReticleMetrics(ship, "inner");
  const innerBombsPercentage = Number(airstrikeSupport(ship)?.plane?.inner_bombs_percentage);
  const detailRows = [
    { label: "Outer reticle", value: `${outer.width}x${outer.height} m` },
  ];
  if (inner) {
    detailRows.push({ label: "Inner reticle", value: `${inner.width}x${inner.height} m` });
  }
  const innerPercentDisplay = innerBombsPercentageDisplay(innerBombsPercentage);
  if (innerPercentDisplay) {
    detailRows.push({
      label: "Inner bombs percentage",
      value: innerPercentDisplay,
    });
  }
  return hoverStatDisplay(`${outer.width}x${outer.height} m`, detailRows);
}

function attackAircraftReticleMetrics(ship, kind = "outer") {
  const squadron = aircraftSquadron(ship, "attack_aircraft");
  const projectile = firstAircraftWeapon(ship, "attack_aircraft")?.projectile;
  if (!squadron || !projectile) return null;
  const salvo = kind === "inner" ? squadron?.reticle_size : squadron?.outer_reticle_size;
  const maxSpread = Array.isArray(squadron?.max_spread) ? squadron.max_spread : null;
  const speedMoveWithBomb = Number(squadron?.speed_move_with_bomb);
  const attackCount = Number(squadron?.attack_count);
  const attackInterval = Number(squadron?.attack_interval);
  if (!Array.isArray(salvo) || salvo.length < 2 || !maxSpread || maxSpread.length < 2) return null;
  const spreadX = Number(maxSpread[0]);
  const spreadY = Number(maxSpread[1]);
  const aspectRatio = Number.isFinite(spreadX) && spreadX !== 0 && Number.isFinite(spreadY) ? spreadY / spreadX : 1;
  const width = roundedInt(60 * Number(salvo[0]));
  const offset = Number.isFinite(speedMoveWithBomb) && Number.isFinite(attackCount) && Number.isFinite(attackInterval)
    ? roundedInt(2.69 * speedMoveWithBomb * (attackCount - 1) * attackInterval)
    : 0;
  const baseHeight = roundedInt((60 * aspectRatio) * Number(salvo[1]));
  if (width == null || baseHeight == null) return null;
  return {
    width,
    height: baseHeight + (offset || 0),
    baseHeight,
    offset,
    aspectRatio,
  };
}

function attackAircraftReticleDisplay(ship) {
  const outer = attackAircraftReticleMetrics(ship, "outer");
  if (!outer) return "Maintenance";
  const inner = attackAircraftReticleMetrics(ship, "inner");
  const innerBombsPercentage = Number(aircraftSquadron(ship, "attack_aircraft")?.inner_bombs_percentage);
  const detailRows = [
    { label: "Outer reticle", value: `${outer.width}x${outer.height} m` },
  ];
  if (inner) {
    detailRows.push({ label: "Inner reticle", value: `${inner.width}x${inner.height} m` });
  }
  const innerPercentDisplay = innerBombsPercentageDisplay(innerBombsPercentage);
  if (innerPercentDisplay) {
    detailRows.push({
      label: "Inner rockets percentage",
      value: innerPercentDisplay,
    });
  }
  return hoverStatDisplay(`${outer.width}x${outer.height} m`, detailRows);
}

function bomberReticleMetrics(ship, kind = "outer") {
  const squadron = aircraftSquadron(ship, "bombers");
  if (!squadron) return null;
  const salvo = kind === "inner" ? squadron?.reticle_size : squadron?.outer_reticle_size;
  const maxSpread = Array.isArray(squadron?.max_spread) ? squadron.max_spread : null;
  const speedMoveWithBomb = Number(squadron?.speed_move_with_bomb);
  const attackCount = Number(squadron?.attack_count);
  const attackInterval = Number(squadron?.attack_interval);
  if (!Array.isArray(salvo) || salvo.length < 2 || !maxSpread || maxSpread.length < 2) return null;
  const spreadX = Number(maxSpread[0]);
  const spreadY = Number(maxSpread[1]);
  const aspectRatio = Number.isFinite(spreadX) && spreadX !== 0 && Number.isFinite(spreadY) ? spreadY / spreadX : 1;
  const width = roundedInt(60 * Number(salvo[0]));
  const offset = Number.isFinite(speedMoveWithBomb) && Number.isFinite(attackCount) && Number.isFinite(attackInterval)
    ? roundedInt(2.69 * speedMoveWithBomb * (attackCount - 1) * attackInterval)
    : 0;
  const baseHeight = roundedInt((60 * aspectRatio) * Number(salvo[1]));
  if (width == null || baseHeight == null) return null;
  return {
    width,
    height: baseHeight + (offset || 0),
  };
}

function bomberReticleDisplay(ship) {
  const outer = bomberReticleMetrics(ship, "outer");
  if (!outer) return "Maintenance";
  const inner = bomberReticleMetrics(ship, "inner");
  const innerBombsPercentage = Number(aircraftSquadron(ship, "bombers")?.inner_bombs_percentage);
  const detailRows = [{ label: "Outer reticle", value: `${outer.width}x${outer.height} m` }];
  if (inner) {
    detailRows.push({ label: "Inner reticle", value: `${inner.width}x${inner.height} m` });
  }
  const innerPercentDisplay = innerBombsPercentageDisplay(innerBombsPercentage);
  if (innerPercentDisplay) {
    detailRows.push({
      label: "Inner bombs percentage",
      value: innerPercentDisplay,
    });
  }
  return hoverStatDisplay(`${outer.width}x${outer.height} m`, detailRows);
}

function mineBomberReticleMetrics(ship, kind = "outer") {
  const squadron = aircraftSquadron(ship, "mine_bombers");
  if (!squadron) return null;
  const salvo = kind === "inner" ? squadron?.reticle_size : squadron?.outer_reticle_size;
  const maxSpread = Array.isArray(squadron?.max_spread) ? squadron.max_spread : null;
  const speedMoveWithBomb = Number(squadron?.speed_move_with_bomb);
  const attackCount = Number(squadron?.attack_count);
  const attackInterval = Number(squadron?.attack_interval);
  if (!Array.isArray(salvo) || salvo.length < 2 || !maxSpread || maxSpread.length < 2) return null;
  const spreadX = Number(maxSpread[0]);
  const spreadY = Number(maxSpread[1]);
  const aspectRatio = Number.isFinite(spreadX) && spreadX !== 0 && Number.isFinite(spreadY) ? spreadY / spreadX : 1;
  const width = roundedInt(60 * Number(salvo[0]));
  const offset = Number.isFinite(speedMoveWithBomb) && Number.isFinite(attackCount) && Number.isFinite(attackInterval)
    ? roundedInt(2.69 * speedMoveWithBomb * (attackCount - 1) * attackInterval)
    : 0;
  const baseHeight = roundedInt((60 * aspectRatio) * Number(salvo[1]));
  if (width == null || baseHeight == null) return null;
  return {
    width,
    height: baseHeight + (offset || 0),
  };
}

function mineBomberReticleDisplay(ship) {
  const outer = mineBomberReticleMetrics(ship, "outer");
  if (!outer) return "Maintenance";
  const inner = mineBomberReticleMetrics(ship, "inner");
  const innerBombsPercentage = Number(aircraftSquadron(ship, "mine_bombers")?.inner_bombs_percentage);
  const detailRows = [{ label: "Outer reticle", value: `${outer.width}x${outer.height} m` }];
  if (inner) {
    detailRows.push({ label: "Inner reticle", value: `${inner.width}x${inner.height} m` });
  }
  const innerPercentDisplay = innerBombsPercentageDisplay(innerBombsPercentage);
  if (innerPercentDisplay) {
    detailRows.push({
      label: "Inner bombs percentage",
      value: innerPercentDisplay,
    });
  }
  return hoverStatDisplay(`${outer.width}x${outer.height} m`, detailRows);
}

function aircraftWeaponPenetration(projectile) {
  if (!projectile) return null;
  if (projectile.ammo_type === "CS") return projectile.alpha_piercing_cs ?? null;
  if (projectile.ammo_type === "HE") return projectile.alpha_piercing_he ?? null;
  if (projectile.ammo_type === "AP") {
    const krupp = Number(projectile.krupp);
    const mass = Number(projectile.bullet_mass);
    const speed = Number(projectile.bullet_speed);
    const diameterM = Number(projectile.caliber_mm) / 1000;
    if (Number.isFinite(krupp) && Number.isFinite(mass) && Number.isFinite(speed) && Number.isFinite(diameterM) && diameterM > 0) {
      return krupp * ((mass * speed * speed) ** 0.69) * (diameterM ** -1.07) * 0.0000001;
    }
  }
  return projectile.alpha_piercing_ap ?? projectile.alpha_piercing ?? projectile.alpha_piercing_he ?? projectile.alpha_piercing_cs ?? null;
}

function nonZeroPercentDisplay(value, options = {}) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return "N/A";
  return formatPercent(numeric, options);
}

function torpedoDamageFromProjectile(projectile) {
  if (!projectile) return null;
  const alphaDamage = Number(projectile.alpha_damage ?? projectile.alphaDamage);
  if (Number.isFinite(alphaDamage)) return Math.floor(alphaDamage * 0.33);
  if (projectile.effective_torpedo_damage != null) {
    const effective = Number(projectile.effective_torpedo_damage);
    return Number.isFinite(effective) ? effective : null;
  }
  return null;
}

function aircraftTorpedoDamage(projectile) {
  return torpedoDamageFromProjectile(projectile);
}

function mineBomberDamage(ship) {
  const squadron = aircraftSquadron(ship, "mine_bombers");
  const projectile = firstAircraftWeapon(ship, "mine_bombers")?.projectile;
  const level = Number(squadron?.plane_level);
  const alpha = Number(projectile?.alpha_damage);
  if (!Number.isFinite(level) || !Number.isFinite(alpha)) return null;
  const multiplier = level === 6 ? 28.05 : level === 8 ? 37.29 : level === 10 ? 45.21 : null;
  if (!multiplier) return null;
  return Math.round(alpha * multiplier);
}

function mineBomberDamageForEntry(squadron, weapon) {
  const level = Number(squadron?.plane_level);
  const alpha = Number(weapon?.projectile?.alpha_damage);
  if (!Number.isFinite(level) || !Number.isFinite(alpha)) return null;
  const multiplier = level === 6 ? 28.05 : level === 8 ? 37.29 : level === 10 ? 45.21 : null;
  if (!multiplier) return null;
  return Math.round(alpha * multiplier);
}

function mineBomberRadius(ship) {
  const squadron = aircraftSquadron(ship, "mine_bombers");
  const speed = Number(squadron?.speed_move_with_bomb);
  const interval = Number(squadron?.attack_interval);
  const size = Number(squadron?.attackers_per_wave);
  if (!Number.isFinite(speed) || !Number.isFinite(interval) || !Number.isFinite(size)) return null;
  return Math.round((12.5 * speed) + (500 * interval) - (34.375 * size) - 275);
}

function mineBomberCount(ship) {
  const squadron = aircraftSquadron(ship, "mine_bombers");
  const attackCount = Number(squadron?.attack_count);
  const attackerSize = Number(squadron?.attackers_per_wave);
  if (!Number.isFinite(attackCount) || !Number.isFinite(attackerSize)) return null;
  return attackCount * attackerSize;
}

function reticleSizeDisplay(value) {
  return "Maintenance";
}

function mainBatteryReloadDetails(ship) {
  const drum = ship.artillery?.main_battery?.drum_artillery || mainBatteryModule(ship)?.drum_artillery;
  if (!drum || !Number.isFinite(Number(drum?.shots_count))) return [];
  const shotsCount = Number(drum.shots_count);
  const shotDelay = Number(drum.shot_delay);
  const fullReloadTime = Number(drum.full_reload_time);
  const params = Array.isArray(drum.charge_time_params) ? drum.charge_time_params.map((value) => Number(value)) : [];
  const firstCharge = params[0];
  const secondCharge = params[1];
  const hasChargeParams = Number.isFinite(firstCharge) && firstCharge > 0 && Number.isFinite(secondCharge) && secondCharge > 0;
  const rows = [];
  if (hasChargeParams) {
    rows.push({ label: "1 salvo reload", value: formatValue(firstCharge, { digits: 1, suffix: " s" }) });
    rows.push({ label: shotsCount > 2 ? `2-${shotsCount} salvos reload` : "2 salvos reload", value: formatValue(secondCharge, { digits: 1, suffix: " s" }) });
  } else if (Number.isFinite(fullReloadTime) && fullReloadTime > 0) {
    rows.push({ label: "Reload time", value: formatValue(fullReloadTime, { digits: 1, suffix: " s" }) });
  }
  if (Number.isFinite(shotDelay)) {
    rows.push({ label: "Minimum Interval Between Salvos", value: formatValue(shotDelay, { digits: 2, suffix: " s" }) });
  }
  rows.push({ label: "Number of Salvos in Series", value: formatValue(shotsCount, { digits: 0 }) });
  return rows;
}

function mainBatteryDisplayedReloadValue(ship) {
  const drum = ship.artillery?.main_battery?.drum_artillery || mainBatteryModule(ship)?.drum_artillery;
  if (drum) {
    const params = Array.isArray(drum.charge_time_params) ? drum.charge_time_params.map((value) => Number(value)) : [];
    const firstCharge = params[0];
    const secondCharge = params[1];
    const hasChargeParams = Number.isFinite(firstCharge) && firstCharge > 0 && Number.isFinite(secondCharge) && secondCharge > 0;
    if (hasChargeParams) return firstCharge;
    const fullReloadTime = Number(drum.full_reload_time);
    if (Number.isFinite(fullReloadTime) && fullReloadTime > 0) return fullReloadTime;
  }
  return ship.artillery?.main_battery?.reload_s;
}

function mainBatterySalvoSeriesCount(ship) {
  const drum = ship.artillery?.main_battery?.drum_artillery || mainBatteryModule(ship)?.drum_artillery;
  const shotsCount = Number(drum?.shots_count);
  return Number.isFinite(shotsCount) ? shotsCount : null;
}

function mainBatteryReloadDisplay(ship) {
  const display = formatValue(mainBatteryDisplayedReloadValue(ship), { digits: 1, suffix: " s" });
  return hoverStatDisplay(display, mainBatteryReloadDetails(ship));
}

function aircraftFiringDelay(ship, key) {
  const durations = firstAircraftWeapon(ship, key)?.projectile?.attack_sequence_durations || [];
  const total = durations
    .map((item) => Number(item))
    .filter((item) => Number.isFinite(item))
    .reduce((sum, item) => sum + item, 0);
  return total || null;
}

function aircraftSpeedStats(ship, key) {
  const squadron = aircraftSquadron(ship, key);
  const cruise = Number(squadron?.speed_move_with_bomb);
  const maxMultiplier = Number(squadron?.speed_max_multiplier);
  const minMultiplier = Number(squadron?.speed_min_multiplier);
  if (!Number.isFinite(cruise)) return null;
  return {
    maximum: Number.isFinite(maxMultiplier) ? cruise * maxMultiplier : cruise,
    cruise,
    minimum: Number.isFinite(minMultiplier) ? cruise * minMultiplier : null,
  };
}

function aircraftMaxSpeedDisplay(ship, key) {
  const entries = aircraftSquadronEntries(ship, key);
  if (!entries.length) return "N/A";
  const displayRows = entries
    .map((squadron) => ({ label: displayAircraftName(squadron), stats: aircraftSpeedStats({ aircraft_squadrons: { [key]: squadron }, __resolvedProfile: true }, key) }))
    .filter((item) => item.stats);
  if (!displayRows.length) return "N/A";
  if (displayRows.length === 1) {
    const stats = displayRows[0].stats;
    const details = [
      { label: "Maximum speed", value: formatValue(stats.maximum, { digits: 0, suffix: " kn" }) },
      { label: "Cruise speed", value: formatValue(stats.cruise, { digits: 0, suffix: " kn" }) },
    ];
    if (stats.minimum != null) details.push({ label: "Minimum speed", value: formatValue(stats.minimum, { digits: 0, suffix: " kn" }) });
    return hoverStatDisplay(formatValue(stats.maximum, { digits: 0, suffix: " kn" }), details);
  }
  const detailRows = displayRows.map((item) => ({
    label: item.label,
    value: formatValue(item.stats.maximum, { digits: 0, suffix: " kn" }),
  }));
  const maxValues = displayRows.map((item) => item.stats.maximum).filter((value) => Number.isFinite(value));
  return hoverStatDisplay(
    `${formatValue(Math.min(...maxValues), { digits: 0, suffix: " kn" })} - ${formatValue(Math.max(...maxValues), { digits: 0, suffix: " kn" })}`,
    detailRows,
  );
}

function aircraftConsumableSlots(ship, key) {
  return (aircraftSquadron(ship, key)?.consumables || [])
    .filter((slot) => (slot.choices || []).length)
    .sort((left, right) => (left.slot ?? 99) - (right.slot ?? 99));
}

function aircraftHasConsumables(ship, key) {
  return aircraftConsumableSlots(ship, key).length > 0;
}

function renderAircraftConsumables(ship, key) {
  const slots = aircraftConsumableSlots(ship, key);
  if (!slots.length) return "N/A";
  return `
    <div class="aircraft-consumables-inline">
      ${slots.map((slot) => renderConsumableSlotChoices(slot.choices || [])).join("")}
    </div>
  `;
}

function allConsumables(ship) {
  return (ship.consumables || []).flatMap((slot) => slot.choices || []);
}

function firstConsumableByType(ship, type) {
  return allConsumables(ship).find((item) => item.consumable_type === type) || null;
}

function firstAirWeapon(ship, predicate = () => true) {
  const weapons = firstAirSupport(ship)?.plane?.weapons || [];
  return weapons.find((weapon) => predicate(weapon)) || null;
}

function isDepthChargeWeapon(weapon) {
  const projectile = weapon?.projectile;
  return projectile?.ammo_type === "depthcharge" || projectile?.typeinfo?.species === "DepthCharge";
}

function isTorpedoBomberWeapon(weapon) {
  const projectile = weapon?.projectile;
  return weapon?.mount === "torpedoName" || projectile?.ammo_type === "torpedo" || projectile?.typeinfo?.species === "Torpedo";
}

function isSkipBomberWeapon(weapon) {
  return weapon?.mount === "skipBombName";
}

function isBomberWeapon(weapon) {
  if (!weapon) return false;
  if (isDepthChargeWeapon(weapon) || isTorpedoBomberWeapon(weapon) || isSkipBomberWeapon(weapon)) return false;
  return weapon.mount === "bombName" || weapon?.projectile?.ammo_type === "bomb";
}

function isAttackAircraftWeapon(weapon) {
  if (!weapon) return false;
  if (isDepthChargeWeapon(weapon) || isTorpedoBomberWeapon(weapon) || isSkipBomberWeapon(weapon) || isBomberWeapon(weapon)) return false;
  return weapon.mount === "rocketName" || weapon?.projectile?.ammo_type === "rocket";
}

function renderTable(title, ships, rows) {
  const context = getParameterRenderContext(title, ships);
  const commonRows = [
    {
      label: "Ship",
      render: (ship) => `<button type="button" class="param-ship-link" data-open-ship="${escapeHtml(ship.identity.code)}">${escapeHtml(ship.displayName)}${parameterShipVariantSuffix(ship) ? ` <span class="param-ship-alt">${escapeHtml(parameterShipVariantSuffix(ship))}</span>` : ""}</button>`,
      sortValue: (ship) => `${ship.displayName}${parameterShipVariantSuffix(ship)}`,
      sortType: "text",
    },
    { label: "Tier", render: (ship) => ship.identity.tier, sortValue: (ship) => ship.identity.tier, sortType: "number" },
    { label: "Class", render: (ship) => escapeHtml(localizedDisplayClass(ship)), sortValue: (ship) => displayClass(ship), sortType: "text" },
    { label: "Nation", render: (ship) => escapeHtml(localizedNationLabel(ship)), sortValue: (ship) => ship.nationLabel, sortType: "text" },
  ];
  const visibleRows = visibleParameterRows(rows, ships).filter((row) => !row.modalOnly);
  const finalRows = [...commonRows, ...visibleRows.filter((row) => !commonRows.some((base) => base.label === row.label))];
  const expandedShips = expandShipsForTorpedoVariants(title, expandShipsForAircraftVariants(title, ships));
  const sortedShips = sortShipsForTable(title, expandedShips, finalRows, context);
  const extremeStates = parameterExtremeStateMaps(finalRows, sortedShips, context);
  const head = finalRows.map((row) => renderSortHeader(title, row, context)).join("");
    const body = sortedShips
      .map((ship, index) => `<tr class="param-row-clickable" data-open-ship-row="${escapeHtml(ship.identity.code)}" data-ship-name="${escapeHtml(ship.displayName)}"><td>${index + 1}</td>${finalRows.map((row) => {
        const classes = [];
        if (row.cellClass) classes.push(row.cellClass);
        const extremeState = extremeStates.get(row)?.get(ship) || "";
        if (extremeState) classes.push(`param-extreme-${extremeState}`);
        return `<td${classes.length ? ` class="${escapeHtml(classes.join(" "))}"` : ""}>${renderValueHtml(row.render(ship, context))}</td>`;
      }).join("")}</tr>`)
      .join("");
  return `
    <section class="parameter-section">
      <div class="parameter-section-header">
        <h3>${uiLabel(title)}</h3>
        <div class="parameter-section-tools">
          ${renderRangeSelect(title, ships)}
        </div>
      </div>
      <div class="param-table-wrap">
        <table class="param-table ${title === "General" ? "param-table-general" : ""}">
          <thead><tr><th>#</th>${head}</tr></thead>
          <tbody>${body}</tbody>
        </table>
      </div>
    </section>
  `;
}

function consumableColumnKey(consumable) {
  return consumable.consumable_type || consumable.id;
}

function consumableColumnLabel(consumable) {
  return CONSUMABLE_TYPE_LABELS[consumable.consumable_type] || consumable.display_name || consumable.id;
}

function detectionRangeKm(rawValue) {
  const numeric = Number(rawValue);
  if (!Number.isFinite(numeric)) return null;
  return Math.ceil((numeric * 30) / 100) / 10;
}

function positivePercentFromMultiplier(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  if (numeric > 1) return `+${formatValue((numeric - 1) * 100, { digits: 0 })}%`;
  return `${formatValue(numeric * 100, { digits: 0 })}%`;
}

function renderConsumableValue(value, className = "") {
  return `<span class="${escapeHtml(className)}">${escapeHtml(value)}</span>`;
}

function consumableTooltipRows(consumable, ownerShip = null) {
  const type = consumable?.consumable_type;
  const hp = ownerShip?.survivability?.hp ?? ownerShip?.hp ?? null;
  const rows = [{ label: "Uses", value: consumableUsesLabel(consumable) }];
  const pushActionCooldown = () => {
    rows.push({ label: "Action time", value: formatValue(consumable?.work_time, { digits: 0, suffix: " s" }) });
    rows.push({ label: "Cooldown time", value: formatValue(consumable?.reload_time, { digits: 0, suffix: " s" }) });
  };

  if (type === "regenCrew") {
    pushActionCooldown();
    const hpPerSecond = Number(hp) * Number(consumable?.regeneration_hp_speed);
    const totalHealed = Number(consumable?.regeneration_hp_speed) * Number(consumable?.work_time) * 100;
    rows.splice(2, 0,
      { label: "HP per second", value: formatValue(hpPerSecond, { digits: 0, grouping: true }) },
      { label: "Total healed", value: formatValue(totalHealed, { digits: 0, suffix: "%" }) },
    );
  } else if (type === "massHeal") {
    pushActionCooldown();
    rows.splice(2, 0,
      { label: "Self HP per second", value: massHealSelfHpPerSecondDisplay(consumable, hp), className: "consumable-hover-line-value-positive" },
      { label: "Total healed", value: formatPercent(massHealSelfTotalHealed(consumable), { digits: 1 }) },
      { label: "Ally HP per second", value: consumableRatioPercent(consumable?.ally_health_regen_percent, 1), className: "consumable-hover-line-value-positive" },
      { label: "Ally total healed", value: formatPercent(massHealAllyTotalHealed(consumable), { digits: 1 }) },
      { label: "Radius", value: massHealRadiusDisplay(consumable) },
    );
  } else if (type === "vampireDamage") {
    rows.push({ label: "Action time", value: formatValue(consumable?.work_time, { digits: 0, suffix: " s" }) });
    rows.push({
      label: "HP restore per Damage",
      value: `${formatValue((Number(consumable?.damage_gm_heal_coeff) || 0) * 100, { digits: 0 })}%`,
      className: "consumable-hover-line-value-positive",
    });
    rows.push({ label: "Cooldown time", value: formatValue(consumable?.reload_time, { digits: 0, suffix: " s" }) });
  } else if (type === "smokeGenerator" || type === "planeSmokeGenerator") {
    rows.push({ label: "Action time", value: formatValue(consumable?.work_time, { digits: 0, suffix: " s" }) });
    rows.push({ label: "Smoke dispersion time", value: formatValue(consumable?.life_time, { digits: 0, suffix: " s" }) });
    rows.push({ label: "Smoke radius", value: formatValue(Number(consumable?.radius) * 30, { digits: 0, suffix: " m" }) });
    rows.push({ label: "Cooldown time", value: formatValue(consumable?.reload_time, { digits: 0, suffix: " s" }) });
  } else if (type === "sonar") {
    rows.push({ label: "Action time", value: formatValue(consumable?.work_time, { digits: 0, suffix: " s" }) });
    rows.push({ label: "Ship detection range", value: formatValue(detectionRangeKm(consumable?.dist_ship), { digits: 1, suffix: " km" }) });
    rows.push({ label: "Torpedo detection range", value: formatValue(detectionRangeKm(consumable?.dist_torpedo), { digits: 1, suffix: " km" }) });
    rows.push({ label: "Mine detection range", value: formatValue(detectionRangeKm(consumable?.dist_sea_mine), { digits: 1, suffix: " km" }) });
    rows.push({ label: "Cooldown time", value: formatValue(consumable?.reload_time, { digits: 0, suffix: " s" }) });
  } else if (type === "rls") {
    rows.push({ label: "Action time", value: formatValue(consumable?.work_time, { digits: 0, suffix: " s" }) });
    rows.push({ label: "Ship detection range", value: formatValue(detectionRangeKm(consumable?.dist_ship), { digits: 1, suffix: " km" }) });
    rows.push({ label: "Cooldown time", value: formatValue(consumable?.reload_time, { digits: 0, suffix: " s" }) });
  } else if (type === "healForsage") {
    pushActionCooldown();
  } else if (type === "speedBoosters") {
    rows.push({ label: "Action time", value: formatValue(consumable?.work_time, { digits: 0, suffix: " s" }) });
    rows.push({ label: "Maximum speed", value: positivePercentFromMultiplier(consumable?.boost_coeff) || "N/A", className: "consumable-hover-line-value-positive" });
    rows.push({ label: "Cooldown time", value: formatValue(consumable?.reload_time, { digits: 0, suffix: " s" }) });
  } else if (type === "airDefenseDisp") {
    rows.push({ label: "Action time", value: formatValue(consumable?.work_time, { digits: 0, suffix: " s" }) });
    rows.push({ label: "Continuous AA damage", value: positivePercentFromMultiplier(consumable?.area_damage_multiplier) || "N/A", className: "consumable-hover-line-value-positive" });
    rows.push({ label: "Flak damage", value: positivePercentFromMultiplier(consumable?.bubble_damage_multiplier) || "N/A", className: "consumable-hover-line-value-positive" });
    rows.push({ label: "Cooldown time", value: formatValue(consumable?.reload_time, { digits: 0, suffix: " s" }) });
  } else if (type === "artilleryBoosters") {
    rows.push({ label: "Action time", value: formatValue(consumable?.work_time, { digits: 0, suffix: " s" }) });
    rows.push({ label: "Reload time", value: positivePercentFromMultiplier(consumable?.boost_coeff) || "N/A", className: "consumable-hover-line-value-positive" });
    rows.push({ label: "Cooldown time", value: formatValue(consumable?.reload_time, { digits: 0, suffix: " s" }) });
  } else if (type === "torpedoReloader") {
    rows.push({ label: "Torpedo reload time", value: formatValue(consumable?.torpedo_reload_time, { digits: 0, suffix: " s" }) });
    rows.push({ label: "Cooldown time", value: formatValue(consumable?.reload_time, { digits: 0, suffix: " s" }) });
  } else if (type === "fighter" || type === "callFighters") {
    rows.push({ label: "Action time", value: formatValue(consumable?.work_time, { digits: 0, suffix: " s" }) });
    rows.push({ label: "Number of fighters", value: formatValue(consumable?.fighters_num, { digits: 0 }) });
    rows.push({ label: "Patrol radius", value: formatValue(Number(consumable?.radius) * 30, { digits: 0, suffix: " m" }) });
    rows.push({ label: "Reaction time", value: formatValue(consumable?.time_delay_attack, { digits: 1, suffix: " s" }) });
    rows.push({ label: "Cooldown time", value: formatValue(consumable?.reload_time, { digits: 0, suffix: " s" }) });
  } else if (type === "scout") {
    rows.push({ label: "Action time", value: formatValue(consumable?.work_time, { digits: 0, suffix: " s" }) });
    rows.push({ label: "Main battery range", value: positivePercentFromMultiplier(consumable?.artillery_dist_coeff) || "N/A", className: "consumable-hover-line-value-positive" });
    if (consumable?.gm_ideal_radius != null) {
      rows.push({ label: "Main battery dispersion", value: positivePercentFromMultiplier(consumable?.gm_ideal_radius) || "N/A", className: "consumable-hover-line-value-positive" });
    }
    rows.push({ label: "Cooldown time", value: formatValue(consumable?.reload_time, { digits: 0, suffix: " s" }) });
  } else if (type === "circleWave") {
    rows.push({ label: "Preparation time", value: formatValue(consumable?.preparation_time, { digits: 0, suffix: " s" }) });
    rows.push({ label: "Action time", value: formatValue(consumable?.work_time, { digits: 0, suffix: " s" }) });
    rows.push({ label: "Submarine detection range", value: formatValue(detectionRangeKm(consumable?.dist_ship), { digits: 1, suffix: " km" }) });
    rows.push({ label: "Cooldown time", value: formatValue(consumable?.reload_time, { digits: 0, suffix: " s" }) });
  } else if (type === "fastRudders") {
    rows.push({ label: "Action time", value: formatValue(consumable?.work_time, { digits: 0, suffix: " s" }) });
    rows.push({ label: "Diving plane shift time", value: positivePercentFromMultiplier(consumable?.buoyancy_rudder_time_coeff) || "N/A", className: "consumable-hover-line-value-positive" });
    rows.push({ label: "Maximum diving and ascent speed", value: positivePercentFromMultiplier(consumable?.max_buoyancy_speed_coeff) || "N/A", className: "consumable-hover-line-value-positive" });
    rows.push({ label: "Cooldown time", value: formatValue(consumable?.reload_time, { digits: 0, suffix: " s" }) });
  } else if (type === "subsEnergyFreeze") {
    rows.push({ label: "Action time", value: formatValue(consumable?.work_time, { digits: 0, suffix: " s" }) });
    rows.push({ label: "Cooldown time", value: formatValue(consumable?.reload_time, { digits: 0, suffix: " s" }) });
  } else if (type === "crashCrew") {
    pushActionCooldown();
  } else {
    pushActionCooldown();
  }
  return rows;
}

function renderConsumableCell(consumable, ownerShip = null) {
  if (!consumable) return `<span class="na-cell">N/A</span>`;
  const icon = consumable.icon
    ? `<img class="consumable-icon modal-consumable-choice-icon" src="${escapeHtml(consumable.icon)}" alt="${escapeHtml(consumable.display_name || consumable.id)}">`
    : `<div class="modal-consumable-choice-fallback">${escapeHtml(consumable.display_name || consumable.id)}</div>`;
  const charges = typeof consumable.num_consumables === "number" && consumable.num_consumables > 0
    ? `<span class="modal-consumable-count">${consumable.num_consumables}</span>`
    : "";
  return `
    <div class="consumable-cell consumable-cell-compact">
      <span class="modal-consumable-choice">
        ${icon}
        ${charges}
        ${renderConsumableTooltip(consumable, ownerShip)}
      </span>
    </div>
  `;
}

function hoverMetric(displayValue, rows) {
  return `
    <span class="detail-hover-wrap">
      <span class="detail-hover-trigger">${escapeHtml(displayValue)}</span>
      <span class="detail-hover-card">
        ${rows.map(([label, value]) => `
          <span class="detail-hover-line">
            <span class="detail-hover-line-label">${escapeHtml(label)}:</span>
            <span class="detail-hover-line-value">${escapeHtml(value)}</span>
          </span>
        `).join("")}
      </span>
    </span>
  `;
}

function repairPartyTotalHealed(consumable) {
  const rate = Number(consumable?.regeneration_hp_speed);
  const time = Number(consumable?.work_time);
  if (!Number.isFinite(rate) || !Number.isFinite(time)) return null;
  return rate * time * 100;
}

function consumableRatioPercent(value, digits = 1) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "N/A";
  return formatValue(numeric * 100, { digits, suffix: "%" });
}

function massHealSelfHpPerSecondDisplay(consumable, hp) {
  const rate = Number(consumable?.own_heal_part);
  if (!Number.isFinite(rate)) return "N/A";
  const percent = consumableRatioPercent(rate, 1);
  const hpPerSecond = Number(hp) * rate;
  if (!Number.isFinite(hpPerSecond)) return percent;
  return `${percent} (${formatValue(hpPerSecond, { digits: 0, grouping: true })})`;
}

function massHealSelfTotalHealed(consumable) {
  const rate = Number(consumable?.own_heal_part);
  const time = Number(consumable?.work_time);
  if (!Number.isFinite(rate) || !Number.isFinite(time)) return null;
  return rate * time * 100;
}

function massHealAllyTotalHealed(consumable) {
  const rate = Number(consumable?.ally_health_regen_percent);
  const time = Number(consumable?.work_time);
  if (!Number.isFinite(rate) || !Number.isFinite(time)) return null;
  return rate * time * 100;
}

function massHealRadiusKm(consumable) {
  const radius = Number(consumable?.work_radius);
  if (!Number.isFinite(radius)) return null;
  return (radius * 30) / 1000;
}

function massHealRadiusDisplay(consumable) {
  return formatValue(massHealRadiusKm(consumable), { digits: 1, suffix: " km" });
}

function consumableTableColumnsFor(consumable) {
  const type = consumable?.consumable_type;
  if (type === "crashCrew") return ["main", "time"];
  if (type === "regenCrew") return ["main", "time", "repair"];
  if (type === "massHeal") return ["main", "time", "repair", "allyHpSecond", "radius"];
  if (type === "smokeScreen" || type === "smokeGenerator") return ["main", "time", "dispersion", "radius"];
  if (type === "sonar") return ["main", "time", "range"];
  if (type === "rls") return ["main", "time", "range"];
  if (type === "engineBoost" || type === "speedBoosters") return ["main", "time", "speed"];
  if (type === "airDefenseDisp" || type === "boosterAA") return ["main", "time", "dps"];
  if (type === "artilleryBoosters" || type === "boosterGunner") return ["main", "time", "reload"];
  if (type === "torpedoReloader" || type === "fighter" || type === "callFighters" || type === "spotter" || type === "scout" || type === "fastRudders" || type === "reserveBattery" || type === "reserveBatteryUnit" || type === "weaponReloadBooster") return ["main"];
  return ["main", "time", "reload"];
}

function consumableTableColumnHeader(part) {
  const labels = {
    main: null,
    time: "Time",
    repair: "Repair %",
    allyHpSecond: "Ally HP/s",
    dispersion: "Dispersion",
    radius: "Radius",
    range: "Range",
    speed: "Speed",
    dps: "DPS",
    reload: "Reload",
  };
  return labels[part] || part;
}

function consumableTableCell(consumable, ownerShip, part) {
  if (!consumable) {
    return part === "main" ? `<span class="na-cell">N/A</span>` : "";
  }
  if (part === "main") return renderConsumableCell(consumable, ownerShip);
  if (part === "time") return formatValue(consumable?.work_time, { digits: 0, suffix: " s" });
  if (part === "reload") return formatValue(consumable?.reload_time, { digits: 0, suffix: " s" });
  if (part === "repair") {
    const total = consumable?.consumable_type === "massHeal"
      ? massHealSelfTotalHealed(consumable)
      : repairPartyTotalHealed(consumable);
    return formatPercent(total, { digits: 1 });
  }
  if (part === "allyHpSecond") return consumableRatioPercent(consumable?.ally_health_regen_percent, 1);
  if (part === "dispersion") return formatValue(consumable?.life_time, { digits: 0, suffix: " s" });
  if (part === "radius") {
    if (consumable?.consumable_type === "massHeal") return massHealRadiusDisplay(consumable);
    return formatValue(Number(consumable?.radius) * 30, { digits: 0, suffix: " m" });
  }
  if (part === "range") {
    if (consumable?.consumable_type === "sonar") {
      const shipRange = detectionRangeKm(consumable?.dist_ship);
      if (shipRange == null) return "N/A";
      return hoverMetric(
        formatValue(shipRange, { digits: 1, suffix: " km" }),
        [
          ["Ship", formatValue(shipRange, { digits: 1, suffix: " km" })],
          ["Torpedoes", formatValue(detectionRangeKm(consumable?.dist_torpedo), { digits: 1, suffix: " km" })],
        ],
      );
    }
    return formatValue(detectionRangeKm(consumable?.dist_ship), { digits: 1, suffix: " km" });
  }
  if (part === "speed") return positivePercentFromMultiplier(consumable?.boost_coeff) || "N/A";
  if (part === "dps") {
    const area = positivePercentFromMultiplier(consumable?.area_damage_multiplier) || "N/A";
    return hoverMetric(area, [
      ["Continuous AA damage", area],
      ["Flak damage", positivePercentFromMultiplier(consumable?.bubble_damage_multiplier) || "N/A"],
    ]);
  }
  return "";
}

function renderConsumablesTable(title, ships) {
  const columns = [];
  const consumablesByShip = new Map();
  ships.forEach((ship) => {
    const consumableMap = new Map();
    allConsumables(ship).forEach((consumable) => {
      const key = consumableColumnKey(consumable);
      consumableMap.set(key, consumable);
      if (!columns.some((column) => column.key === key)) {
        columns.push({ key, label: consumableColumnLabel(consumable), parts: consumableTableColumnsFor(consumable) });
      }
    });
    consumablesByShip.set(ship.identity.code, consumableMap);
  });
  const consumableOrder = [
  "Damage con.",
  "Repair party",
  "Mass heal",
  "Smoke",
  "Hydro",
  "Radar",
  "Engine boost",
  "DFAA",
  "MBRB",
  "TRB",
  "Fighter",
  "Spotter",
  "Enhanced rudder",
  "Res. Unit",
];

columns.sort((a, b) => {
  const ai = consumableOrder.indexOf(a.label);
  const bi = consumableOrder.indexOf(b.label);
  const av = ai === -1 ? 999 : ai;
  const bv = bi === -1 ? 999 : bi;
  return av - bv || a.label.localeCompare(b.label);
});

  const baseRows = [
    { label: "Ship", render: (ship) => `<button type="button" class="param-ship-link" data-open-ship="${escapeHtml(ship.identity.code)}">${escapeHtml(ship.displayName)}</button>`, sortValue: (ship) => ship.displayName, sortType: "text" },
    { label: "Tier", render: (ship) => ship.identity.tier, sortValue: (ship) => ship.identity.tier, sortType: "number" },
    { label: "Class", render: (ship) => escapeHtml(localizedDisplayClass(ship)), sortValue: (ship) => displayClass(ship), sortType: "text" },
    { label: "Nation", render: (ship) => escapeHtml(localizedNationLabel(ship)), sortValue: (ship) => ship.nationLabel, sortType: "text" },
  ];
  const columnRows = columns.flatMap((column, columnIndex) => ([
    ...column.parts.map((part) => ({
      label: part === "main" ? column.label : consumableTableColumnHeader(part),
      groupIndex: columnIndex,
      groupPart: part,
      render: (ship) => {
        const consumable = consumablesByShip.get(ship.identity.code)?.get(column.key);
        return consumableTableCell(consumable, ship, part);
      },
      sortValue: (ship) => {
        const consumable = consumablesByShip.get(ship.identity.code)?.get(column.key);
        if (!consumable) return null;
        if (part === "main") return consumable.display_name || consumable.id;
        if (part === "time") return consumable.work_time ?? null;
        if (part === "reload") return consumable.reload_time ?? null;
        if (part === "repair") return consumable.consumable_type === "massHeal" ? massHealSelfTotalHealed(consumable) : repairPartyTotalHealed(consumable);
        if (part === "allyHpSecond") return consumable.ally_health_regen_percent ?? null;
        if (part === "dispersion") return consumable.life_time ?? null;
        if (part === "radius") return consumable.consumable_type === "massHeal" ? massHealRadiusKm(consumable) : Number(consumable.radius) * 30 || null;
        if (part === "range") return detectionRangeKm(consumable.dist_ship);
        if (part === "speed") return consumable.boost_coeff ?? null;
        if (part === "dps") return consumable.area_damage_multiplier ?? null;
        return null;
      },
      sortType: part === "main" ? "text" : "number",
    })),
  ]));
  const finalRows = [...baseRows, ...columnRows];
  const sortedShips = sortShipsForTable(title, ships, finalRows);
  const baseColumnCount = baseRows.length;
  const head = finalRows
    .map((row, index) => {
      const classes = [];
      if (index >= baseColumnCount && row.groupPart === "main") classes.push("consumables-divider-col");
      if (row.groupPart) classes.push(`consumables-col-${row.groupPart}`);
      const active = state.parameterSort?.group === title && state.parameterSort?.label === row.label;
      const direction = active ? state.parameterSort.direction : null;
      const arrow = direction === "asc" ? " &#9650;" : direction === "desc" ? " &#9660;" : "";
      return `<th class="${escapeHtml(classes.join(" "))}"><button type="button" class="param-sort-button ${active ? "active" : ""}" data-sort-group="${escapeHtml(title)}" data-sort-label="${escapeHtml(row.label)}" data-sort-type="${escapeHtml(row.sortType || "auto")}">${escapeHtml(row.label)}${arrow}</button></th>`;
    })
    .join("");
  const body = sortedShips
    .map((ship, index) => `
      <tr>
        <td>${index + 1}</td>
        ${finalRows.map((row, rowIndex) => {
          const classes = [];
          if (rowIndex >= baseColumnCount && row.groupPart === "main") classes.push("consumables-divider-col");
          if (row.groupPart) classes.push(`consumables-col-${row.groupPart}`);
          return `<td class="${escapeHtml(classes.join(" "))}">${row.render(ship)}</td>`;
        }).join("")}
      </tr>
    `)
    .join("");

  return `
    <section class="parameter-section">
      <h3>${uiLabel(title)}</h3>
      <div class="param-table-wrap consumables-table-wrap">
        <table class="param-table consumables-table">
          <thead>
            <tr>
              <th>#</th>
              ${head}
            </tr>
          </thead>
          <tbody>${body}</tbody>
        </table>
      </div>
    </section>
  `;
}

function normalizeSortValue(value) {
  if (value === null || value === undefined || value === "" || value === "N/A") return null;
  if (typeof value === "number") return value;
  if (typeof value === "boolean") return value ? 1 : 0;
  const text = `${value}`.trim();
  const numeric = text.replace(/,/g, "").match(/^-?\d+(?:\.\d+)?/);
  if (numeric) return Number(numeric[0]);
  return text.toLowerCase();
}

function parameterExtremeDirection(row) {
  if (!row || row.sortType === "text" || PARAMETER_EXTREME_EXCLUDED_LABELS.has(row.label)) return null;
  const label = `${row.label || ""}`.toLowerCase();
  if (
    PARAMETER_LOW_IS_GOOD_LABELS.has(row.label)
    || label.includes("detect")
    || label.includes("reload")
    || label.includes("180")
    || label.includes("turning radius")
    || label.includes("rudder")
    || label.includes("dispersion")
    || label.includes("flight time")
    || label.includes("impact angle")
    || label.includes("acceleration")
    || label.includes("reaction time")
    || label.includes("sector time")
    || label.includes("cooldown")
    || label.includes("fuse time")
    || label.includes("depletion")
  ) {
    return "low";
  }
  return "high";
}

function parameterExtremeState(row, ship, ships, context = null) {
  if (!state.parameterExtremeHighlight || !row?.sortValue || !Array.isArray(ships) || ships.length < 2) return "";
  const direction = parameterExtremeDirection(row);
  if (!direction) return "";
  const values = ships
    .map((item) => ({ ship: item, value: normalizeSortValue(row.sortValue(item, context)) }))
    .filter((item) => typeof item.value === "number" && Number.isFinite(item.value));
  if (values.length < 2) return "";
  const unique = new Set(values.map((item) => item.value));
  if (unique.size < 2) return "";
  const bestValue = direction === "low"
    ? Math.min(...values.map((item) => item.value))
    : Math.max(...values.map((item) => item.value));
  const worstValue = direction === "low"
    ? Math.max(...values.map((item) => item.value))
    : Math.min(...values.map((item) => item.value));
  const current = values.find((item) => item.ship === ship)?.value;
  if (current == null) return "";
  if (current === bestValue) return "best";
  if (current === worstValue) return "worst";
  return "";
}

function parameterExtremeStateMaps(rows, ships, context = null) {
  if (!state.parameterExtremeHighlight) return new Map();
  const result = new Map();
  rows.forEach((row) => {
    const direction = parameterExtremeDirection(row);
    if (!direction || !row?.sortValue) return;
    const values = ships
      .map((ship) => ({ ship, value: normalizeSortValue(row.sortValue(ship, context)) }))
      .filter((item) => typeof item.value === "number" && Number.isFinite(item.value));
    if (values.length < 2 || new Set(values.map((item) => item.value)).size < 2) return;
    const numbers = values.map((item) => item.value);
    const bestValue = direction === "low" ? Math.min(...numbers) : Math.max(...numbers);
    const worstValue = direction === "low" ? Math.max(...numbers) : Math.min(...numbers);
    const rowMap = new Map();
    values.forEach((item) => {
      if (item.value === bestValue) rowMap.set(item.ship, "best");
      if (item.value === worstValue) rowMap.set(item.ship, "worst");
    });
    result.set(row, rowMap);
  });
  return result;
}

function defaultSortDirection(row) {
  return row.sortType === "text" ? "asc" : "desc";
}

function compareSortValues(left, right, direction) {
  if (left == null && right == null) return 0;
  if (left == null) return 1;
  if (right == null) return -1;
  if (typeof left === "number" && typeof right === "number") {
    return direction === "asc" ? left - right : right - left;
  }
  return direction === "asc"
    ? `${left}`.localeCompare(`${right}`)
    : `${right}`.localeCompare(`${left}`);
}

function sortShipsForTable(title, ships, rows, context = null) {
  const sort = state.parameterSort;
  if (!sort || sort.group !== title) return [...ships];
  const row = rows.find((item) => item.label === sort.label);
  if (!row) return [...ships];
  return [...ships].sort((left, right) => {
    const a = normalizeSortValue(row.sortValue(left, context));
    const b = normalizeSortValue(row.sortValue(right, context));
    const diff = compareSortValues(a, b, sort.direction);
    if (diff !== 0) return diff;
    return left.displayName.localeCompare(right.displayName);
  });
}

function renderSortHeader(group, row, context = null) {
  const active = state.parameterSort?.group === group && state.parameterSort?.label === row.label;
  const direction = active ? state.parameterSort.direction : null;
  const arrow = direction === "asc" ? " &#9650;" : direction === "desc" ? " &#9660;" : "";
  return `<th${row.headerClass ? ` class="${escapeHtml(row.headerClass)}"` : ""}><button type="button" class="param-sort-button ${active ? "active" : ""}" data-sort-group="${escapeHtml(group)}" data-sort-label="${escapeHtml(row.label)}" data-sort-type="${escapeHtml(row.sortType || "auto")}">${statHelpLabelHtml(row.headerLabel || row.label, group, context)}${arrow}</button></th>`;
}

let cachedParameterDefinitions = null;

function parameterDefinitions() {
  if (!cachedParameterDefinitions) {
    cachedParameterDefinitions = [
    {
      label: "General",
      available: () => true,
      rows: [
        { label: "Year", modalLabel: (ship) => modalYearLabel(ship), render: (ship) => formatYearLabel(ship.identity.year_label), sortValue: (ship) => sortYearValue(ship.identity.year_label), sortType: "number" },
        ["Length", (ship) => formatValue(ship.mobility?.length_m, { digits: 1, suffix: " m" })],
        ["Beam", (ship) => formatValue(ship.mobility?.beam_m, { digits: 1, suffix: " m" })],
        ["Tonnage", (ship) => formatValue(ship.mobility?.tonnage_t, { digits: 0, suffix: " t", grouping: true })],
        ["Detect. by sea", (ship) => formatValue(ship.mobility?.detect_by_sea_km, { digits: 2, suffix: " km" })],
        ["Detect. by air", (ship) => formatValue(ship.mobility?.detect_by_air_km, { digits: 2, suffix: " km" })],
        ["Power / weight", (ship) => formatValue(ship.mobility?.power_to_weight_hp_t, { digits: 2, suffix: " hp/t" })],
        ["Max speed", (ship) => formatValue(ship.mobility?.max_speed_kn, { digits: 1, suffix: " kn" })],
        { label: "Acceleration", render: (ship) => accelerationDisplay(ship), sortValue: (ship) => shipAccelerationSeconds(ship), sortType: "number" },
        ["Rudder shift", (ship) => formatValue(ship.mobility?.rudder_shift_s, { digits: 1, suffix: " s" })],
        ["Turning radius", (ship) => formatValue(ship.mobility?.turning_radius_m, { digits: 0, suffix: " m", grouping: true })],
          {
            label: "Combat instruction",
            render: (ship) => hasCombatInstruction(ship) ? "O" : "N/A",
            sortValue: (ship) => hasCombatInstruction(ship) ? 1 : 0,
            sortType: "number",
            visibleWhen: (ships) => ships.some((ship) => hasCombatInstruction(ship)),
            tableOnly: true,
            headerClass: "combat-instruction-col",
            cellClass: "combat-instruction-col",
          },
      ],
    },
    {
      label: "Survivability",
      available: (ship) => ship.survivability?.hp != null,
      rows: [
        ["Health", (ship) => formatValue(ship.survivability?.hp, { digits: 0, grouping: true })],
        ["Repair %", (ship) => formatPercent(ship.survivability?.repair_percent, { scale: 100 })],
        {
          label: "Cit. repair %",
          render: (ship) => formatPercent(ship.survivability?.citadel_repair_percent, { scale: 100 }),
          sortValue: (ship) => ship.survivability?.citadel_repair_percent,
          sortType: "number",
          visibleWhen: (ships) => ships.some((ship) => ship.survivability?.citadel_repair_percent != null),
        },
        ["Fire resist.", (ship) => formatPercent(ship.survivability?.fire_resistance, { scale: 100 })],
        ["Fire duration", (ship) => formatValue(ship.survivability?.fire_duration_s, { digits: 0, suffix: " s" })],
        ["Fire damage", (ship) => formatPercent(ship.survivability?.fire_damage_fraction, { digits: 1 })],
        ["No of fires", (ship) => formatValue(ship.survivability?.fire_count, { digits: 0 })],
        ["Torpedo protection", (ship) => formatPercent(ship.survivability?.torpedo_protection_percent, { scale: 100 })],
        ["Flood duration", (ship) => formatValue(ship.survivability?.flood_duration_s, { digits: 0, suffix: " s" })],
        ["Flooding damage", (ship) => formatPercent(ship.survivability?.flood_damage_fraction, { digits: 1 })],
        ["No of floodings", (ship) => formatValue(ship.survivability?.flood_count, { digits: 0 })],
      ],
    },
    {
      label: "Diving",
      available: (ship) => ship.diving?.dive_capacity != null,
      rows: [
        ["Detectability", (ship) => formatValue(ship.diving?.detectability_km, { digits: 2, suffix: " km" })],
        ["Submerged speed", (ship) => formatValue(ship.diving?.submerged_speed_kn, { digits: 1, suffix: " kn" })],
        ["Diving plane shift", (ship) => formatValue(ship.diving?.diving_plane_shift_s, { digits: 1, suffix: " s" })],
        ["Dive speed", (ship) => formatValue(ship.diving?.dive_speed_ms, { digits: 1, suffix: " m/s" })],
        ["Dive capacity", (ship) => formatValue(ship.diving?.dive_capacity, { digits: 0 })],
        ["Depletion rate", (ship) => formatValue(ship.diving?.depletion_rate, { digits: 2 })],
        ["Recharge rate", (ship) => formatValue(ship.diving?.recharge_rate, { digits: 2 })],
      ],
    },
      {
        label: "Main battery",
        available: (ship) => ship.artillery?.main_battery?.gun_count != null,
        rows: [
          { label: "Description", render: (ship) => mainBatteryDescription(ship), sortValue: (ship) => mainBatteryDescription(ship), sortType: "text" },
          { label: "AP DPM", render: (ship) => formatValue(mainBatteryDpm(ship, "AP"), { digits: 0, grouping: true }), sortValue: (ship) => mainBatteryDpm(ship, "AP"), sortType: "number", visibleWhen: (ships) => ships.some((ship) => hasMainBatteryAmmo(ship, "AP")) },
          { label: "HE DPM", render: (ship) => formatValue(mainBatteryDpm(ship, "HE"), { digits: 0, grouping: true }), sortValue: (ship) => mainBatteryDpm(ship, "HE"), sortType: "number", visibleWhen: (ships) => ships.some((ship) => hasMainBatteryAmmo(ship, "HE")) },
          { label: "SAP DPM", render: (ship) => formatValue(mainBatteryDpm(ship, "SAP"), { digits: 0, grouping: true }), sortValue: (ship) => mainBatteryDpm(ship, "SAP"), sortType: "number", visibleWhen: (ships) => ships.some((ship) => hasMainBatteryAmmo(ship, "SAP")) },
          { label: "AP salvo", render: (ship) => formatValue(mainBatterySalvo(ship, "AP"), { digits: 0, grouping: true }), sortValue: (ship) => mainBatterySalvo(ship, "AP"), sortType: "number", visibleWhen: (ships) => ships.some((ship) => hasMainBatteryAmmo(ship, "AP")) },
          { label: "HE salvo", render: (ship) => formatValue(mainBatterySalvo(ship, "HE"), { digits: 0, grouping: true }), sortValue: (ship) => mainBatterySalvo(ship, "HE"), sortType: "number", visibleWhen: (ships) => ships.some((ship) => hasMainBatteryAmmo(ship, "HE")) },
          { label: "SAP salvo", render: (ship) => formatValue(mainBatterySalvo(ship, "SAP"), { digits: 0, grouping: true }), sortValue: (ship) => mainBatterySalvo(ship, "SAP"), sortType: "number", visibleWhen: (ships) => ships.some((ship) => hasMainBatteryAmmo(ship, "SAP")) },
          { label: "Range", render: (ship) => formatDistanceMeters(ship.artillery?.main_battery?.range_m), sortValue: (ship) => ship.artillery?.main_battery?.range_m, sortType: "number" },
          { label: "Reload", render: (ship) => mainBatteryReloadDisplay(ship), sortValue: (ship) => mainBatteryDisplayedReloadValue(ship), sortType: "number" },
          {
            label: "No. of Salvo Series",
            render: (ship) => formatValue(mainBatterySalvoSeriesCount(ship), { digits: 0 }),
            sortValue: (ship) => mainBatterySalvoSeriesCount(ship),
            sortType: "number",
            visibleWhen: (ships) => ships.some((ship) => mainBatterySalvoSeriesCount(ship) != null),
            headerClass: "salvo-series-col",
            cellClass: "salvo-series-col",
          },
          { label: "180\u00b0 turn", render: (ship) => formatValue(mainBatteryTurn180(ship), { digits: 1, suffix: " s" }), sortValue: (ship) => mainBatteryTurn180(ship), sortType: "number" },
        { label: "Hor. dispersion", render: (ship, context) => mainBatteryDispersionDisplay(ship, context, "horizontal"), sortValue: (ship, context) => horizontalDispersionMeters(mainBatteryModule(ship), context?.range_m), sortType: "number" },
        { label: "Ver. dispersion", render: (ship, context) => mainBatteryDispersionDisplay(ship, context, "vertical"), sortValue: (ship, context) => verticalDispersionMeters(mainBatteryModule(ship), context?.range_m), sortType: "number" },
        { label: "Sigma", render: (ship) => formatSigma(ship.artillery?.main_battery?.sigma_count), sortValue: (ship) => ship.artillery?.main_battery?.sigma_count, sortType: "number" },
        { label: "Flight time", render: (ship, context) => mainBatteryFlightTimeDisplay(ship, context), sortValue: (ship, context) => {
          const values = mainBatteryResultsAtRange(ship, context).map((result) => result.time_s).filter((value) => typeof value === "number");
          return values.length ? Math.max(...values) : null;
        }, sortType: "number" },
        { label: "Shells / min", render: (ship) => formatValue(mainBatteryShellsPerMinute(ship), { digits: 1 }), sortValue: (ship) => mainBatteryShellsPerMinute(ship), sortType: "number" },
      ],
    },
    {
      label: "Medium guns",
      available: (ship) => mediumBatteryModules(ship).length > 0,
      rows: [
        { label: "Description", render: (ship) => mediumBatteryDescription(ship), sortValue: (ship) => mediumBatteryDescription(ship), sortType: "text" },
        { label: "DPM", modalLabel: (ship) => `${mediumBatteryAmmoPrefix(mediumBatteryProjectile(ship))} DPM`, render: (ship) => formatValue(mediumBatteryDpm(ship), { digits: 0, grouping: true }), sortValue: (ship) => mediumBatteryDpm(ship), sortType: "number" },
        { label: "Salvo", modalLabel: (ship) => `${mediumBatteryAmmoPrefix(mediumBatteryProjectile(ship))} salvo`, render: (ship) => formatValue(mediumBatterySalvo(ship), { digits: 0, grouping: true }), sortValue: (ship) => mediumBatterySalvo(ship), sortType: "number" },
        { label: "Range", render: (ship) => formatDistanceMeters(mediumBattery(ship)?.range_m), sortValue: (ship) => mediumBattery(ship)?.range_m, sortType: "number" },
        { label: "Reload", render: (ship) => formatValue(mediumBatteryReloadSeconds(ship), { digits: 1, suffix: " s" }), sortValue: (ship) => mediumBatteryReloadSeconds(ship), sortType: "number" },
        { label: "Full reload time", render: (ship) => formatValue(mediumBatteryDrum(ship)?.full_reload_time, { digits: 1, suffix: " s" }), sortValue: (ship) => mediumBatteryDrum(ship)?.full_reload_time, sortType: "number", visibleWhen: (ships) => ships.some((ship) => Number.isFinite(Number(mediumBatteryDrum(ship)?.full_reload_time))) },
        { label: "Salvo interval", render: (ship) => formatValue(mediumBatteryDrum(ship)?.shot_delay, { digits: 2, suffix: " s" }), sortValue: (ship) => mediumBatteryDrum(ship)?.shot_delay, sortType: "number", visibleWhen: (ships) => ships.some((ship) => Number.isFinite(Number(mediumBatteryDrum(ship)?.shot_delay))) },
        { label: "Salvos in series", render: (ship) => formatValue(mediumBatteryDrum(ship)?.shots_count, { digits: 0 }), sortValue: (ship) => mediumBatteryDrum(ship)?.shots_count, sortType: "number", visibleWhen: (ships) => ships.some((ship) => Number.isFinite(Number(mediumBatteryDrum(ship)?.shots_count))) },
        { label: "Sigma", render: (ship) => formatSigma(mediumBattery(ship)?.sigma_count), sortValue: (ship) => mediumBattery(ship)?.sigma_count, sortType: "number" },
        { label: "180 turn", render: (ship) => formatValue(mediumBatteryTurn180(ship), { digits: 1, suffix: " s" }), sortValue: (ship) => mediumBatteryTurn180(ship), sortType: "number" },
        { label: "Penetration", render: (ship) => formatValue(mediumBatteryPenetration(ship), { digits: 0, suffix: " mm" }), sortValue: (ship) => mediumBatteryPenetration(ship), sortType: "number" },
        { label: "Fire chance", render: (ship) => formatPercent(mediumBatteryFireChance(ship), { scale: 100 }), sortValue: (ship) => mediumBatteryFireChance(ship), sortType: "number", visibleWhen: (ships) => ships.some((ship) => mediumBatteryFireChance(ship) != null) },
        { label: "Shells/min", render: (ship) => formatValue(mediumBatteryShellsPerMinute(ship), { digits: 1 }), sortValue: (ship) => mediumBatteryShellsPerMinute(ship), sortType: "number" },
      ],
    },
    {
      label: "AP Shells",
      available: (ship) => firstProjectile(ship, "AP") != null,
      rows: [
        ["Description", (ship) => shellDescription(firstProjectile(ship, "AP"))],
        ["Weight", (ship) => formatValue(firstProjectile(ship, "AP")?.bullet_mass, { digits: 0, grouping: true, suffix: " kg" })],
        ["Damage", (ship) => formatValue(firstProjectile(ship, "AP")?.alpha_damage, { digits: 0, grouping: true })],
        ["Initial speed", (ship) => formatValue(firstProjectile(ship, "AP")?.bullet_speed, { digits: 0, suffix: " m/s" })],
        ["Drag coeff.", (ship) => formatValue(firstProjectile(ship, "AP")?.bullet_air_drag, { digits: 3 })],
        ["Flight time", (ship, context) => shellFlightTimeDisplay(ship, firstProjectile(ship, "AP"), context, "AP Shells")],
        ["Impact speed", (ship, context) => shellImpactSpeedDisplay(ship, firstProjectile(ship, "AP"), context, "AP Shells")],
        ["Impact angle", (ship, context) => shellImpactAngleDisplay(ship, firstProjectile(ship, "AP"), context, "AP Shells")],
        ["Krupp", (ship) => formatValue(firstProjectile(ship, "AP")?.krupp, { digits: 0, grouping: true })],
        ["Penetration", (ship, context) => shellPenetrationDisplay(ship, firstProjectile(ship, "AP"), context, "AP Shells")],
        ["Overmatch", (ship) => formatValue(shellOvermatch(firstProjectile(ship, "AP")), { digits: 0, suffix: " mm" })],
        ["Ricochet", (ship) => shellRicochet(firstProjectile(ship, "AP"))],
        ["Threshold", (ship) => formatValue(firstProjectile(ship, "AP")?.detonator_threshold, { digits: 0, suffix: " mm" })],
        ["Fuse time", (ship) => formatValue(firstProjectile(ship, "AP")?.detonator, { digits: 3, suffix: " s" })],
      ],
    },
    {
      label: "HE Shells",
      available: (ship) => firstProjectile(ship, "HE") != null,
      rows: [
        ["Description", (ship) => shellDescription(firstProjectile(ship, "HE"))],
        ["Weight", (ship) => formatValue(firstProjectile(ship, "HE")?.bullet_mass, { digits: 0, grouping: true, suffix: " kg" })],
        ["Damage", (ship) => formatValue(firstProjectile(ship, "HE")?.alpha_damage, { digits: 0, grouping: true })],
        ["Initial speed", (ship) => formatValue(firstProjectile(ship, "HE")?.bullet_speed, { digits: 0, suffix: " m/s" })],
        ["Drag coeff.", (ship) => formatValue(firstProjectile(ship, "HE")?.bullet_air_drag, { digits: 3 })],
        ["Flight time", (ship, context) => shellFlightTimeDisplay(ship, firstProjectile(ship, "HE"), context, "HE Shells")],
        ["Impact speed", (ship, context) => shellImpactSpeedDisplay(ship, firstProjectile(ship, "HE"), context, "HE Shells")],
        ["Impact angle", (ship, context) => shellImpactAngleDisplay(ship, firstProjectile(ship, "HE"), context, "HE Shells")],
        ["Penetration", (ship) => formatValue(firstProjectile(ship, "HE")?.alpha_piercing_he, { digits: 0, suffix: " mm" })],
        {
          label: "Fire chance",
          render: (ship) => fireChanceDisplay(firstProjectile(ship, "HE")?.burn_prob, { scale: 100 }),
          sortValue: (ship) => positiveRatioValue(firstProjectile(ship, "HE")?.burn_prob),
          sortType: "number",
          visibleWhen: (ships) => ships.some((ship) => positiveRatioValue(firstProjectile(ship, "HE")?.burn_prob) != null),
        },
        ["Fires / min", (ship) => formatValue(shellFirePerMinute(ship, firstProjectile(ship, "HE")), { digits: 1 })],
      ],
    },
    {
      label: "SAP Shells",
      available: (ship) => firstProjectile(ship, "SAP") != null,
      rows: [
        ["Description", (ship) => shellDescription(firstProjectile(ship, "SAP"))],
        ["Weight", (ship) => formatValue(firstProjectile(ship, "SAP")?.bullet_mass, { digits: 0, grouping: true, suffix: " kg" })],
        ["Damage", (ship) => formatValue(firstProjectile(ship, "SAP")?.alpha_damage, { digits: 0, grouping: true })],
        ["Initial speed", (ship) => formatValue(firstProjectile(ship, "SAP")?.bullet_speed, { digits: 0, suffix: " m/s" })],
        ["Drag coeff.", (ship) => formatValue(firstProjectile(ship, "SAP")?.bullet_air_drag, { digits: 3 })],
        ["Flight time", (ship, context) => shellFlightTimeDisplay(ship, firstProjectile(ship, "SAP"), context, "SAP Shells")],
        ["Impact speed", (ship, context) => shellImpactSpeedDisplay(ship, firstProjectile(ship, "SAP"), context, "SAP Shells")],
        ["Impact angle", (ship, context) => shellImpactAngleDisplay(ship, firstProjectile(ship, "SAP"), context, "SAP Shells")],
        ["Penetration", (ship) => formatValue(firstProjectile(ship, "SAP")?.alpha_piercing_cs, { digits: 0, suffix: " mm" })],
        ["Ricochet", (ship) => shellRicochet(firstProjectile(ship, "SAP"))],
        ["Threshold", (ship) => formatValue(firstProjectile(ship, "SAP")?.detonator_threshold, { digits: 0, suffix: " mm" })],
      ],
    },
    {
      label: "Sonar",
      available: (ship) => ship.sonar?.range_m != null,
      rows: [
        ["Range", (ship) => formatDistanceMeters(ship.sonar?.range_m)],
        ["Reload", (ship) => formatValue(ship.sonar?.reload_s, { digits: 1, suffix: " s" })],
        ["Wave speed", (ship) => formatValue(ship.sonar?.wave_speed, { digits: 0, suffix: " m/s" })],
      ],
    },
    {
      label: "Secondaries",
      available: (ship) => secondaryGunModules(ship).length > 0,
      rows: [
        ["Description", (ship) => secondaryDescription(ship, { color: false })],
        { label: "Secondary DPM", render: (ship) => secondaryDpmDisplay(ship), sortValue: (ship) => secondaryDpm(ship), sortType: "number" },
        { label: "DPM contribution", render: (ship) => secondaryDpmContributionDisplay(ship) },
        ["Range", (ship) => formatDistanceMeters(secondaryModule(ship)?.range_m ?? secondaryModule(ship)?.max_dist_m)],
        { label: "Reload", render: (ship) => secondaryRangeStat(ship, (group) => group?.reload_s, (value) => formatValue(value, { digits: 1, suffix: " s" }), { digits: 1 }), sortValue: (ship) => secondaryModule(ship)?.reload_s ?? null, sortType: "number" },
        ["Flight time", (ship, context) => secondariesFlightTimeDisplay(ship, context)],
        ["Hor. dispersion", (ship, context) => secondariesDispersionDisplay(ship, context)],
        ["Sigma", (ship) => formatSigma(secondarySigma(ship))],
        ["Penetration", (ship, context) => secondaryRangeStat(ship, (group) => secondaryPenetrationValue(ship, group, context), (value) => formatValue(value, { digits: 0, suffix: " mm" }), { digits: 0 })],
        {
          label: "Fire chance",
          render: (ship) => secondaryRangeStat(ship, (group) => {
            const burnProb = positiveRatioValue(group?.projectile?.burn_prob);
            return burnProb == null ? null : burnProb * 100;
          }, (value) => formatValue(value, { digits: 0, suffix: "%" }), { digits: 0 }),
          visibleWhen: (ships) => ships.some((ship) => secondaryUsesFire(ship)),
        },
        {
          label: "Fires / min",
          render: (ship) => secondaryTotalStat(ship, (group) => secondaryGroupFirePerMinute(group), {
          formatter: (value) => formatValue(value, { digits: 1 }),
          detailFormatter: (value) => formatValue(value, { digits: 1 }),
          }),
          visibleWhen: (ships) => ships.some((ship) => secondaryUsesFire(ship)),
        },
        { label: "Shells / min", render: (ship) => secondaryBroadsideStatDisplay(ship, (module) => secondaryModuleShellsPerMinuteValue(module), {
          formatter: (value) => formatValue(value, { digits: 1 }),
          detailFormatter: (value) => formatValue(value, { digits: 1 }),
        }), sortValue: (ship) => secondariesShellsPerMinute(ship), sortType: "number" },
      ],
    },
    {
      label: "Torpedoes",
      available: (ship) => torpedoModules(ship).length > 0,
      rows: [
        ["Description", (ship) => torpedoDescription(ship)],
        ["Type", (ship) => torpedoTypeDisplay(firstTorpedoProjectile(ship))],
        {
          label: "Loaders",
          render: (ship) => torpedoLoaders(ship),
          sortValue: (ship) => torpedoLoaders(ship),
          sortType: "text",
          visibleWhen: (ships) => ships.some((ship) => {
            const loaders = resolvedShipView(ship).torpedoes?.loaders;
            return Array.isArray(loaders) && loaders.length;
          }),
        },
        ["Damage", (ship) => formatValue(torpedoEffectiveDamage(ship), { digits: 0, grouping: true })],
        ["Torpedo DPM", (ship) => formatValue(torpedoDpm(ship), { digits: 0, grouping: true })],
        ["Range", (ship) => firstTorpedoProjectile(ship)?.max_dist != null ? formatValue(firstTorpedoProjectile(ship)?.max_dist * 0.03, { digits: 1, suffix: " km" }) : "N/A"],
        ["Flood chance", (ship) => formatPercent(firstTorpedoProjectile(ship)?.uw_critical, { scale: 100 })],
        {
          label: "Fire chance",
          render: (ship) => torpedoFireChanceDisplay(firstTorpedoProjectile(ship)),
          sortValue: (ship) => {
            const value = positiveRatioValue(firstTorpedoProjectile(ship)?.burn_prob);
            return value == null ? null : value * 100;
          },
          sortType: "number",
          visibleWhen: (ships) => ships.some((ship) => isThermalTorpedoProjectile(firstTorpedoProjectile(ship))),
        },
        ["Reload", (ship) => formatValue(torpedoReloadSeconds(ship), { digits: 1, suffix: " s" })],
        ["Speed", (ship) => formatValue(firstTorpedoProjectile(ship)?.speed, { digits: 0, suffix: " kn" })],
        ["Detectability", (ship) => formatValue(firstTorpedoProjectile(ship)?.visibility_factor, { digits: 1, suffix: " km" })],
        ["Reaction time", (ship) => formatValue(torpedoReactionTime(ship), { digits: 1, suffix: " s" })],
        { label: "Torpedo/min", render: (ship) => formatValue(torpedoesPerMinute(ship), { digits: 1 }), sortValue: (ship) => torpedoesPerMinute(ship), sortType: "number" },
      ],
    },
      {
        label: "Anti-aircraft",
        available: (ship) => (ship.anti_air?.auras?.length || 0) > 0,
        rows: [
          { label: "Long range", modalLabelClass: "modal-stat-label-strong", render: (ship) => aaRangeDisplay(ship.anti_air?.long_range_m), sortValue: (ship) => ship.anti_air?.long_range_m, sortType: "number", visibleWhen: (ships) => ships.some((ship) => ship.anti_air?.long_range_m != null) },
          { label: "Long DPS", render: (ship) => aaDpsDisplay(ship.anti_air?.long_dps), sortValue: (ship) => ship.anti_air?.long_dps, sortType: "number", visibleWhen: (ships) => ships.some((ship) => ship.anti_air?.long_dps != null) },
          { label: "Long Hit Chance", headerLabel: "Hit Chance", modalLabel: "Hit Chance", render: (ship) => aaHitChanceDisplay(ship.anti_air?.long_hit_chance), sortValue: (ship) => ship.anti_air?.long_hit_chance, sortType: "number", visibleWhen: (ships) => ships.some((ship) => ship.anti_air?.long_hit_chance != null) },
          { label: "Medium range", modalLabelClass: "modal-stat-label-strong", render: (ship) => aaRangeDisplay(ship.anti_air?.medium_range_m), sortValue: (ship) => ship.anti_air?.medium_range_m, sortType: "number", visibleWhen: (ships) => ships.some((ship) => ship.anti_air?.medium_range_m != null) },
          { label: "Medium DPS", render: (ship) => aaDpsDisplay(ship.anti_air?.medium_dps), sortValue: (ship) => ship.anti_air?.medium_dps, sortType: "number", visibleWhen: (ships) => ships.some((ship) => ship.anti_air?.medium_dps != null) },
          { label: "Medium Hit Chance", headerLabel: "Hit Chance", modalLabel: "Hit Chance", render: (ship) => aaHitChanceDisplay(ship.anti_air?.medium_hit_chance), sortValue: (ship) => ship.anti_air?.medium_hit_chance, sortType: "number", visibleWhen: (ships) => ships.some((ship) => ship.anti_air?.medium_hit_chance != null) },
          { label: "Short range", modalLabelClass: "modal-stat-label-strong", render: (ship) => aaRangeDisplay(ship.anti_air?.short_range_m), sortValue: (ship) => ship.anti_air?.short_range_m, sortType: "number", visibleWhen: (ships) => ships.some((ship) => ship.anti_air?.short_range_m != null) },
          { label: "Short DPS", render: (ship) => aaDpsDisplay(ship.anti_air?.short_dps), sortValue: (ship) => ship.anti_air?.short_dps, sortType: "number", visibleWhen: (ships) => ships.some((ship) => ship.anti_air?.short_dps != null) },
          { label: "Short Hit Chance", headerLabel: "Hit Chance", modalLabel: "Hit Chance", render: (ship) => aaHitChanceDisplay(ship.anti_air?.short_hit_chance), sortValue: (ship) => ship.anti_air?.short_hit_chance, sortType: "number", visibleWhen: (ships) => ships.some((ship) => ship.anti_air?.short_hit_chance != null) },
          { label: "Flak count", modalLabelClass: "modal-stat-label-strong", render: (ship) => ship.anti_air?.flak_count || "N/A", sortValue: (ship) => `${ship.anti_air?.flak_count || ""}`, sortType: "text", visibleWhen: (ships) => ships.some((ship) => ship.anti_air?.flak_count != null) },
          { label: "Flak DPS", render: (ship) => aaDpsDisplay(ship.anti_air?.flak_damage), sortValue: (ship) => ship.anti_air?.flak_damage, sortType: "number", visibleWhen: (ships) => ships.some((ship) => ship.anti_air?.flak_damage != null) },
          { label: "Sector time", modalLabelClass: "modal-stat-label-strong", render: (ship) => formatValue(ship.anti_air?.sector_time_s, { digits: 0, suffix: " s" }), sortValue: (ship) => ship.anti_air?.sector_time_s, sortType: "number" },
          { label: "Sector %", render: (ship) => aaSectorBonus(ship) == null ? "N/A" : `+${formatValue(aaSectorBonus(ship), { digits: 0 })}%`, sortValue: (ship) => aaSectorBonus(ship), sortType: "number" },
          { label: "DFAA", render: (ship) => aaDfaaHover(ship), sortValue: (ship) => aaDfaaBonus(ship), sortType: "number", visibleWhen: (ships) => ships.some((ship) => aaDfaaBonus(ship) != null), modalOnly: true },
          { label: "DFAA %", render: (ship) => aaDfaaHover(ship), sortValue: (ship) => aaDfaaBonus(ship), sortType: "number", visibleWhen: (ships) => ships.some((ship) => aaDfaaBonus(ship) != null), tableOnly: true },
        ],
      },
    {
      label: "Depth charges",
      available: (ship) => firstAirWeapon(ship, isDepthChargeWeapon) != null,
      rows: [
        ["Aircraft", (ship) => displayAircraftName(firstAirSupport(ship)?.plane)],
        ["Depth charge", (ship) => displayProjectileName(firstAirWeapon(ship, isDepthChargeWeapon)?.projectile)],
        ["Damage", (ship) => formatValue(firstAirWeapon(ship, isDepthChargeWeapon)?.projectile?.alpha_damage, { digits: 0, grouping: true })],
        ["Reload", (ship) => formatValue(firstAirSupport(ship)?.reload_time, { digits: 1, suffix: " s" })],
        ["Attacks", (ship) => firstAirSupport(ship)?.plane?.attack_count],
      ],
    },
    {
      label: "Airstrike",
      available: (ship) => firstAirSupport(ship) != null,
      rows: [
        ["Attacks", (ship) => formatValue(airstrikeSupport(ship)?.charges_num, { digits: 0 })],
        ["Reload", (ship) => formatValue(airstrikeSupport(ship)?.reload_time, { digits: 1, suffix: " s" })],
        ["Min range", (ship) => formatDistanceMeters(airstrikeSupport(ship)?.min_dist)],
        ["Max range", (ship) => formatDistanceMeters(airstrikeSupport(ship)?.max_dist)],
        ["Aircraft health", (ship) => formatValue(airstrikeSupport(ship)?.plane?.max_health, { digits: 0, grouping: true })],
        ["Bombs", (ship) => formatValue(airstrikeBombCount(ship), { digits: 0, grouping: true })],
        {
          label: "Reticle size",
          render: (ship) => airstrikeReticleDisplay(ship),
          sortValue: (ship) => airstrikeReticleMetrics(ship, "outer")?.width,
          sortType: "number",
          visibleWhen: (ships) => ships.some((ship) => airstrikeReticleMetrics(ship, "outer") != null),
        },
        {
          label: "Deto. timer",
          render: (ship) => formatValue(airstrikeProjectile(ship)?.max_depth_blow_time, { digits: 1, suffix: " s" }),
          sortValue: (ship) => airstrikeProjectile(ship)?.max_depth_blow_time,
          sortType: "number",
          visibleWhen: (ships) => ships.some((ship) => airstrikeProjectile(ship)?.max_depth_blow_time != null),
        },
        {
          label: "Deto. depth",
          render: (ship) => {
            const value = airstrikeProjectile(ship)?.max_depth;
            return value == null ? "N/A" : formatValue(Math.abs(Number(value)), { digits: 0, suffix: " m" });
          },
          sortValue: (ship) => {
            const value = airstrikeProjectile(ship)?.max_depth;
            return value == null ? null : Math.abs(Number(value));
          },
          sortType: "number",
          visibleWhen: (ships) => ships.some((ship) => airstrikeProjectile(ship)?.ammo_type === "depthcharge" && airstrikeProjectile(ship)?.max_depth != null),
        },
        ["Damage", (ship) => formatValue(airstrikeProjectile(ship)?.alpha_damage, { digits: 0, grouping: true })],
        {
          label: "Penetration",
          render: (ship) => {
            const value = airstrikePenetration(airstrikeProjectile(ship));
            return Number.isFinite(Number(value))
              ? formatValue(Math.round(Number(value)), { digits: 0, suffix: " mm" })
              : "N/A";
          },
          sortValue: (ship) => {
            const value = airstrikePenetration(airstrikeProjectile(ship));
            return Number.isFinite(Number(value)) ? Math.round(Number(value)) : null;
          },
          sortType: "number",
          visibleWhen: (ships) => ships.some((ship) => {
            const projectile = airstrikeProjectile(ship);
            return projectile?.ammo_type !== "depthcharge" && airstrikePenetration(projectile) != null;
          }),
        },
        {
          label: "Fire chance",
          render: (ship) => fireChanceDisplay(airstrikeProjectile(ship)?.burn_prob, { scale: 100 }),
          sortValue: (ship) => positiveRatioValue(airstrikeProjectile(ship)?.burn_prob),
          sortType: "number",
          visibleWhen: (ships) => ships.some((ship) => positiveRatioValue(airstrikeProjectile(ship)?.burn_prob) != null),
        },
        {
          label: "Flood chance",
          render: (ship) => nonZeroPercentDisplay(airstrikeProjectile(ship)?.uw_critical, { scale: 100 }),
          sortValue: (ship) => airstrikeProjectile(ship)?.uw_critical,
          sortType: "number",
          visibleWhen: (ships) => ships.some((ship) => airstrikeProjectile(ship)?.ammo_type === "depthcharge" && airstrikeProjectile(ship)?.uw_critical != null),
        },
      ],
    },
    {
      label: "Scouts",
      available: (ship) => helperAirSupport(ship, "spy") != null,
      rows: [
        ["Description", (ship) => displayAircraftName(helperAirSupport(ship, "spy")?.plane)],
        ["Health", (ship) => formatValue(helperAirSupport(ship, "spy")?.plane?.max_health, { digits: 0, grouping: true })],
        ["Available Flights", (ship) => formatValue(helperAirSupport(ship, "spy")?.charges_num, { digits: 0 })],
        ["Reload Time", (ship) => formatValue(helperAirSupport(ship, "spy")?.reload_time, { digits: 1, suffix: " s" })],
        ["Action Time", (ship) => formatValue(helperAirSupport(ship, "spy")?.work_time, { digits: 1, suffix: " s" })],
        ["Number of Aircraft", (ship) => formatValue(helperAirSupport(ship, "spy")?.plane?.attackers_per_wave, { digits: 0 })],
      ],
    },
    {
      label: "Smoke Screen Aircraft",
      available: (ship) => helperAirSupport(ship, "smoke") != null,
      rows: [
        ["Description", (ship) => displayAircraftName(helperAirSupport(ship, "smoke")?.plane)],
        ["Health", (ship) => formatValue(helperAirSupport(ship, "smoke")?.plane?.max_health, { digits: 0, grouping: true })],
        ["Available Flights", (ship) => formatValue(helperAirSupport(ship, "smoke")?.charges_num, { digits: 0 })],
        ["Reload Time", (ship) => formatValue(helperAirSupport(ship, "smoke")?.reload_time, { digits: 1, suffix: " s" })],
        ["Action Time", (ship) => formatValue(helperAirSupport(ship, "smoke")?.work_time, { digits: 1, suffix: " s" })],
        ["Smoke screen dispersion time", (ship) => formatValue(planeConsumableById(helperAirSupport(ship, "smoke")?.plane, "PCY049_PlaneSmokeGenerator")?.life_time, { digits: 0, suffix: " s" })],
      ],
    },
    {
      label: "Escort Spotters",
      available: (ship) => helperAirSupport(ship, "scout") != null,
      rows: [
        ["Description", (ship) => displayAircraftName(helperAirSupport(ship, "scout")?.plane)],
        ["Health", (ship) => formatValue(helperAirSupport(ship, "scout")?.plane?.max_health, { digits: 0, grouping: true })],
        ["Available Flights", (ship) => formatValue(helperAirSupport(ship, "scout")?.charges_num, { digits: 0 })],
        ["Reload Time", (ship) => formatValue(helperAirSupport(ship, "scout")?.reload_time, { digits: 1, suffix: " s" })],
        ["Action Time", (ship) => formatValue(helperAirSupport(ship, "scout")?.work_time, { digits: 1, suffix: " s" })],
        ["Main battery firing range", (ship) => {
          const value = helperSupportBuffPercent(helperAirSupport(ship, "scout")?.buff_params?.GMMaxDist);
          return value == null ? "N/A" : `+${formatValue(value, { digits: 0 })}%`;
        }],
        ["Main battery dispersion", (ship) => {
          const value = helperSupportBuffPercent(helperAirSupport(ship, "scout")?.buff_params?.GMIdealRadius);
          return value == null ? "N/A" : `+${formatValue(value, { digits: 0 })}%`;
        }],
      ],
    },
    {
      label: "Attack aircraft",
      available: (ship) => aircraftSquadron(ship, "attack_aircraft") != null,
      rows: [
        ["Description", (ship) => aircraftDescription(ship, "attack_aircraft")],
        ["Health", (ship) => aircraftVariantStatDisplay(ship, "attack_aircraft", ({ squadron }) => squadron?.max_health, (value) => formatValue(value, { digits: 0, grouping: true }))],
        ["Max speed", (ship) => aircraftMaxSpeedDisplay(ship, "attack_aircraft")],
        ["Detectability", (ship) => aircraftVariantStatDisplay(ship, "attack_aircraft", ({ squadron }) => squadron?.detectability, (value) => formatValue(value, { digits: 1, suffix: " km" }))],
        ["On deck", (ship) => aircraftVariantStatDisplay(ship, "attack_aircraft", ({ squadron }) => squadron?.on_deck, (value) => formatValue(value, { digits: 0 }))],
        ["Regeneration", (ship) => aircraftVariantStatDisplay(ship, "attack_aircraft", ({ squadron }) => squadron?.regeneration_time, (value) => formatValue(value, { digits: 1, suffix: " s" }))],
        ["Squadron", (ship) => aircraftSquadronSize(ship, "attack_aircraft") || "N/A"],
        ["Rockets", (ship) => aircraftVariantStatDisplay(ship, "attack_aircraft", ({ squadron }) => squadron?.attack_count, (value) => formatValue(value, { digits: 0 }))],
        ["Reticle size", (ship) => attackAircraftReticleDisplay(ship)],
        ["Firing delay", (ship) => aircraftVariantStatDisplay(ship, "attack_aircraft", ({ squadron, weapon }) => {
          const durations = weapon?.projectile?.attack_sequence_durations || [];
          return durations.map((item) => Number(item)).filter((item) => Number.isFinite(item)).reduce((sum, item) => sum + item, 0) || null;
        }, (value) => formatValue(value, { digits: 1, suffix: " s" }))],
        ["Type", (ship) => aircraftVariantStatDisplay(ship, "attack_aircraft", ({ weapon }) => aircraftWeaponType(weapon?.projectile), (value) => `${value}`)],
        ["Damage", (ship) => aircraftVariantStatDisplay(ship, "attack_aircraft", ({ weapon }) => weapon?.projectile?.alpha_damage, (value) => formatValue(value, { digits: 0, grouping: true }))],
        {
          label: "Fire chance",
          render: (ship) => aircraftVariantStatDisplay(ship, "attack_aircraft", ({ weapon }) => positiveRatioValue(weapon?.projectile?.burn_prob), (value) => formatPercent(value, { scale: 100 }), { empty: null }),
          sortValue: (ship) => positiveRatioValue(firstAircraftWeapon(ship, "attack_aircraft")?.projectile?.burn_prob),
          sortType: "number",
          visibleWhen: (ships) => ships.some((ship) => aircraftWeaponEntries(ship, "attack_aircraft").some(({ weapon }) => positiveRatioValue(weapon?.projectile?.burn_prob) != null)),
        },
        ["Penetration", (ship) => aircraftVariantStatDisplay(ship, "attack_aircraft", ({ weapon }) => aircraftWeaponPenetration(weapon?.projectile), (value) => formatValue(value, { digits: 0, suffix: " mm" }))],
        {
          label: "Consumables",
          render: (ship) => renderAircraftConsumables(ship, "attack_aircraft"),
          sortValue: () => null,
          sortType: "text",
          modalOnly: true,
          visibleWhen: (ships) => ships.some((ship) => aircraftHasConsumables(ship, "attack_aircraft")),
        },
      ],
    },
    {
      label: "Torpedo bombers",
      available: (ship) => aircraftSquadron(ship, "torpedo_bombers") != null,
      rows: [
        ["Description", (ship) => aircraftDescription(ship, "torpedo_bombers")],
        ["Health", (ship) => aircraftVariantStatDisplay(ship, "torpedo_bombers", ({ squadron }) => squadron?.max_health, (value) => formatValue(value, { digits: 0, grouping: true }))],
        ["Max speed", (ship) => aircraftMaxSpeedDisplay(ship, "torpedo_bombers")],
        ["Detectability", (ship) => aircraftVariantStatDisplay(ship, "torpedo_bombers", ({ squadron }) => squadron?.detectability, (value) => formatValue(value, { digits: 1, suffix: " km" }))],
        ["On deck", (ship) => aircraftVariantStatDisplay(ship, "torpedo_bombers", ({ squadron }) => squadron?.on_deck, (value) => formatValue(value, { digits: 0 }))],
        ["Regeneration", (ship) => aircraftVariantStatDisplay(ship, "torpedo_bombers", ({ squadron }) => squadron?.regeneration_time, (value) => formatValue(value, { digits: 1, suffix: " s" }))],
        ["Squadron", (ship) => aircraftSquadronSize(ship, "torpedo_bombers") || "N/A"],
        ["Torpedoes", (ship) => aircraftVariantStatDisplay(ship, "torpedo_bombers", ({ squadron }) => squadron?.attack_count, (value) => formatValue(value, { digits: 0 }))],
        ["Torpedo speed", (ship) => aircraftVariantStatDisplay(ship, "torpedo_bombers", ({ weapon }) => weapon?.projectile?.speed, (value) => formatValue(value, { digits: 0, suffix: " kn" }))],
        ["Arming time", (ship) => aircraftVariantStatDisplay(ship, "torpedo_bombers", ({ weapon }) => weapon?.projectile?.arming_time, (value) => formatValue(value, { digits: 1, suffix: " s" }))],
        ["Arming distance", (ship) => aircraftVariantStatDisplay(ship, "torpedo_bombers", ({ weapon }) => {
          const speed = Number(weapon?.projectile?.speed);
          const armingTime = Number(weapon?.projectile?.arming_time);
          return Number.isFinite(speed) && Number.isFinite(armingTime) ? speed * armingTime * 2.686 : null;
        }, (value) => formatValue(value, { digits: 0, suffix: " m" }))],
        ["Range", (ship) => aircraftVariantStatDisplay(ship, "torpedo_bombers", ({ weapon }) => {
          const maxDist = Number(weapon?.projectile?.max_dist);
          return Number.isFinite(maxDist) ? (maxDist * 30) / 1000 : null;
        }, (value) => formatValue(value, { digits: 1, suffix: " km" }))],
        ["Damage", (ship) => aircraftVariantStatDisplay(ship, "torpedo_bombers", ({ weapon }) => aircraftTorpedoDamage(weapon?.projectile), (value) => formatValue(value, { digits: 0, grouping: true }))],
        ["Flood chance", (ship) => aircraftVariantStatDisplay(ship, "torpedo_bombers", ({ weapon }) => weapon?.projectile?.uw_critical, (value) => formatPercent(value, { scale: 100 }))],
        {
          label: "Consumables",
          render: (ship) => renderAircraftConsumables(ship, "torpedo_bombers"),
          sortValue: () => null,
          sortType: "text",
          modalOnly: true,
          visibleWhen: (ships) => ships.some((ship) => aircraftHasConsumables(ship, "torpedo_bombers")),
        },
      ],
    },
    {
      label: "Bombers",
      available: (ship) => aircraftSquadron(ship, "bombers") != null,
      rows: [
        ["Description", (ship) => aircraftDescription(ship, "bombers")],
        ["Health", (ship) => aircraftVariantStatDisplay(ship, "bombers", ({ squadron }) => squadron?.max_health, (value) => formatValue(value, { digits: 0, grouping: true }))],
        ["Max speed", (ship) => aircraftMaxSpeedDisplay(ship, "bombers")],
        ["Detectability", (ship) => aircraftVariantStatDisplay(ship, "bombers", ({ squadron }) => squadron?.detectability, (value) => formatValue(value, { digits: 1, suffix: " km" }))],
        ["On deck", (ship) => aircraftVariantStatDisplay(ship, "bombers", ({ squadron }) => squadron?.on_deck, (value) => formatValue(value, { digits: 0 }))],
        ["Regeneration", (ship) => aircraftVariantStatDisplay(ship, "bombers", ({ squadron }) => squadron?.regeneration_time, (value) => formatValue(value, { digits: 1, suffix: " s" }))],
        ["Squadron", (ship) => aircraftSquadronSize(ship, "bombers") || "N/A"],
        ["Bombs", (ship) => aircraftVariantStatDisplay(ship, "bombers", ({ squadron }) => squadron?.attack_count, (value) => formatValue(value, { digits: 0 }))],
        ["Reticle size", (ship) => bomberReticleDisplay(ship)],
        ["Type", (ship) => aircraftVariantStatDisplay(ship, "bombers", ({ weapon }) => aircraftWeaponType(weapon?.projectile), (value) => `${value}`)],
        ["Damage", (ship) => aircraftVariantStatDisplay(ship, "bombers", ({ weapon }) => weapon?.projectile?.alpha_damage, (value) => formatValue(value, { digits: 0, grouping: true }))],
        {
          label: "Fire chance",
          render: (ship) => aircraftVariantStatDisplay(ship, "bombers", ({ weapon }) => {
            return weapon?.projectile?.ammo_type === "HE" ? positiveRatioValue(weapon?.projectile?.burn_prob) : null;
          }, (value) => formatPercent(value, { scale: 100 }), { empty: null }),
          sortValue: (ship) => positiveRatioValue(firstAircraftWeapon(ship, "bombers")?.projectile?.burn_prob),
          sortType: "number",
          visibleWhen: (ships) => ships.some((ship) => firstAircraftWeapon(ship, "bombers")?.projectile?.ammo_type === "HE" && positiveRatioValue(firstAircraftWeapon(ship, "bombers")?.projectile?.burn_prob) != null),
        },
        ["Penetration", (ship) => aircraftVariantStatDisplay(ship, "bombers", ({ weapon }) => aircraftWeaponPenetration(weapon?.projectile), (value) => formatValue(value, { digits: 0, suffix: " mm" }))],
        {
          label: "Consumables",
          render: (ship) => renderAircraftConsumables(ship, "bombers"),
          sortValue: () => null,
          sortType: "text",
          modalOnly: true,
          visibleWhen: (ships) => ships.some((ship) => aircraftHasConsumables(ship, "bombers")),
        },
      ],
    },
    {
      label: "Skip bombers",
      available: (ship) => aircraftSquadron(ship, "skip_bombers") != null,
      rows: [
        ["Description", (ship) => aircraftDescription(ship, "skip_bombers")],
        ["Health", (ship) => aircraftVariantStatDisplay(ship, "skip_bombers", ({ squadron }) => squadron?.max_health, (value) => formatValue(value, { digits: 0, grouping: true }))],
        ["Max speed", (ship) => aircraftMaxSpeedDisplay(ship, "skip_bombers")],
        ["Detectability", (ship) => aircraftVariantStatDisplay(ship, "skip_bombers", ({ squadron }) => squadron?.detectability, (value) => formatValue(value, { digits: 1, suffix: " km" }))],
        ["On deck", (ship) => aircraftVariantStatDisplay(ship, "skip_bombers", ({ squadron }) => squadron?.on_deck, (value) => formatValue(value, { digits: 0 }))],
        ["Regeneration", (ship) => aircraftVariantStatDisplay(ship, "skip_bombers", ({ squadron }) => squadron?.regeneration_time, (value) => formatValue(value, { digits: 1, suffix: " s" }))],
        ["Squadron", (ship) => aircraftSquadronSize(ship, "skip_bombers") || "N/A"],
        ["Bombs", (ship) => aircraftVariantStatDisplay(ship, "skip_bombers", ({ squadron }) => squadron?.attack_count, (value) => formatValue(value, { digits: 0 }))],
        ["Type", (ship) => aircraftVariantStatDisplay(ship, "skip_bombers", ({ weapon }) => aircraftWeaponType(weapon?.projectile), (value) => `${value}`)],
        ["Damage", (ship) => aircraftVariantStatDisplay(ship, "skip_bombers", ({ weapon }) => weapon?.projectile?.alpha_damage, (value) => formatValue(value, { digits: 0, grouping: true }))],
        {
          label: "Fire chance",
          render: (ship) => aircraftVariantStatDisplay(ship, "skip_bombers", ({ weapon }) => positiveRatioValue(weapon?.projectile?.burn_prob), (value) => formatPercent(value, { scale: 100 }), { empty: null }),
          sortValue: (ship) => positiveRatioValue(firstAircraftWeapon(ship, "skip_bombers")?.projectile?.burn_prob),
          sortType: "number",
          visibleWhen: (ships) => ships.some((ship) => aircraftWeaponEntries(ship, "skip_bombers").some(({ weapon }) => positiveRatioValue(weapon?.projectile?.burn_prob) != null)),
        },
        ["Penetration", (ship) => aircraftVariantStatDisplay(ship, "skip_bombers", ({ weapon }) => aircraftWeaponPenetration(weapon?.projectile), (value) => formatValue(value, { digits: 0, suffix: " mm" }))],
        {
          label: "Consumables",
          render: (ship) => renderAircraftConsumables(ship, "skip_bombers"),
          sortValue: () => null,
          sortType: "text",
          modalOnly: true,
          visibleWhen: (ships) => ships.some((ship) => aircraftHasConsumables(ship, "skip_bombers")),
        },
      ],
    },
    {
      label: "Mine bombers",
      available: (ship) => aircraftSquadron(ship, "mine_bombers") != null,
      rows: [
        ["Description", (ship) => aircraftDescription(ship, "mine_bombers")],
        ["Health", (ship) => aircraftVariantStatDisplay(ship, "mine_bombers", ({ squadron }) => squadron?.max_health, (value) => formatValue(value, { digits: 0, grouping: true }))],
        ["Max speed", (ship) => aircraftMaxSpeedDisplay(ship, "mine_bombers")],
        ["Detectability", (ship) => aircraftVariantStatDisplay(ship, "mine_bombers", ({ squadron }) => squadron?.detectability, (value) => formatValue(value, { digits: 1, suffix: " km" }))],
        ["On deck", (ship) => aircraftVariantStatDisplay(ship, "mine_bombers", ({ squadron }) => squadron?.on_deck, (value) => formatValue(value, { digits: 0 }))],
        ["Regeneration", (ship) => aircraftVariantStatDisplay(ship, "mine_bombers", ({ squadron }) => squadron?.regeneration_time, (value) => formatValue(value, { digits: 1, suffix: " s" }))],
        ["Squadron", (ship) => aircraftSquadronSize(ship, "mine_bombers") || "N/A"],
        ["Number of Mine", (ship) => aircraftVariantStatDisplay(ship, "mine_bombers", ({ squadron }) => {
          const attackCount = Number(squadron?.attack_count);
          const attackerSize = Number(squadron?.attackers_per_wave);
          return Number.isFinite(attackCount) && Number.isFinite(attackerSize) ? attackCount * attackerSize : null;
        }, (value) => formatValue(value, { digits: 0 }))],
        ["Damage", (ship) => aircraftVariantStatDisplay(ship, "mine_bombers", ({ squadron, weapon }) => mineBomberDamageForEntry(squadron, weapon), (value) => formatValue(value, { digits: 0, grouping: true }))],
        ["Radius", (ship) => aircraftVariantStatDisplay(ship, "mine_bombers", ({ squadron }) => {
          const speed = Number(squadron?.speed_move_with_bomb);
          const interval = Number(squadron?.attack_interval);
          const size = Number(squadron?.attackers_per_wave);
          return Number.isFinite(speed) && Number.isFinite(interval) && Number.isFinite(size)
            ? Math.round((12.5 * speed) + (500 * interval) - (34.375 * size) - 275)
            : null;
        }, (value) => formatValue(value, { digits: 0, suffix: " m" }))],
        ["Flood chance", (ship) => aircraftVariantStatDisplay(ship, "mine_bombers", ({ weapon }) => weapon?.projectile?.uw_critical, (value) => formatPercent(value, { scale: 100 }))],
        {
          label: "Consumables",
          render: (ship) => renderAircraftConsumables(ship, "mine_bombers"),
          sortValue: () => null,
          sortType: "text",
          modalOnly: true,
          visibleWhen: (ships) => ships.some((ship) => aircraftHasConsumables(ship, "mine_bombers")),
        },
      ],
    },
    {
      label: "Consumables",
      available: (ship) => allConsumables(ship).length > 0,
      rows: [],
      customRender: renderConsumablesTable,
    },
    ];
  }
  return cachedParameterDefinitions;
}

function availableParameterDefinitions(ships) {
  const defs = parameterDefinitions();
  if (!ships.length) return [];
  return defs.filter((def) => ships.some((ship) => def.available(ship)));
}

function renderParameterTabs(ships = comparisonShips(), defs = availableParameterDefinitions(ships)) {
  if (!defs.some((def) => def.label === state.activeParameterGroup)) {
    state.activeParameterGroup = defs[0]?.label || "General";
  }

  els.parameterTabs.innerHTML = "";
  defs.forEach((def) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "parameter-group";
    input.checked = state.activeParameterGroup === def.label;
    input.addEventListener("change", () => {
      state.activeParameterGroup = def.label;
      renderParameterSection(ships, defs);
      syncRoute({ replace: true });
    });
    label.append(input, document.createTextNode(` ${uiLabel(def.label)}`));
    els.parameterTabs.appendChild(label);
  });
}

function refreshParameterView(options = {}) {
  const ships = comparisonShips();
  const defs = availableParameterDefinitions(ships);
  renderParameterTabs(ships, defs);
  renderParameterSection(ships, defs);
  if (state.activeMainTab === "parameters" && options.syncRoute !== false) {
    syncRoute({ replace: true });
  }
}

const refreshFilterAndParameterViewThrottled = rafThrottle(() => {
  renderFilterPane();
  refreshParameterView();
});

function directHoverCardFor(trigger) {
  return Array.from(trigger.children).find((child) => (
    child.classList?.contains("stat-hover-card")
    || child.classList?.contains("consumable-hover-card")
    || child.classList?.contains("detail-hover-card")
    || child.classList?.contains("ship-research-card")
  )) || null;
}

function positionFloatingTableHover() {
  const { trigger, card } = floatingTableHover;
  if (!trigger || !card || !document.body.contains(trigger)) {
    hideFloatingTableHover();
    return;
  }

  const margin = 8;
  const gap = 8;
  const triggerRect = trigger.getBoundingClientRect();
  const cardRect = card.getBoundingClientRect();
  const maxLeft = Math.max(margin, window.innerWidth - cardRect.width - margin);
  const maxTop = Math.max(margin, window.innerHeight - cardRect.height - margin);

  const centered = card.classList.contains("floating-consumable-hover-card")
    || card.classList.contains("floating-detail-hover-card");
  const researchTooltip = card.classList.contains("floating-ship-research-card");
  let left = centered ? triggerRect.left + triggerRect.width / 2 - cardRect.width / 2 : triggerRect.left;
  let top = triggerRect.bottom + gap;
  if (researchTooltip) {
    const compactResearchTrigger = trigger.classList.contains("research-path-ship");
    if (compactResearchTrigger) {
      left = triggerRect.left;
      top = triggerRect.bottom + gap;
      if (top + cardRect.height > window.innerHeight - margin) {
        top = triggerRect.top - cardRect.height - gap;
      }
    } else {
      left = triggerRect.right + gap;
      top = triggerRect.top;
      if (left + cardRect.width > window.innerWidth - margin) {
        left = triggerRect.left - cardRect.width - gap;
      }
    }
  } else if (top + cardRect.height > window.innerHeight - margin) {
    top = triggerRect.top - cardRect.height - gap;
  }

  left = Math.min(Math.max(margin, left), maxLeft);
  top = Math.min(Math.max(margin, top), maxTop);
  card.style.left = `${left}px`;
  card.style.top = `${top}px`;
}

function setFloatingTableHoverListeners(enabled) {
  if (enabled === floatingTableHover.listening) return;
  floatingTableHover.listening = enabled;
  const action = enabled ? "addEventListener" : "removeEventListener";
  window[action]("scroll", positionFloatingTableHover, true);
  window[action]("resize", positionFloatingTableHover);
}

function hideFloatingTableHover(trigger = null) {
  if (trigger && floatingTableHover.trigger !== trigger) return;
  setFloatingTableHoverListeners(false);
  floatingTableHover.card?.remove();
  floatingTableHover.trigger = null;
  floatingTableHover.card = null;
}

function showFloatingTableHover(trigger) {
  if (floatingTableHover.trigger === trigger) {
    positionFloatingTableHover();
    return;
  }

  const template = directHoverCardFor(trigger);
  if (!template) return;

  hideFloatingTableHover();
  const card = template.cloneNode(true);
  if (card.classList.contains("consumable-hover-card")) {
    card.classList.add("floating-consumable-hover-card");
  } else if (card.classList.contains("detail-hover-card")) {
    card.classList.add("floating-detail-hover-card");
  } else if (card.classList.contains("ship-research-card")) {
    card.classList.add("floating-ship-research-card");
  } else {
    card.classList.add("floating-stat-hover-card");
  }
  card.setAttribute("aria-hidden", "true");
  card.style.visibility = "hidden";
  document.body.appendChild(card);

  floatingTableHover.trigger = trigger;
  floatingTableHover.card = card;
  setFloatingTableHoverListeners(true);
  positionFloatingTableHover();
  card.style.visibility = "";
}

function parameterHoverTriggerFromEvent(event) {
  const target = event.target instanceof Element ? event.target : null;
  if (!target || !els.parameterOutput.contains(target)) return null;
  const trigger = target.closest(".param-table-wrap .stat-hover, .param-table-wrap .modal-consumable-choice, .param-table-wrap .detail-hover-wrap");
  return trigger && els.parameterOutput.contains(trigger) ? trigger : null;
}

function handleParameterOutputPointerOver(event) {
  const trigger = parameterHoverTriggerFromEvent(event);
  if (!trigger) return;
  const related = event.relatedTarget instanceof Node ? event.relatedTarget : null;
  if (related && trigger.contains(related)) return;
  showFloatingTableHover(trigger);
}

function handleParameterOutputPointerOut(event) {
  const trigger = parameterHoverTriggerFromEvent(event);
  if (!trigger) return;
  const related = event.relatedTarget instanceof Node ? event.relatedTarget : null;
  if (related && trigger.contains(related)) return;
  hideFloatingTableHover(trigger);
}

function modalHoverTriggerFromEvent(event) {
  const target = event.target instanceof Element ? event.target : null;
  if (!target || !els.modalContent?.contains(target)) return null;
  const trigger = target.closest("#modal-content .detail-hover-wrap, #modal-content .modal-consumable-choice");
  return trigger && els.modalContent.contains(trigger) ? trigger : null;
}

function handleModalPointerOver(event) {
  const trigger = modalHoverTriggerFromEvent(event);
  if (!trigger) return;
  const related = event.relatedTarget instanceof Node ? event.relatedTarget : null;
  if (related && trigger.contains(related)) return;
  showFloatingTableHover(trigger);
}

function handleModalPointerOut(event) {
  const trigger = modalHoverTriggerFromEvent(event);
  if (!trigger) return;
  const related = event.relatedTarget instanceof Node ? event.relatedTarget : null;
  if (related && trigger.contains(related)) return;
  hideFloatingTableHover(trigger);
}

function nationHoverTriggerFromEvent(event) {
  const target = event.target instanceof Element ? event.target : null;
  if (!target) return null;
  const trigger = target.closest(".ship-node, .research-path-ship");
  const inNationTree = els.nationTree.contains(trigger);
  const inResearchCalculator = els.researchCalculator?.contains(trigger);
  return trigger && (inNationTree || inResearchCalculator) && directHoverCardFor(trigger) ? trigger : null;
}

function handleNationTreePointerOver(event) {
  const trigger = nationHoverTriggerFromEvent(event);
  if (!trigger) return;
  const related = event.relatedTarget instanceof Node ? event.relatedTarget : null;
  if (related && trigger.contains(related)) return;
  showFloatingTableHover(trigger);
}

function handleNationTreePointerOut(event) {
  const trigger = nationHoverTriggerFromEvent(event);
  if (!trigger) return;
  const related = event.relatedTarget instanceof Node ? event.relatedTarget : null;
  if (related && trigger.contains(related)) return;
  hideFloatingTableHover(trigger);
}

function renderParameterSection(ships = comparisonShips(), defs = availableParameterDefinitions(ships)) {
  hideFloatingTableHover();
  if (!ships.length) {
    els.parameterOutput.className = "";
    els.parameterOutput.innerHTML = "";
    configureAdSensePlacements();
    return;
  }

  const activeDef = defs.find((def) => def.label === state.activeParameterGroup) || defs[0];
  state.activeParameterGroup = activeDef.label;
  const visibleShips = ships.filter((ship) => activeDef.available(ship));
  if (!visibleShips.length) {
    els.parameterOutput.className = "empty-panel";
    els.parameterOutput.textContent = `No ships in the current selection have ${activeDef.label.toLowerCase()} data.`;
    configureAdSensePlacements();
    return;
  }
  els.parameterOutput.className = "";
  els.parameterOutput.innerHTML = activeDef.customRender
    ? activeDef.customRender(activeDef.label, visibleShips)
    : renderTable(activeDef.label, visibleShips, activeDef.rows);
  configureAdSensePlacements();
}

function handleParameterOutputClick(event) {
  const target = event.target instanceof Element ? event.target : null;
  if (!target) return;

  const extremeToggle = target.closest("[data-extreme-toggle]");
  if (extremeToggle && els.parameterOutput.contains(extremeToggle)) {
    event.preventDefault();
    setParameterExtremeHighlight(!state.parameterExtremeHighlight);
    return;
  }

  const rangeButton = target.closest(".parameter-range-button[data-range-group]");
  if (rangeButton && els.parameterOutput.contains(rangeButton)) {
    event.preventDefault();
    const group = rangeButton.dataset.rangeGroup;
    const step = Number(rangeButton.dataset.rangeStep || 0);
    const min = Number(rangeButton.dataset.rangeMin || 1);
    const max = Number(rangeButton.dataset.rangeMax || min);
    const current = state.parameterRanges[group] ?? min;
    state.parameterRanges[group] = clamp(current + step, min, max);
    renderParameterSection();
    return;
  }

  const sortButton = target.closest("[data-sort-label]");
  if (sortButton && els.parameterOutput.contains(sortButton)) {
    event.preventDefault();
    const group = sortButton.dataset.sortGroup;
    const label = sortButton.dataset.sortLabel;
    const sortType = sortButton.dataset.sortType === "text" ? "text" : "number";
    if (state.parameterSort?.group === group && state.parameterSort?.label === label) {
      state.parameterSort = { group, label, direction: state.parameterSort.direction === "desc" ? "asc" : "desc" };
    } else {
      state.parameterSort = { group, label, direction: defaultSortDirection({ sortType }) };
    }
    renderParameterSection();
    return;
  }

  const shipButton = target.closest("[data-open-ship]");
  if (shipButton && els.parameterOutput.contains(shipButton)) {
    event.preventDefault();
    event.stopPropagation();
    openShipModal(shipButton.dataset.openShip);
    return;
  }

  const shipRow = target.closest("[data-open-ship-row]");
  if (shipRow && els.parameterOutput.contains(shipRow)) {
    openShipModal(shipRow.dataset.openShipRow);
  }
}

function detailTable(title, rows) {
  return `
    <div class="detail-card">
      <h3>${escapeHtml(title)}</h3>
      <table><tbody>${rows.map(([label, value]) => `<tr><td>${escapeHtml(label)}</td><td>${value}</td></tr>`).join("")}</tbody></table>
    </div>
  `;
}

function renderConsumableSlotChoices(choices, ownerShip = null) {
  return `
    <div class="modal-consumable-options">
      ${choices.map((consumable) => `
        <div class="modal-consumable-choice">
          ${consumable.icon
            ? `<img class="modal-consumable-choice-icon" src="${escapeHtml(consumable.icon)}" alt="${escapeHtml(consumable.display_name || consumable.id)}">`
            : `<div class="modal-consumable-choice-fallback">${escapeHtml(consumable.display_name || consumable.id)}</div>`}
          ${typeof consumable.num_consumables === "number" && consumable.num_consumables >= 0
            ? `<span class="modal-consumable-count">${consumable.num_consumables}</span>`
            : ""}
          ${renderConsumableTooltip(consumable, ownerShip)}
        </div>
      `).join("")}
    </div>
  `;
}

function consumableUsesLabel(consumable) {
  const uses = consumable?.num_consumables;
  if (uses === -1) return "Unlimited";
  return Number.isFinite(Number(uses)) ? `${Number(uses)}` : "N/A";
}

function cleanConsumableDescription(description) {
  if (!description) return "";
  return decodeHtmlText(description)
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/<\/?p[^>]*>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function renderConsumableTooltip(consumable, ownerShip = null) {
  const rows = consumableTooltipRows(consumable, ownerShip);
  const description = cleanConsumableDescription(consumable.description);
  return `
    <span class="consumable-hover-card">
      <span class="consumable-hover-title">${escapeHtml(consumable.display_name || consumable.id || "Consumable")}</span>
      ${description ? `<span class="consumable-hover-description">${escapeHtml(description)}</span>` : ""}
      <span class="consumable-hover-divider"></span>
      ${rows.map((row) => `
        <span class="consumable-hover-line">
          <span class="consumable-hover-line-label">${escapeHtml(uiLabel(row.label))}:</span>
          <span class="consumable-hover-line-value ${row.className || ""}">${escapeHtml(row.value)}</span>
        </span>
      `).join("")}
    </span>
  `;
}

function renderConsumableSummary(ship) {
  const slots = (ship.consumables || [])
    .filter((slot) => (slot.choices || []).length)
    .sort((left, right) => (left.slot ?? 99) - (right.slot ?? 99));
  if (!slots.length) return `<div class="modal-consumables empty-panel compact">${escapeHtml(uiLabel("No consumables found."))}</div>`;
  return `
    <section class="modal-stat-card modal-consumables-card">
      <h4>${escapeHtml(uiLabel("Consumables"))}</h4>
      <div class="modal-slot-list">
        ${slots.map((slot) => `
          <div class="modal-slot-row">
            <div class="modal-slot-label">${escapeHtml(uiLabel("Slot"))} ${(slot.slot ?? 0) + 1}</div>
            ${renderConsumableSlotChoices(slot.choices || [], ship)}
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function hasCombatInstruction(ship) {
  return !!(ship?.combat_instruction && ship.combat_instruction.rage_mode_name);
}

function formatCombatInstructionDetail(detail) {
  if (!detail) return "N/A";
  if (typeof detail.value === "string") return escapeHtml(detail.value);
  const digits = Number.isInteger(Number(detail.value)) ? 0 : 1;
  const baseValue = formatValue(detail.value, {
    digits,
    suffix: detail.suffix || "",
    grouping: typeof detail.value === "number" && Math.abs(detail.value) >= 1000,
  });
  const signedValue = `${detail.sign || ""}${baseValue}`;
  const escapedValue = escapeHtml(signedValue);
  if (detail.tone === "positive" || detail.tone === "negative") {
    return `<span class="combat-instruction-value-${detail.tone}">${escapedValue}</span>`;
  }
  return escapedValue;
}

function aaRangeDisplay(value) {
  return formatDistanceMeters(value);
}

function aaDpsDisplay(value) {
  return formatValue(value, { digits: 0 });
}

function aaHitChanceDisplay(value) {
  return formatPercent(value, { digits: 0, scale: 100 });
}

function aaSectorBonus(ship) {
  const value = ship.anti_air?.sector_damage_multiplier;
  if (value == null) return null;
  return value > 1 ? (value - 1) * 100 : value * 100;
}

function firstDfaaConsumable(ship) {
  return allConsumables(ship).find((item) => {
    const id = `${item?.id || ""}`;
    return item?.consumable_type === "airDefenseDisp"
      || item?.consumable_type === "boosterAA"
      || id.toLowerCase() === "pcy011_airdefensedisppremium";
  }) || null;
}

function aaDfaaBonus(ship) {
  const consumable = firstDfaaConsumable(ship);
  const value = consumable?.modifiers?.areaDamageMultiplier ?? consumable?.area_damage_multiplier;
  if (value == null) return null;
  return value > 1 ? (value - 1) * 100 : value * 100;
}

function aaDfaaHover(ship) {
  const consumable = firstDfaaConsumable(ship);
  if (!consumable) return "N/A";
  const area = positivePercentFromMultiplier(consumable?.modifiers?.areaDamageMultiplier ?? consumable?.area_damage_multiplier);
  const flak = positivePercentFromMultiplier(consumable?.modifiers?.bubbleDamageMultiplier ?? consumable?.bubble_damage_multiplier);
  if (!area) return "N/A";
  return hoverMetric(area, [
    ["Continuous AA damage", area],
    ["Flak damage", flak || "N/A"],
  ]);
}

function renderCombatInstructionSummary(ship) {
  const instruction = ship?.combat_instruction;
  if (!hasCombatInstruction(ship)) return "";
  const rows = (instruction.details || [])
    .filter((detail) => detail && detail.label && detail.value != null && detail.value !== "")
      .map((detail) => `
        <tr>
          <td>${escapeHtml(detail.label)}</td>
         <td>${formatCombatInstructionDetail(detail)}</td>
        </tr>
      `)
    .join("");
  const iconMarkup = instruction.icon || instruction.background_icon
    ? `
      <div class="combat-instruction-icon-stack">
        ${instruction.background_icon ? `<img class="combat-instruction-icon combat-instruction-icon-bg" src="${escapeHtml(instruction.background_icon)}" alt="">` : ""}
        ${instruction.icon ? `<img class="combat-instruction-icon combat-instruction-icon-fg" src="${escapeHtml(instruction.icon)}" alt="${escapeHtml(instruction.display_name || "Combat instruction")}">` : ""}
      </div>
    `
    : "";
  return `
    <section class="modal-stat-card combat-instruction-card">
      <h4>Combat instructions</h4>
      <div class="combat-instruction-name">${escapeHtml(instruction.display_name || instruction.rage_mode_name || "Combat instruction")}</div>
      ${iconMarkup}
      <table><tbody>${rows}</tbody></table>
    </section>
  `;
}

function modalGroupRows(ship, groupLabel) {
  const def = parameterDefinitions().find((group) => group.label === groupLabel);
  if (!def || !def.available(ship)) return null;
  const context = getDefaultRenderContext(groupLabel, [ship]);
  const rows = visibleParameterRows(def.rows, [ship])
    .filter((row) => !row.tableOnly)
    .filter((row) => !["Ship", "Tier", "Class", "Nation"].includes(row.label))
    .map((row) => [{
      text: typeof row.modalLabel === "function" ? row.modalLabel(ship) : row.modalLabel || row.headerLabel || row.label,
      className: row.modalLabelClass || "",
      helpGroup: groupLabel,
      helpContext: context,
    }, row.render(ship, context)]);
  if (!rows.length) return null;
  let title = groupLabel;
  if (groupLabel === "Secondaries") {
    title = secondaryAmmoTypeLabel(ship);
  } else if (groupLabel === "Medium guns") {
    title = "Medium-caliber battery";
  } else if (groupLabel === "Torpedoes") {
    title = torpedoTitleForProjectile(firstTorpedoProjectile(ship), ship?.__torpedoVariantIndex);
  } else if (groupLabel === "Attack aircraft") {
    title = aircraftSectionLabel(ship, "attack_aircraft", "Attack aircraft");
    title += aircraftVariantSuffix(ship, "attack_aircraft");
  } else if (groupLabel === "Torpedo bombers") {
    title = aircraftSectionLabel(ship, "torpedo_bombers", "Torpedo bombers");
    title += aircraftVariantSuffix(ship, "torpedo_bombers");
  } else if (groupLabel === "Airstrike") {
    title = airstrikeSectionLabel(ship);
  } else if (groupLabel === "Bombers") {
    title = aircraftSectionLabel(ship, "bombers", "Bombers");
    title += aircraftVariantSuffix(ship, "bombers");
  } else if (groupLabel === "Skip bombers") {
    title = aircraftSectionLabel(ship, "skip_bombers", "Skip bombers");
    title += aircraftVariantSuffix(ship, "skip_bombers");
  } else if (groupLabel === "Mine bombers") {
    title = aircraftSectionLabel(ship, "mine_bombers", "Mine bombers");
    title += aircraftVariantSuffix(ship, "mine_bombers");
  }
  return [title, rows];
}

function modalGroupVariantShips(ship, groupLabel) {
  if (groupLabel === "Torpedoes") {
    const entries = allTorpedoVariantEntries(ship);
    return entries.length > 1 ? entries.map((entry) => withTorpedoVariant(ship, entry.index)) : [ship];
  }
  const aircraftKey = aircraftGroupKeyForTitle(groupLabel);
  if (aircraftKey) {
    const entries = aircraftSquadronEntries(ship, aircraftKey);
    return entries.length > 1
      ? entries.map((_, index) => ({
        ...ship,
        __aircraftVariantKey: aircraftKey,
        __aircraftVariantIndex: index,
        __aircraftVariantAlt: index > 0,
      }))
      : [ship];
  }
  return [ship];
}

function summaryModalGroups(ship) {
  return parameterDefinitions()
    .filter((group) => group.label !== "Consumables" && group.available(ship))
    .flatMap((group) => modalGroupVariantShips(ship, group.label).map((variantShip) => modalGroupRows(variantShip, group.label)))
    .filter(Boolean);
}

function renderShipDescription(ship) {
  if (!ship.identity.description) return "";
  return `<div class="summary-copy">${shipDescriptionHtml(ship.identity.description)}</div>`;
}

function decodeHtmlText(value) {
  const textarea = document.createElement("textarea");
  textarea.innerHTML = `${value || ""}`;
  return textarea.value;
}

function shipDescriptionHtml(description) {
  const raw = decodeHtmlText(description).trim();
  if (!raw) return "";
  if (!/<\/?[a-z][\s\S]*>/i.test(raw)) {
    return `<p>${escapeHtml(raw)}</p>`;
  }

  const container = document.createElement("div");
  container.innerHTML = raw;
  container.querySelectorAll("script, style").forEach((node) => node.remove());

  const paragraphs = [...container.querySelectorAll("p")]
    .map((node) => node.textContent.replace(/\u00a0/g, " ").replace(/\s+/g, " ").trim())
    .filter(Boolean);

  if (!paragraphs.length) {
    const text = container.textContent.replace(/\u00a0/g, " ").replace(/\s+/g, " ").trim();
    return text ? `<p>${escapeHtml(text)}</p>` : "";
  }

  return paragraphs.map((text) => `<p>${escapeHtml(text)}</p>`).join("");
}

function serviceYearLabel(ship) {
  return ship.identity.is_paper_ship ? "Year of design" : "Entered service";
}

function serviceYearValue(ship) {
  return formatYearLabel(ship.identity.year_label);
}

function modalStatCard(title, rows, helpOptions = {}) {
  const visibleRows = (rows || []).filter((row) => Array.isArray(row) && row[1] != null && row[1] !== "");
  if (!visibleRows.length) return "";
  return `
      <section class="modal-stat-card">
        <h4>${escapeHtml(uiLabel(title))}</h4>
        <table><tbody>${visibleRows.map(([label, value]) => {
          const labelText = typeof label === "object" ? label.text : label;
          const labelClass = typeof label === "object" && label.className ? ` class="${escapeHtml(label.className)}"` : "";
          const helpGroup = typeof label === "object" ? label.helpGroup || helpOptions.groupLabel : helpOptions.groupLabel;
          const helpContext = typeof label === "object" ? label.helpContext || helpOptions.context : helpOptions.context;
          return `<tr><td${labelClass} data-modal-stat-label="${escapeHtml(labelText)}">${statHelpLabelHtml(labelText, helpGroup, helpContext)}</td><td>${renderValueHtml(value)}</td></tr>`;
        }).join("")}</tbody></table>
      </section>
    `;
}

function modalSpecColumns(columns, helpOptions = {}) {
  const cards = columns.map(([title, rows]) => modalStatCard(title, rows, helpOptions)).filter(Boolean);
  const layoutClass = cards.length === 2 ? " is-two-column" : cards.length === 1 ? " is-one-column" : "";
  return `<div class="modal-spec-columns${layoutClass}">${cards.join("")}</div>`;
}

function resetModalCompare() {
  state.modalCompare = {
    enabled: false,
    mode: "inline",
    secondaryCode: null,
  };
  state.modalCompareHighlight = false;
}

function modalCompareMode() {
  return "inline";
}

function modalCompareOptions(primaryCode) {
  return state.ships
    .filter((ship) => ship.identity.code !== primaryCode)
    .sort((left, right) => (
      (left.identity.tier - right.identity.tier)
      || displayClass(left).localeCompare(displayClass(right))
      || localizedNationLabel(left).localeCompare(localizedNationLabel(right))
      || left.displayName.localeCompare(right.displayName)
    ));
}

function renderModalCompareSelect(name, selectedCode, excludedCode, label, pickSlot) {
  const options = modalCompareOptions(excludedCode).map((ship) => (
    `<option value="${escapeHtml(ship.identity.code)}"${ship.identity.code === selectedCode ? " selected" : ""}>${escapeHtml(`${ship.displayName} - ${ship.identity.tier} ${displaySelectClass(ship)} ${localizedNationLabel(ship)}`)}</option>`
  )).join("");
  return `
    <label class="modal-compare-select-label">
      <span>${escapeHtml(label)}</span>
      <select data-modal-compare-select="${escapeHtml(name)}">
        <option value="">${escapeHtml(t("modal.compareSelect", "Select a ship..."))}</option>
        ${options}
      </select>
    </label>
    <button type="button" class="modal-compare-pick" data-modal-compare-pick="${escapeHtml(pickSlot)}">${escapeHtml(t("modal.comparePick", "Pick"))}</button>
  `;
}

function renderModalCompareSearch(primaryShip) {
  const primaryCode = primaryShip.identity.code;
  const selectedCode = state.modalCompare.secondaryCode || "";
  const highlightActive = !!state.modalCompareHighlight;
  return `
    <div class="modal-compare-toolbar">
      ${renderModalCompareSelect("primary", primaryCode, selectedCode, t("modal.comparePrimaryTarget", "Primary ship"), "primary")}
      ${renderModalCompareSelect("secondary", selectedCode, primaryCode, t("modal.compareTarget", "Compare with"), "secondary")}
      <button type="button" class="modal-compare-highlight-toggle ${highlightActive ? "active" : ""}" data-modal-compare-highlight aria-pressed="${highlightActive ? "true" : "false"}">${escapeHtml(t("modal.compareHighlight", "Show best/worst"))}</button>
      <button type="button" class="modal-compare-close" data-modal-compare-close>${escapeHtml(t("common.close", "Close"))}</button>
    </div>
  `;
}

function renderModalCompareCard(ship, labelKey) {
  const name = shipModalDisplayName(ship);
  return `
    <section class="modal-compare-card" data-modal-compare-card="${escapeHtml(labelKey)}">
      <div class="modal-compare-card-title">
        <span>${escapeHtml(name)}</span>
        <small>${escapeHtml(t("shipMeta.line", "{nation} tier {tier} {class}", {
          nation: localizedNationLabel(ship),
          tier: ship.identity.tier,
          class: uiLabelLower(displayClass(ship)),
        }))}</small>
      </div>
      ${renderModalTabContent(ship, state.activeModalTab, { suppressCharts: true })}
    </section>
  `;
}

function renderModalHeroMeta(ship) {
  return escapeHtml(t("shipMeta.line", "{nation} tier {tier} {class}", {
    nation: localizedNationLabel(ship),
    tier: ship.identity.tier,
    class: uiLabelLower(displayClass(ship)),
  }));
}

function renderModalBadges(ship) {
  return `
    <div class="modal-badges">
      <span class="badge">${escapeHtml(ship.nationLabel)}</span>
      <span class="badge">${escapeHtml(availabilityLabel(ship.availability))}</span>
      <span class="badge">${escapeHtml(ship.roleLabel || "No Role")}</span>
    </div>
  `;
}

function renderModalSingleIntro(ship) {
  return `
    <div class="modal-hero">
      <p>${renderModalHeroMeta(ship)}</p>
      ${renderShipCloneLine(ship)}
      ${modalTreeLinks(ship)}
    </div>
    <div class="modal-top">
      <div class="modal-top-media">${shipCardImage(ship, "modal-preview")}</div>
      <div class="modal-top-copy">
        ${renderShipDescription(ship)}
        ${renderModalBadges(ship)}
      </div>
    </div>
    ${renderShipModuleIcons(ship)}
  `;
}

function renderModalCompareHeroCard(ship, label) {
  if (!ship) {
    return `
      <section class="modal-compare-hero-card modal-compare-hero-empty">
        <p>${escapeHtml(t("modal.compareEmpty", "Select a second ship to compare specs."))}</p>
      </section>
    `;
  }
  return `
    <section class="modal-compare-hero-card">
      <div class="modal-compare-hero-title">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(shipModalDisplayName(ship))}</strong>
        <small>${renderModalHeroMeta(ship)}</small>
      </div>
      <div class="modal-compare-hero-media">
        ${shipCardImage(ship, "modal-preview")}
        ${renderShipModuleIcons(ship)}
      </div>
      <div class="modal-compare-hero-copy">
        ${renderShipDescription(ship)}
        ${renderModalBadges(ship)}
      </div>
    </section>
  `;
}

function renderModalCompareHero(primaryShip, secondaryShip) {
  return `
    <div class="modal-compare-hero-grid">
      ${renderModalCompareHeroCard(primaryShip, t("modal.comparePrimary", "Primary"))}
      ${renderModalCompareHeroCard(secondaryShip, t("modal.compareSecondary", "Compare"))}
    </div>
  `;
}

function renderModalCompareLayout(primaryShip, secondaryShip) {
  const picker = renderModalCompareSearch(primaryShip);
  const secondaryContent = secondaryShip
    ? renderModalCompareCard(secondaryShip, "secondary")
    : `<section class="modal-compare-card modal-compare-empty"><p>${escapeHtml(t("modal.compareEmpty", "Select a second ship to compare specs."))}</p></section>`;
  return `
    <div class="modal-compare-mode">
      ${picker}
      ${renderModalCompareSharedCharts(primaryShip, secondaryShip)}
      <div class="modal-compare-grid">
        ${renderModalCompareCard(primaryShip, "primary")}
        ${secondaryContent}
      </div>
    </div>
  `;
}

function modalShellChartGroupForTab(tab) {
  if (tab === "ap") return "AP Shells";
  if (tab === "he") return "HE Shells";
  if (tab === "sap") return "SAP Shells";
  if (tab === "secondaries") return "Secondaries";
  return null;
}

function renderModalCompareSharedCharts(primaryShip, secondaryShip) {
  const groupLabel = modalShellChartGroupForTab(state.activeModalTab);
  if (!groupLabel || !secondaryShip) return "";
  const primaryView = modalShipView(primaryShip);
  const secondaryView = modalShipView(secondaryShip);
  const projectile = projectileForShellChart(primaryView, groupLabel);
  if (!projectile) return "";
  const context = getModalRenderContext(groupLabel, [primaryView, secondaryView]);
  return `
    <section class="modal-compare-shared-charts">
      <div class="modal-panel-header"><h3>${escapeHtml(t("modal.compareCharts", "Comparison charts"))}</h3>${renderModalRangeControl(groupLabel, [primaryView, secondaryView])}</div>
      ${renderShellChartsPanel(primaryView, projectile, context, groupLabel, {
        compareShips: [primaryView, secondaryView],
        hideCompareControls: true,
      })}
    </section>
  `;
}

function renderModalTabs(tabs) {
  return `
    <div class="modal-tabs-bar">
      ${tabs.map(([key, label]) => `<button type="button" class="modal-switch ${key === state.activeModalTab ? "active" : ""}" data-modal-tab="${escapeHtml(key)}">${escapeHtml(uiLabel(label))}</button>`).join("")}
    </div>
  `;
}

function updateModalStickyTitleHeight() {
  const title = els.modalContent?.querySelector(".modal-sticky-title");
  if (!title || !els.modalContent) return;
  els.modalContent.style.setProperty("--modal-sticky-title-height", `${Math.ceil(title.getBoundingClientRect().height)}px`);
}

function renderModalCompareWindow(ship, labelKey, tabs) {
  const label = labelKey === "primary" ? t("modal.comparePrimary", "Primary") : t("modal.compareSecondary", "Compare");
  return `
    <section class="modal-compare-window modal-compare-card" data-modal-compare-card="${escapeHtml(labelKey)}">
      <div class="modal-compare-window-title">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(shipModalDisplayName(ship))}</strong>
      </div>
      ${renderModalCompareHeroCard(ship, label)}
      ${renderModalTabs(tabs)}
      <div class="modal-panel modal-panel-single modal-compare-window-panel">
        <div class="modal-panel-body">
          ${renderModalTabContent(ship, state.activeModalTab)}
        </div>
      </div>
    </section>
  `;
}

function renderModalCompareSeparateLayout(primaryShip, secondaryShip, tabs) {
  const picker = renderModalCompareSearch(primaryShip);
  const secondaryContent = secondaryShip
    ? renderModalCompareWindow(secondaryShip, "secondary", tabs)
    : `<section class="modal-compare-window modal-compare-empty"><p>${escapeHtml(t("modal.compareEmpty", "Select a second ship to compare specs."))}</p></section>`;
  return `
    <div class="modal-compare-separate-mode">
      ${picker}
      <div class="modal-compare-window-grid">
        ${renderModalCompareWindow(primaryShip, "primary", tabs)}
        ${secondaryContent}
      </div>
    </div>
  `;
}

function modalCompareTabShips(primaryShip, secondaryShip) {
  return [primaryShip, secondaryShip].filter(Boolean).map((ship) => modalShipView(ship));
}

function modalTabsForShips(primaryShip, secondaryShip = null) {
  const ships = state.modalCompare.enabled ? modalCompareTabShips(primaryShip, secondaryShip) : [modalShipView(primaryShip)];
  const hasMainBattery = ships.some((item) => mainBatteryModules(item).length > 0);
  const hasMediumBattery = ships.some((item) => mediumBatteryModules(item).length > 0);
  const torpedoTabIndexes = new Set();
  ships.forEach((item) => {
    allTorpedoVariantEntries(item).forEach((entry) => torpedoTabIndexes.add(entry.index));
  });
  return [
    ["summary", "Summary"],
    hasMainBattery ? ["main", "Main battery"] : null,
    hasMainBattery && ships.some((item) => firstProjectile(item, "HE")) ? ["he", "HE shells"] : null,
    hasMainBattery && ships.some((item) => firstProjectile(item, "AP")) ? ["ap", "AP shells"] : null,
    hasMainBattery && ships.some((item) => firstProjectile(item, "SAP")) ? ["sap", "SAP shells"] : null,
    hasMediumBattery ? ["medium", "Medium guns"] : null,
    ...[...torpedoTabIndexes].sort((left, right) => left - right).map((index) => [torpedoModalTabKey(index), `Torpedoes${variantAltSuffix(index)}`]),
    ships.some((item) => secondaryGunModules(item).length > 0) ? ["secondaries", "Secondaries"] : null,
  ].filter(Boolean);
}

function modalCompareRowKey(label, occurrence) {
  const normalized = `${label || ""}`.trim().toLowerCase();
  const baseKey = ["year", "year of design", "entered service"].includes(normalized) ? "__year" : normalized;
  return `${baseKey}::${occurrence || 0}`;
}

function modalCompareOrderedMerge(primaryItems, secondaryItems) {
  const merged = primaryItems.map((item) => ({ ...item }));
  const hasKey = (key) => merged.some((item) => item.key === key);
  secondaryItems.forEach((item, index) => {
    if (hasKey(item.key)) return;
    let insertAt = merged.length;
    for (let prev = index - 1; prev >= 0; prev -= 1) {
      const found = merged.findIndex((mergedItem) => mergedItem.key === secondaryItems[prev].key);
      if (found !== -1) {
        insertAt = found + 1;
        break;
      }
    }
    if (insertAt === merged.length) {
      for (let next = index + 1; next < secondaryItems.length; next += 1) {
        const found = merged.findIndex((mergedItem) => mergedItem.key === secondaryItems[next].key);
        if (found !== -1) {
          insertAt = found;
          break;
        }
      }
    }
    merged.splice(insertAt, 0, { ...item });
  });
  return merged;
}

function modalCompareTableSections(card) {
  return [...card.querySelectorAll(".modal-stat-card")]
    .filter((section) => !section.classList.contains("modal-consumables-card"))
    .filter((section) => !section.classList.contains("combat-instruction-card"))
    .map((section, index) => {
      const title = section.querySelector("h4")?.textContent?.trim() || "";
      const tbody = section.querySelector("tbody");
      return tbody ? { key: title ? title.toLowerCase() : `__untitled_${index}`, title, section, tbody } : null;
    })
    .filter(Boolean);
}

function createModalComparePlaceholderSection(title) {
  const section = document.createElement("section");
  section.className = "modal-stat-card modal-compare-placeholder-section";
  section.innerHTML = `<h4>${escapeHtml(title)}</h4><table><tbody></tbody></table>`;
  return section;
}

function createModalComparePlaceholderRow(label) {
  const row = document.createElement("tr");
  row.className = "modal-compare-placeholder-row";
  row.innerHTML = `
    <td data-modal-stat-label="${escapeHtml(label)}">${escapeHtml(uiLabel(label))}</td>
    <td><span class="muted-value">N/A</span></td>
  `;
  return row;
}

function modalCompareSectionRows(section) {
  const seenLabels = new Map();
  return [...section.tbody.querySelectorAll("tr")].map((row) => {
    const labelCell = row.querySelector("td[data-modal-stat-label]") || row.querySelector("td");
    const label = labelCell?.dataset?.modalStatLabel || labelCell?.textContent?.trim() || "";
    if (!label) return null;
    const normalizedLabel = modalCompareRowKey(label, 0).replace(/::0$/, "");
    const occurrence = seenLabels.get(normalizedLabel) || 0;
    seenLabels.set(normalizedLabel, occurrence + 1);
    return { key: modalCompareRowKey(label, occurrence), label, row };
  }).filter(Boolean);
}

function syncModalCompareBlockHeights(selector) {
  if (!els.modalContent) return;
  const blocks = [...els.modalContent.querySelectorAll(selector)];
  if (blocks.length !== 2) return;
  blocks.forEach((block) => { block.style.minHeight = ""; });
  const maxHeight = Math.max(...blocks.map((block) => block.getBoundingClientRect().height));
  if (Number.isFinite(maxHeight) && maxHeight > 0) {
    blocks.forEach((block) => { block.style.minHeight = `${Math.ceil(maxHeight)}px`; });
  }
}

function alignModalCompareHeroHeights() {
  syncModalCompareBlockHeights(".modal-compare-hero-grid > .modal-compare-hero-card");
  syncModalCompareBlockHeights(".modal-compare-window-grid > .modal-compare-window > .modal-compare-hero-card");
  syncModalCompareBlockHeights(".modal-compare-window-grid > .modal-compare-window > .modal-compare-hero-card .modal-compare-hero-media");
}

function alignModalCompareRows() {
  if (!state.modalCompare.enabled || !els.modalContent) return;
  alignModalCompareHeroHeights();
  const cards = [...els.modalContent.querySelectorAll(".modal-compare-card[data-modal-compare-card]")];
  if (cards.length !== 2) return;
  const sectionLists = cards.map(modalCompareTableSections);
  if (!sectionLists[0].length || !sectionLists[1].length) return;
  const sectionOrder = modalCompareOrderedMerge(
    sectionLists[0].map(({ key, title }) => ({ key, title })),
    sectionLists[1].map(({ key, title }) => ({ key, title })),
  );
  const sectionMaps = sectionLists.map((sections) => new Map(sections.map((section) => [section.key, section])));
  const sectionParents = sectionLists.map((sections, index) => sections[0]?.section.parentElement || cards[index].querySelector(".modal-panel-body") || cards[index]);

  sectionOrder.forEach((entry) => {
    sectionMaps.forEach((sectionMap, index) => {
      if (sectionMap.has(entry.key)) return;
      const section = createModalComparePlaceholderSection(entry.title);
      const wrapped = { key: entry.key, title: entry.title, section, tbody: section.querySelector("tbody") };
      sectionMap.set(entry.key, wrapped);
      sectionParents[index].appendChild(section);
    });
  });

  sectionParents.forEach((parent, index) => {
    sectionOrder.forEach((entry) => {
      const section = sectionMaps[index].get(entry.key)?.section;
      if (section) parent.appendChild(section);
    });
  });

  sectionOrder.forEach((entry) => {
    const sections = sectionMaps.map((sectionMap) => sectionMap.get(entry.key));
    const rowLists = sections.map(modalCompareSectionRows);
    const rowOrder = modalCompareOrderedMerge(
      rowLists[0].map(({ key, label }) => ({ key, label })),
      rowLists[1].map(({ key, label }) => ({ key, label })),
    );
    const rowMaps = rowLists.map((rows) => new Map(rows.map((row) => [row.key, row])));
    rowOrder.forEach((rowEntry) => {
      sections.forEach((section, index) => {
        if (!rowMaps[index].has(rowEntry.key)) {
          rowMaps[index].set(rowEntry.key, {
            key: rowEntry.key,
            label: rowEntry.label,
            row: createModalComparePlaceholderRow(rowEntry.label),
          });
        }
      });
    });
    sections.forEach((section, index) => {
      rowOrder.forEach((rowEntry) => {
        const row = rowMaps[index].get(rowEntry.key)?.row;
        if (row) section.tbody.appendChild(row);
      });
    });
    rowOrder.forEach((rowEntry) => {
      const rows = rowMaps.map((rowMap) => rowMap.get(rowEntry.key)?.row).filter(Boolean);
      rows.forEach((row) => { row.style.height = ""; });
      const maxHeight = Math.max(...rows.map((row) => row.getBoundingClientRect().height));
      if (Number.isFinite(maxHeight) && maxHeight > 0) {
        rows.forEach((row) => { row.style.height = `${Math.ceil(maxHeight)}px`; });
      }
    });
  });
}

function modalCompareNumericValue(text) {
  const normalized = `${text || ""}`.replace(/,/g, "").replace(/\u2212/g, "-");
  if (!normalized || /\bN\/A\b/i.test(normalized)) return null;
  const match = normalized.match(/-?\d+(?:\.\d+)?/);
  if (!match) return null;
  const value = Number(match[0]);
  return Number.isFinite(value) ? value : null;
}

function applyModalCompareHighlights() {
  if (!state.modalCompare.enabled || !state.modalCompareHighlight || !els.modalContent) return;
  const cards = [...els.modalContent.querySelectorAll(".modal-compare-card[data-modal-compare-card]")];
  if (cards.length !== 2) return;
  const rowsByKey = cards.map((card) => {
    const rows = new Map();
    card.querySelectorAll(".modal-stat-card").forEach((statCard) => {
      const title = statCard.querySelector("h4")?.textContent?.trim() || "";
      statCard.querySelectorAll("tbody tr").forEach((row) => {
        const cells = row.querySelectorAll("td");
        if (cells.length < 2) return;
        const label = cells[0].dataset.modalStatLabel || cells[0].textContent.trim();
        if (!label || MODAL_COMPARE_EXTREME_EXCLUDED_LABELS.has(label)) return;
        const value = modalCompareNumericValue(cells[1].textContent);
        if (value == null) return;
        rows.set(`${title}::${label}`, { label, value, cell: cells[1] });
      });
    });
    return rows;
  });

  rowsByKey[0].forEach((left, key) => {
    const right = rowsByKey[1].get(key);
    if (!right || left.value === right.value) return;
    const lowIsGood = PARAMETER_LOW_IS_GOOD_LABELS.has(left.label);
    const leftBest = lowIsGood ? left.value < right.value : left.value > right.value;
    left.cell.classList.add(leftBest ? "param-extreme-best" : "param-extreme-worst");
    right.cell.classList.add(leftBest ? "param-extreme-worst" : "param-extreme-best");
  });
}

function shellDescription(projectile) {
  return projectile?.caliber_mm ? `${formatValue(projectile.caliber_mm, { digits: 0 })} mm` : "N/A";
}

function weaponModuleDisplayName(module) {
  const rawName = module?.name || "";
  return module?.display_name
    || module?.translated_name
    || rawName
    || "Unknown weapon";
}

function shipModalDisplayName(ship) {
  return ship?.identity?.full_name
    || ship?.fullDisplayName
    || ship?.identity?.display_name
    || ship?.displayName
    || prettyShipName(ship?.identity?.name)
    || ship?.identity?.code
    || "Unknown";
}

function shipParentReferenceCode(reference) {
  const value = `${reference || ""}`.trim();
  if (!value) return "";
  return value.split("_", 1)[0];
}

function shipCloneParent(ship) {
  const reference = ship?.identity?.parent_ship || ship?.identity?.parentShip || ship?.parentShip || ship?.parent_ship;
  const code = shipParentReferenceCode(reference);
  if (!code) return null;
  return state.ships.find((item) => item.identity?.code === code || item.identity?.name === reference) || {
    identity: {
      code,
      name: reference,
      display_name: reference ? reference.split("_").slice(1).join(" ").trim() : code,
    },
  };
}

function renderShipCloneLine(ship) {
  const parent = shipCloneParent(ship);
  if (!parent) return "";
  const parentName = shipModalDisplayName(parent);
  const parentCode = parent?.identity?.code;
  const canOpenParent = parentCode && state.ships.some((item) => item.identity?.code === parentCode);
  const parentMarkup = canOpenParent
    ? `<button class="modal-clone-link" type="button" data-modal-nav="${escapeHtml(parentCode)}">${escapeHtml(parentName)}</button>`
    : escapeHtml(parentName);
  return `<p class="modal-clone-line">${escapeHtml(t("modal.cloneOf", "Clone of"))} ${parentMarkup}</p>`;
}

function weaponDescriptionDetails(modules) {
  const groups = new Map();
  (modules || []).forEach((module) => {
    const barrels = module?.barrels;
    if (!barrels) return;
    const rawName = module?.name || "Unknown weapon";
    const key = `${barrels}|${rawName}`;
    if (!groups.has(key)) {
      groups.set(key, {
        barrels,
        rawName,
        displayName: weaponModuleDisplayName(module),
        mounts: 0,
      });
    }
    groups.get(key).mounts += 1;
  });
  return [...groups.values()]
    .sort((left, right) => right.mounts - left.mounts || right.barrels - left.barrels || left.rawName.localeCompare(right.rawName))
    .map((group) => ({
      label: `${group.mounts}x${group.barrels}`,
      value: group.displayName,
    }));
}

function weaponDescriptionHover(display, modules) {
  const details = weaponDescriptionDetails(modules);
  if (!details.length) return display;
  return `
    <span class="stat-hover weapon-description-hover">
      ${display}<sup class="stat-hover-marker">*</sup>
      <span class="stat-hover-card">
        ${details.map((detail) => `
          <span class="stat-hover-line weapon-description-line">
            <em class="weapon-description-count">${escapeHtml(detail.label)}</em>
            <span class="weapon-description-name">${escapeHtml(detail.value)}</span>
          </span>
        `).join("")}
      </span>
    </span>
  `;
}

function weaponModuleMatches(module, species, fallbackPattern) {
  const typeinfo = module?.typeinfo || {};
  if (typeinfo.species || typeinfo.type) {
    return typeinfo.species === species && typeinfo.type === "Gun";
  }
  return fallbackPattern.test(module?.slot || "");
}

function mainBatteryModules(ship) {
  return (ship.artillery?.main_battery?.modules || [])
    .filter((module) => weaponModuleMatches(module, "Main", /^HP_[A-Z]GM_\d+$/))
    .sort((left, right) => {
      const leftNum = Number((left?.slot || "").match(/_(\d+)$/)?.[1] || 9999);
      const rightNum = Number((right?.slot || "").match(/_(\d+)$/)?.[1] || 9999);
      return leftNum - rightNum;
    });
}

function mediumBattery(ship) {
  return ship?.artillery?.medium_battery || {};
}

function mediumBatteryModules(ship) {
  return (mediumBattery(ship).modules || [])
    .filter((module) => weaponModuleMatches(module, "Main", /^HP_[A-Z]GM_\d+$/))
    .sort((left, right) => {
      const leftNum = Number((left?.slot || "").match(/_(\d+)$/)?.[1] || 9999);
      const rightNum = Number((right?.slot || "").match(/_(\d+)$/)?.[1] || 9999);
      return leftNum - rightNum;
    });
}

function mediumBatteryProjectiles(ship) {
  return uniqueProjectiles(mediumBattery(ship).projectiles || []);
}

function mediumBatteryProjectile(ship) {
  const projectiles = mediumBatteryProjectiles(ship);
  return projectiles.find((projectile) => projectile?.ammo_type === "CS")
    || projectiles.find((projectile) => projectile?.ammo_type === "HE")
    || projectiles.find((projectile) => projectile?.ammo_type === "AP")
    || projectiles[0]
    || null;
}

function mediumBatteryAmmoPrefix(projectile) {
  if (projectile?.ammo_type === "CS") return "SAP";
  if (projectile?.ammo_type === "HE") return "HE";
  if (projectile?.ammo_type === "AP") return "AP";
  return "Shell";
}

function mediumBatteryDescription(ship) {
  const modules = mediumBatteryModules(ship);
  const caliber = mediumBattery(ship).caliber_mm;
  if (!modules.length || !caliber) return "N/A";
  const counts = new Map();
  modules.forEach((module) => {
    const barrels = Number(module?.barrels);
    if (!Number.isFinite(barrels) || barrels <= 0) return;
    counts.set(barrels, (counts.get(barrels) || 0) + 1);
  });
  const parts = [...counts.entries()]
    .sort((left, right) => right[1] - left[1] || right[0] - left[0])
    .map(([barrels, mounts]) => String(mounts) + "x" + String(barrels));
  return parts.length
    ? weaponDescriptionHover(parts.join(", ") + " " + formatValue(caliber, { digits: 0 }) + " mm", modules)
    : "N/A";
}

function mediumBatteryBroadsideValue(ship, valueGetter) {
  const modules = mediumBatteryModules(ship);
  const broadside = weaponBroadsideMaxValue(ship, modules, "main", valueGetter);
  if (broadside != null) return broadside;
  const values = modules
    .map((module) => Number(valueGetter(module)))
    .filter((value) => Number.isFinite(value));
  return values.length ? values.reduce((sum, value) => sum + value, 0) : null;
}

function mediumBatterySalvo(ship) {
  const projectile = mediumBatteryProjectile(ship);
  const damage = Number(projectile?.alpha_damage);
  if (!Number.isFinite(damage) || damage <= 0) return null;
  return mediumBatteryBroadsideValue(ship, (module) => {
    const barrels = Number(module?.barrels);
    return Number.isFinite(barrels) && barrels > 0 ? barrels * damage : null;
  });
}

function mediumBatteryShellsPerMinute(ship) {
  const battery = mediumBattery(ship);
  return mediumBatteryBroadsideValue(ship, (module) => {
    const barrels = Number(module?.barrels);
    const reload = Number(module?.reload_s ?? battery?.reload_s);
    if (!Number.isFinite(barrels) || barrels <= 0 || !Number.isFinite(reload) || reload <= 0) return null;
    return barrels * (60 / reload);
  });
}

function mediumBatteryDpm(ship) {
  const projectile = mediumBatteryProjectile(ship);
  const damage = Number(projectile?.alpha_damage);
  const shellsMinute = mediumBatteryShellsPerMinute(ship);
  if (!Number.isFinite(damage) || damage <= 0 || !Number.isFinite(shellsMinute)) return null;
  return damage * shellsMinute;
}

function mediumBatteryTurn180(ship) {
  const rotation = Number(mediumBatteryModules(ship)[0]?.rotation_deg_per_s);
  return Number.isFinite(rotation) && rotation > 0 ? 180 / rotation : null;
}

function mediumBatteryDrum(ship) {
  return mediumBattery(ship).drum_artillery || mediumBatteryModules(ship)[0]?.drum_artillery || null;
}

function mediumBatteryReloadSeconds(ship) {
  const reload = Number(mediumBattery(ship).reload_s ?? mediumBatteryModules(ship)[0]?.reload_s);
  return Number.isFinite(reload) && reload > 0 ? reload : null;
}

function mediumBatteryPenetration(ship) {
  const projectile = mediumBatteryProjectile(ship);
  if (projectile?.ammo_type === "CS") return projectile?.alpha_piercing_cs ?? null;
  if (projectile?.ammo_type === "HE") return projectile?.alpha_piercing_he ?? null;
  return projectile?.alpha_piercing_ap ?? projectile?.alpha_piercing ?? null;
}

function mediumBatteryFireChance(ship) {
  const projectile = mediumBatteryProjectile(ship);
  return projectile?.ammo_type === "HE" ? positiveRatioValue(projectile?.burn_prob) : null;
}

function secondaryGunModules(ship) {
  return (ship.artillery?.secondaries || [])
    .filter((module) => weaponModuleMatches(module, "Secondary", /^HP_[A-Z]GS_\d+$/))
    .sort((left, right) => {
      const leftNum = Number((left?.slot || "").match(/_(\d+)$/)?.[1] || 9999);
      const rightNum = Number((right?.slot || "").match(/_(\d+)$/)?.[1] || 9999);
      return leftNum - rightNum;
    });
}

function secondaryModuleGroupKey(module) {
  const projectile = secondaryPreferredProjectile(module);
  return [
    module?.caliber_mm ?? "",
    module?.barrels ?? "",
    module?.reload_s ?? "",
    projectile?.id ?? "",
    module?.sigma_count ?? "",
    module?.max_dist_m ?? module?.range_m ?? "",
  ].join("|");
}

function secondaryModuleGroupsFromModules(modules) {
  const groups = new Map();
  (modules || []).forEach((module) => {
    const projectile = secondaryPreferredProjectile(module);
    const key = secondaryModuleGroupKey(module);
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        caliber_mm: module?.caliber_mm ?? null,
        barrels: module?.barrels ?? null,
        reload_s: module?.reload_s ?? null,
        sigma_count: module?.sigma_count ?? null,
        max_dist_m: module?.max_dist_m ?? module?.range_m ?? null,
        range_m: module?.range_m ?? module?.max_dist_m ?? null,
        projectile,
        mounts: 0,
        modules: [],
      });
    }
    const group = groups.get(key);
    group.mounts += 1;
    group.modules.push(module);
  });
  return [...groups.values()].sort((left, right) => (
    (right.caliber_mm || 0) - (left.caliber_mm || 0)
    || (right.barrels || 0) - (left.barrels || 0)
    || `${left.key}`.localeCompare(`${right.key}`)
  ));
}

function secondaryGroupColorMapFromModules(modules) {
  const groups = secondaryModuleGroupsFromModules(modules);
  if (groups.length <= 1) return new Map();
  return new Map(groups.map((group, index) => [group.key, SECONDARY_GROUP_COLORS[index % SECONDARY_GROUP_COLORS.length]]));
}

function secondaryGroupColorStyle(color) {
  return color ? ` style="--weapon-group-color: ${escapeHtml(color)}; color: ${escapeHtml(color)};"` : "";
}

function secondaryDescriptionHover(display, groups, colorMap) {
  if (!groups.length) return display;
  return `
    <span class="stat-hover weapon-description-hover secondary-description-hover">
      ${display}<sup class="stat-hover-marker">*</sup>
      <span class="stat-hover-card">
        ${groups.map((group) => {
          const color = colorMap.get(group.key);
          return `
            <span class="stat-hover-line weapon-description-line"${secondaryGroupColorStyle(color)}>
              <em class="weapon-description-count">${escapeHtml(secondaryGroupLabel(group))}</em>
              <span class="weapon-description-name">${escapeHtml(weaponModuleDisplayName(group.modules?.[0]))}</span>
            </span>
          `;
        }).join("")}
      </span>
    </span>
  `;
}

function secondaryDescription(ship, options = {}) {
  const modules = secondaryGunModules(ship);
  if (!modules.length) return "N/A";
  const groups = secondaryModuleGroupsFromModules(modules);
  const useColor = options.color !== false;
  const colorMap = useColor ? secondaryGroupColorMapFromModules(modules) : new Map();
  const parts = groups
    .filter((group) => group?.mounts && group?.barrels && group?.caliber_mm)
    .map((group) => {
      const color = useColor ? colorMap.get(group.key) : null;
      return `<span class="secondary-description-part"${secondaryGroupColorStyle(color)}>${escapeHtml(secondaryGroupLabel(group))}</span>`;
    });
  return parts.length ? secondaryDescriptionHover(parts.join("<br>"), groups, colorMap) : "N/A";
}

function secondaryPreferredProjectile(module) {
  const shells = module?.shells || [];
  return shells.find((shell) => shell.ammo_type === "HE")
    || shells.find((shell) => shell.ammo_type === "CS")
    || shells.find((shell) => shell.ammo_type === "AP")
    || shells[0]
    || null;
}

function secondaryAmmoTypeLabel(ship) {
  const types = [...new Set(secondaryModuleGroups(ship).map((group) => group?.projectile?.ammo_type).filter(Boolean))];
  if (!types.length) return "Secondaries";
  if (types.length === 1) {
    if (types[0] === "HE") return "HE Secondaries";
    if (types[0] === "AP") return "AP Secondaries";
    if (types[0] === "CS") return "SAP Secondaries";
  }
  return "Secondaries";
}

function secondaryUsesFire(ship) {
  return secondaryModuleGroups(ship).some((group) => {
    const ammoType = group?.projectile?.ammo_type;
    const burnProb = group?.projectile?.burn_prob;
    return ammoType === "HE" && typeof burnProb === "number" && burnProb > 0;
  });
}

function secondaryChartProjectile(ship) {
  return secondaryModuleGroups(ship).find((group) => group?.projectile)?.projectile
    ?? secondaryPreferredProjectile(secondaryModule(ship));
}

function secondaryPenetrationValue(ship, group, context) {
  const projectile = group?.projectile;
  const ammoType = projectile?.ammo_type;
  if (ammoType === "AP") {
    const ballisticPenetration = shellResultAtRange(
      ship,
      projectile,
      secondaryShellContextForGroup(context, ship, group),
      "Secondaries",
    )?.penetration_mm;
    const numericPenetration = Number(ballisticPenetration);
    if (Number.isFinite(numericPenetration)) return numericPenetration;
  }
  if (ammoType === "CS") return projectile?.alpha_piercing_cs ?? null;
  if (ammoType === "HE") return projectile?.alpha_piercing_he ?? null;
  return projectile?.alpha_piercing_ap
    ?? projectile?.alpha_piercing
    ?? projectile?.alpha_piercing_he
    ?? null;
}

function secondarySigma(ship) {
  const modules = secondaryGunModules(ship);
  if (!modules.length) return null;
  const module = modules.find((item) => /_GS_1$/.test(item?.slot || "")) || modules[0];
  const sigma = module?.sigma_count
    ?? modules.find((item) => item?.sigma_count != null)?.sigma_count
    ?? null;
  return sigma ?? 1.0;
}

function secondaryModuleGroups(ship) {
  return secondaryModuleGroupsFromModules(secondaryGunModules(ship));
}

function secondaryGroupLabel(group) {
  if (!group?.mounts || !group?.barrels || !group?.caliber_mm) return "Unknown";
  return `${group.mounts}x${group.barrels} ${formatValue(group.caliber_mm, { digits: 0 })} mm`;
}

function hoverStatDisplay(display, details) {
  if (!details || details.length <= 1) return display;
  return `
    <span class="stat-hover">
      ${display}<sup class="stat-hover-marker">*</sup>
      <span class="stat-hover-card">
        ${details.map((detail) => `
          <span class="stat-hover-line">
            <span class="stat-hover-line-label">${escapeHtml(detail.label)}:</span>
            <span class="stat-hover-line-value">${escapeHtml(detail.value)}</span>
          </span>
        `).join("")}
      </span>
    </span>
  `;
}

function secondaryRangeStat(ship, valueGetter, formatter, options = {}) {
  const groups = secondaryModuleGroups(ship);
  const values = groups
    .map((group) => ({ label: secondaryGroupLabel(group), raw: valueGetter(group) }))
    .filter((item) => typeof item.raw === "number" && Number.isFinite(item.raw));
  if (!values.length) return "N/A";
  const details = values.map((item) => ({ label: item.label, value: formatter(item.raw) }));
  const uniqueDetailValues = [...new Set(details.map((item) => item.value))];
  const unique = [...new Set(values.map((item) => Number(item.raw.toFixed(options.digits ?? 1))))].sort((a, b) => a - b);
  const display = unique.length === 1
    ? formatter(unique[0])
    : `${formatter(unique[0])} - ${formatter(unique[unique.length - 1])}`;
  if (uniqueDetailValues.length === 1) return display;
  return hoverStatDisplay(display, details);
}

function secondaryTotalStat(ship, valueGetter, options = {}) {
  const groups = secondaryModuleGroups(ship);
  const values = groups
    .map((group) => ({ label: secondaryGroupLabel(group), raw: valueGetter(group) }))
    .filter((item) => typeof item.raw === "number" && Number.isFinite(item.raw));
  if (!values.length) return "N/A";
  const total = values.reduce((sum, item) => sum + item.raw, 0);
  const formatter = options.formatter || ((value) => formatValue(value, options));
  const detailFormatter = options.detailFormatter || formatter;
  const details = values.map((item) => ({ label: item.label, value: detailFormatter(item.raw) }));
  return hoverStatDisplay(formatter(total), details);
}

function shellsPerMinute(reloadS, gunCount = 1) {
  if (!reloadS || !gunCount) return null;
  return (60 / reloadS) * gunCount;
}

function mainBatteryModuleShellsPerMinuteValue(ship, module) {
  const barrels = Number(module?.barrels);
  const reload = Number(module?.reload_s ?? ship?.artillery?.main_battery?.reload_s);
  if (!Number.isFinite(barrels) || barrels <= 0 || !Number.isFinite(reload) || reload <= 0) {
    return null;
  }
  return barrels * (60 / reload);
}

function mainBatteryShellsPerMinute(ship) {
  const broadside = weaponBroadsideMaxValue(
    ship,
    mainBatteryModules(ship),
    "main",
    (module) => mainBatteryModuleShellsPerMinuteValue(ship, module),
  );
  if (broadside != null) return broadside;
  return shellsPerMinute(ship.artillery?.main_battery?.reload_s, ship.artillery?.main_battery?.gun_count);
}

function mainBatteryModuleDpmValue(ship, projectile, module) {
  const barrels = Number(module?.barrels);
  const reload = Number(module?.reload_s ?? ship?.artillery?.main_battery?.reload_s);
  const damage = Number(projectile?.alpha_damage);
  if (!Number.isFinite(barrels) || barrels <= 0 || !Number.isFinite(reload) || reload <= 0 || !Number.isFinite(damage) || damage <= 0) {
    return null;
  }
  return barrels * damage * (60 / reload);
}

function mainBatterySalvo(ship, type) {
  const projectile = firstProjectile(ship, type);
  const gunCount = ship.artillery?.main_battery?.gun_count;
  if (!projectile?.alpha_damage || !gunCount) return null;
  return projectile.alpha_damage * gunCount;
}

function mainBatteryDpm(ship, type) {
  const projectile = firstProjectile(ship, type);
  if (!projectile?.alpha_damage) return null;
  const broadside = weaponBroadsideMaxValue(
    ship,
    mainBatteryModules(ship),
    "main",
    (module) => mainBatteryModuleDpmValue(ship, projectile, module),
  );
  if (broadside != null) return broadside;
  const salvo = mainBatterySalvo(ship, type);
  const shellsMin = mainBatteryShellsPerMinute(ship);
  const gunCount = ship.artillery?.main_battery?.gun_count;
  if (!salvo || !shellsMin || !gunCount) return null;
  return salvo * (shellsMin / gunCount);
}

function mainBatteryTurn180(ship) {
  const rotation = ship.artillery?.main_battery?.modules?.[0]?.rotation_deg_per_s;
  if (!rotation) return null;
  return 180 / rotation;
}

function mainBatteryDescription(ship) {
  const modules = mainBatteryModules(ship);
  const caliber = ship.artillery?.main_battery?.caliber_mm;
  if (!modules.length || !caliber) return "N/A";
  const counts = new Map();
  modules.forEach((module) => {
    const barrels = module?.barrels;
    if (!barrels) return;
    counts.set(barrels, (counts.get(barrels) || 0) + 1);
  });
  const parts = [...counts.entries()]
    .sort((left, right) => right[1] - left[1] || right[0] - left[0])
    .map(([barrels, mounts]) => `${mounts}x${barrels}`);
  return weaponDescriptionHover(`${parts.join(", ")} ${formatValue(caliber, { digits: 0 })} mm`, modules);
}

function torpedoDescription(ship) {
  const modules = torpedoModules(ship);
  if (!modules.length) return "N/A";
  const counts = new Map();
  modules.forEach((module) => {
    const barrels = module?.barrels;
    if (!barrels) return;
    counts.set(barrels, (counts.get(barrels) || 0) + 1);
  });
  const projectile = firstTorpedoProjectile(ship);
  const caliber = projectile?.caliber_mm;
  const parts = [...counts.entries()]
    .sort((left, right) => right[1] - left[1] || right[0] - left[0])
    .map(([barrels, mounts]) => `${mounts}x${barrels}`);
  return parts.length && caliber ? weaponDescriptionHover(`${parts.join(", ")} ${formatValue(caliber, { digits: 0 })} mm`, modules) : "N/A";
}

function shellRicochet(projectile) {
  if (projectile?.ricochet_at == null || projectile?.always_ricochet_at == null) return "N/A";
  return `${formatValue(projectile.ricochet_at, { digits: 0 })}-${formatValue(projectile.always_ricochet_at, { digits: 0 })}\u00b0`;
}

function shellOvermatch(projectile) {
  if (!projectile?.caliber_mm) return null;
  return Math.floor(projectile.caliber_mm / 14.3);
}

function shellFirePerMinute(ship, projectile) {
  const burnProb = positiveRatioValue(projectile?.burn_prob);
  if (burnProb == null) return null;
  const salvoShellCount = ship?.artillery?.main_battery?.gun_count;
  const reload = ship?.artillery?.main_battery?.reload_s;
  if (!salvoShellCount || !reload) return null;
  const fireChancePercent = burnProb * 100;
  return ((salvoShellCount * fireChancePercent) * (60 / reload)) / 100;
}

function secondaryFirePerMinute(ship) {
  const total = secondaryModuleGroups(ship).reduce((sum, group) => sum + (secondaryGroupFirePerMinute(group) || 0), 0);
  return total || null;
}

function isThermalTorpedoProjectile(projectile) {
  const ammoType = `${projectile?.ammo_type || ""}`;
  return ammoType.startsWith("torpedo") && positiveRatioValue(projectile?.burn_prob) != null;
}

function torpedoFireChanceDisplay(projectile) {
  const burnProb = positiveRatioValue(projectile?.burn_prob);
  return burnProb == null ? uiLabel("N/A") : fireChanceDisplay(burnProb, { scale: 100 });
}

function torpedoTitleForProjectile(projectile, variantIndex = 0) {
  const baseTitle = isThermalTorpedoProjectile(projectile) ? "Thermal torpedo" : "Torpedoes";
  return `${baseTitle}${variantAltSuffix(variantIndex)}`;
}

function torpedoTypeDisplay(projectile) {
  if (!projectile?.ammo_type) return uiLabel("N/A");
  if (isThermalTorpedoProjectile(projectile)) return uiLabel("Thermal torpedo");
  if (projectile.ammo_type === "torpedo") return uiLabel("Normal");
  if (projectile.ammo_type === "torpedo_alternative") return uiLabel("Alternative");
  if (projectile.ammo_type === "torpedo_deepwater") {
    const ignored = projectile.ignore_classes || [];
    const codeMap = {
      AircraftCarrier: "CV",
      Battleship: "BB",
      Cruiser: "CA",
      Destroyer: "DD",
      Submarine: "SS",
      AirCarrier: "CV",
    };
    const allClasses = ["AircraftCarrier", "Battleship", "Cruiser", "Destroyer", "Submarine"];
    const canHit = allClasses.filter((item) => !ignored.includes(item)).map((item) => codeMap[item]).join(", ");
    return `<span title="${escapeHtml(t("torpedo.canHit", "Can hit: {classes}", { classes: canHit }))}">${escapeHtml(uiLabel("Deepwater"))}</span>`;
  }
  return projectile.ammo_type;
}

function torpedoLoaders(ship) {
  const loaders = resolvedShipView(ship).torpedoes?.loaders;
  if (!Array.isArray(loaders) || !loaders.length) return "N/A";
  return loaders.slice(0, 2).join(", ");
}

function uniqueProjectiles(projectiles) {
  const seen = new Set();
  return (projectiles || []).filter((projectile) => {
    if (!projectile?.id || seen.has(projectile.id)) return false;
    seen.add(projectile.id);
    return true;
  });
}

function mainBatteryProjectiles(ship) {
  return uniqueProjectiles(ship.artillery?.main_battery?.projectiles || []);
}

function mainBatteryResultsAtRange(ship, context) {
  return mainBatteryProjectiles(ship)
    .map((projectile) => shellResultAtRange(ship, projectile, context, "Main battery"))
    .filter(Boolean);
}

function projectileAmmoLabel(projectile) {
  if (!projectile?.ammo_type) return "Shell";
  const isRussian = state.language === "ru";
  if (projectile.ammo_type === "AP") return isRussian ? "ББ" : "AP";
  if (projectile.ammo_type === "HE") return isRussian ? "ОФ" : "HE";
  if (projectile.ammo_type === "CS") return isRussian ? "ПББ" : "SAP";
  return projectile.ammo_type;
}

function shellChartUnitLabel(metric) {
  if (state.language !== "ru") return metric === "penetration" ? "mm / km" : "s / km";
  return metric === "penetration" ? "мм / км" : "с / км";
}

function shellChartAxisUnit(metric) {
  if (state.language !== "ru") return metric === "penetration" ? "mm" : "s";
  return metric === "penetration" ? "мм" : "с";
}

function shellChartDistanceUnit() {
  return state.language === "ru" ? "км" : "km";
}

function mainBatteryDetailedResultsAtRange(ship, context) {
  return mainBatteryProjectiles(ship)
    .map((projectile) => ({
      label: projectileAmmoLabel(projectile),
      result: shellResultAtRange(ship, projectile, context, "Main battery"),
    }))
    .filter((item) => item.result);
}

function mainBatteryFlightTimeDisplay(ship, context) {
  const values = mainBatteryDetailedResultsAtRange(ship, context)
    .map((item) => ({ label: item.label, raw: item.result?.time_s }))
    .filter((item) => typeof item.raw === "number" && Number.isFinite(item.raw));
  if (!values.length) return "N/A";
  const roundedValues = values.map((item) => ({
    label: item.label,
    rounded: Number(item.raw.toFixed(1)),
  }));
  const detailMap = new Map();
  roundedValues.forEach((item) => {
    if (!detailMap.has(item.rounded)) {
      detailMap.set(item.rounded, []);
    }
    detailMap.get(item.rounded).push(item.label);
  });
  const unique = [...detailMap.keys()].sort((a, b) => a - b);
  const display = unique.length === 1
    ? formatValue(unique[0], { digits: 1, suffix: " s" })
    : `${formatValue(unique[0], { digits: 1, suffix: " s" })} - ${formatValue(unique[unique.length - 1], { digits: 1, suffix: " s" })}`;
  if (unique.length === 1) return display;
  const details = unique.map((value) => ({
    label: detailMap.get(value).join("/"),
    value: formatValue(value, { digits: 1, suffix: " s" }),
  }));
  return hoverStatDisplay(display, details);
}

function shellFlightTimeDisplay(ship, projectile, context, groupLabel) {
  const result = shellResultAtRange(ship, projectile, context, groupLabel);
  return formatValue(result?.time_s, { digits: 1, suffix: " s" });
}

function shellImpactSpeedDisplay(ship, projectile, context, groupLabel) {
  const result = shellResultAtRange(ship, projectile, context, groupLabel);
  return formatValue(result?.impact_speed, { digits: 0, suffix: " m/s" });
}

function shellImpactAngleDisplay(ship, projectile, context, groupLabel) {
  const result = shellResultAtRange(ship, projectile, context, groupLabel);
  return formatValue(result?.impact_angle_deg, { digits: 1, suffix: "\u00b0" });
}

function shellPenetrationDisplay(ship, projectile, context, groupLabel) {
  const result = shellResultAtRange(ship, projectile, context, groupLabel);
  return formatValue(result?.penetration_mm, { digits: 0, suffix: " mm" });
}

function mainBatteryDispersionDisplay(ship, context, axis = "horizontal") {
  const module = mainBatteryModule(ship);
  const value = axis === "vertical"
    ? verticalDispersionMeters(module, context?.range_m)
    : horizontalDispersionMeters(module, context?.range_m);
  return formatValue(value, { digits: 0, suffix: " m" });
}

function secondariesFlightTimeDisplay(ship, context) {
  return secondaryRangeStat(
    ship,
    (group) => shellResultAtRange(
      ship,
      group.projectile,
      secondaryShellContextForGroup(context, ship, group),
      "Secondaries",
    )?.time_s,
    (value) => formatValue(value, { digits: 1, suffix: " s" }),
    { digits: 1 },
  );
}

function secondariesDispersionDisplay(ship, context) {
  return secondaryRangeStat(
    ship,
    (group) => horizontalDispersionMeters(group?.modules?.[0], context?.range_m),
    (value) => formatValue(value, { digits: 0, suffix: " m" }),
    { digits: 0 },
  );
}

function secondariesSigmaDisplay(ship) {
  return secondaryRangeStat(
    ship,
    (group) => group?.sigma_count ?? 1.0,
    (value) => formatSigma(value),
    { digits: 2 },
  );
}

function torpedoTubeCount(ship) {
  const total = torpedoModules(ship).reduce((sum, module) => sum + (Number(module?.barrels) || 0), 0);
  return total || null;
}

function torpedoReloadSeconds(ship) {
  const resolved = resolvedShipView(ship);
  const module = firstTorpedoModule(resolved);
  return module?.reload_s ?? resolved.torpedoes?.reload_s ?? null;
}

function torpedoesPerMinute(ship) {
  const tubes = torpedoTubeCount(ship);
  const reload = torpedoReloadSeconds(ship);
  if (!tubes || !reload) return null;
  return tubes * (60 / reload);
}

function torpedoDpm(ship) {
  const torpedoesMin = torpedoesPerMinute(ship);
  const damagePerTorpedo = torpedoEffectiveDamage(ship);
  if (damagePerTorpedo == null || !torpedoesMin) return null;
  return damagePerTorpedo * torpedoesMin;
}

function torpedoEffectiveDamage(ship) {
  const projectile = firstTorpedoProjectile(ship);
  return torpedoDamageFromProjectile(projectile);
}

function torpedoReactionTime(ship) {
  const projectile = firstTorpedoProjectile(ship);
  if (!projectile?.visibility_factor || !projectile?.speed) return null;
  return (projectile.visibility_factor / (projectile.speed * TORPEDO_REACTION_SPEED_FACTOR)) * 1000;
}

function secondariesShellsPerMinute(ship) {
  const broadside = secondaryBroadsideStatValue(ship, (module) => secondaryModuleShellsPerMinuteValue(module));
  if (broadside != null) return broadside;
  const total = secondaryModuleGroups(ship).reduce((sum, group) => sum + (secondaryGroupShellsPerMinute(group) || 0), 0);
  return total || null;
}

function secondaryProjectile(ship) {
  const module = secondaryModule(ship);
  return module?.shells?.find((shell) => shell.ammo_type === "HE") || module?.shells?.[0] || null;
}

function secondaryDpm(ship) {
  const broadside = weaponBroadsideMaxValue(
    ship,
    secondaryGunModules(ship),
    "secondary",
    (module) => secondaryModuleFirepowerWeight(module),
  );
  if (broadside != null) return broadside;
  const total = secondaryModuleGroups(ship).reduce((sum, group) => sum + (secondaryGroupDpm(group) || 0), 0);
  return total || null;
}

function secondaryDpmDisplay(ship) {
  return secondaryBroadsideStatDisplay(ship, (module) => secondaryModuleFirepowerWeight(module), {
    formatter: (value) => formatValue(value, { digits: 0, grouping: true }),
    detailFormatter: (value) => formatValue(value, { digits: 0, grouping: true }),
  });
}

function secondaryModuleShellsPerMinuteValue(module) {
  const barrels = Number(module?.barrels);
  const reload = Number(module?.reload_s);
  if (!Number.isFinite(barrels) || barrels <= 0 || !Number.isFinite(reload) || reload <= 0) {
    return null;
  }
  return barrels * (60 / reload);
}

function secondaryBroadsideStatResult(ship, valueGetter) {
  const modules = secondaryGunModules(ship);
  const result = weaponBroadsideMaxResult(ship, modules, "secondary", valueGetter);
  return result?.value > 0 ? result : null;
}

function secondaryBroadsideStatValue(ship, valueGetter) {
  return secondaryBroadsideStatResult(ship, valueGetter)?.value ?? null;
}

function secondaryBroadsideStatDisplay(ship, valueGetter, options = {}) {
  const result = secondaryBroadsideStatResult(ship, valueGetter);
  if (!result) return "N/A";
  const formatter = options.formatter || ((value) => formatValue(value, options));
  const detailFormatter = options.detailFormatter || formatter;
  const groups = secondaryModuleGroups(ship);
  const details = groups
    .map((group) => {
      const groupItems = (result.items || []).filter((item) => secondaryModuleGroupKey(item.module) === group.key);
      const raw = result.angle == null ? 0 : weightedAvailableValue(groupItems, result.angle, valueGetter);
      return { label: secondaryGroupLabel(group), raw };
    })
    .filter((item) => typeof item.raw === "number" && Number.isFinite(item.raw) && item.raw > 0)
    .map((item) => ({ label: item.label, value: detailFormatter(item.raw) }));
  return hoverStatDisplay(formatter(result.value), details);
}

function secondaryBroadsideGroupValues(ship, valueGetter) {
  const result = secondaryBroadsideStatResult(ship, valueGetter);
  if (!result) return [];
  return secondaryModuleGroups(ship)
    .map((group) => {
      const groupItems = (result.items || []).filter((item) => secondaryModuleGroupKey(item.module) === group.key);
      const raw = result.angle == null ? 0 : weightedAvailableValue(groupItems, result.angle, valueGetter);
      return { label: secondaryGroupLabel(group), raw };
    })
    .filter((item) => typeof item.raw === "number" && Number.isFinite(item.raw) && item.raw > 0);
}

function secondaryDpmContributionDisplay(ship) {
  const values = secondaryBroadsideGroupValues(ship, (module) => secondaryModuleFirepowerWeight(module));
  if (!values.length) return "N/A";
  const total = values.reduce((sum, item) => sum + item.raw, 0);
  if (!total) return "N/A";
  const contributions = values
    .map((item) => ({
      ...item,
      percent: (item.raw / total) * 100,
    }))
    .sort((left, right) => right.percent - left.percent);
  const top = contributions[0];
  const display = contributions.length === 1
    ? "100%"
    : `${escapeHtml(top.label)} ${formatValue(top.percent, { digits: 0, suffix: "%" })}`;
  const details = contributions.map((item) => ({
    label: item.label,
    value: `${formatValue(item.percent, { digits: 1, suffix: "%" })} (${formatValue(item.raw, { digits: 0, grouping: true })})`,
  }));
  return hoverStatDisplay(display, details);
}

function secondaryHittingDpmDisplay(ship) {
  return secondaryBroadsideStatDisplay(ship, (module) => {
    const value = secondaryModuleFirepowerWeight(module);
    return Number.isFinite(value) ? value * 0.52 : null;
  }, {
    formatter: (value) => formatValue(value, { digits: 0, grouping: true }),
    detailFormatter: (value) => formatValue(value, { digits: 0, grouping: true }),
  });
}

function secondaryGroupShellsPerMinute(group) {
  const totalBarrels = (group?.mounts || 0) * (group?.barrels || 0);
  const reload = group?.reload_s;
  if (!reload || !totalBarrels) return null;
  return (60 / reload) * totalBarrels;
}

function secondaryGroupDpm(group) {
  const spm = secondaryGroupShellsPerMinute(group);
  const damage = group?.projectile?.alpha_damage || 0;
  if (!spm || !damage) return null;
  return damage * spm;
}

function secondaryGroupFirePerMinute(group) {
  const burnProb = positiveRatioValue(group?.projectile?.burn_prob);
  const salvoShellCount = (group?.mounts || 0) * (group?.barrels || 0);
  const reload = group?.reload_s;
  if (burnProb == null || !salvoShellCount || !reload) return null;
  const fireChancePercent = burnProb * 100;
  return (((salvoShellCount * fireChancePercent) * (60 / reload)) / 100);
}

function maxHorizontalSector(ship, secondary = false) {
  const modules = secondary ? secondaryGunModules(ship) : mainBatteryModules(ship);
  const spans = modules
    .map((module) => module.horizontal_sector)
    .filter((sector) => Array.isArray(sector) && sector.length === 2)
    .map(([min, max]) => Math.max(Math.abs(min), Math.abs(max)));
  return spans.length ? Math.max(...spans) : 45;
}

function renderArcPanel(leftAngle, rightAngle, titleLeft = "", titleRight = "") {
  const center = 110;
  const radius = 82;
  const toPoint = (angle, r = radius) => {
    const rad = (angle - 90) * Math.PI / 180;
    return [center + Math.cos(rad) * r, center + Math.sin(rad) * r];
  };
  const makeSector = (start, end, fill) => {
    const [x1, y1] = toPoint(start);
    const [x2, y2] = toPoint(end);
    const large = Math.abs(end - start) > 180 ? 1 : 0;
    return `<path d="M ${center} ${center} L ${x1} ${y1} A ${radius} ${radius} 0 ${large} 1 ${x2} ${y2} Z" fill="${fill}" opacity="0.6"></path>`;
  };
  return `
    <div class="arc-visuals">
      <svg viewBox="0 0 220 220" class="arc-panel">
        <circle cx="${center}" cy="${center}" r="${radius}" fill="#f3f0f0" stroke="#d9d2d2"></circle>
        ${makeSector(180 - leftAngle, 180 + leftAngle, "#d77b7b")}
        <rect x="98" y="54" width="24" height="112" rx="10" fill="#c9c9c9" stroke="#595959"></rect>
        <line x1="${center}" y1="12" x2="${center}" y2="208" stroke="#555" stroke-dasharray="4 4"></line>
      </svg>
      <svg viewBox="0 0 220 220" class="arc-panel">
        <circle cx="${center}" cy="${center}" r="${radius}" fill="#faf8f8" stroke="#d9d2d2"></circle>
        <circle cx="${center}" cy="${center}" r="58" fill="none" stroke="#ddd"></circle>
        <circle cx="${center}" cy="${center}" r="34" fill="none" stroke="#ddd"></circle>
        ${makeSector(180 - rightAngle, 180 + rightAngle, "#d77b7b")}
        <line x1="${center}" y1="12" x2="${center}" y2="208" stroke="#555" stroke-dasharray="4 4"></line>
        <text x="18" y="72" class="arc-label">${titleLeft}</text>
        <text x="176" y="72" class="arc-label">${titleRight}</text>
      </svg>
    </div>
  `;
}

function hashString32(value) {
  let hash = 2166136261;
  const text = `${value ?? ""}`;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function seededRandom(seed) {
  let stateValue = seed >>> 0;
  return () => {
    stateValue += 0x6D2B79F5;
    let value = stateValue;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

function gaussianRandom(random) {
  let first = 0;
  let second = 0;
  while (first === 0) first = random();
  while (second === 0) second = random();
  return Math.sqrt(-2 * Math.log(first)) * Math.cos(2 * Math.PI * second);
}

function randomShellDeviation(random, sigma) {
  const angle = random() * Math.PI;
  const gaussian = gaussianRandom(random) / Math.max(Number(sigma) || 1, 0.2);
  const fallback = random() * 2 - 1;
  const magnitude = Math.abs(gaussian) <= 1 ? gaussian : fallback;
  const lateral = Math.sin(angle) * magnitude;
  let longitudinal = Math.cos(angle) * magnitude;
  if (longitudinal > 0) longitudinal = 10 * Math.log(0.1 * longitudinal + 1);
  return { longitudinal, lateral };
}

function shellDispersionMetrics(ship, projectile, context, groupLabel) {
  const module = mainBatteryModule(ship);
  const rangeM = context?.range_m;
  const lateralRadiusM = horizontalDispersionMeters(module, rangeM);
  const perpendicularRadiusM = verticalDispersionMeters(module, rangeM);
  if (!module || !projectile || !Number.isFinite(lateralRadiusM) || !Number.isFinite(perpendicularRadiusM)) return null;
  const result = shellResultAtRange(ship, projectile, context, groupLabel);
  const impactAngleDeg = Number(result?.impact_angle_deg);
  const impactAngleRad = (clamp(Number.isFinite(impactAngleDeg) ? impactAngleDeg : 10, 2, 45) * Math.PI) / 180;
  const longitudinalRadiusM = perpendicularRadiusM / Math.max(Math.sin(impactAngleRad), 0.035);
  if (!Number.isFinite(longitudinalRadiusM) || longitudinalRadiusM <= 0 || lateralRadiusM <= 0) return null;
  return {
    lateralRadiusM,
    longitudinalRadiusM,
    sigma: Number(ship.artillery?.main_battery?.sigma_count) || Number(module?.sigma_count) || 1,
  };
}

function shellDispersionPoints(ship, projectile, context, groupLabel, metrics, shotCount = state.shellDispersionShots) {
  const count = clampShellDispersionShots(shotCount);
  const seed = hashString32([
    ship?.identity?.code,
    projectile?.id || projectile?.name || projectile?.ammo_type,
    context?.range_m,
    metrics?.sigma,
    count,
  ].join("|"));
  const random = seededRandom(seed);
  return Array.from({ length: count }, () => randomShellDeviation(random, metrics?.sigma));
}

function rangeLabelFromContext(context) {
  if (context?.range_km == null) return "N/A";
  return `${formatValue(context.range_km, { digits: 0 })} km`;
}

function secondaryShellContextForGroup(context, ship, group) {
  const maxRangeM = secondaryGroupTheoreticalRangeMeters(ship, group);
  return {
    ...context,
    max_range_m: maxRangeM ?? context?.max_range_m ?? null,
  };
}

function secondaryGroupTheoreticalRangeMeters(ship, group) {
  const baseRange = Number(group?.max_dist_m ?? group?.range_m);
  if (!Number.isFinite(baseRange) || baseRange <= 0) return null;
  return baseRange * secondaryTheoreticalRangeMultiplier(ship);
}

function shellChartRangeKm(ship, groupLabel, secondaryGroup = null) {
  if (groupLabel === "Secondaries" && secondaryGroup) {
    const maxRangeM = secondaryGroupTheoreticalRangeMeters(ship, secondaryGroup);
    return maxRangeM ? Math.min(SHELL_CHART_DEFAULT_MAX_KM, maxSelectableRangeKm(maxRangeM)) : 0;
  }
  const options = rangeOptionsKm(groupLabel, [ship]);
  if (options.length) return Math.min(SHELL_CHART_DEFAULT_MAX_KM, options[options.length - 1]);
  const maxRangeM = weaponRangeMetersForGroup(ship, groupLabel);
  return maxRangeM ? Math.min(SHELL_CHART_DEFAULT_MAX_KM, maxSelectableRangeKm(maxRangeM)) : 0;
}

function shellChartSeries(ship, projectile, context, groupLabel, metric, secondaryGroup = null) {
  const maxKm = shellChartRangeKm(ship, groupLabel, secondaryGroup);
  if (!ship || !projectile || !maxKm) return [];
  const shellContext = groupLabel === "Secondaries" && secondaryGroup
    ? secondaryShellContextForGroup(context, ship, secondaryGroup)
    : context;
  const series = [];
  for (let km = 1; km <= maxKm; km += 1) {
    const result = shellResultAtRange(ship, projectile, {
      ...shellContext,
      groupLabel,
      range_km: km,
      range_m: km * 1000,
    }, groupLabel);
    const value = metric === "penetration" ? result?.penetration_mm : result?.time_s;
    if (typeof value === "number" && Number.isFinite(value)) {
      series.push({ km, value });
    }
  }
  return series;
}

function projectileForShellChart(ship, groupLabel) {
  if (groupLabel === "AP Shells") return firstProjectile(ship, "AP");
  if (groupLabel === "HE Shells") return firstProjectile(ship, "HE");
  if (groupLabel === "SAP Shells") return firstProjectile(ship, "SAP");
  if (groupLabel === "Secondaries") return secondaryChartProjectile(ship);
  return null;
}

function secondaryChartSeriesLabel(ship, group) {
  const shipName = shipModalDisplayName(ship);
  const groupLabel = secondaryGroupLabel(group);
  return groupLabel && groupLabel !== "Unknown" ? `${shipName} ${groupLabel}` : shipName;
}

function shellChartCompareShips(primaryShip, groupLabel, options = {}) {
  const explicitShips = Array.isArray(options.compareShips) ? options.compareShips : null;
  const candidates = explicitShips || [
    primaryShip,
    ...state.modalChartCompareCodes
      .map((code) => state.ships.find((ship) => ship.identity.code === code))
      .filter(Boolean),
  ];
  const seen = new Set();
  const ships = candidates
    .map((ship) => modalShipView(ship))
    .filter((ship) => {
      const code = ship?.identity?.code;
      if (!code || seen.has(code)) return false;
      seen.add(code);
      return projectileForShellChart(ship, groupLabel) != null;
    });
  if (explicitShips) return ships;
  const [first, ...rest] = ships;
  return [
    first,
    ...rest.sort((left, right) => (
      (left.identity.tier - right.identity.tier)
      || displayClass(left).localeCompare(displayClass(right))
      || localizedNationLabel(left).localeCompare(localizedNationLabel(right))
      || shipModalDisplayName(left).localeCompare(shipModalDisplayName(right))
    )),
  ].filter(Boolean);
}

function shellChartCompareOptions(primaryShip, selectedShips, groupLabel) {
  const selectedCodes = new Set((selectedShips || []).map((ship) => ship.identity.code));
  return state.ships
    .filter((ship) => !selectedCodes.has(ship.identity.code))
    .filter((ship) => projectileForShellChart(modalShipView(ship), groupLabel) != null)
    .sort((left, right) => (
      (left.identity.tier - right.identity.tier)
      || displayClass(left).localeCompare(displayClass(right))
      || localizedNationLabel(left).localeCompare(localizedNationLabel(right))
      || left.displayName.localeCompare(right.displayName)
    ));
}

function shellChartSeriesDefinitions(ship, projectile, context, groupLabel, metric, options) {
  options = options || {};
  const chartShips = shellChartCompareShips(ship, groupLabel, options);
  const defs = [];
  chartShips.forEach((chartShip) => {
    if (groupLabel === "Secondaries") {
      secondaryModuleGroups(chartShip).forEach((group) => {
        const chartProjectile = group?.projectile;
        if (!chartProjectile) return;
        if (metric === "penetration" && chartProjectile.ammo_type !== "AP") return;
        defs.push({
          ship: chartShip,
          group,
          label: secondaryChartSeriesLabel(chartShip, group),
          projectile: chartProjectile,
          series: shellChartSeries(chartShip, chartProjectile, context, groupLabel, metric, group),
        });
      });
      return;
    }
    const chartProjectile = chartShip.identity.code === ship?.identity?.code
      ? projectile
      : projectileForShellChart(chartShip, groupLabel);
    defs.push({
      ship: chartShip,
      group: null,
      label: shipModalDisplayName(chartShip),
      projectile: chartProjectile,
      series: shellChartSeries(chartShip, chartProjectile, context, groupLabel, metric),
    });
  });
  return defs
    .filter((item) => item.projectile && item.series.length >= 2)
    .map((item, index) => ({
      ...item,
      color: SHELL_CHART_SERIES_COLORS[index % SHELL_CHART_SERIES_COLORS.length],
    }));
}

function shellChartStep(maxValue, targetTicks = 5) {
  const max = Number(maxValue);
  if (!Number.isFinite(max) || max <= 0) return 1;
  const rough = max / Math.max(1, targetTicks);
  const power = 10 ** Math.floor(Math.log10(rough));
  const normalized = rough / power;
  const multiplier = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return multiplier * power;
}

function shellChartTicks(minValue, maxValue, step) {
  const min = Math.floor(minValue / step) * step;
  const max = Math.ceil(maxValue / step) * step;
  const ticks = [];
  for (let value = min; value <= max + step * 0.5; value += step) {
    ticks.push(Math.max(0, Number(value.toFixed(4))));
  }
  return [...new Set(ticks)];
}

function shellChartYBounds(rawMin, rawMax, metric) {
  const isTime = metric === "time";
  if (isTime) {
    const yMin = 0;
    const yMax = Math.max(2, Math.ceil(Number(rawMax || 0) + 2));
    return {
      yMin,
      yMax,
      step: shellChartStep(yMax - yMin, 5),
    };
  }
  const step = shellChartStep(rawMax - Math.min(rawMin, rawMax), 5);
  const yMin = Math.max(0, Math.floor(rawMin / step) * step);
  return {
    yMin,
    yMax: Math.max(yMin + step, rawMax),
    step,
  };
}

function shellChartTooltipText(ship, metric, point, label = null) {
  const shipName = label || shipModalDisplayName(ship);
  const value = shellChartTooltipValue(metric, point.value);
  return `${shipName} (${formatValue(point.km, { digits: point.km % 1 ? 1 : 0, suffix: " km" })}, ${value})`;
}

function shellChartTooltipValue(metric, value) {
  return metric === "penetration"
    ? formatValue(value, { digits: 0, suffix: ` ${shellChartAxisUnit(metric)}` })
    : formatValue(value, { digits: 1, suffix: ` ${shellChartAxisUnit(metric)}` });
}

function renderShellLineChart(ship, projectile, context, groupLabel, metric, options = {}) {
  const seriesDefs = shellChartSeriesDefinitions(ship, projectile, context, groupLabel, metric, options);
  if (!seriesDefs.length) return "";
  const series = seriesDefs[0].series;
  const viewWidth = 820;
  const viewHeight = 300;
  const margin = { top: 20, right: 28, bottom: 42, left: 64 };
  const plotWidth = viewWidth - margin.left - margin.right;
  const plotHeight = viewHeight - margin.top - margin.bottom;
  const maxKm = Math.max(...seriesDefs.flatMap((item) => item.series.map((point) => point.km)));
  const values = seriesDefs.flatMap((item) => item.series.map((point) => point.value));
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const isTime = metric === "time";
  const { yMin, yMax, step } = shellChartYBounds(rawMin, rawMax, metric);
  let yTicks = shellChartTicks(yMin, yMax, step);
  yTicks = yTicks.filter((tick) => tick <= yMax);
  if (!yTicks.some((tick) => Math.abs(tick - yMax) < 0.001)) yTicks.push(yMax);
  yTicks.sort((left, right) => left - right);
  const xForKm = (km) => margin.left + ((km - 1) / Math.max(1, maxKm - 1)) * plotWidth;
  const yForValue = (value) => margin.top + ((yMax - value) / Math.max(1, yMax - yMin)) * plotHeight;
  const lineMarkup = seriesDefs.map((item) => {
    const path = item.series
      .map((point, index) => `${index === 0 ? "M" : "L"} ${svgNumber(xForKm(point.km))} ${svgNumber(yForValue(point.value))}`)
      .join(" ");
    return `<path class="shell-chart-line" d="${path}" style="--shell-chart-color: ${escapeHtml(item.color)};"></path>`;
  }).join("");
  const targetKm = Number(context?.range_km);
  const hasTarget = Number.isFinite(targetKm) && targetKm >= 1 && targetKm <= maxKm;
  const targetX = hasTarget ? xForKm(targetKm) : null;
  const targetPoint = hasTarget
    ? series.reduce((best, point) => Math.abs(point.km - targetKm) < Math.abs(best.km - targetKm) ? point : best, series[0])
    : null;
  const metricLabel = isTime ? "Flight time" : "Penetration";
  const yUnit = shellChartAxisUnit(metric);
  const unitLabel = shellChartUnitLabel(metric);
  const ammoLabel = groupLabel === "Secondaries"
    ? (metric === "penetration" ? projectileAmmoLabel({ ammo_type: "AP" }) : uiLabel("Secondaries"))
    : projectileAmmoLabel(projectile);
  const lineClass = isTime ? "shell-chart-line-time" : "shell-chart-line-penetration";
  const serializedSeries = series
    .map((point) => `${Number(point.km).toFixed(3)},${Number(point.value).toFixed(6)}`)
    .join(";");
  const serializedSeriesData = JSON.stringify(seriesDefs.map((item) => ({
    ship: item.label || shipModalDisplayName(item.ship),
    color: item.color,
    values: item.series.map((point) => [
      Number(point.km.toFixed(3)),
      Number(point.value.toFixed(6)),
    ]),
  })));
  const xGrid = Array.from({ length: maxKm }, (_, index) => index + 1).map((km) => {
    const x = xForKm(km);
    const label = km === 1 || km === maxKm || km % 2 === 0;
    return `
      <line class="shell-chart-grid shell-chart-grid-x" x1="${svgNumber(x)}" y1="${margin.top}" x2="${svgNumber(x)}" y2="${margin.top + plotHeight}"></line>
      ${label ? `<text class="shell-chart-axis-label" x="${svgNumber(x)}" y="${viewHeight - 15}" text-anchor="middle">${km}</text>` : ""}
    `;
  }).join("");
  const yGrid = yTicks.map((tick) => {
    const y = yForValue(tick);
    return `
      <line class="shell-chart-grid" x1="${margin.left}" y1="${svgNumber(y)}" x2="${margin.left + plotWidth}" y2="${svgNumber(y)}"></line>
      <text class="shell-chart-axis-label" x="${margin.left - 10}" y="${svgNumber(y + 5)}" text-anchor="end">${formatValue(tick, { digits: tick % 1 ? 1 : 0 })}</text>
    `;
  }).join("");
  const pointMarkup = seriesDefs.map((item) => item.series.map((point) => {
    const x = xForKm(point.km);
    const y = yForValue(point.value);
    const tooltip = shellChartTooltipText(item.ship, metric, point, item.label);
    return `
      <circle class="shell-chart-point-hit" cx="${svgNumber(x)}" cy="${svgNumber(y)}" r="9" data-shell-chart-point="${escapeHtml(tooltip)}"></circle>
      <circle class="shell-chart-point" cx="${svgNumber(x)}" cy="${svgNumber(y)}" r="${seriesDefs.length > 1 ? 2.6 : 3}" style="--shell-chart-color: ${escapeHtml(item.color)};"></circle>
    `;
  }).join("")).join("");
  const legendMarkup = seriesDefs.length > 1 ? `
    <div class="shell-chart-legend">
      ${seriesDefs.map((item) => `<span><i style="background: ${escapeHtml(item.color)}"></i>${escapeHtml(item.label || shipModalDisplayName(item.ship))}</span>`).join("")}
    </div>
  ` : "";
  const targetMarkup = hasTarget ? `
    <line class="shell-chart-target-line" x1="${svgNumber(targetX)}" y1="${margin.top}" x2="${svgNumber(targetX)}" y2="${margin.top + plotHeight}"></line>
    <g class="shell-chart-target-label">
      <rect x="${svgNumber(targetX - 22)}" y="${margin.top + 8}" width="44" height="20" rx="3"></rect>
      <text x="${svgNumber(targetX)}" y="${margin.top + 23}" text-anchor="middle">${formatValue(targetKm, { digits: 0, suffix: ` ${shellChartDistanceUnit()}` })}</text>
    </g>
    ${targetPoint ? `<circle class="shell-chart-target-point" cx="${svgNumber(xForKm(targetPoint.km))}" cy="${svgNumber(yForValue(targetPoint.value))}" r="4.5"></circle>` : ""}
  ` : "";

  return `
    <section class="shell-chart-card shell-chart-zoomable" data-shell-chart-zoom-title="${escapeHtml(uiLabel(metricLabel))}" role="button" tabindex="0">
      <button class="shell-chart-zoom-button" type="button" aria-label="${escapeHtml(t("common.expand", "Expand"))}" title="${escapeHtml(t("common.expand", "Expand"))}">+</button>
      <div class="shell-chart-header">
        <h4>${escapeHtml(uiLabel(metricLabel))}</h4>
        <span>${escapeHtml(ammoLabel)} &middot; ${escapeHtml(unitLabel)}</span>
      </div>
      <svg viewBox="0 0 ${viewWidth} ${viewHeight}" class="shell-line-chart ${lineClass}" role="img" aria-label="${escapeHtml(`${ammoLabel} ${uiLabel(metricLabel)}`)}" data-shell-chart-values="${escapeHtml(serializedSeries)}" data-shell-chart-series="${escapeHtml(serializedSeriesData)}" data-shell-chart-metric="${escapeHtml(metric)}" data-shell-chart-ship="${escapeHtml(shipModalDisplayName(ship))}" data-shell-chart-left="${margin.left}" data-shell-chart-top="${margin.top}" data-shell-chart-width="${plotWidth}" data-shell-chart-height="${plotHeight}" data-shell-chart-y-min="${yMin}" data-shell-chart-y-max="${yMax}">
        <rect class="shell-chart-plot-bg" x="${margin.left}" y="${margin.top}" width="${plotWidth}" height="${plotHeight}"></rect>
        ${xGrid}
        ${yGrid}
        <line class="shell-chart-axis" x1="${margin.left}" y1="${margin.top + plotHeight}" x2="${margin.left + plotWidth}" y2="${margin.top + plotHeight}"></line>
        <line class="shell-chart-axis" x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${margin.top + plotHeight}"></line>
        ${lineMarkup}
        ${targetMarkup}
        ${pointMarkup}
        <rect class="shell-chart-hover-capture" x="${margin.left}" y="${margin.top}" width="${plotWidth}" height="${plotHeight}" data-shell-chart-hover="true"></rect>
        <g class="shell-chart-hover-guide hidden">
          <line class="shell-chart-hover-guide-line" data-shell-chart-guide-x x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${margin.top + plotHeight}"></line>
          <line class="shell-chart-hover-guide-line" data-shell-chart-guide-y x1="${margin.left}" y1="${margin.top}" x2="${margin.left + plotWidth}" y2="${margin.top}"></line>
          <circle class="shell-chart-hover-guide-point" data-shell-chart-guide-point cx="${margin.left}" cy="${margin.top}" r="4"></circle>
        </g>
        <text class="shell-chart-axis-title shell-chart-x-title" x="${svgNumber(margin.left + plotWidth / 2)}" y="${viewHeight - 2}" text-anchor="middle">${escapeHtml(shellChartDistanceUnit())}</text>
        <text class="shell-chart-axis-title" x="${margin.left - 42}" y="${margin.top + 12}" text-anchor="middle">${escapeHtml(yUnit)}</text>
      </svg>
      ${legendMarkup}
    </section>
  `;
}

function renderShellChartsPanel(ship, projectile, context, groupLabel, options = {}) {
  if (!ship || !projectile) return "";
  const flightChart = renderShellLineChart(ship, projectile, context, groupLabel, "time", options);
  const hasPenetrationChart = groupLabel === "Secondaries"
    ? shellChartCompareShips(ship, groupLabel, options).some((chartShip) => secondaryModuleGroups(chartShip).some((group) => group?.projectile?.ammo_type === "AP"))
    : projectile?.ammo_type === "AP";
  const penetrationChart = hasPenetrationChart
    ? renderShellLineChart(ship, projectile, context, groupLabel, "penetration", options)
    : "";
  if (!flightChart && !penetrationChart) return "";
  const compareControls = options.hideCompareControls ? "" : renderShellChartCompareControls(ship, groupLabel);
  return `
    <div class="shell-charts-panel ${options.compact ? "shell-charts-panel-compact" : ""}">
      ${compareControls}
      ${flightChart}
      ${penetrationChart}
    </div>
  `;
}

function renderShellChartCompareControls(ship, groupLabel) {
  if (state.modalCompare.enabled) return "";
  const selectedShips = shellChartCompareShips(ship, groupLabel);
  const extraShips = selectedShips
    .filter((item) => item.identity.code !== ship.identity.code)
    .sort((left, right) => (
      (left.identity.tier - right.identity.tier)
      || displayClass(left).localeCompare(displayClass(right))
      || localizedNationLabel(left).localeCompare(localizedNationLabel(right))
      || shipModalDisplayName(left).localeCompare(shipModalDisplayName(right))
    ));
  return `
    <div class="shell-chart-compare-toolbar">
      <span>${escapeHtml(t("modal.chartCompare", "Chart compare"))}</span>
      <button type="button" data-shell-chart-compare-pick="${escapeHtml(groupLabel)}">${escapeHtml(t("common.add", "Add"))}</button>
      <div class="shell-chart-compare-chips">
        ${extraShips.map((item) => `
          <button type="button" class="shell-chart-compare-chip" data-shell-chart-compare-remove="${escapeHtml(item.identity.code)}">
            ${escapeHtml(shipModalDisplayName(item))}<span aria-hidden="true">x</span>
          </button>
        `).join("")}
      </div>
    </div>
  `;
}

function ensureShellChartTooltip() {
  if (shellChartTooltip) return shellChartTooltip;
  shellChartTooltip = document.createElement("div");
  shellChartTooltip.className = "shell-chart-tooltip hidden";
  document.body.appendChild(shellChartTooltip);
  return shellChartTooltip;
}

function hideShellChartTooltip() {
  if (shellChartTooltip) shellChartTooltip.classList.add("hidden");
  hideShellChartGuides(els.modalContent || document);
}

function moveShellChartTooltip(event, text) {
  const tooltip = ensureShellChartTooltip();
  tooltip.textContent = text;
  tooltip.classList.remove("hidden");
  const offset = 14;
  const width = tooltip.offsetWidth || 220;
  const height = tooltip.offsetHeight || 34;
  const x = Math.min(window.innerWidth - width - 10, event.clientX + offset);
  const y = Math.max(10, event.clientY - height - offset);
  tooltip.style.left = `${Math.max(10, x)}px`;
  tooltip.style.top = `${y}px`;
}

function shellChartValuesFromSvg(svg) {
  return `${svg?.dataset?.shellChartValues || ""}`
    .split(";")
    .map((entry) => {
      const [km, value] = entry.split(",").map(Number);
      return Number.isFinite(km) && Number.isFinite(value) ? { km, value } : null;
    })
    .filter(Boolean)
    .sort((left, right) => left.km - right.km);
}

function shellChartSeriesFromSvg(svg) {
  try {
    const parsed = JSON.parse(svg?.dataset?.shellChartSeries || "[]");
    return Array.isArray(parsed)
      ? parsed.map((item) => ({
        ship: `${item?.ship || ""}`,
        color: `${item?.color || ""}`,
        values: Array.isArray(item?.values)
          ? item.values
            .map((point) => ({ km: Number(point?.[0]), value: Number(point?.[1]) }))
            .filter((point) => Number.isFinite(point.km) && Number.isFinite(point.value))
            .sort((left, right) => left.km - right.km)
          : [],
      })).filter((item) => item.values.length >= 2)
      : [];
  } catch (_) {
    return [];
  }
}

function interpolateShellChartValue(points, km) {
  if (!points.length || !Number.isFinite(km)) return null;
  if (km <= points[0].km) return points[0];
  if (km >= points[points.length - 1].km) return points[points.length - 1];
  const rightIndex = points.findIndex((point) => point.km >= km);
  const right = points[rightIndex];
  const left = points[rightIndex - 1] || right;
  const span = Math.max(0.0001, right.km - left.km);
  const ratio = clamp((km - left.km) / span, 0, 1);
  return {
    km,
    value: left.value + (right.value - left.value) * ratio,
  };
}

function hideShellChartGuide(svg) {
  svg?.querySelector(".shell-chart-hover-guide")?.classList.add("hidden");
}

function hideShellChartGuides(scope = document) {
  scope.querySelectorAll?.(".shell-chart-hover-guide").forEach((guide) => {
    guide.classList.add("hidden");
  });
}

function updateShellChartGuide(svg, point) {
  const guide = svg?.querySelector(".shell-chart-hover-guide");
  if (!guide || !point) return;
  const left = Number(svg.dataset.shellChartLeft);
  const top = Number(svg.dataset.shellChartTop);
  const width = Number(svg.dataset.shellChartWidth);
  const height = Number(svg.dataset.shellChartHeight);
  if (![left, top, width, height, point.svgX, point.svgY].every(Number.isFinite)) return;
  guide.classList.remove("hidden");
  const guideX = guide.querySelector("[data-shell-chart-guide-x]");
  const guideY = guide.querySelector("[data-shell-chart-guide-y]");
  const marker = guide.querySelector("[data-shell-chart-guide-point]");
  guideX?.setAttribute("x1", svgNumber(point.svgX));
  guideX?.setAttribute("x2", svgNumber(point.svgX));
  guideX?.setAttribute("y1", svgNumber(point.svgY));
  guideX?.setAttribute("y2", svgNumber(top + height));
  guideY?.setAttribute("x1", svgNumber(left));
  guideY?.setAttribute("x2", svgNumber(point.svgX));
  guideY?.setAttribute("y1", svgNumber(point.svgY));
  guideY?.setAttribute("y2", svgNumber(point.svgY));
  marker?.setAttribute("cx", svgNumber(point.svgX));
  marker?.setAttribute("cy", svgNumber(point.svgY));
}

function shellChartPointFromEvent(event, svg) {
  const left = Number(svg.dataset.shellChartLeft);
  const top = Number(svg.dataset.shellChartTop);
  const width = Number(svg.dataset.shellChartWidth);
  const height = Number(svg.dataset.shellChartHeight);
  if (![left, top, width, height].every(Number.isFinite)) return null;
  let svgX = null;
  let svgY = null;
  try {
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const converted = point.matrixTransform(svg.getScreenCTM().inverse());
    svgX = converted.x;
    svgY = converted.y;
  } catch (_) {
    const box = svg.getBoundingClientRect();
    svgX = left + ((event.clientX - box.left) / Math.max(1, box.width)) * (Number(svg.getAttribute("viewBox")?.split(/\s+/)[2]) || 820);
    svgY = top + ((event.clientY - box.top) / Math.max(1, box.height)) * (Number(svg.getAttribute("viewBox")?.split(/\s+/)[3]) || 300);
  }
  if (svgX < left || svgX > left + width || svgY < top || svgY > top + height) return null;
  const seriesList = shellChartSeriesFromSvg(svg);
  const values = seriesList.length ? seriesList.flatMap((item) => item.values) : shellChartValuesFromSvg(svg);
  if (!values.length) return null;
  const minKm = Math.min(...values.map((point) => point.km));
  const maxKm = Math.max(...values.map((point) => point.km));
  const km = minKm + ((svgX - left) / Math.max(1, width)) * (maxKm - minKm);
  let valuePoint = null;
  if (seriesList.length) {
    const yMin = Number(svg.dataset.shellChartYMin);
    const yMax = Number(svg.dataset.shellChartYMax);
    const candidates = seriesList
      .map((item) => {
        if (km < item.values[0].km || km > item.values[item.values.length - 1].km) return null;
        const point = interpolateShellChartValue(item.values, km);
        if (!point) return null;
        const valueY = [yMin, yMax].every(Number.isFinite)
          ? top + ((yMax - point.value) / Math.max(1, yMax - yMin)) * height
          : svgY;
        return {
          ...point,
          shipName: item.ship,
          color: item.color,
          svgY: clamp(valueY, top, top + height),
          distance: Math.abs(valueY - svgY),
        };
      })
      .filter(Boolean);
    const nearest = [...candidates].sort((leftItem, rightItem) => leftItem.distance - rightItem.distance)[0] || null;
    valuePoint = nearest ? { ...nearest, allPoints: candidates } : null;
  } else {
    valuePoint = interpolateShellChartValue(values, km);
  }
  if (!valuePoint) return null;
  const yMin = Number(svg.dataset.shellChartYMin);
  const yMax = Number(svg.dataset.shellChartYMax);
  const valueY = valuePoint.svgY ?? ([yMin, yMax].every(Number.isFinite)
    ? top + ((yMax - valuePoint.value) / Math.max(1, yMax - yMin)) * height
    : svgY);
  return {
    ...valuePoint,
    svgX,
    svgY: clamp(valueY, top, top + height),
  };
}

function handleShellChartPointerMove(event) {
  const svg = event.target instanceof Element ? event.target.closest(".shell-line-chart[data-shell-chart-values]") : null;
  if (!svg) {
    hideShellChartTooltip();
    hideShellChartGuides(els.modalContent || document);
    return;
  }
  const point = shellChartPointFromEvent(event, svg);
  if (!point) {
    hideShellChartTooltip();
    hideShellChartGuide(svg);
    return;
  }
  hideShellChartGuides(els.modalContent || document);
  updateShellChartGuide(svg, point);
  const shipName = point.shipName || svg.dataset.shellChartShip || "";
  const metric = svg.dataset.shellChartMetric || "time";
  const text = Array.isArray(point.allPoints) && point.allPoints.length > 1
    ? [
      formatValue(point.km, { digits: 1, suffix: " km" }),
      ...point.allPoints.map((item) => `${item.shipName}: ${shellChartTooltipValue(metric, item.value)}`),
    ].join("\n")
    : `${shipName} (${formatValue(point.km, { digits: 1, suffix: " km" })}, ${shellChartTooltipValue(metric, point.value)})`;
  moveShellChartTooltip(event, text);
}

function closeShellChartZoom() {
  const overlay = document.querySelector(".shell-chart-zoom-overlay");
  if (!overlay) return;
  overlay.classList.add("hidden");
  overlay.querySelector(".shell-chart-zoom-body").innerHTML = "";
  hideShellChartTooltip();
}

function ensureShellChartZoomOverlay() {
  let overlay = document.querySelector(".shell-chart-zoom-overlay");
  if (overlay) return overlay;
  overlay = document.createElement("div");
  overlay.className = "shell-chart-zoom-overlay hidden";
  overlay.innerHTML = `
    <div class="shell-chart-zoom-backdrop" data-shell-chart-zoom-close></div>
    <div class="shell-chart-zoom-card" role="dialog" aria-modal="true" aria-labelledby="shell-chart-zoom-title">
      <button class="shell-chart-zoom-close" type="button" aria-label="${escapeHtml(t("common.close", "Close"))}" data-shell-chart-zoom-close>x</button>
      <div class="shell-chart-zoom-body"></div>
      <div class="shell-chart-zoom-title" id="shell-chart-zoom-title"></div>
    </div>
  `;
  overlay.addEventListener("click", (event) => {
    if (event.target.closest("[data-shell-chart-zoom-close]")) {
      event.preventDefault();
      closeShellChartZoom();
    }
  });
  overlay.addEventListener("pointermove", handleShellChartPointerMove);
  overlay.addEventListener("pointerleave", hideShellChartTooltip);
  document.body.appendChild(overlay);
  return overlay;
}

function openShellChartZoom(card) {
  if (!card) return;
  const overlay = ensureShellChartZoomOverlay();
  const body = overlay.querySelector(".shell-chart-zoom-body");
  const title = overlay.querySelector(".shell-chart-zoom-title");
  const clone = card.cloneNode(true);
  clone.classList.remove("shell-chart-zoomable");
  clone.classList.add("shell-chart-zoom-clone");
  clone.removeAttribute("role");
  clone.removeAttribute("tabindex");
  clone.querySelectorAll(".shell-chart-zoom-button").forEach((button) => button.remove());
  body.innerHTML = "";
  body.appendChild(clone);
  title.textContent = card.dataset.shellChartZoomTitle || "";
  overlay.classList.remove("hidden");
}

function bindShellChartZoomInteractions(root) {
  root.querySelectorAll(".shell-chart-card.shell-chart-zoomable").forEach((card) => {
    const open = (event) => {
      event.preventDefault();
      openShellChartZoom(card);
    };
    card.addEventListener("click", open);
    card.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      open(event);
    });
  });
}

function renderShellDispersionGraph(ship, projectile, context, groupLabel, shotCount = state.shellDispersionShots) {
  const metrics = shellDispersionMetrics(ship, projectile, context, groupLabel);
  if (!metrics) return "";
  const points = shellDispersionPoints(ship, projectile, context, groupLabel, metrics, shotCount);
  const viewWidth = 760;
  const viewHeight = 350;
  const centerX = 390;
  const centerY = 185;
  const radiusX = 280;
  const radiusY = clamp(radiusX * (metrics.lateralRadiusM / metrics.longitudinalRadiusM), 46, 120);
  const topY = Math.max(38, centerY - radiusY - 28);
  const topLabelY = Math.max(30, topY - 8);
  const leftX = centerX - radiusX - 32;
  const horizontalLabel = formatValue(metrics.longitudinalRadiusM * 2, { digits: 0, grouping: true, suffix: " m" });
  const verticalLabel = formatValue(metrics.lateralRadiusM * 2, { digits: 0, grouping: true, suffix: " m" });
  const dotMarkup = points.map((point, index) => {
    const x = centerX + point.longitudinal * radiusX;
    const y = centerY + point.lateral * radiusY;
    const opacity = 0.24 + (index % 5) * 0.055;
    return `<circle class="shell-dispersion-dot" cx="${svgNumber(x)}" cy="${svgNumber(y)}" r="${index % 7 === 0 ? 4.2 : 3.4}" opacity="${svgNumber(opacity)}"></circle>`;
  }).join("");
  return `
    <svg viewBox="0 0 ${viewWidth} ${viewHeight}" class="dispersion-graph shell-dispersion-graph" role="img" aria-label="${escapeHtml(projectileAmmoLabel(projectile))} shell dispersion">
      <ellipse class="shell-dispersion-ellipse" cx="${centerX}" cy="${centerY}" rx="${radiusX}" ry="${svgNumber(radiusY)}"></ellipse>
      ${dotMarkup}
      <line class="shell-dispersion-measure" x1="${centerX - radiusX}" y1="${svgNumber(topY)}" x2="${centerX + radiusX}" y2="${svgNumber(topY)}"></line>
      <line class="shell-dispersion-measure" x1="${centerX - radiusX}" y1="${svgNumber(topY)}" x2="${centerX - radiusX}" y2="${svgNumber(topY + 12)}"></line>
      <line class="shell-dispersion-measure" x1="${centerX + radiusX}" y1="${svgNumber(topY)}" x2="${centerX + radiusX}" y2="${svgNumber(topY + 12)}"></line>
      <text class="shell-dispersion-label" x="${centerX}" y="${svgNumber(topLabelY)}" text-anchor="middle">${horizontalLabel}</text>
      <line class="shell-dispersion-measure" x1="${leftX}" y1="${svgNumber(centerY - radiusY)}" x2="${leftX}" y2="${svgNumber(centerY + radiusY)}"></line>
      <line class="shell-dispersion-measure" x1="${leftX}" y1="${svgNumber(centerY - radiusY)}" x2="${leftX + 12}" y2="${svgNumber(centerY - radiusY)}"></line>
      <line class="shell-dispersion-measure" x1="${leftX}" y1="${svgNumber(centerY + radiusY)}" x2="${leftX + 12}" y2="${svgNumber(centerY + radiusY)}"></line>
      <text class="shell-dispersion-label" x="${leftX - 8}" y="${svgNumber(centerY + 5)}" text-anchor="end">${verticalLabel}</text>
    </svg>
  `;
}

function renderShellDispersionControls() {
  const shots = clampShellDispersionShots(state.shellDispersionShots);
  state.shellDispersionShots = shots;
  return `
    <label class="shell-dispersion-control">
      <span>Shots Number</span>
      <input class="shell-dispersion-shot-input" type="number" min="${SHELL_DISPERSION_MIN_SHOTS}" max="${SHELL_DISPERSION_MAX_SHOTS}" step="1" value="${shots}" data-shell-dispersion-shots>
    </label>
  `;
}

function renderTrajectoryPanel(rangeLabel, ship = null, projectile = null, context = null, groupLabel = "Main battery") {
  return `
    <div class="trajectory-wrap">
      ${renderShellChartsPanel(ship, projectile, context, groupLabel)}
      ${renderShellDispersionControls()}
      <div class="shell-dispersion-graph-slot">
        ${renderShellDispersionGraph(ship, projectile, context, groupLabel)}
      </div>
    </div>
  `;
}

function activeModalShellDispersionArgs() {
  const groupByTab = {
    ap: ["AP", "AP Shells"],
    he: ["HE", "HE Shells"],
    sap: ["SAP", "SAP Shells"],
  };
  const entry = groupByTab[state.activeModalTab];
  if (!entry || !state.activeModalShipCode) return null;
  const ship = state.ships.find((item) => item.identity.code === state.activeModalShipCode);
  if (!ship) return null;
  const activeShip = modalShipView(ship);
  const [ammoType, groupLabel] = entry;
  const projectile = firstProjectile(activeShip, ammoType);
  if (!projectile) return null;
  return {
    ship: activeShip,
    projectile,
    context: getModalRenderContext(groupLabel, [activeShip]),
    groupLabel,
  };
}

function updateActiveShellDispersionGraph() {
  const slot = els.modalContent?.querySelector(".shell-dispersion-graph-slot");
  const args = activeModalShellDispersionArgs();
  if (!slot || !args) return;
  slot.innerHTML = renderShellDispersionGraph(args.ship, args.projectile, args.context, args.groupLabel);
}

function bindShellDispersionShotInputs() {
  els.modalContent.querySelectorAll("[data-shell-dispersion-shots]").forEach((input) => {
    input.addEventListener("input", () => {
      if (input.value.trim() === "") return;
      state.shellDispersionShots = clampShellDispersionShots(input.value);
      updateActiveShellDispersionGraph();
    });
    input.addEventListener("change", () => {
      state.shellDispersionShots = clampShellDispersionShots(input.value);
      input.value = state.shellDispersionShots;
      updateActiveShellDispersionGraph();
    });
  });
}

function hardpointModulePosition(module, hardpoint, hasSchematic, schematicForward) {
  const x = Number(hardpoint?.x);
  const y = Number(hardpoint?.y);
  const z = Number(hardpoint?.z);
  const yawDeg = Number(hardpoint?.yawDeg);
  const layout = hardpoint?.layout || null;
  const layoutX = Number(layout?.x);
  const layoutY = Number(layout?.y);
  const layoutZ = Number(layout?.z);
  if (Number.isFinite(layoutX) && Number.isFinite(layoutY)) {
    return {
      forward: layoutY,
      side: layoutX > 0.001 ? 2 : layoutX < -0.001 ? 0 : 1,
      schematicForward: hasSchematic ? schematicForward : null,
      schematicSide: null,
      lateral: layoutX,
      vertical: Number.isFinite(layoutZ) ? layoutZ : Number.isFinite(y) ? y : null,
      z: layoutY,
      layoutX,
      layoutY,
      layoutZ: Number.isFinite(layoutZ) ? layoutZ : null,
      rawX: Number.isFinite(x) ? x : null,
      rawY: Number.isFinite(y) ? y : null,
      rawZ: Number.isFinite(z) ? z : null,
      yawDeg: Number.isFinite(yawDeg) ? yawDeg : null,
      hardpointYawDeg: Number.isFinite(yawDeg) ? yawDeg : null,
      yawSource: Number.isFinite(yawDeg) ? "hardpoint" : null,
      transformMode: hardpoint.transformMode || "full-parent-chain",
      source: "hardpoint-layout",
    };
  }
  if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) return null;
  return {
    forward: z,
    side: x > 0.001 ? 2 : x < -0.001 ? 0 : 1,
    schematicForward: hasSchematic ? schematicForward : null,
    schematicSide: null,
    lateral: x,
    vertical: y,
    z,
    yawDeg: Number.isFinite(yawDeg) ? yawDeg : null,
    hardpointYawDeg: Number.isFinite(yawDeg) ? yawDeg : null,
    yawSource: Number.isFinite(yawDeg) ? "hardpoint" : null,
    transformMode: hardpoint.transformMode || "full-parent-chain",
    source: "hardpoint",
  };
}

function torpedoHybridHardpointPosition(hardpointPosition, schematicForward, schematicSide) {
  if (!hardpointPosition || !Number.isFinite(Number(schematicForward)) || !Number.isFinite(Number(schematicSide))) {
    return hardpointPosition;
  }
  return {
    ...hardpointPosition,
    schematicForward,
    schematicSide,
  };
}

function gameparamsHullModulePosition(module, hasSchematic, schematicForward, hullX, hullY, hullZ, hullYawDeg, hardpoint) {
  return {
    forward: hullY,
    side: hullX > 0.001 ? 2 : hullX < -0.001 ? 0 : 1,
    schematicForward: hasSchematic ? schematicForward : null,
    schematicSide: null,
    lateral: hullX,
    vertical: hullZ,
    z: hullZ,
    yawDeg: Number.isFinite(hullYawDeg) ? hullYawDeg : null,
    hardpointYawDeg: hardpoint && Number.isFinite(Number(hardpoint.yawDeg)) ? Number(hardpoint.yawDeg) : null,
    yawSource: Number.isFinite(hullYawDeg) ? "hull-angle" : null,
    source: "gameparams-hull",
  };
}

function torpedoHardpointMatchesSchematic(hardpointPosition, schematicSide) {
  if (!hardpointPosition || !Number.isFinite(Number(schematicSide))) return true;
  const expectedSide = Number(schematicSide);
  const layoutX = Number(hardpointPosition.layoutX);
  const lateral = Number.isFinite(layoutX) ? layoutX : Number(hardpointPosition.lateral);
  const yawDeg = finiteNumberOrNull(hardpointPosition.yawDeg ?? hardpointPosition.hardpointYawDeg);
  if (Number.isFinite(yawDeg)) {
    const yaw = signedAngle(yawDeg);
    if (Math.abs(Math.abs(yaw) - 90) <= 35) {
      if (expectedSide <= 0.15) return yaw > 0;
      if (expectedSide >= 1.85) return yaw < 0;
    }
  }
  if (Math.abs(expectedSide - 1) <= 0.15) {
    return !Number.isFinite(lateral) || Math.abs(lateral) <= 0.35;
  }
  if (expectedSide <= 0.15) {
    return !Number.isFinite(lateral) || lateral >= 0.035;
  }
  if (expectedSide >= 1.85) {
    return !Number.isFinite(lateral) || lateral <= -0.035;
  }
  return true;
}

function modulePosition(module, kind = null) {
  const position = module?.position;
  const schematicForward = Array.isArray(position) && position.length >= 2 ? finiteNumberOrNull(position[0]) : null;
  const schematicSide = Array.isArray(position) && position.length >= 2 ? finiteNumberOrNull(position[1]) : null;
  const hasSchematic = Number.isFinite(schematicForward) && Number.isFinite(schematicSide);
  const hullYawDeg = finiteNumberOrNull(module?.hull_angle_deg);
  const hullPosition = module?.hull_position;
  const hullPositionSource = module?.hull_position_source;
  const hullX = Array.isArray(hullPosition) && hullPosition.length >= 3 ? finiteNumberOrNull(hullPosition[0]) : null;
  const hullY = Array.isArray(hullPosition) && hullPosition.length >= 3 ? finiteNumberOrNull(hullPosition[1]) : null;
  const hullZ = Array.isArray(hullPosition) && hullPosition.length >= 3 ? finiteNumberOrNull(hullPosition[2]) : null;
  const hasHullPosition = Number.isFinite(hullX) && Number.isFinite(hullY) && Number.isFinite(hullZ);
  const hardpoint = module?.hardpoint;
  const hardpointPosition = hardpointModulePosition(module, hardpoint, hasSchematic, schematicForward);
  if (kind === "torpedo" && hardpointPosition && hasSchematic && !torpedoHardpointMatchesSchematic(hardpointPosition, schematicSide)) {
    return {
      forward: schematicForward,
      side: schematicSide,
      schematicForward,
      schematicSide,
      yawDeg: Number.isFinite(hullYawDeg) ? hullYawDeg : hardpointPosition.yawDeg,
      hardpointYawDeg: hardpointPosition.hardpointYawDeg,
      yawSource: Number.isFinite(hullYawDeg) ? "hull-angle" : hardpointPosition.yawSource,
      source: "schematic",
    };
  }
  if (hardpointPosition) {
    return kind === "torpedo" && hasSchematic
      ? torpedoHybridHardpointPosition(hardpointPosition, schematicForward, schematicSide)
      : hardpointPosition;
  }
  if (kind === "torpedo" && hasHullPosition) {
    return gameparamsHullModulePosition(module, hasSchematic, schematicForward, hullX, hullY, hullZ, hullYawDeg, hardpoint);
  }
  if (kind === "main" || kind === "secondary") {
    if (!hasSchematic) return null;
    return {
      forward: schematicForward,
      side: schematicSide,
      schematicForward,
      schematicSide,
      yawDeg: Number.isFinite(hullYawDeg) ? hullYawDeg : null,
      yawSource: Number.isFinite(hullYawDeg) ? "hull-angle" : null,
      source: "schematic",
    };
  }
  if (kind === "torpedo" && hasSchematic) {
    return {
      forward: schematicForward,
      side: schematicSide,
      schematicForward,
      schematicSide,
      yawDeg: Number.isFinite(hullYawDeg) ? hullYawDeg : null,
      yawSource: Number.isFinite(hullYawDeg) ? "hull-angle" : null,
      source: "schematic",
    };
  }
  if (kind === "torpedo") return null;
  if (hasHullPosition && hullPositionSource === "gameparams-hull") {
    return gameparamsHullModulePosition(module, hasSchematic, schematicForward, hullX, hullY, hullZ, hullYawDeg, hardpoint);
  }
  if (hasSchematic) {
    return {
      forward: schematicForward,
      side: schematicSide,
      schematicForward,
      schematicSide,
      yawDeg: Number.isFinite(hullYawDeg) ? hullYawDeg : null,
      yawSource: Number.isFinite(hullYawDeg) ? "hull-angle" : null,
      source: "schematic",
    };
  }
  return null;
}

function moduleSector(module) {
  const sector = module?.horizontal_sector;
  if (!Array.isArray(sector) || sector.length < 2) return null;
  const start = Number(sector[0]);
  const end = Number(sector[1]);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  return { start, end };
}

function moduleAdditionalSectors(module) {
  const sectors = module?.additional_aim_sectors || module?.additionalAimSector || [];
  if (!Array.isArray(sectors)) return [];
  return sectors
    .map((sector) => {
      if (!Array.isArray(sector) || sector.length < 2) return null;
      const start = Number(sector[0]);
      const end = Number(sector[1]);
      if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
      return { start, end };
    })
    .filter(Boolean);
}

function moduleDeadZones(module) {
  const zones = module?.dead_zones || module?.deadZone || module?.dead_zone || [];
  if (!Array.isArray(zones)) return [];
  return zones
    .map((zone) => {
      if (!Array.isArray(zone) || zone.length < 2) return null;
      const start = Number(zone[0]);
      const end = Number(zone[1]);
      if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
      if (Math.abs(start - end) < 0.001) return null;
      return { start, end };
    })
    .filter(Boolean);
}

function itemSchematicSide(item) {
  return Number(item?.position?.schematicSide ?? item?.position?.side);
}

function torpedoExpectedSectorSideSign(item, threshold = 0.05) {
  const side = itemSchematicSide(item);
  if (Number.isFinite(side) && Math.abs(side - 1) <= 0.15) return 0;

  const lateral = Number(item?.position?.lateral ?? item?.position?.layoutX);
  if (Number.isFinite(lateral) && Math.abs(lateral) > threshold) {
    return lateral > 0 ? 1 : -1;
  }

  if (!Number.isFinite(side)) return 0;
  if (side <= 0.15) return 1;
  if (side >= 1.85) return -1;
  return 0;
}


function torpedoAdditionalSectorShouldUseSideRotation(sector, item) {
  if (!sector) return false;
  const expectedSign = torpedoExpectedSectorSideSign(item);
  if (!expectedSign) return false;
  const sweep = angleSweep(sector.start, sector.end);
  if (sweep < 20 || sweep > 140) return false;
  if (!sectorContainsAngle(sector, 0)) return false;
  const yawDeg = finiteNumberOrNull(item?.position?.yawDeg);
  const sideMountedHardpoint = ["hardpoint", "hardpoint-layout", "hybrid"].includes(item?.position?.source)
    && Number.isFinite(yawDeg)
    && Math.abs(Math.abs(signedAngle(yawDeg)) - 90) <= 35;
  if (sideMountedHardpoint) return true;
  const edgeDistance = Math.min(Math.abs(Number(sector.start)), Math.abs(Number(sector.end)));
  return Number.isFinite(edgeDistance) && edgeDistance >= 10;
}

function torpedoAdditionalSectorSideRotation(item) {
  const yawDeg = finiteNumberOrNull(item?.position?.yawDeg);
  if (Number.isFinite(yawDeg) && Math.abs(Math.abs(signedAngle(yawDeg)) - 90) <= 35) {
    return yawDeg;
  }
  const expectedSign = torpedoExpectedSectorSideSign(item);
  if (!expectedSign) return 0;
  return expectedSign > 0 ? 90 : -90;
}

function mainBatteryDisplaySectorForItem(sector, item) {
  if (!sector) return null;
  return sector;
}

function mainBatterySectorRotation(item, domain) {
  const yawDeg = Number(item?.position?.yawDeg);
  if (Number.isFinite(yawDeg)) return yawDeg;
  return 0;
}

function torpedoDisplaySectorForItem(sector, item, ship = null) {
  if (!sector) return null;
  if (item?.position?.source !== "schematic") return sector;
  const expectedSign = torpedoExpectedSectorSideSign(item);
  if (!expectedSign) return sector;
  const actualSign = sectorSideSign(sector);
  if (!actualSign) return sector;
  return actualSign === expectedSign ? sector : mirrorHorizontalSector(sector);
}

function torpedoDisplayAdditionalSectorForItem(sector, item, ship = null) {
  if (torpedoAdditionalSectorShouldUseSideRotation(sector, item)) {
    return rotateSector(sector, torpedoAdditionalSectorSideRotation(item));
  }
  const displayedSector = torpedoDisplaySectorForItem(sector, item, ship);
  const expectedSign = torpedoExpectedSectorSideSign(item);
  const actualSign = sectorSideSign(displayedSector);
  if (!expectedSign || !actualSign || actualSign === expectedSign) {
    return displayedSector;
  }
  return mirrorHorizontalSector(displayedSector);
}

function torpedoSchematicSideRotation(item) {
  const side = itemSchematicSide(item);
  if (!Number.isFinite(side)) return null;
  if (side <= 0.15) return 90;
  if (side >= 1.85) return 270;
  return 0;
}

function itemPhysicalSideSign(item, threshold = 0.05) {
  const lateral = Number(item?.position?.lateral);
  if (Number.isFinite(lateral) && Math.abs(lateral) > threshold) {
    return lateral > 0 ? 1 : -1;
  }

  const side = itemSchematicSide(item);
  if (Number.isFinite(side) && Math.abs(side - 1) > threshold) {
    return side > 1 ? 1 : -1;
  }

  return 0;
}

function secondaryDisplaySectorForItem(sector, item) {
  if (!sector) return null;
  // Secondary arcs are already stored as ship-relative sectors in GameParams.
  // Hardpoint data is used for position, but using physical X/Y to mirror these
  // sectors makes odd deck mounts count as firing through the ship.
  return sector;
}

function isSubmarineShip(ship) {
  return ship?.shipClass === "Submarine"
    || ship?.typeinfo?.species === "Submarine"
    || ship?.identity?.class === "Submarine"
    || ship?.identity?.species === "Submarine";
}

function isAirCarrierShip(ship) {
  return ship?.shipClass === "AircraftCarrier"
    || ship?.shipClass === "AirCarrier"
    || ship?.typeinfo?.species === "AirCarrier"
    || ship?.identity?.class === "AirCarrier"
    || ship?.identity?.species === "AirCarrier";
}

const ASYMMETRIC_SECONDARY_LAYOUT_SHIP_CODES = new Set([
  "PASB208",
  "PASB209",
  "PASB210",
]);

function hasHybridFlightDeckSecondaryLayout(ship) {
  const code = ship?.identity?.code;
  if (code && ASYMMETRIC_SECONDARY_LAYOUT_SHIP_CODES.has(code)) return true;

  const description = `${ship?.identity?.description || ship?.description || ""}`.toLowerCase();
  return description.includes("flight deck")
    && (description.includes("hybrid") || description.includes("carrier"));
}

function isCenterlineTorpedoItem(item) {
  const side = finiteNumberOrNull(item?.position?.side);
  const schematicSide = finiteNumberOrNull(item?.position?.schematicSide);
  const lateral = finiteNumberOrNull(item?.position?.lateral);
  if (Number.isFinite(schematicSide)) return Math.abs(schematicSide - 1) <= 0.15;
  if (Number.isFinite(side)) return Math.abs(side - 1) <= 0.15;
  return Number.isFinite(lateral) && Math.abs(lateral) <= 0.18;
}

function torpedoSectorRotation(item, domain, ship = null) {
  const yawDeg = finiteNumberOrNull(item?.position?.yawDeg);
  if (isSubmarineShip(ship) && isCenterlineTorpedoItem(item)) {
    if (Number.isFinite(yawDeg)) {
      const yaw = signedAngle(yawDeg);
      if (Math.abs(Math.abs(yaw) - 180) <= 55) return 180;
      if (Math.abs(yaw) <= 55) return 0;
    }
    const midpoint = (domain.min + domain.max) / 2;
    return item.position.forward > midpoint ? 180 : 0;
  }
  if (torpedoShouldUseAdditionalAimSectors(item)) {
    return 0;
  }
  if (["hardpoint", "hardpoint-layout", "hybrid"].includes(item?.position?.source) && Number.isFinite(yawDeg)) {
    return yawDeg;
  }
  return 0;
}

function torpedoShouldUseAdditionalAimSectors(item) {
  if (!item?.sector || !Array.isArray(item?.additionalSectors) || !item.additionalSectors.length) return false;
  const rawSpan = Math.abs(Number(item.sector.end) - Number(item.sector.start));
  return Number.isFinite(rawSpan) && rawSpan <= 5;
}

function orientedSecondaryLikeSectorData(item, sectorOverride = null, ship = null) {
  const itemWithSector = sectorOverride ? { ...item, sector: sectorOverride } : item;
  const rawSector = secondaryDisplaySectorForItem(itemWithSector.sector, itemWithSector);
  const rawDeadZones = (itemWithSector.deadZones || [])
    .map((deadZone) => secondaryDisplaySectorForItem(deadZone, itemWithSector));
  const rotationItem = { ...itemWithSector, sector: rawSector, deadZones: rawDeadZones };
  const rotation = secondarySectorRotation(rotationItem, ship);
  const sector = rotateSector(rawSector, rotation);
  const deadZones = rawDeadZones.map((deadZone) => rotateSector(deadZone, rotation));
  const sectors = splitSectorByDeadZones(sector, deadZones);
  const isOmnidirectional = angleSweep(sector?.start ?? 0, sector?.end ?? 0) >= 359.9 && deadZones.length > 0;
  return {
    rawSector: rawSector,
    finalSector: sector,
    usedSectorSource: "raw-horiz-sector",
    sector,
    deadZones,
    rawDeadZones,
    finalDeadZones: deadZones,
    sectors,
    labelAngles: isOmnidirectional ? sectorLabelAngles(sector, deadZones) : sectorPieceLabelAngles(sectors),
    isOmnidirectional,
  };
}

function orientedMainBatterySectorData(item, domain) {
  const rotation = mainBatterySectorRotation(item, domain);
  const rawSector = mainBatteryDisplaySectorForItem(item.sector, item);
  const rawDeadZones = (item.deadZones || [])
    .map((deadZone) => mainBatteryDisplaySectorForItem(deadZone, item));
  const sector = rotateSector(rawSector, rotation);
  const deadZones = rawDeadZones.map((deadZone) => rotateSector(deadZone, rotation));
  const sectors = splitSectorByDeadZones(sector, deadZones);
  const isOmnidirectional = angleSweep(sector?.start ?? 0, sector?.end ?? 0) >= 359.9 && deadZones.length > 0;
  return {
    rawSector: rawSector,
    finalSector: sector,
    usedSectorSource: "raw-horiz-sector",
    sector,
    deadZones,
    rawDeadZones,
    finalDeadZones: deadZones,
    sectors,
    labelAngles: isOmnidirectional ? sectorLabelAngles(sector, deadZones) : sectorPieceLabelAngles(sectors),
    isOmnidirectional,
  };
}

function orientedModuleSectorData(item, domain, kind = null, ship = null) {
  if (!item.sector || !item.position) {
    return {
      sector: item.sector,
      deadZones: [],
      sectors: item.sector ? [item.sector] : [],
      labelAngles: [],
      isOmnidirectional: false,
    };
  }
  if (kind === "main") {
    return orientedMainBatterySectorData(item, domain);
  }
  if (kind === "secondary") {
    return orientedSecondaryLikeSectorData(item, null, ship);
  }
  if (kind === "torpedo") {
    const rotation = torpedoSectorRotation(item, domain, ship);
    const sector = rotateSector(torpedoDisplaySectorForItem(item.sector, item, ship), rotation);
    const deadZones = (item.deadZones || [])
      .map((deadZone) => torpedoDisplaySectorForItem(deadZone, item, ship))
      .map((deadZone) => rotateSector(deadZone, rotation));
    const baseSectors = splitSectorByDeadZones(sector, deadZones);
    const additionalSectors = torpedoShouldUseAdditionalAimSectors(item)
      ? (item.additionalSectors || [])
        .map((additionalSector) => torpedoDisplayAdditionalSectorForItem(additionalSector, item, ship))
        .map((additionalSector) => rotateSector(additionalSector, rotation))
        .filter(Boolean)
      : [];
    const additionalPieces = additionalSectors.flatMap((additionalSector) => splitSectorByDeadZones(additionalSector, deadZones));
    const drawableSectors = additionalPieces.length ? additionalPieces : baseSectors;
    return {
      sector,
      deadZones,
      sectors: drawableSectors,
      labelAngles: sectorPieceLabelAngles(drawableSectors),
      isOmnidirectional: angleSweep(sector?.start ?? 0, sector?.end ?? 0) >= 359.9 && deadZones.length > 0,
    };
  }
  return orientedMainBatterySectorData(item, domain);
}

function shouldUseSchematicForward(items) {
  const hybridItems = items.filter((item) => (
    item.position?.source === "hybrid"
    && Number.isFinite(Number(item.position.schematicForward))
    && Number.isFinite(Number(item.position.z))
  ));
  if (hybridItems.length < 2) return false;
  const zValues = hybridItems.map((item) => Number(item.position.z));
  const zSpan = Math.max(Math.max(...zValues) - Math.min(...zValues), 0.001);
  const rowTolerance = Math.max(0.35, zSpan * 0.08);
  const rows = new Map();
  hybridItems.forEach((item) => {
    const rowKey = Number(item.position.schematicForward).toFixed(2);
    if (!rows.has(rowKey)) rows.set(rowKey, []);
    rows.get(rowKey).push(Number(item.position.z));
  });
  return [...rows.values()].some((row) => (
    row.length > 1 && Math.max(...row) - Math.min(...row) > rowTolerance
  ));
}

function positionedWeaponModules(modules, kind = null) {
  const items = (modules || [])
    .map((module, index) => ({
      module,
      index,
      position: modulePosition(module, kind),
      sector: moduleSector(module),
      additionalSectors: moduleAdditionalSectors(module),
      deadZones: moduleDeadZones(module),
    }))
    .filter((item) => item.position)
    .sort((left, right) => (
      left.position.forward - right.position.forward
      || left.position.side - right.position.side
      || left.index - right.index
    ));
  if (shouldUseSchematicForward(items)) {
    items.forEach((item) => {
      if (item.position?.source !== "hybrid") return;
      item.position = {
        ...item.position,
        forward: item.position.schematicForward,
        source: "schematic",
      };
    });
    items.sort((left, right) => (
      left.position.forward - right.position.forward
      || left.position.side - right.position.side
      || left.index - right.index
    ));
  }
  return items;
}

function secondarySectorRotation(item, ship = null) {
  const yawDeg = Number(item?.position?.yawDeg);
  if (Number.isFinite(yawDeg)) return yawDeg;
  return 0;
}

function hardpointShipDomain(ship, items) {
  const hardpointItems = items.filter((item) => ["hardpoint", "hardpoint-layout"].includes(item.position?.source));
  if (!hardpointItems.length || hardpointItems.length !== items.length) return null;
  const sourcePoints = hardpointItems.map((item) => ({
    x: Number(item.position.lateral) || 0,
    z: Number(item.position.z),
  }));
  const finitePoints = sourcePoints.filter((point) => (
    Number.isFinite(Number(point.x))
    && Number.isFinite(Number(point.z))
  ));
  if (!finitePoints.length) return null;

  let zMin = Math.min(...finitePoints.map((point) => Number(point.z)));
  let zMax = Math.max(...finitePoints.map((point) => Number(point.z)));
  let zSpan = zMax - zMin;
  if (zSpan < 0.001) {
    zMin -= 1;
    zMax += 1;
    zSpan = zMax - zMin;
  }
  const zPadding = Math.max(
    zSpan * SHIP_ANGLE_VIEWBOX.hardpointLongitudinalPaddingRatio,
    SHIP_ANGLE_VIEWBOX.hardpointMinLongitudinalPadding,
  );
  zMin -= zPadding;
  zMax += zPadding;
  zSpan = zMax - zMin;
  const lateralMax = finitePoints.reduce((current, point) => Math.max(current, Math.abs(Number(point.x) || 0)), 0);
  return {
    min: -zMax,
    max: -zMin,
    zMin,
    zMax,
    zSpan,
    lateralMax,
    source: "fixed-silhouette",
  };
}

function angleForwardDomain(items, ship = null) {
  const shipDomain = hardpointShipDomain(ship, items);
  if (shipDomain) return shipDomain;

  const hardpointItems = items.filter((item) => item.position?.source === "hardpoint");
  const domainItems = hardpointItems.length ? hardpointItems : items;
  const values = domainItems.map((item) => item.position.forward);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const lateralItems = items.filter((item) => Number.isFinite(Number(item.position?.lateral)));
  const lateralMax = lateralItems.reduce((current, item) => Math.max(current, Math.abs(Number(item.position.lateral) || 0)), 0);
  if (!hardpointItems.length && min >= 0 && max <= 6.6) {
    return { min: 0, max: 6.6, lateralMax };
  }
  if (Math.abs(max - min) < 0.001) {
    return { min: min - 1, max: max + 1, lateralMax };
  }
  return { min, max, lateralMax };
}

function interpolateShipAngleBounds(yNorm) {
  const rows = SHIP_ANGLE_IMAGE_BOUNDS;
  const y = clamp(yNorm, 0, 1);
  for (let index = 1; index < rows.length; index += 1) {
    const previous = rows[index - 1];
    const next = rows[index];
    if (y <= next[0]) {
      const span = Math.max(next[0] - previous[0], 0.001);
      const t = clamp((y - previous[0]) / span, 0, 1);
      return {
        left: previous[1] + (next[1] - previous[1]) * t,
        right: previous[2] + (next[2] - previous[2]) * t,
      };
    }
  }
  const last = rows[rows.length - 1];
  return { left: last[1], right: last[2] };
}


function torpedoHardpointLayoutPointSideSign(item) {
  if (isCenterlineHardpointLayoutTorpedoPoint(item)) return 0;
  const yawDeg = finiteNumberOrNull(item?.position?.yawDeg);
  if (Number.isFinite(yawDeg)) {
    const yaw = signedAngle(yawDeg);
    if (Math.abs(Math.abs(yaw) - 90) <= 35) return yaw > 0 ? 1 : -1;
  }
  const sectors = Array.isArray(item?.sectors) ? item.sectors : [];
  for (const sector of sectors) {
    const sign = sectorSideSign(sector);
    if (sign) return sign;
  }

  const schematicSide = finiteNumberOrNull(item?.position?.schematicSide);
  if (Number.isFinite(schematicSide)) {
    if (schematicSide <= 0.15) return 1;
    if (schematicSide >= 1.85) return -1;
  }

  const layoutX = finiteNumberOrNull(item?.position?.layoutX);
  if (Number.isFinite(layoutX) && Math.abs(layoutX) > 0.035) return layoutX > 0 ? 1 : -1;

  const lateral = finiteNumberOrNull(item?.position?.lateral);
  if (Number.isFinite(lateral) && Math.abs(lateral) > 0.035) return lateral > 0 ? 1 : -1;
  return 0;
}

function isCenterlineHardpointLayoutTorpedoPoint(item) {
  const position = item?.position || {};
  const layoutX = finiteNumberOrNull(position.layoutX);
  const lateral = finiteNumberOrNull(position.lateral);
  const rawX = finiteNumberOrNull(position.rawX);
  const yawDeg = finiteNumberOrNull(position.yawDeg);
  if (Number.isFinite(yawDeg)) {
    const yaw = signedAngle(yawDeg);
    if (Math.abs(Math.abs(yaw) - 90) <= 35) return false;
  }

  const schematicSide = finiteNumberOrNull(position.schematicSide);
  if (Number.isFinite(schematicSide)) return Math.abs(schematicSide - 1) <= 0.15;

  const side = finiteNumberOrNull(position.side);
  if (Number.isFinite(side) && Math.abs(side - 1) > 0.15) return false;

  const lateralValue = Number.isFinite(layoutX) ? layoutX : lateral;
  if (Number.isFinite(lateralValue) && Math.abs(lateralValue) <= 0.035) return true;
  return Number.isFinite(rawX) && Math.abs(rawX) <= 0.035;
}

function shipAnglePoint(item, domain, kind = null) {
  const cfg = SHIP_ANGLE_VIEWBOX;
  if (item.position?.source === "hardpoint-layout") {
    const layoutX = Number(item.position.layoutX);
    const layoutY = Number(item.position.layoutY);
    if (Number.isFinite(layoutX) && Number.isFinite(layoutY)) {
      const layoutScale = kind === "main"
        ? cfg.mainHardpointLayoutScale
        : (kind === "secondary" ? cfg.secondaryHardpointLayoutScale : 1);
      const layoutXScale = kind === "secondary"
        ? cfg.secondaryHardpointLayoutXScale
        : cfg.hardpointLayoutXScale;
      const y = cfg.sectorCenterY - clamp(layoutY, -1.35, 1.35) * cfg.hardpointLayoutYScale * layoutScale;
      const pointSideSign = kind === "torpedo" ? torpedoHardpointLayoutPointSideSign(item) : 0;
      if (kind === "torpedo" && pointSideSign) {
        const bodyHalfWidth = shipAngleBodyHalfWidthAtY(y);
        const lateralMax = Math.max(Number(domain?.lateralMax) || 0, Math.abs(layoutX), 0.001);
        const lateralRatio = clamp(Math.abs(layoutX) / lateralMax, 0, 1);
        const edgeFactor = 1.02 + lateralRatio * 0.10;
        return {
          x: cfg.centerX + pointSideSign * bodyHalfWidth * edgeFactor,
          y,
          yNorm: clamp((1 - layoutY) / 2, 0, 1),
        };
      }
      return {
        x: cfg.centerX + clamp(layoutX, -1.35, 1.35) * layoutXScale,
        y,
        yNorm: clamp((1 - layoutY) / 2, 0, 1),
      };
    }
  }
  const imageX = cfg.centerX - cfg.imageWidth / 2;
  const lateral = Number(item.position.lateral);
  const schematicSideValue = item.position.schematicSide;
  const schematicSide = schematicSideValue == null ? null : Number(schematicSideValue);
  const hasHardpointLateral = Number.isFinite(lateral);
  const hasSchematicSide = Number.isFinite(schematicSide);
  const useHardpointLateral = hasHardpointLateral && !hasSchematicSide;
  const yNorm = domain.source === "fixed-silhouette" && Number.isFinite(Number(item.position.z))
    ? cfg.hardpointTopNorm + clamp((domain.zMax - item.position.z) / Math.max(domain.zSpan, 0.001), 0, 1) * (cfg.hardpointBottomNorm - cfg.hardpointTopNorm)
    : item.position?.source === "gameparams-hull"
      ? clamp((1 - item.position.forward) / 2, 0, 1)
      : clamp((item.position.forward - domain.min) / Math.max(domain.max - domain.min, 0.001), 0, 1);
  const y = domain.source === "fixed-silhouette"
    ? cfg.imageY + yNorm * cfg.imageHeight
    : cfg.imageY + 34 + yNorm * (cfg.imageHeight - 68);
  const imageYNorm = clamp((y - cfg.imageY) / cfg.imageHeight, 0, 1);
  const bounds = interpolateShipAngleBounds(imageYNorm);
  const left = imageX + (bounds.left / 131) * cfg.imageWidth;
  const right = imageX + (bounds.right / 131) * cfg.imageWidth;
  const lateralFactor = item.position?.source === "gameparams-hull" && kind === "secondary"
    ? cfg.secondaryLateralFactor
    : useHardpointLateral
      ? cfg.hardpointLateralFactor
      : cfg.schematicLateralFactor;
  const rawHalfWidth = ((right - left) / 2) * lateralFactor;
  const isSideMountedSchematicTorpedo = kind === "torpedo"
    && !useHardpointLateral
    && hasSchematicSide
    && Math.abs(schematicSide - 1) > 0.15;
  const halfWidth = isSideMountedSchematicTorpedo
    ? Math.max(rawHalfWidth, cfg.imageWidth * 0.34)
    : rawHalfWidth;
  const sideNorm = useHardpointLateral
    ? clamp(0.5 + lateral / (2 * Math.max(domain.lateralMax || 0, 0.001)), 0, 1)
    : clamp(1 - schematicSide / 2, 0, 1);
  const x = cfg.centerX + (sideNorm - 0.5) * 2 * halfWidth;
  return { x, y, yNorm };
}

function shipAngleBodyHalfWidthAtY(y) {
  const cfg = SHIP_ANGLE_VIEWBOX;
  const imageX = cfg.centerX - cfg.imageWidth / 2;
  const imageYNorm = clamp((y - cfg.imageY) / cfg.imageHeight, 0, 1);
  const bounds = interpolateShipAngleBounds(imageYNorm);
  const left = imageX + (bounds.left / 131) * cfg.imageWidth;
  const right = imageX + (bounds.right / 131) * cfg.imageWidth;
  return Math.max((right - left) / 2, 1);
}

function hardpointSlotNumber(slot) {
  const match = `${slot || ""}`.match(/_(\d+)$/);
  return match ? Number(match[1]) : null;
}

function secondarySectorSideSign(item) {
  return sectorSideSign(item?.sector);
}

function secondaryYawSideSign(item) {
  const yawDeg = Number(item?.position?.yawDeg);
  if (!Number.isFinite(yawDeg)) return 0;
  const yaw = signedAngle(yawDeg);
  return Math.abs(Math.abs(yaw) - 90) <= 55
    ? (yaw > 0 ? 1 : -1)
    : 0;
}

function secondaryDisplaySideSign(item, index, centerlineThreshold = 0.16, useSectorBias = false) {
  const rawSector = item?.sector || moduleSector(item?.module);
  const lateral = Number(item?.position?.lateral);
  const rawSectorSign = sectorSideSign(rawSector);
  const yawSign = secondaryYawSideSign(item);
  if (rawSector && angleSweep(rawSector.start, rawSector.end) >= 260) return 0;
  if (rawSectorSign) return rawSectorSign;
  if (Number.isFinite(lateral) && Math.abs(lateral) <= centerlineThreshold) {
    if (useSectorBias && rawSectorSign) return rawSectorSign;
    if (rawSectorSign && yawSign && rawSectorSign === yawSign) return rawSectorSign;
    if (yawSign) return yawSign;
    return 0;
  }
  if (useSectorBias && rawSectorSign) return rawSectorSign;
  if (Number.isFinite(lateral)) {
    return lateral > 0 ? 1 : -1;
  }
  if (rawSectorSign != null) return rawSectorSign;
  const schematicSide = Number(item?.position?.schematicSide ?? item?.position?.side);
  if (Number.isFinite(schematicSide)) {
    if (Math.abs(schematicSide - 1) <= 0.08) return 0;
    if (Math.abs(schematicSide - 1) > 0.08) return schematicSide > 1 ? 1 : -1;
  }
  const yawDeg = Number(item?.position?.yawDeg);
  if (Number.isFinite(yawDeg) && Math.abs(yawDeg) > 35 && Math.abs(Math.abs(yawDeg) - 180) > 20) {
    return yawDeg > 0 ? 1 : -1;
  }
  const slotNumber = hardpointSlotNumber(item?.module?.slot);
  if (Number.isFinite(slotNumber)) {
    return slotNumber % 2 === 0 ? 1 : -1;
  }
  return index % 2 ? 1 : -1;
}

function secondaryShouldUseSectorBias(items, centerlineThreshold) {
  const sideItems = items
    .map((item) => {
      const rawSector = item?.sector || moduleSector(item?.module);
      if (!rawSector || angleSweep(rawSector.start, rawSector.end) >= 260) return null;
      const sectorSign = sectorSideSign(rawSector);
      const lateral = Number(item?.position?.lateral);
      const lateralSign = Number.isFinite(lateral) && Math.abs(lateral) > centerlineThreshold
        ? Math.sign(lateral)
        : 0;
      return { sectorSign, lateralSign };
    })
    .filter(Boolean);
  if (sideItems.length < 4) return false;
  const sectorPositive = sideItems.filter((item) => item.sectorSign > 0).length;
  const sectorNegative = sideItems.filter((item) => item.sectorSign < 0).length;
  const lateralPositive = sideItems.filter((item) => item.lateralSign > 0).length;
  const lateralNegative = sideItems.filter((item) => item.lateralSign < 0).length;
  const sectorHasBothSides = sectorPositive > 0 && sectorNegative > 0;
  if (!sectorHasBothSides) return false;
  const lateralImbalance = Math.abs(lateralPositive - lateralNegative);
  return lateralPositive === 0
    || lateralNegative === 0
    || lateralImbalance >= Math.max(2, Math.ceil(sideItems.length * 0.4));
}

function secondaryLateralScale(entries) {
  const values = entries
    .filter((entry) => entry.sign !== 0)
    .map((entry) => entry.lateralMagnitude)
    .filter((value) => Number.isFinite(value) && value > 0)
    .sort((left, right) => left - right);
  if (!values.length) return 0;
  const quantileIndex = Math.min(values.length - 1, Math.floor((values.length - 1) * 0.82));
  return Math.max(values[quantileIndex], values[0], 0.001);
}

function secondaryPointOffset(y, magnitude, lateralScale) {
  const cfg = SHIP_ANGLE_VIEWBOX;
  const halfWidth = shipAngleBodyHalfWidthAtY(y) * cfg.secondaryLateralFactor;
  const normalized = clamp(magnitude / Math.max(lateralScale || 0, 0.001), 0, 1);
  return halfWidth * (0.54 + normalized * 0.24);
}

function secondaryEntryGroupKey(entry) {
  return secondaryModuleGroupKey(entry.item?.module);
}

function groupedSecondaryEntries(entries) {
  const groups = new Map();
  entries.forEach((entry) => {
    const key = secondaryEntryGroupKey(entry);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(entry);
  });
  return groups;
}

function rebalanceSecondarySideEntries(entries, centerlineThreshold) {
  groupedSecondaryEntries(entries).forEach((groupEntries) => {
    const sideEntries = groupEntries.filter((entry) => entry.sign !== 0);
    if (sideEntries.length < 4) return;
    const desiredDifference = sideEntries.length % 2;
    const smallLateralLimit = Math.max(centerlineThreshold * 2.25, 0.35);

    while (true) {
      const port = sideEntries.filter((entry) => entry.sign < 0).length;
      const starboard = sideEntries.filter((entry) => entry.sign > 0).length;
      const difference = Math.abs(port - starboard);
      if (difference <= desiredDifference) break;

      const majoritySign = port > starboard ? -1 : 1;
      const candidate = sideEntries
        .filter((entry) => (
          entry.sign === majoritySign
          && entry.lateralMagnitude <= smallLateralLimit
        ))
        .sort((left, right) => (
          left.lateralMagnitude - right.lateralMagnitude
          || Math.abs(left.y - SHIP_ANGLE_VIEWBOX.sectorCenterY) - Math.abs(right.y - SHIP_ANGLE_VIEWBOX.sectorCenterY)
          || left.index - right.index
        ))[0];
      if (!candidate) break;
      candidate.sign = -majoritySign;
    }
  });
}

function alignSecondarySideRows(entries, lateralScale) {
  groupedSecondaryEntries(entries).forEach((groupEntries) => {
    const port = groupEntries
      .filter((entry) => entry.sign < 0)
      .sort((left, right) => left.y - right.y || left.index - right.index);
    const starboard = groupEntries
      .filter((entry) => entry.sign > 0)
      .sort((left, right) => left.y - right.y || left.index - right.index);
    const pairCount = Math.min(port.length, starboard.length);
    if (pairCount < 2) return;

    for (let index = 0; index < pairCount; index += 1) {
      const pair = [port[index], starboard[index]];
      const y = pair.reduce((sum, entry) => sum + entry.y, 0) / pair.length;
      const magnitude = Math.max(...pair.map((entry) => entry.lateralMagnitude));
      const offset = secondaryPointOffset(y, magnitude, lateralScale);
      pair.forEach((entry) => {
        entry.y = y;
        entry.x = SHIP_ANGLE_VIEWBOX.centerX + entry.sign * offset;
        entry.aligned = true;
      });
    }
  });
}

function secondaryEntryLateralMagnitude(entry, items) {
  const value = Math.abs(Number(items[entry.index]?.position?.lateral));
  return Number.isFinite(value) ? value : 0;
}

function secondaryEntryModuleKey(entry, items) {
  return secondaryModuleGroupKey(items[entry.index]?.module);
}

function secondaryEntryPhysicalSideSign(entry, items, threshold = 0.16) {
  const lateral = Number(items[entry.index]?.position?.lateral);
  if (!Number.isFinite(lateral) || Math.abs(lateral) <= threshold) return 0;
  return lateral > 0 ? 1 : -1;
}

function secondaryEntriesSharePhysicalSide(left, right, items) {
  const leftSign = secondaryEntryPhysicalSideSign(left, items);
  const rightSign = secondaryEntryPhysicalSideSign(right, items);
  return leftSign !== 0 && leftSign === rightSign;
}

function secondaryPairOffset(y, magnitude, lateralMax) {
  const cfg = SHIP_ANGLE_VIEWBOX;
  const halfWidth = shipAngleBodyHalfWidthAtY(y) * cfg.secondaryLateralFactor;
  const normalized = clamp(magnitude / Math.max(lateralMax || 0, 0.001), 0, 1);
  return halfWidth * (0.38 + normalized * 0.34);
}

function applySecondarySymmetricPairs(entries, items, lateralMax) {
  const sideEntries = entries
    .filter((entry) => entry.sign !== 0)
    .map((entry) => ({
      entry,
      slotNumber: hardpointSlotNumber(entry.slot),
    }))
    .filter((item) => Number.isFinite(item.slotNumber))
    .sort((left, right) => left.slotNumber - right.slotNumber || left.entry.index - right.entry.index);
  const used = new Set();
  let pairId = 0;
  for (let index = 0; index < sideEntries.length; index += 1) {
    const current = sideEntries[index];
    if (used.has(current.entry.index)) continue;
    const match = sideEntries.slice(index + 1).find((candidate) => (
      !used.has(candidate.entry.index)
      && Math.abs(candidate.slotNumber - current.slotNumber) === 1
      && secondaryEntryModuleKey(candidate.entry, items) === secondaryEntryModuleKey(current.entry, items)
      && Math.abs(candidate.entry.y - current.entry.y) <= 90
      && !secondaryEntriesSharePhysicalSide(current.entry, candidate.entry, items)
    ));
    if (!match) continue;

    const y = (current.entry.y + match.entry.y) / 2;
    const magnitude = (
      secondaryEntryLateralMagnitude(current.entry, items)
      + secondaryEntryLateralMagnitude(match.entry, items)
    ) / 2;
    const offset = secondaryPairOffset(y, magnitude, lateralMax);
    const orderedEntries = [current.entry, match.entry]
      .slice()
      .sort((left, right) => {
        if (left.sign !== right.sign) return left.sign - right.sign;
        const leftLateral = Number(items[left.index]?.position?.lateral);
        const rightLateral = Number(items[right.index]?.position?.lateral);
        if (Number.isFinite(leftLateral) && Number.isFinite(rightLateral) && Math.abs(leftLateral - rightLateral) > 0.08) {
          return leftLateral - rightLateral;
        }
        return (hardpointSlotNumber(left.slot) ?? left.index) - (hardpointSlotNumber(right.slot) ?? right.index);
      });
    orderedEntries.forEach((entry, sideIndex) => {
      entry.sign = sideIndex === 0 ? -1 : 1;
      entry.y = y;
      entry.x = SHIP_ANGLE_VIEWBOX.centerX + entry.sign * offset;
      entry.aligned = true;
      entry.paired = true;
      entry.pairId = pairId;
    });
    used.add(current.entry.index);
    used.add(match.entry.index);
    pairId += 1;
  }
}

function secondaryLayoutHasPhysicalSideImbalance(entries, centerlineThreshold) {
  const sideEntries = entries.filter((entry) => {
    const lateral = Number(entry?.item?.position?.lateral);
    return Number.isFinite(lateral) && Math.abs(lateral) > centerlineThreshold;
  });
  if (sideEntries.length < 6) return false;

  const portCount = sideEntries.filter((entry) => Number(entry.item.position.lateral) < 0).length;
  const starboardCount = sideEntries.filter((entry) => Number(entry.item.position.lateral) > 0).length;
  const difference = Math.abs(portCount - starboardCount);
  return difference >= Math.max(2, Math.ceil(sideEntries.length * 0.3));
}

function shouldPreserveSecondaryAsymmetricLayout(ship, entries, centerlineThreshold) {
  return isAirCarrierShip(ship)
    || hasHybridFlightDeckSecondaryLayout(ship)
    || secondaryLayoutHasPhysicalSideImbalance(entries, centerlineThreshold);
}

function spreadSecondaryPairedRows(entries, minGap, topLimit, bottomLimit) {
  const groups = new Map();
  entries
    .filter((entry) => entry.paired && Number.isFinite(entry.pairId))
    .forEach((entry) => {
      if (!groups.has(entry.pairId)) groups.set(entry.pairId, []);
      groups.get(entry.pairId).push(entry);
    });
  const rows = [...groups.entries()]
    .map(([id, rowEntries]) => ({
      id,
      entries: rowEntries,
      y: rowEntries.reduce((sum, entry) => sum + entry.y, 0) / rowEntries.length,
    }))
    .sort((left, right) => left.y - right.y || left.id - right.id);
  if (rows.length < 2) return;

  const originalCenter = rows.reduce((sum, row) => sum + row.y, 0) / rows.length;
  const yValues = rows.map((row) => row.y);
  for (let index = 1; index < yValues.length; index += 1) {
    if (yValues[index] < yValues[index - 1] + minGap) {
      yValues[index] = yValues[index - 1] + minGap;
    }
  }
  const newCenter = rows.length
    ? yValues.reduce((sum, value) => sum + value, 0) / yValues.length
    : originalCenter;
  let offset = originalCenter - newCenter;
  if (yValues[0] + offset < topLimit) offset = topLimit - yValues[0];
  if (yValues[yValues.length - 1] + offset > bottomLimit) {
    offset = bottomLimit - yValues[yValues.length - 1];
  }
  rows.forEach((row, index) => {
    const y = clamp(yValues[index] + offset, topLimit, bottomLimit);
    row.entries.forEach((entry) => {
      entry.y = y;
    });
  });
}

function tidySecondaryAnglePoints(points, items, ship = null) {
  if (!Array.isArray(points) || points.length < 6) return points;
  const cfg = SHIP_ANGLE_VIEWBOX;
  const lateralValues = items
    .map((item) => Math.abs(Number(item?.position?.lateral)))
    .filter((value) => Number.isFinite(value));
  const lateralMax = lateralValues.length ? Math.max(...lateralValues) : 0;
  const centerlineThreshold = Math.max(0.16, lateralMax * 0.14);
  const useSectorBias = secondaryShouldUseSectorBias(items, centerlineThreshold);
  const entries = points.map((point, index) => {
    const item = items[index];
    const sign = secondaryDisplaySideSign(item, index, centerlineThreshold, useSectorBias);
    const lateralMagnitude = Math.abs(Number(item?.position?.lateral));
    return {
      ...point,
      index,
      item,
      slot: item?.module?.slot,
      sign,
      lateralMagnitude: Number.isFinite(lateralMagnitude) ? lateralMagnitude : 0,
    };
  });

  const preserveAsymmetricLayout = shouldPreserveSecondaryAsymmetricLayout(ship, entries, centerlineThreshold);
  if (preserveAsymmetricLayout) {
    entries.forEach((entry) => {
      const physicalSign = itemPhysicalSideSign(entry.item, centerlineThreshold);
      if (physicalSign) entry.sign = physicalSign;
    });
  }
  if (!preserveAsymmetricLayout) {
    rebalanceSecondarySideEntries(entries, centerlineThreshold);
  }
  const lateralScale = secondaryLateralScale(entries) || lateralMax;
  if (!preserveAsymmetricLayout) {
    alignSecondarySideRows(entries, lateralScale);
    applySecondarySymmetricPairs(entries, items, lateralScale);
  }

  return entries
    .sort((left, right) => left.index - right.index)
    .map((entry) => {
      if (entry.sign === 0) return { x: cfg.centerX, y: entry.y, yNorm: entry.yNorm };
      if (entry.aligned) return { x: entry.x, y: entry.y, yNorm: entry.yNorm };
      const offset = secondaryPointOffset(entry.y, entry.lateralMagnitude, lateralScale);
      return {
        x: cfg.centerX + entry.sign * offset,
        y: entry.y,
        yNorm: entry.yNorm,
      };
    });
}

function tidySubmarineTorpedoAnglePoints(points, items) {
  if (!Array.isArray(points) || !points.length) return points;
  const cfg = SHIP_ANGLE_VIEWBOX;
  const entries = points.map((point, index) => ({
    ...point,
    index,
    item: items[index],
  }));
  const centerlineEntries = entries
    .filter((entry) => isCenterlineTorpedoItem(entry.item))
    .sort((left, right) => left.y - right.y || left.index - right.index);
  const rows = [];
  const rowTolerance = 9;
  centerlineEntries.forEach((entry) => {
    const row = rows.find((candidate) => Math.abs(candidate.y - entry.y) <= rowTolerance);
    if (row) {
      row.entries.push(entry);
      row.y = row.entries.reduce((sum, item) => sum + item.y, 0) / row.entries.length;
    } else {
      rows.push({ y: entry.y, entries: [entry] });
    }
  });

  rows.forEach((row) => {
    const rowY = row.entries.reduce((sum, entry) => sum + entry.y, 0) / row.entries.length;
    row.entries
      .sort((left, right) => {
        const leftLateral = Number(left.item?.position?.lateral);
        const rightLateral = Number(right.item?.position?.lateral);
        const leftVertical = Number(left.item?.position?.vertical);
        const rightVertical = Number(right.item?.position?.vertical);
        if (Number.isFinite(leftLateral) && Number.isFinite(rightLateral) && Math.abs(leftLateral - rightLateral) > 0.001) {
          return leftLateral - rightLateral;
        }
        if (Number.isFinite(leftVertical) && Number.isFinite(rightVertical) && Math.abs(leftVertical - rightVertical) > 0.001) {
          return rightVertical - leftVertical;
        }
        return left.index - right.index;
      })
      .forEach((entry, index, ordered) => {
        const gap = ordered.length >= 6 ? 5 : ordered.length >= 4 ? 6 : 7;
        entry.x = cfg.centerX + (index - (ordered.length - 1) / 2) * gap;
        entry.y = rowY;
      });
  });

  entries
    .filter((entry) => !isCenterlineTorpedoItem(entry.item))
    .forEach((entry) => {
      const lateral = Number(entry.item?.position?.lateral);
      if (Number.isFinite(lateral) && Math.abs(lateral) <= 0.04) {
        entry.x = cfg.centerX;
      }
    });

  return entries
    .sort((left, right) => left.index - right.index)
    .map((entry) => ({ x: entry.x, y: entry.y, yNorm: entry.yNorm }));
}

function resolveAnglePointCollisions(points) {
  const adjusted = points.map((point) => ({ ...point }));
  for (let index = 0; index < adjusted.length; index += 1) {
    let collision = 0;
    for (let other = 0; other < index; other += 1) {
      const dx = adjusted[index].x - adjusted[other].x;
      const dy = adjusted[index].y - adjusted[other].y;
      if (Math.hypot(dx, dy) < 2.5) collision += 1;
    }
    if (collision) {
      const direction = collision % 2 ? 1 : -1;
      adjusted[index].x += direction * (4 + Math.floor(collision / 2) * 3);
      adjusted[index].y += Math.floor((collision + 1) / 2);
    }
  }
  return adjusted;
}

function rayCircleIntersection(origin, circle, radius, degrees) {
  const radians = normalizeAngle(degrees) * Math.PI / 180;
  const direction = {
    x: Math.sin(radians),
    y: -Math.cos(radians),
  };
  const offset = {
    x: origin.x - circle.x,
    y: origin.y - circle.y,
  };
  const b = offset.x * direction.x + offset.y * direction.y;
  const c = offset.x * offset.x + offset.y * offset.y - radius * radius;
  const discriminant = b * b - c;
  if (discriminant < 0) {
    return polarPoint(circle.x, circle.y, radius, degrees);
  }

  const root = Math.sqrt(discriminant);
  const candidates = [-b - root, -b + root].filter((value) => value >= 0);
  const distance = candidates.length ? Math.min(...candidates) : Math.max(-b - root, -b + root);
  return {
    x: origin.x + direction.x * distance,
    y: origin.y + direction.y * distance,
  };
}

function circleAngle(point, circle) {
  return normalizeAngle(Math.atan2(point.x - circle.x, circle.y - point.y) * 180 / Math.PI);
}

function circleArcSweep(startPoint, endPoint, circle, preferLargeArc) {
  const start = circleAngle(startPoint, circle);
  const end = circleAngle(endPoint, circle);
  const clockwise = angleSweep(start, end);
  const counterClockwise = angleSweep(end, start);
  if (preferLargeArc) {
    return clockwise >= counterClockwise
      ? { largeArc: clockwise > 180 ? 1 : 0, sweep: 1 }
      : { largeArc: counterClockwise > 180 ? 1 : 0, sweep: 0 };
  }
  return clockwise <= counterClockwise
    ? { largeArc: clockwise > 180 ? 1 : 0, sweep: 1 }
    : { largeArc: counterClockwise > 180 ? 1 : 0, sweep: 0 };
}

function circleArcForSector(startPoint, endPoint, origin, circle, radius, sector) {
  const startAngle = circleAngle(startPoint, circle);
  const endAngle = circleAngle(endPoint, circle);
  const candidates = [
    { distance: clockwiseDelta(startAngle, endAngle), sweep: 1 },
    { distance: clockwiseDelta(endAngle, startAngle), sweep: 0 },
  ].map((candidate) => {
    const samples = [0.25, 0.5, 0.75];
    const score = samples.reduce((total, fraction) => {
      const angle = candidate.sweep
        ? startAngle + candidate.distance * fraction
        : startAngle - candidate.distance * fraction;
      const point = polarPoint(circle.x, circle.y, radius, angle);
      return total + (sectorContainsAngle(sector, circleAngle(point, origin)) ? 1 : 0);
    }, 0);
    return {
      ...candidate,
      score,
      largeArc: candidate.distance > 180 ? 1 : 0,
    };
  });
  const best = candidates.sort((left, right) => right.score - left.score)[0];
  if (best?.score > 0) {
    return { largeArc: best.largeArc, sweep: best.sweep };
  }
  return circleArcSweep(startPoint, endPoint, circle, angleSweep(sector.start, sector.end) > 180);
}

function sectorPathInFixedCircle(origin, circle, radius, sector) {
  if (!sector) return "";
  const sweep = angleSweep(sector.start, sector.end);
  if (sweep >= 359.9) {
    return sectorPath(circle.x, circle.y, radius, { start: 0, end: 360 });
  }
  const start = rayCircleIntersection(origin, circle, radius, sector.start);
  const end = rayCircleIntersection(origin, circle, radius, sector.end);
  const arc = circleArcForSector(start, end, origin, circle, radius, sector);
  return [
    `M ${svgNumber(origin.x)} ${svgNumber(origin.y)}`,
    `L ${svgNumber(start.x)} ${svgNumber(start.y)}`,
    `A ${radius} ${radius} 0 ${arc.largeArc} ${arc.sweep} ${svgNumber(end.x)} ${svgNumber(end.y)}`,
    "Z",
  ].join(" ");
}

function sectorOuterArcInFixedCircle(origin, circle, radius, sector) {
  if (!sector) return "";
  const sweep = angleSweep(sector.start, sector.end);
  if (sweep >= 359.9) {
    return [
      `M ${svgNumber(circle.x)} ${svgNumber(circle.y - radius)}`,
      `A ${radius} ${radius} 0 1 1 ${svgNumber(circle.x)} ${svgNumber(circle.y + radius)}`,
      `A ${radius} ${radius} 0 1 1 ${svgNumber(circle.x)} ${svgNumber(circle.y - radius)}`,
    ].join(" ");
  }
  const start = rayCircleIntersection(origin, circle, radius, sector.start);
  const end = rayCircleIntersection(origin, circle, radius, sector.end);
  const arc = circleArcForSector(start, end, origin, circle, radius, sector);
  return [
    `M ${svgNumber(start.x)} ${svgNumber(start.y)}`,
    `A ${radius} ${radius} 0 ${arc.largeArc} ${arc.sweep} ${svgNumber(end.x)} ${svgNumber(end.y)}`,
  ].join(" ");
}

function angleValueText(origin, circle, radius, angle) {
  if (!Number.isFinite(Number(angle))) return "";
  const edgePoint = rayCircleIntersection(origin, circle, radius, angle);
  const fromCircle = {
    x: edgePoint.x - circle.x,
    y: edgePoint.y - circle.y,
  };
  const length = Math.max(Math.hypot(fromCircle.x, fromCircle.y), 1);
  const normalized = normalizeAngle(angle);
  const isNearCenterline = Math.min(
    Math.abs(normalized),
    Math.abs(normalized - 180),
    Math.abs(normalized - 360),
  ) < 3;
  const labelOffset = isNearCenterline ? 22 : 16;
  const labelPoint = {
    x: edgePoint.x + (fromCircle.x / length) * labelOffset,
    y: edgePoint.y + (fromCircle.y / length) * labelOffset,
  };
  if (isNearCenterline) {
    labelPoint.x += 18;
  }
  const forwardOffset = Math.min(normalized, 360 - normalized);
  const aftOffset = Math.abs(180 - normalized);
  const label = Math.min(forwardOffset, aftOffset);
  return `<text class="ship-angle-sector-label" x="${svgNumber(labelPoint.x)}" y="${svgNumber(labelPoint.y)}">${formatValue(label, { digits: 0 })}\u00b0</text>`;
}

function angleEndpointText(origin, circle, radius, sector, which) {
  if (!sector) return "";
  const angle = which === "start" ? sector.start : sector.end;
  return angleValueText(origin, circle, radius, angle);
}

function angleBoundaryLines(origin, circle, radius, sector, className = "ship-angle-sector-boundary") {
  if (!sector) return "";
  const start = rayCircleIntersection(origin, circle, radius, sector.start);
  const end = rayCircleIntersection(origin, circle, radius, sector.end);
  const boundaryClass = escapeHtml(className);
  return `
    <line class="${boundaryClass}" x1="${svgNumber(origin.x)}" y1="${svgNumber(origin.y)}" x2="${svgNumber(start.x)}" y2="${svgNumber(start.y)}"></line>
    <line class="${boundaryClass}" x1="${svgNumber(origin.x)}" y1="${svgNumber(origin.y)}" x2="${svgNumber(end.x)}" y2="${svgNumber(end.y)}"></line>
  `;
}

function secondaryModuleFirepowerWeight(module) {
  const barrels = Number(module?.barrels);
  const reload = Number(module?.reload_s);
  const damage = Number(secondaryPreferredProjectile(module)?.alpha_damage);
  if (Number.isFinite(barrels) && barrels > 0 && Number.isFinite(reload) && reload > 0 && Number.isFinite(damage) && damage > 0) {
    return (barrels * damage * 60) / reload;
  }
  return Number.isFinite(barrels) && barrels > 0 ? barrels : 1;
}

function orientedWeaponItemsForFirepower(ship, modules, kind) {
  const decorated = withExternalHardpoints(ship, modules, kind);
  const items = positionedWeaponModules(decorated, kind);
  if (!items.length) return [];
  const domain = angleForwardDomain(items, ship);
  return items.map((item) => {
    const sectorData = orientedModuleSectorData(item, domain, kind, ship);
    return {
      ...item,
      rawSector: sectorData.rawSector,
      finalSector: sectorData.finalSector,
      usedSectorSource: sectorData.usedSectorSource,
      rawDeadZones: sectorData.rawDeadZones,
      finalDeadZones: sectorData.finalDeadZones,
      sector: sectorData.sector,
      deadZones: sectorData.deadZones,
      sectors: sectorData.sectors,
      isOmnidirectional: sectorData.isOmnidirectional,
    };
  });
}

function weightedAvailableValue(items, angle, valueGetter) {
  return items.reduce((sum, item) => {
    const value = Number(valueGetter(item.module, item));
    if (!Number.isFinite(value) || value <= 0) return sum;
    const sectors = item?.sectors || [];
    return sectors.some((sector) => sectorContainsAngle(sector, angle)) ? sum + value : sum;
  }, 0);
}

function maxAvailableWeightedResult(items, valueGetter, side = null) {
  const breakpoints = firepowerBreakpoints(items);
  const candidates = [];
  breakpoints.slice(0, -1).forEach((start, index) => {
    const end = breakpoints[index + 1];
    if (end - start <= 0.001) return;
    const midpoint = start + (end - start) / 2;
    if (!side || firepowerAngleSide(midpoint) === side) {
      candidates.push(midpoint);
    }
  });
  if (!candidates.length) candidates.push(90, 270);
  return candidates.reduce((best, angle) => {
    const value = weightedAvailableValue(items, angle, valueGetter);
    return value > best.value ? { value, angle } : best;
  }, { value: 0, angle: candidates[0] ?? null });
}

function maxAvailableWeightedValue(items, valueGetter, side = null) {
  return maxAvailableWeightedResult(items, valueGetter, side).value;
}

function weaponBroadsideMaxResult(ship, modules, kind, valueGetter) {
  const items = orientedWeaponItemsForFirepower(ship, modules, kind);
  if (!items.length) return null;
  const port = maxAvailableWeightedResult(items, valueGetter, "port");
  const starboard = maxAvailableWeightedResult(items, valueGetter, "starboard");
  const broadside = port.value >= starboard.value ? port : starboard;
  if (broadside.value > 0) return { ...broadside, items };
  const all = maxAvailableWeightedResult(items, valueGetter);
  return all.value > 0 ? { ...all, items } : null;
}

function weaponBroadsideMaxValue(ship, modules, kind, valueGetter) {
  return weaponBroadsideMaxResult(ship, modules, kind, valueGetter)?.value ?? null;
}

function moduleFirepowerWeight(item, kind = null) {
  if (kind === "secondary") {
    return secondaryModuleFirepowerWeight(item?.module);
  }
  const barrels = Number(item?.module?.barrels);
  return Number.isFinite(barrels) && barrels > 0 ? barrels : 1;
}

function firepowerAvailableWeight(items, angle, kind = null) {
  return items.reduce((sum, item) => {
    const sectors = item?.sectors || [];
    const canFire = sectors.some((sector) => sectorContainsAngle(sector, angle));
    return canFire ? sum + moduleFirepowerWeight(item, kind) : sum;
  }, 0);
}

function firepowerTotalWeight(items, kind = null) {
  return items.reduce((sum, item) => sum + moduleFirepowerWeight(item, kind), 0);
}

function firepowerAngleSide(angle) {
  const normalized = normalizeAngle(angle);
  if (Math.abs(normalized) <= 0.001 || Math.abs(normalized - 180) <= 0.001) return "center";
  return normalized < 180 ? "starboard" : "port";
}

function isSideBasedFirepowerKind(kind) {
  return kind === "secondary" || kind === "torpedo";
}

function firepowerMaxAvailableWeight(items, side = null, kind = null) {
  const breakpoints = firepowerBreakpoints(items);
  const candidates = [];
  breakpoints.slice(0, -1).forEach((start, index) => {
    const end = breakpoints[index + 1];
    if (end - start <= 0.001) return;
    const midpoint = start + (end - start) / 2;
    if (!side || side === "center" || firepowerAngleSide(midpoint) === side) {
      candidates.push(midpoint);
    }
  });
  if (!candidates.length) candidates.push(90, 270);
  return candidates.reduce((best, angle) => Math.max(best, firepowerAvailableWeight(items, angle, kind)), 0);
}

function firepowerDenominator(items, angle, kind = null, cache = null) {
  const total = firepowerTotalWeight(items, kind);
  if (!total) return 0;
  if (!isSideBasedFirepowerKind(kind)) {
    const key = "max";
    if (cache && cache[key] != null) return cache[key];
    const value = firepowerMaxAvailableWeight(items, null, kind) || total;
    if (cache) cache[key] = value;
    return value;
  }
  const side = firepowerAngleSide(angle);
  const key = side === "center" ? "all" : side;
  if (cache && cache[key] != null) return cache[key];
  const sideMax = firepowerMaxAvailableWeight(items, key === "all" ? null : key, kind);
  const value = sideMax || firepowerMaxAvailableWeight(items, null, kind) || total;
  if (cache) cache[key] = value;
  return value;
}

function angleFirepowerRatio(items, angle, kind = null, denominatorCache = null) {
  const denominator = firepowerDenominator(items, angle, kind, denominatorCache);
  if (!denominator) return 0;
  const available = firepowerAvailableWeight(items, angle, kind);
  return clamp(available / denominator, 0, 1);
}

function firepowerBreakpoints(items) {
  const breakpoints = [0, 180, 360];
  items.forEach((item) => {
    (item?.sectors || []).forEach((sector) => {
      if (!sector || angleSweep(sector.start, sector.end) >= 359.9) return;
      breakpoints.push(normalizeAngle(sector.start));
      const end = normalizeAngle(sector.end);
      breakpoints.push(end === 0 ? 360 : end);
    });
  });
  return [...breakpoints]
    .filter((angle) => Number.isFinite(angle))
    .sort((left, right) => left - right)
    .reduce((unique, angle) => {
      const previous = unique[unique.length - 1];
      if (previous == null || Math.abs(previous - angle) > 0.001) {
        unique.push(angle);
      }
      return unique;
    }, []);
}

function firepowerIntervals(items, kind = null) {
  const breakpoints = firepowerBreakpoints(items);
  const denominatorCache = {};
  return breakpoints.slice(0, -1)
    .map((start, index) => {
      const end = breakpoints[index + 1];
      if (end - start <= 0.001) return null;
      const midpoint = start + (end - start) / 2;
      return {
        start,
        end,
        side: firepowerAngleSide(midpoint),
        ratio: angleFirepowerRatio(items, midpoint, kind, denominatorCache),
      };
    })
    .filter(Boolean);
}

function firepowerPathPoints(items, circle, radius, kind = null) {
  const intervals = firepowerIntervals(items, kind);
  const step = SHIP_ANGLE_VIEWBOX.firepowerSampleStep;
  const points = [];
  intervals.forEach((interval) => {
    const pushPoint = (angle) => {
      points.push(polarPoint(circle.x, circle.y, radius * interval.ratio, angle));
    };
    pushPoint(interval.start);
    for (let angle = Math.ceil(interval.start / step) * step; angle < interval.end; angle += step) {
      if (angle > interval.start + 0.001) pushPoint(angle);
    }
    pushPoint(interval.end);
  });
  return points;
}

function firepowerPath(items, circle, radius, kind = null) {
  if (!items.length) return "";
  const points = firepowerPathPoints(items, circle, radius, kind);
  if (!points.length) return "";
  const allOuter = points.every((point) => Math.abs(Math.hypot(point.x - circle.x, point.y - circle.y) - radius) < 0.1);
  if (allOuter) return sectorPath(circle.x, circle.y, radius, { start: 0, end: 360 });
  return [
    `M ${svgNumber(points[0].x)} ${svgNumber(points[0].y)}`,
    ...points.slice(1).map((point) => `L ${svgNumber(point.x)} ${svgNumber(point.y)}`),
    "Z",
  ].join(" ");
}

function firepowerGridLines(circle, radius) {
  return [0, 45, 90, 135, 180, 225, 270, 315].map((angle) => {
    const edge = polarPoint(circle.x, circle.y, radius, angle);
    return `<line class="firepower-grid-line" x1="${svgNumber(circle.x)}" y1="${svgNumber(circle.y)}" x2="${svgNumber(edge.x)}" y2="${svgNumber(edge.y)}"></line>`;
  }).join("");
}

function firepowerRings(circle, radius) {
  return [0.25, 0.5, 0.75, 1].map((ratio) => (
    `<circle class="firepower-ring ${ratio === 1 ? "outer" : ""}" cx="${circle.x}" cy="${circle.y}" r="${svgNumber(radius * ratio)}"></circle>`
  )).join("");
}

function angleOffsetLabelValue(angle) {
  const normalized = normalizeAngle(angle);
  const forwardOffset = Math.min(normalized, 360 - normalized);
  const aftOffset = Math.abs(180 - normalized);
  return Math.min(forwardOffset, aftOffset);
}

function fullFirepowerRanges(items, kind = null) {
  const fullIntervals = firepowerIntervals(items, kind).filter((interval) => interval.ratio >= 0.999);
  if (!fullIntervals.length) return [];
  const ranges = fullIntervals.reduce((merged, interval) => {
    const previous = merged[merged.length - 1];
    const sameSide = !isSideBasedFirepowerKind(kind) || previous?.side === interval.side;
    if (previous && sameSide && Math.abs(previous.end - interval.start) <= 0.001) {
      previous.end = interval.end;
    } else {
      merged.push({ start: interval.start, end: interval.end, side: interval.side });
    }
    return merged;
  }, []);
  if (kind !== "secondary" && ranges.length > 1 && ranges[0].start <= 0.001 && Math.abs(ranges[ranges.length - 1].end - 360) <= 0.001) {
    const first = ranges.shift();
    const last = ranges.pop();
    ranges.push({ start: last.start, end: first.end + 360, side: last.side });
  }
  return ranges;
}

function firepowerFullBoundaryAngles(items, kind = null) {
  const angles = fullFirepowerRanges(items, kind)
    .filter((range) => angleSweep(range.start, range.end) < 359.9)
    .flatMap((range) => [range.start, range.end]);
  return uniqueAngleValues(angles);
}

function firepowerBoundaryGuide(circle, radius, angle) {
  const edge = polarPoint(circle.x, circle.y, radius, angle);
  const dx = edge.x - circle.x;
  const dy = edge.y - circle.y;
  const length = Math.max(Math.hypot(dx, dy), 1);
  const labelPoint = {
    x: edge.x + (dx / length) * 16,
    y: edge.y + (dy / length) * 16,
  };
  const label = angleOffsetLabelValue(angle);
  return `
    <line class="firepower-full-boundary" x1="${svgNumber(circle.x)}" y1="${svgNumber(circle.y)}" x2="${svgNumber(edge.x)}" y2="${svgNumber(edge.y)}"></line>
    <text class="firepower-full-label" x="${svgNumber(labelPoint.x)}" y="${svgNumber(labelPoint.y)}">${formatValue(label, { digits: 0 })}\u00b0</text>
  `;
}

function firepowerBoundaryGuides(items, circle, radius, kind = null) {
  return firepowerFullBoundaryAngles(items, kind)
    .map((angle) => firepowerBoundaryGuide(circle, radius, angle))
    .join("");
}

function sectorAttribute(sectors) {
  return (sectors || [])
    .map((sector) => `${Number(sector.start).toFixed(3)},${Number(sector.end).toFixed(3)}`)
    .join("|");
}

function singleSectorAttribute(sector) {
  if (!sector) return "";
  return `${Number(sector.start).toFixed(3)},${Number(sector.end).toFixed(3)}`;
}

function firepowerIntervalAttribute(items, kind = null) {
  return firepowerIntervals(items, kind)
    .map((interval) => [
      interval.start.toFixed(3),
      interval.end.toFixed(3),
      interval.ratio.toFixed(4),
    ].join(","))
    .join(";");
}

function shipAngleSilhouetteBox(scaleX = SHIP_ANGLE_VIEWBOX.silhouetteScaleX, scaleY = SHIP_ANGLE_VIEWBOX.silhouetteScaleY, centerY = null) {
  const cfg = SHIP_ANGLE_VIEWBOX;
  const width = cfg.imageWidth * scaleX;
  const height = cfg.imageHeight * scaleY;
  const middleY = Number.isFinite(Number(centerY))
    ? Number(centerY)
    : cfg.imageY + cfg.imageHeight / 2;
  return {
    x: cfg.centerX - width / 2,
    y: middleY - height / 2,
    width,
    height,
  };
}

function shipAngleSectorRadius(kind = null) {
  const cfg = SHIP_ANGLE_VIEWBOX;
  return kind === "secondary" ? cfg.secondarySectorRadius : cfg.sectorRadius;
}

function renderFirepowerDiagram(title, items, kind = null) {
  const cfg = SHIP_ANGLE_VIEWBOX;
  const sectorRadius = shipAngleSectorRadius(kind);
  const circle = { x: cfg.centerX, y: cfg.sectorCenterY };
  const imageBox = shipAngleSilhouetteBox(
    cfg.firepowerImageScale * cfg.silhouetteScaleX,
    cfg.firepowerImageScale * cfg.silhouetteScaleY,
    cfg.sectorCenterY,
  );
  const path = firepowerPath(items, circle, sectorRadius, kind);
  const intervalData = firepowerIntervalAttribute(items, kind);
  return `
    <svg class="firepower-diagram" viewBox="0 0 ${cfg.width} ${cfg.height}" role="img" aria-label="${escapeHtml(title)} firepower coverage" data-firepower-intervals="${escapeHtml(intervalData)}" data-firepower-kind="${escapeHtml(kind || "")}" data-firepower-radius="${svgNumber(sectorRadius)}">
      <image class="ship-angle-silhouette firepower-silhouette" href="/data/ship_angle.png?v=20260430" x="${svgNumber(imageBox.x)}" y="${svgNumber(imageBox.y)}" width="${svgNumber(imageBox.width)}" height="${svgNumber(imageBox.height)}" preserveAspectRatio="xMidYMid meet"></image>
      ${path ? `<path class="firepower-area" d="${path}"></path>` : ""}
      <g class="firepower-grid">
        ${firepowerGridLines(circle, sectorRadius)}
        ${firepowerRings(circle, sectorRadius)}
      </g>
      <g class="firepower-full-boundaries">
        ${firepowerBoundaryGuides(items, circle, sectorRadius, kind)}
      </g>
      <path class="ship-angle-bow-arrow" d="M ${cfg.centerX - 6} 18 L ${cfg.centerX} 10 L ${cfg.centerX + 6} 18"></path>
      <line class="ship-angle-centerline" x1="${cfg.centerX}" y1="18" x2="${cfg.centerX}" y2="${cfg.height - 42}"></line>
      <circle class="firepower-hover-target" cx="${cfg.centerX}" cy="${cfg.sectorCenterY}" r="${sectorRadius}"></circle>
      <g class="firepower-hover-overlay" aria-hidden="true">
        <line class="firepower-hover-line" x1="${cfg.centerX}" y1="${cfg.sectorCenterY}" x2="${cfg.centerX}" y2="${cfg.sectorCenterY - sectorRadius}"></line>
        <circle class="firepower-hover-dot" cx="${cfg.centerX}" cy="${cfg.sectorCenterY - sectorRadius}" r="4"></circle>
        <g class="firepower-hover-readout" transform="translate(${cfg.centerX + 64} ${cfg.sectorCenterY - sectorRadius + 26})">
          <rect class="firepower-hover-box" x="-60" y="-38" width="120" height="58" rx="4" ry="4"></rect>
          <text class="firepower-hover-text" data-firepower-angle y="-22">0\u00b0</text>
          <text class="firepower-hover-text strong" data-firepower-percent y="-4">0%</text>
          <text class="firepower-hover-text" data-firepower-guns y="14">Guns: 0</text>
        </g>
      </g>
    </svg>
  `;
}

function angleRangeLabel(sector) {
  if (!sector) return "Unknown firing sector";
  return `${formatValue(normalizeAngle(sector.start), { digits: 0 })}\u00b0 - ${formatValue(normalizeAngle(sector.end), { digits: 0 })}\u00b0`;
}

function renderShipAnglePanel(title = "Firing angles", modules = [], ship = null, kind = null) {
  const items = positionedWeaponModules(modules, kind);
  const cfg = SHIP_ANGLE_VIEWBOX;
  const sectorRadius = shipAngleSectorRadius(kind);
  const silhouetteBox = shipAngleSilhouetteBox(
    cfg.silhouetteScaleX,
    cfg.silhouetteScaleY,
    cfg.sectorCenterY,
  );
  const silhouetteCenterY = silhouetteBox.y + silhouetteBox.height / 2;
  if (!items.length) {
    return `
      <div class="ship-angle-panel" aria-label="${escapeHtml(title)}">
        <img class="ship-angle-image" src="/data/ship_angle.png?v=20260430" alt="${escapeHtml(title)}">
      </div>
    `;
  }

  const domain = angleForwardDomain(items, ship);
  const orientedItems = items.map((item) => {
    const sectorData = orientedModuleSectorData(item, domain, kind, ship);
    return {
      ...item,
      rawSector: sectorData.rawSector,
      finalSector: sectorData.finalSector,
      usedSectorSource: sectorData.usedSectorSource,
      rawDeadZones: sectorData.rawDeadZones,
      finalDeadZones: sectorData.finalDeadZones,
      sector: sectorData.sector,
      deadZones: sectorData.deadZones,
      sectors: sectorData.sectors,
      labelAngles: sectorData.labelAngles,
      isOmnidirectional: sectorData.isOmnidirectional,
    };
  });
  const mappedPoints = orientedItems.map((item) => shipAnglePoint(item, domain, kind));
  const usesHardpointLayout = kind !== "secondary" && orientedItems.every((item) => item.position?.source === "hardpoint-layout");
  const usesGameparamsHullLayout = orientedItems.every((item) => item.position?.source === "gameparams-hull");
  const rawPoints = kind === "torpedo" && isSubmarineShip(ship)
    ? tidySubmarineTorpedoAnglePoints(mappedPoints, orientedItems)
    : usesHardpointLayout || (kind === "secondary" && usesGameparamsHullLayout)
      ? mappedPoints
      : kind === "secondary"
        ? tidySecondaryAnglePoints(mappedPoints, orientedItems, ship)
        : mappedPoints;
  const points = usesHardpointLayout || (kind === "secondary" && orientedItems.length >= 6) || (kind === "torpedo" && isSubmarineShip(ship))
    ? rawPoints
    : resolveAnglePointCollisions(rawPoints);
  const dotRadius = kind === "secondary" && orientedItems.length >= 12
    ? cfg.secondaryDotRadius
    : cfg.dotRadius;
  const hitTargetRadius = kind === "secondary" && orientedItems.length >= 12 ? 11 : 13;
  const circleCenter = { x: cfg.centerX, y: cfg.sectorCenterY };
  const hoverSectors = orientedItems.map((item, index) => (
    (item.sectors || [])
      .map((sector) => sectorPathInFixedCircle(points[index], circleCenter, sectorRadius, sector))
      .filter(Boolean)
  ));
  const sectorOutlines = orientedItems.map((item, index) => (
    item.isOmnidirectional
      ? [sectorOuterArcInFixedCircle(points[index], circleCenter, sectorRadius, { start: 0, end: 360 })]
      : (item.sectors || []).map((sector) => sectorOuterArcInFixedCircle(points[index], circleCenter, sectorRadius, sector))
  ).filter(Boolean));
  const secondaryColorMap = kind === "secondary"
    ? secondaryGroupColorMapFromModules(orientedItems.map((item) => item.module))
    : new Map();

  return `
    <div class="ship-angle-panel ship-angle-panel-pair ship-angle-zoomable" aria-label="${escapeHtml(title)}" data-ship-angle-title="${escapeHtml(title)}" role="button" tabindex="0">
      <button class="ship-angle-zoom-button" type="button" aria-label="${escapeHtml(t("shipAngle.expand", "Expand firing angle diagrams"))}" title="${escapeHtml(t("shipAngle.expand", "Expand firing angle diagrams"))}">+</button>
      <svg class="ship-angle-diagram ${kind === "secondary" ? "secondary-angle-diagram" : ""}" viewBox="0 0 ${cfg.width} ${cfg.height}" role="img" aria-label="${escapeHtml(title)}">
        <image class="ship-angle-silhouette" data-silhouette-center-y="${svgNumber(silhouetteCenterY)}" data-sector-center-y="${svgNumber(cfg.sectorCenterY)}" href="/data/ship_angle.png?v=20260430" x="${svgNumber(silhouetteBox.x)}" y="${svgNumber(silhouetteBox.y)}" width="${svgNumber(silhouetteBox.width)}" height="${svgNumber(silhouetteBox.height)}" preserveAspectRatio="xMidYMid meet"></image>
        <g class="ship-angle-sector-layer">
          ${orientedItems.map((item, index) => {
            const point = points[index];
            const paths = hoverSectors[index] || [];
            const outlinePaths = sectorOutlines[index] || [];
            const deadZonePaths = item.isOmnidirectional
              ? (item.deadZones || [])
                .map((deadZone) => sectorPathInFixedCircle(point, circleCenter, sectorRadius, deadZone))
                .filter(Boolean)
              : [];
            return `
              <g class="ship-angle-sector-group ${item.isOmnidirectional ? "omnidirectional" : "limited-traverse"}" data-angle-index="${index}">
                ${paths.map((path) => `<path class="ship-angle-sector ship-angle-sector-hover" d="${path}"></path>`).join("")}
                ${deadZonePaths.map((path) => `<path class="ship-angle-dead-zone" d="${path}"></path>`).join("")}
                ${outlinePaths.map((path) => `<path class="ship-angle-sector-outline" d="${path}"></path>`).join("")}
                ${item.isOmnidirectional ? (item.deadZones || []).map((deadZone) => angleBoundaryLines(point, circleCenter, sectorRadius, deadZone, "ship-angle-dead-zone-boundary")).join("") : ""}
                ${(item.sectors || []).map((sector) => angleBoundaryLines(point, circleCenter, sectorRadius, sector)).join("")}
              </g>
            `;
          }).join("")}
        </g>
        <path class="ship-angle-bow-arrow" d="M ${cfg.centerX - 6} 18 L ${cfg.centerX} 10 L ${cfg.centerX + 6} 18"></path>
        <line class="ship-angle-centerline" x1="${cfg.centerX}" y1="18" x2="${cfg.centerX}" y2="${cfg.height - 42}"></line>
        <g class="ship-angle-turret-layer">
          ${orientedItems.map((item, index) => {
            const point = points[index];
            const moduleName = weaponModuleDisplayName(item.module);
            const secondaryColor = kind === "secondary" ? secondaryColorMap.get(secondaryModuleGroupKey(item.module)) : null;
            const turretStyle = secondaryColor
              ? ` style="--weapon-dot-color: ${escapeHtml(secondaryColor)}; --weapon-dot-hover-color: ${escapeHtml(secondaryColor)};"`
              : "";
            return `
              <g class="ship-angle-turret ${item.isOmnidirectional ? "omnidirectional" : "limited-traverse"}" data-angle-index="${index}" data-angle-sectors="${escapeHtml(sectorAttribute(item.sectors))}" data-raw-sector="${escapeHtml(singleSectorAttribute(item.rawSector))}" data-final-sector="${escapeHtml(singleSectorAttribute(item.finalSector || item.sector))}" data-used-sector-source="${escapeHtml(item.usedSectorSource || "")}" tabindex="0" aria-label="${escapeHtml(moduleName)}"${turretStyle}>
                ${(item.labelAngles || []).map((angle) => angleValueText(point, circleCenter, sectorRadius, angle)).join("")}
                <circle class="ship-angle-hit-target" cx="${svgNumber(point.x)}" cy="${svgNumber(point.y)}" r="${hitTargetRadius}"></circle>
                <circle class="ship-angle-dot" cx="${svgNumber(point.x)}" cy="${svgNumber(point.y)}" r="${dotRadius}"></circle>
                <text class="ship-angle-hover-label" x="${cfg.centerX}" y="${cfg.labelY}">${escapeHtml(moduleName)}</text>
              </g>
            `;
          }).join("")}
        </g>
      </svg>
      ${renderFirepowerDiagram(title, orientedItems, kind)}
    </div>
  `;
}

function shipAngleZoomTitle(panel) {
  const activeShip = state.activeModalShipCode
    ? state.ships.find((ship) => ship.identity?.code === state.activeModalShipCode)
    : null;
  const shipName = activeShip ? shipModalDisplayName(activeShip) : "";
  const panelTitle = panel?.dataset?.shipAngleTitle || panel?.getAttribute("aria-label") || t("shipAngle.firingAngles", "Firing angles");
  return shipName ? `${shipName} - ${panelTitle}` : panelTitle;
}

function closeShipAngleZoom() {
  const overlay = document.querySelector(".ship-angle-zoom-overlay");
  if (!overlay) return;
  overlay.classList.add("hidden");
  overlay.setAttribute("aria-hidden", "true");
  overlay.querySelector(".ship-angle-zoom-body").innerHTML = "";
  document.removeEventListener("keydown", handleShipAngleZoomKeydown);
}

function handleShipAngleZoomKeydown(event) {
  if (event.key === "Escape") closeShipAngleZoom();
}

function ensureShipAngleZoomOverlay() {
  let overlay = document.querySelector(".ship-angle-zoom-overlay");
  if (overlay) return overlay;
  overlay = document.createElement("div");
  overlay.className = "ship-angle-zoom-overlay hidden";
  overlay.setAttribute("aria-hidden", "true");
  overlay.innerHTML = `
    <div class="ship-angle-zoom-backdrop" data-ship-angle-zoom-close></div>
    <div class="ship-angle-zoom-card" role="dialog" aria-modal="true" aria-labelledby="ship-angle-zoom-title">
      <button class="ship-angle-zoom-close" type="button" aria-label="${escapeHtml(t("common.close", "Close"))}" data-ship-angle-zoom-close>+</button>
      <div class="ship-angle-zoom-body"></div>
      <div class="ship-angle-zoom-title" id="ship-angle-zoom-title"></div>
    </div>
  `;
  overlay.addEventListener("click", (event) => {
    if (event.target.closest("[data-ship-angle-zoom-close]")) {
      event.preventDefault();
      closeShipAngleZoom();
    }
  });
  document.body.appendChild(overlay);
  return overlay;
}

function openShipAngleZoom(panel) {
  if (!panel) return;
  const overlay = ensureShipAngleZoomOverlay();
  const body = overlay.querySelector(".ship-angle-zoom-body");
  const title = overlay.querySelector(".ship-angle-zoom-title");
  const clone = panel.cloneNode(true);
  clone.classList.remove("ship-angle-zoomable");
  clone.classList.add("ship-angle-zoom-clone");
  clone.removeAttribute("role");
  clone.removeAttribute("tabindex");
  clone.querySelectorAll(".ship-angle-zoom-button").forEach((button) => button.remove());
  body.innerHTML = "";
  body.appendChild(clone);
  title.textContent = shipAngleZoomTitle(panel);
  overlay.classList.remove("hidden");
  overlay.setAttribute("aria-hidden", "false");
  bindShipAngleInteractions(clone);
  document.addEventListener("keydown", handleShipAngleZoomKeydown);
}

function bindShipAngleZoomInteractions(root) {
  root.querySelectorAll(".ship-angle-panel-pair.ship-angle-zoomable").forEach((panel) => {
    panel.addEventListener("click", (event) => {
      event.preventDefault();
      openShipAngleZoom(panel);
    });
    panel.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      openShipAngleZoom(panel);
    });
  });
}

function bindShipAngleInteractions(root) {
  root.querySelectorAll(".ship-angle-diagram").forEach((diagram) => {
    const deactivateAll = () => {
      diagram.querySelectorAll(".ship-angle-sector-group.active").forEach((sector) => {
        sector.classList.remove("active");
      });
      diagram.classList.remove("has-active");
    };

    diagram.querySelectorAll(".ship-angle-turret[data-angle-index]").forEach((turret) => {
      const sector = diagram.querySelector(`.ship-angle-sector-group[data-angle-index="${turret.dataset.angleIndex}"]`);
      if (!sector) return;
      const activate = () => {
        deactivateAll();
        diagram.classList.add("has-active");
        sector.classList.add("active");
      };
      const deactivate = () => {
        sector.classList.remove("active");
        if (!diagram.querySelector(".ship-angle-sector-group.active")) {
          diagram.classList.remove("has-active");
        }
      };
      turret.addEventListener("mouseenter", activate);
      turret.addEventListener("mouseleave", deactivate);
      turret.addEventListener("focus", activate);
      turret.addEventListener("blur", deactivate);
    });
  });
  bindShipAngleZoomInteractions(root);
  bindFirepowerInteractions(root);
}

function parseFirepowerIntervals(value) {
  return `${value || ""}`
    .split(";")
    .map((chunk) => {
      const [start, end, ratio] = chunk.split(",").map(Number);
      if (!Number.isFinite(start) || !Number.isFinite(end) || !Number.isFinite(ratio)) return null;
      return { start, end, ratio };
    })
    .filter(Boolean);
}

function firepowerRatioFromIntervals(intervals, angle) {
  const normalized = normalizeAngle(angle);
  const match = intervals.find((interval) => (
    normalized >= interval.start - 0.001
    && normalized < interval.end - 0.001
  ));
  if (match) return match.ratio;
  const wrapMatch = intervals.find((interval) => interval.end > 360 && (
    normalized >= interval.start - 0.001
    || normalized < normalizeAngle(interval.end) - 0.001
  ));
  return wrapMatch?.ratio ?? 0;
}

function svgPointFromPointer(svg, event) {
  if (typeof svg.createSVGPoint === "function" && svg.getScreenCTM()) {
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    return point.matrixTransform(svg.getScreenCTM().inverse());
  }
  const rect = svg.getBoundingClientRect();
  const viewBox = svg.viewBox.baseVal;
  return {
    x: viewBox.x + ((event.clientX - rect.left) / Math.max(rect.width, 1)) * viewBox.width,
    y: viewBox.y + ((event.clientY - rect.top) / Math.max(rect.height, 1)) * viewBox.height,
  };
}

function clampFirepowerReadoutPosition(point) {
  const cfg = SHIP_ANGLE_VIEWBOX;
  return {
    x: clamp(point.x, 54, cfg.width - 54),
    y: clamp(point.y, 42, cfg.height - 54),
  };
}

function parseAngleSectors(value) {
  return `${value || ""}`
    .split("|")
    .map((chunk) => {
      const [start, end] = chunk.split(",").map(Number);
      if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
      return { start, end };
    })
    .filter(Boolean);
}

function setFirepowerAngleAvailability(diagram, angle) {
  const panel = diagram.closest(".ship-angle-panel-pair");
  const angleDiagram = panel?.querySelector(".ship-angle-diagram");
  if (!angleDiagram) return 0;
  let availableCount = 0;
  angleDiagram.classList.add("has-firepower-angle");
  angleDiagram.querySelectorAll(".ship-angle-turret[data-angle-index]").forEach((turret) => {
    const sectors = parseAngleSectors(turret.dataset.angleSectors);
    const canFire = sectors.some((sector) => sectorContainsAngle(sector, angle));
    turret.classList.toggle("firepower-unavailable", !canFire);
    if (canFire) availableCount += 1;
    const sectorGroup = angleDiagram.querySelector(`.ship-angle-sector-group[data-angle-index="${turret.dataset.angleIndex}"]`);
    if (sectorGroup) sectorGroup.classList.toggle("firepower-unavailable", !canFire);
  });
  return availableCount;
}

function clearFirepowerAngleAvailability(diagram) {
  const panel = diagram.closest(".ship-angle-panel-pair");
  const angleDiagram = panel?.querySelector(".ship-angle-diagram");
  if (!angleDiagram) return;
  angleDiagram.classList.remove("has-firepower-angle");
  angleDiagram.querySelectorAll(".firepower-unavailable").forEach((node) => {
    node.classList.remove("firepower-unavailable");
  });
}

function bindFirepowerInteractions(root) {
  root.querySelectorAll(".firepower-diagram").forEach((diagram) => {
    const intervals = parseFirepowerIntervals(diagram.dataset.firepowerIntervals);
    const kind = diagram.dataset.firepowerKind || "";
    const overlay = diagram.querySelector(".firepower-hover-overlay");
    const line = diagram.querySelector(".firepower-hover-line");
    const dot = diagram.querySelector(".firepower-hover-dot");
    const readout = diagram.querySelector(".firepower-hover-readout");
    const angleText = diagram.querySelector("[data-firepower-angle]");
    const percentText = diagram.querySelector("[data-firepower-percent]");
    const gunsText = diagram.querySelector("[data-firepower-guns]");
    if (!overlay || !line || !dot || !readout || !angleText || !percentText || !gunsText) return;

    const cfg = SHIP_ANGLE_VIEWBOX;
    const circle = { x: cfg.centerX, y: cfg.sectorCenterY };
    const radius = Number(diagram.dataset.firepowerRadius) || cfg.sectorRadius;
    const activate = () => diagram.classList.add("is-hovering");
    const deactivate = () => diagram.classList.remove("is-hovering");
    const update = (event) => {
      const point = svgPointFromPointer(diagram, event);
      const angle = circleAngle(point, circle);
      const edge = polarPoint(circle.x, circle.y, radius, angle);
      const labelAnchor = polarPoint(circle.x, circle.y, radius + 30, angle);
      const readoutPoint = clampFirepowerReadoutPosition(labelAnchor);
      const ratio = firepowerRatioFromIntervals(intervals, angle);
      const availableCount = setFirepowerAngleAvailability(diagram, angle);
      line.setAttribute("x2", svgNumber(edge.x));
      line.setAttribute("y2", svgNumber(edge.y));
      dot.setAttribute("cx", svgNumber(edge.x));
      dot.setAttribute("cy", svgNumber(edge.y));
      readout.setAttribute("transform", `translate(${svgNumber(readoutPoint.x)} ${svgNumber(readoutPoint.y)})`);
      angleText.textContent = `${formatValue(angleOffsetLabelValue(angle), { digits: 0 })}\u00b0`;
      percentText.textContent = `${formatValue(ratio * 100, { digits: 0 })}% firepower`;
      gunsText.textContent = `${kind === "torpedo" ? "Launchers" : "Guns"}: ${availableCount}`;
      activate();
    };

    diagram.addEventListener("pointerenter", (event) => update(event));
    diagram.addEventListener("pointermove", update);
    diagram.addEventListener("pointerleave", () => {
      deactivate();
      clearFirepowerAngleAvailability(diagram);
    });
  });
}

function moduleCategoryLabel(category) {
  const labels = {
    Artillery: "Main Battery",
    Hull: "Hull",
    Torpedoes: "Torpedoes",
    Sonar: "Sonar",
    Suo: "Gun Fire Control System",
    Fighter: "Attack Aircraft",
    TorpedoBomber: "Torpedo Bombers",
    DiveBomber: "Bombers",
    SkipBomber: "Skip Bombers",
    Engine: "Engine",
  };
  return labels[category] || category || "Module";
}

function moduleOptionTooltip(option) {
  const name = escapeHtml(option.display_name || option.upgrade_id || option.category || "Module");
  const category = escapeHtml(moduleCategoryLabel(option.category));
  const details = [];
  const costXp = Number(option.cost_xp);
  const costCr = Number(option.cost_cr);
  if (Number.isFinite(costXp) && costXp > 0) {
    details.push(`<div class="module-tooltip-row"><span class="module-tooltip-label">Research XP</span><strong class="module-tooltip-value">${costXp.toLocaleString("en-US")}</strong></div>`);
  }
  if (Number.isFinite(costCr) && costCr > 0) {
    details.push(`<div class="module-tooltip-row"><span class="module-tooltip-label">Purchase credits</span><strong class="module-tooltip-value">${costCr.toLocaleString("en-US")}</strong></div>`);
  }
  if (Array.isArray(option.unlocks) && option.unlocks.length) {
    details.push(`<div class="module-tooltip-row"><span class="module-tooltip-label">Unlocks</span><strong class="module-tooltip-value">${escapeHtml(option.unlocks.join(", "))}</strong></div>`);
  }
  return `
    <div class="module-tooltip">
      <div class="module-tooltip-title">${name}</div>
      <div class="module-tooltip-type">${category}</div>
      ${details.length ? `<div class="module-tooltip-divider"></div><div class="module-tooltip-details">${details.join("")}</div>` : ""}
    </div>
  `;
}

function defaultModalSelections(ship) {
  const selected = {};
  (ship?.module_options || []).forEach((group) => {
    const options = group?.options || [];
    const picked = state.activeConfig === "stock" ? options[0] : options[options.length - 1];
    if (picked?.upgrade_id) {
      selected[group.category] = picked.upgrade_id;
    }
  });
  return selected;
}

function modalSelectedUpgradeId(ship, category) {
  if (state.activeModalShipCode !== ship?.identity?.code) return defaultModalSelections(ship)[category];
  return state.modalSelectedUpgrades?.[category] || defaultModalSelections(ship)[category];
}

function modalSelectedUpgradeSnapshot(ship, nextCategory = null, nextUpgradeId = null) {
  const snapshot = {
    ...defaultModalSelections(ship),
    ...(state.activeModalShipCode === ship?.identity?.code ? (state.modalSelectedUpgrades || {}) : {}),
  };
  if (nextCategory && nextUpgradeId) snapshot[nextCategory] = nextUpgradeId;
  return snapshot;
}

function modalProfileCacheKey(shipCode, config, selectedMap) {
  const selected = Object.values(selectedMap || {})
    .filter(Boolean)
    .sort()
    .join(",");
  return `${shipCode}|${config}|${selected}`;
}

function getCachedModalProfile(shipCode, config, selectedMap) {
  return state.modalProfileCache[modalProfileCacheKey(shipCode, config, selectedMap)] || null;
}

function setCachedModalProfile(shipCode, config, selectedMap, profile) {
  state.modalProfileCache[modalProfileCacheKey(shipCode, config, selectedMap)] = profile;
}

function getCachedModalProfilePromise(shipCode, config, selectedMap) {
  return state.modalProfilePromiseCache[modalProfileCacheKey(shipCode, config, selectedMap)] || null;
}

function setCachedModalProfilePromise(shipCode, config, selectedMap, promise) {
  const key = modalProfileCacheKey(shipCode, config, selectedMap);
  if (promise) {
    state.modalProfilePromiseCache[key] = promise;
  } else {
    delete state.modalProfilePromiseCache[key];
  }
}

function modalSelectedCsv(selectedMap) {
  return Object.values(selectedMap || {}).filter(Boolean).join(",");
}

async function selectModalModule(shipCode, category, upgradeId) {
  if (!shipCode || !category || !upgradeId) return;
  const ship = state.ships.find((item) => item.identity.code === shipCode);
  if (!ship) return;
  const selectedSnapshot = modalSelectedUpgradeSnapshot(ship, category, upgradeId);
  state.modalSelectedUpgrades = selectedSnapshot;
  state.modalProfileError = null;
  const requestSeq = ++state.modalProfileRequestSeq;
  const cachedProfile = getCachedModalProfile(shipCode, state.activeConfig, selectedSnapshot);
  state.modalProfileOverride = cachedProfile || null;
  renderShipModal(shipCode);
  try {
    const profile = await loadModalProfile(ship, selectedSnapshot);
    if (requestSeq !== state.modalProfileRequestSeq || state.activeModalShipCode !== shipCode) return;
    state.modalProfileOverride = profile;
    state.modalProfileError = null;
  } catch (error) {
    if (requestSeq !== state.modalProfileRequestSeq || state.activeModalShipCode !== shipCode) return;
    state.modalProfileOverride = null;
    state.modalProfileError = error?.message || "Failed to load selected module profile.";
  }
  renderShipModal(shipCode);
}

function notOwnedModuleIconUrl(option) {
  return option?.icon_url ? option.icon_url.replace(/\.png$/i, "_researched.png") : null;
}

function modalModuleGroupUsesIndependentTypes(group) {
  const types = new Set((group?.options || []).map((option) => option?.uc_type).filter(Boolean));
  return group?.category === "Suo" && types.has("_FlightControl") && types.has("_Suo");
}

function modalSelectedUpgradeIdsForGroup(ship, group) {
  const selectedUpgradeId = modalSelectedUpgradeId(ship, group.category);
  if (!modalModuleGroupUsesIndependentTypes(group)) {
    return new Set(selectedUpgradeId ? [selectedUpgradeId] : []);
  }

  const byType = new Map();
  (group.options || []).forEach((option) => {
    const type = option?.uc_type || option?.category || "default";
    if (!byType.has(type)) byType.set(type, []);
    byType.get(type).push(option);
  });

  const selectedIds = new Set();
  byType.forEach((options) => {
    const ranked = [...options].sort((left, right) => (
      (Number(left?.depth) || 0) - (Number(right?.depth) || 0)
      || String(left?.upgrade_id || "").localeCompare(String(right?.upgrade_id || ""))
    ));
    const explicit = ranked.find((option) => option?.upgrade_id === selectedUpgradeId);
    const picked = explicit || (state.activeConfig === "stock" ? ranked[0] : ranked[ranked.length - 1]);
    if (picked?.upgrade_id) selectedIds.add(picked.upgrade_id);
  });
  return selectedIds;
}

function renderShipModuleIcons(ship) {
  const groups = ship.module_options || [];
  if (!groups.length) return "";
  return `
    <div class="modal-modules-wrap">
    <div class="modal-module-grid">
      ${groups.map((group) => {
        const activeUpgradeIds = modalSelectedUpgradeIdsForGroup(ship, group);
        return `
        <div class="modal-module-group" data-module-category="${group.category}">
          ${(group.options || []).map((option) => {
            const isActive = activeUpgradeIds.has(option?.upgrade_id);
            const iconUrl = isActive ? option.icon_url : (notOwnedModuleIconUrl(option) || option.icon_url);
            return `
            <button type="button" class="modal-module-icon ${isActive ? "is-selected" : "is-unselected"}" data-module-category="${escapeHtml(group.category)}" data-module-upgrade="${escapeHtml(option.upgrade_id || "")}" data-ship-code="${escapeHtml(ship.identity.code)}" aria-pressed="${isActive ? "true" : "false"}">
              ${iconUrl
                ? `<img src="${escapeHtml(iconUrl)}" alt="${escapeHtml(option.display_name || option.category)}">`
                : `<span>${escapeHtml((option.category || "?").slice(0, 1))}</span>`}
              ${moduleOptionTooltip(option)}
            </button>
          `;
          }).join("")}
        </div>
      `;
      }).join("")}
    </div>
    </div>
  `;
}

function shipMatchesTechRef(ship, ref) {
  if (!ship || !ref) return false;
  if (ship.identity?.name === ref) return true;
  const prefix = typeof ref === "string" && ref.includes("_") ? ref.split("_", 1)[0] : ref;
  return ship.identity?.code === prefix;
}

function techShipLabel(ship) {
  return ship?.displayName
    || prettyShipName(ship?.identity?.name)
    || ship?.identity?.code
    || "Unknown";
}

function modalTreeLinks(ship) {
  const nextRefs = ship.tech_tree?.next_ship_refs || ship.tech_tree?.next_refs || [];
  const nextCodes = ship.tech_tree?.next_ship_codes || [];
  const nextShips = state.ships.filter((candidate) =>
    nextRefs.some((ref) => shipMatchesTechRef(candidate, ref)) || nextCodes.includes(candidate.identity?.code)
  );
  const previousShips = state.ships.filter((candidate) =>
    (candidate.tech_tree?.next_ship_refs || candidate.tech_tree?.next_refs || []).some((ref) => shipMatchesTechRef(ship, ref))
    || (candidate.tech_tree?.next_ship_codes || []).includes(ship.identity?.code)
  );
  if (!nextShips.length && !previousShips.length) return "";
  const renderLinks = (ships) => ships
    .map((candidate) => `<button type="button" class="modal-tree-link" data-modal-nav="${escapeHtml(candidate.identity.code)}">${escapeHtml(techShipLabel(candidate))}</button>`)
    .join(" ");
  const previousMarkup = previousShips.length
    ? `<span class="modal-tree-nav-prev">${renderLinks(previousShips)}</span><span class="modal-tree-nav-arrow">&larr;</span>`
    : "";
  const nextMarkup = nextShips.length
    ? `<span class="modal-tree-nav-arrow">&rarr;</span><span class="modal-tree-nav-next">${renderLinks(nextShips)}</span>`
    : "";
  return `
    <div class="modal-tree-nav">
      <div class="modal-tree-nav-links">
        ${previousMarkup}
        ${nextMarkup}
      </div>
    </div>
  `;
}

function renderModalTabContent(ship, tab, options = {}) {
  const activeShip = modalShipView(ship);
  const ap = firstProjectile(activeShip, "AP");
  const he = firstProjectile(activeShip, "HE");
  const sap = firstProjectile(activeShip, "SAP");
  const mainRange = formatDistanceMeters(activeShip.artillery?.main_battery?.range_m);
  const mainModalContext = getModalRenderContext("Main battery", [activeShip]);
  const apModalContext = getModalRenderContext("AP Shells", [activeShip]);
  const heModalContext = getModalRenderContext("HE Shells", [activeShip]);
  const sapModalContext = getModalRenderContext("SAP Shells", [activeShip]);
  const secondaryModalContext = getModalRenderContext("Secondaries", [activeShip]);

  if (tab === "main") {
    return `
      <div class="modal-panel-header"><h3>${uiLabel("Main battery")}</h3>${renderModalRangeControl("Main battery", [activeShip])}</div>
      ${modalSpecColumns([
        ["Main battery", [
          ["Description", mainBatteryDescription(activeShip)],
          ap ? ["AP DPM", formatValue(mainBatteryDpm(activeShip, "AP"), { digits: 0, grouping: true })] : null,
          he ? ["HE DPM", formatValue(mainBatteryDpm(activeShip, "HE"), { digits: 0, grouping: true })] : null,
          sap ? ["SAP DPM", formatValue(mainBatteryDpm(activeShip, "SAP"), { digits: 0, grouping: true })] : null,
        ]],
        ["", [
          ap ? ["AP salvo", formatValue(mainBatterySalvo(activeShip, "AP"), { digits: 0, grouping: true })] : null,
          he ? ["HE salvo", formatValue(mainBatterySalvo(activeShip, "HE"), { digits: 0, grouping: true })] : null,
          sap ? ["SAP salvo", formatValue(mainBatterySalvo(activeShip, "SAP"), { digits: 0, grouping: true })] : null,
          ["Range", mainRange],
          ["Reload", mainBatteryReloadDisplay(activeShip)],
        ]],
        ["", [
          ["Sigma", formatSigma(activeShip.artillery?.main_battery?.sigma_count)],
          ["180 turn", formatValue(activeShip.artillery?.main_battery?.modules?.[0]?.rotation_deg_per_s ? 180 / activeShip.artillery.main_battery.modules[0].rotation_deg_per_s : null, { digits: 1, suffix: " s" })],
          ["Flight time", mainBatteryFlightTimeDisplay(activeShip, mainModalContext)],
          ["Hor. dispersion", mainBatteryDispersionDisplay(activeShip, mainModalContext, "horizontal")],
          ["Ver. dispersion", mainBatteryDispersionDisplay(activeShip, mainModalContext, "vertical")],
          ["Shells/min", formatValue(mainBatteryShellsPerMinute(activeShip), { digits: 1 })],
        ]],
      ], { groupLabel: "Main battery", context: mainModalContext })}
      ${renderShipAnglePanel(t("shipAngle.mainBattery", "Main battery firing angles"), withExternalHardpoints(activeShip, mainBatteryModules(activeShip), "main"), activeShip, "main")}
    `;
  }

  if (tab === "medium") {
    const battery = mediumBattery(activeShip);
    const projectile = mediumBatteryProjectile(activeShip);
    const ammoPrefix = mediumBatteryAmmoPrefix(projectile);
    const drum = mediumBatteryDrum(activeShip);
    const fullReloadTime = Number(drum?.full_reload_time);
    const salvoInterval = Number(drum?.shot_delay);
    const salvosInSeries = Number(drum?.shots_count);
    const fireChance = projectile?.ammo_type === "HE" ? positiveRatioValue(projectile?.burn_prob) : null;
    return (
      '<div class="modal-panel-header"><h3>' + uiLabel("Medium-caliber battery") + '</h3><span>'
      + uiLabel("Firing range") + ': ' + formatDistanceMeters(battery?.range_m) + '</span></div>'
      + modalSpecColumns([
        ["Medium-caliber battery", [
          ["Description", mediumBatteryDescription(activeShip)],
          [ammoPrefix + " DPM", formatValue(mediumBatteryDpm(activeShip), { digits: 0, grouping: true })],
          [ammoPrefix + " salvo", formatValue(mediumBatterySalvo(activeShip), { digits: 0, grouping: true })],
        ]],
        ["", [
          ["Range", formatDistanceMeters(battery?.range_m)],
          ["Reload", formatValue(battery?.reload_s, { digits: 1, suffix: " s" })],
          Number.isFinite(fullReloadTime) ? ["Full reload time", formatValue(fullReloadTime, { digits: 1, suffix: " s" })] : null,
          Number.isFinite(salvoInterval) ? ["Salvo interval", formatValue(salvoInterval, { digits: 2, suffix: " s" })] : null,
        ]],
        ["", [
          Number.isFinite(salvosInSeries) ? ["Salvos in series", formatValue(salvosInSeries, { digits: 0 })] : null,
          ["Sigma", formatSigma(battery?.sigma_count)],
          ["180 turn", formatValue(mediumBatteryTurn180(activeShip), { digits: 1, suffix: " s" })],
          ["Penetration", formatValue(mediumBatteryPenetration(activeShip), { digits: 0, suffix: " mm" })],
          fireChance != null ? ["Fire chance", formatPercent(fireChance, { scale: 100 })] : null,
          ["Shells/min", formatValue(mediumBatteryShellsPerMinute(activeShip), { digits: 1 })],
        ]],
      ], { groupLabel: "Medium-caliber battery" })
      + renderShipAnglePanel(
        t("shipAngle.mediumBattery", "Medium-caliber battery firing angles"),
        withExternalHardpoints(activeShip, mediumBatteryModules(activeShip), "main"),
        activeShip,
        "main",
      )
    );
  }

  const torpedoTabIndex = torpedoModalTabIndex(tab);
  if (torpedoTabIndex != null) {
    const torpedoShip = withTorpedoVariant(activeShip, torpedoTabIndex);
    const torpedo = firstTorpedoProjectile(torpedoShip);
    const torpedoRange = torpedo?.max_dist != null ? formatValue(torpedo.max_dist * 0.03, { digits: 1, suffix: " km" }) : "N/A";
    const loaderText = torpedoLoaders(torpedoShip);
    const torpedoTitle = torpedoTitleForProjectile(torpedo, torpedoTabIndex);
    return `
      <div class="modal-panel-header"><h3>${uiLabel(torpedoTitle)}</h3><span>${uiLabel("Firing range")}: ${torpedoRange}</span></div>
      ${modalSpecColumns([
        [torpedoTitle, [
          ["Description", torpedoDescription(torpedoShip)],
          ["Type", torpedoTypeDisplay(torpedo)],
          loaderText !== "N/A" ? ["Loaders", loaderText] : null,
          ["Damage", formatValue(torpedoEffectiveDamage(torpedoShip), { digits: 0, grouping: true })],
        ]],
        ["", [
          ["Torpedo DPM", formatValue(torpedoDpm(torpedoShip), { digits: 0, grouping: true })],
          ["Range", torpedoRange],
          ["Reload", formatValue(torpedoReloadSeconds(torpedoShip), { digits: 1, suffix: " s" })],
          ["Speed", formatValue(torpedo?.speed, { digits: 0, suffix: " kn" })],
        ]],
        ["", [
          ["Detectability", formatValue(torpedo?.visibility_factor, { digits: 1, suffix: " km" })],
          ["Reaction time", formatValue(torpedoReactionTime(torpedoShip), { digits: 1, suffix: " s" })],
          ["Flood chance", formatPercent(torpedo?.uw_critical, { scale: 100 })],
          isThermalTorpedoProjectile(torpedo) ? ["Fire chance", torpedoFireChanceDisplay(torpedo)] : null,
          ["Torpedo/min", formatValue(torpedoesPerMinute(torpedoShip), { digits: 1 })],
        ]],
      ], { groupLabel: "Torpedoes" })}
      ${renderShipAnglePanel(t("shipAngle.torpedoes", "Torpedo firing angles"), withExternalHardpoints(torpedoShip, torpedoModules(torpedoShip), "torpedo"), torpedoShip, "torpedo")}
    `;
  }

  if (tab === "ap") {
    const apRange = rangeLabelFromContext(apModalContext);
    return `
      <div class="modal-panel-header"><h3>${uiLabel("AP Shells")}</h3>${renderModalRangeControl("AP Shells", [activeShip])}</div>
      ${modalSpecColumns([
        ["AP shells", [
          ["Weight", formatValue(ap?.bullet_mass, { digits: 0, grouping: true, suffix: " kg" })],
          ["Damage", formatValue(ap?.alpha_damage, { digits: 0, grouping: true })],
          ["Initial speed", formatValue(ap?.bullet_speed, { suffix: " m/s" })],
          ["Drag coeff.", formatValue(ap?.bullet_air_drag, { digits: 3 })],
        ]],
        ["", [
          ["Flight time", shellFlightTimeDisplay(activeShip, ap, apModalContext, "AP Shells")],
          ["Impact speed", shellImpactSpeedDisplay(activeShip, ap, apModalContext, "AP Shells")],
          ["Impact angle", shellImpactAngleDisplay(activeShip, ap, apModalContext, "AP Shells")],
          ["Krupp", formatValue(ap?.krupp, { digits: 0, grouping: true })],
          ["Penetration", shellPenetrationDisplay(activeShip, ap, apModalContext, "AP Shells")],
        ]],
        ["", [
          ["Overmatch", formatValue(shellOvermatch(ap), { digits: 0, suffix: " mm" })],
          ["Ricochet", shellRicochet(ap)],
          ["Threshold", formatValue(ap?.detonator_threshold, { digits: 0, suffix: " mm" })],
          ["Fuse time", formatValue(ap?.detonator, { digits: 3, suffix: " s" })],
        ]],
      ], { groupLabel: "AP Shells", context: apModalContext })}
      ${options.suppressCharts ? "" : renderTrajectoryPanel(apRange, activeShip, ap, apModalContext, "AP Shells")}
    `;
  }

  if (tab === "he") {
    const heRange = rangeLabelFromContext(heModalContext);
    return `
      <div class="modal-panel-header"><h3>${uiLabel("HE Shells")}</h3>${renderModalRangeControl("HE Shells", [activeShip])}</div>
      ${modalSpecColumns([
        ["HE shells", [
          ["Weight", formatValue(he?.bullet_mass, { digits: 0, grouping: true, suffix: " kg" })],
          ["Damage", formatValue(he?.alpha_damage, { digits: 0, grouping: true })],
          ["Initial speed", formatValue(he?.bullet_speed, { suffix: " m/s" })],
          ["Drag coeff.", formatValue(he?.bullet_air_drag, { digits: 3 })],
        ]],
        ["", [
          ["Flight time", shellFlightTimeDisplay(activeShip, he, heModalContext, "HE Shells")],
          ["Impact speed", shellImpactSpeedDisplay(activeShip, he, heModalContext, "HE Shells")],
          ["Impact angle", shellImpactAngleDisplay(activeShip, he, heModalContext, "HE Shells")],
          ["Penetration", formatValue(he?.alpha_piercing_he, { digits: 0, suffix: " mm" })],
          ["Fire chance", fireChanceDisplay(he?.burn_prob, { scale: 100 })],
        ]],
        ["", [
          ["Fires/min", formatValue(shellFirePerMinute(activeShip, he), { digits: 1 })],
        ]],
      ], { groupLabel: "HE Shells", context: heModalContext })}
      ${options.suppressCharts ? "" : renderTrajectoryPanel(heRange, activeShip, he, heModalContext, "HE Shells")}
    `;
  }

  if (tab === "sap") {
    const sapRange = rangeLabelFromContext(sapModalContext);
    return `
      <div class="modal-panel-header"><h3>${uiLabel("SAP Shells")}</h3>${renderModalRangeControl("SAP Shells", [activeShip])}</div>
      ${modalSpecColumns([
        ["SAP shells", [
          ["Description", shellDescription(sap)],
          ["Weight", formatValue(sap?.bullet_mass, { digits: 0, grouping: true, suffix: " kg" })],
          ["Damage", formatValue(sap?.alpha_damage, { digits: 0, grouping: true })],
          ["Initial speed", formatValue(sap?.bullet_speed, { suffix: " m/s" })],
          ["Drag coeff.", formatValue(sap?.bullet_air_drag, { digits: 3 })],
        ]],
        ["", [
          ["Flight time", shellFlightTimeDisplay(activeShip, sap, sapModalContext, "SAP Shells")],
          ["Impact speed", shellImpactSpeedDisplay(activeShip, sap, sapModalContext, "SAP Shells")],
          ["Impact angle", shellImpactAngleDisplay(activeShip, sap, sapModalContext, "SAP Shells")],
          ["Penetration", formatValue(sap?.alpha_piercing_cs, { digits: 0, suffix: " mm" })],
          ["Ricochet", shellRicochet(sap)],
        ]],
        ["", [
          ["Threshold", formatValue(sap?.detonator_threshold, { digits: 0, suffix: " mm" })],
        ]],
      ], { groupLabel: "SAP Shells", context: sapModalContext })}
      ${options.suppressCharts ? "" : renderTrajectoryPanel(sapRange, activeShip, sap, sapModalContext, "SAP Shells")}
    `;
  }

  if (tab === "secondaries") {
    const secondaryTitle = secondaryAmmoTypeLabel(activeShip);
    const showSecondaryFire = secondaryUsesFire(activeShip);
    return `
      <div class="modal-panel-header"><h3>${uiLabel(secondaryTitle)}</h3>${renderModalRangeControl("Secondaries", [activeShip])}</div>
      ${modalSpecColumns([
        [secondaryTitle, [
          ["Description", secondaryDescription(activeShip)],
          ["Secondary DPM", secondaryDpmDisplay(activeShip)],
          ["Hitting DPM", secondaryHittingDpmDisplay(activeShip)],
          ["DPM contribution", secondaryDpmContributionDisplay(activeShip)],
          ["Range", secondaryRangeStat(activeShip, (group) => group?.max_dist_m ?? group?.range_m, (value) => formatDistanceMeters(value), { digits: 0 })],
        ]],
        ["", [
          ["Reload", secondaryRangeStat(activeShip, (group) => group?.reload_s, (value) => formatValue(value, { digits: 1, suffix: " s" }), { digits: 1 })],
          ["Flight time", secondariesFlightTimeDisplay(activeShip, secondaryModalContext)],
          ["Hor. dispersion", secondariesDispersionDisplay(activeShip, secondaryModalContext)],
          ["Sigma", secondariesSigmaDisplay(activeShip)],
        ]],
        ["", [
          ["Penetration", secondaryRangeStat(activeShip, (group) => secondaryPenetrationValue(activeShip, group, secondaryModalContext), (value) => formatValue(value, { digits: 0, suffix: " mm" }), { digits: 0 })],
          showSecondaryFire ? ["Fire chance", secondaryRangeStat(activeShip, (group) => {
            const burnProb = positiveRatioValue(group?.projectile?.burn_prob);
            return burnProb == null ? null : burnProb * 100;
          }, (value) => formatValue(value, { digits: 0, suffix: "%" }), { digits: 0 })] : null,
          showSecondaryFire ? ["Fires/min", secondaryTotalStat(activeShip, (group) => secondaryGroupFirePerMinute(group), {
            formatter: (value) => formatValue(value, { digits: 1 }),
            detailFormatter: (value) => formatValue(value, { digits: 1 }),
          })] : null,
          ["Shells/min", secondaryBroadsideStatDisplay(activeShip, (module) => secondaryModuleShellsPerMinuteValue(module), {
            formatter: (value) => formatValue(value, { digits: 1 }),
            detailFormatter: (value) => formatValue(value, { digits: 1 }),
          })],
        ]],
      ], { groupLabel: "Secondaries", context: secondaryModalContext })}
      ${options.suppressCharts ? "" : renderShellChartsPanel(activeShip, secondaryChartProjectile(activeShip), secondaryModalContext, "Secondaries", { compact: true })}
      ${renderShipAnglePanel(t("shipAngle.secondaries", "Secondary battery firing angles"), withExternalHardpoints(activeShip, secondaryGunModules(activeShip), "secondary"), activeShip, "secondary")}
    `;
  }

  return `
    ${modalSpecColumns(summaryModalGroups(activeShip))}
    ${renderCombatInstructionSummary(activeShip)}
    ${renderConsumableSummary(activeShip)}
  `;
}

async function loadModalProfile(ship, selectedMap = state.modalSelectedUpgrades) {
  const cached = getCachedModalProfile(ship.identity.code, state.activeConfig, selectedMap);
  if (cached) return cached;
  await loadStaticModalProfiles(state.dataServer, state.language, state.activeConfig, ship.identity.code);
  const staticProfile = staticModalProfilePayload(ship.identity.code, state.activeConfig, selectedMap);
  if (staticProfile) {
    setCachedModalProfile(ship.identity.code, state.activeConfig, selectedMap, staticProfile);
    return staticProfile;
  }
  const inflight = getCachedModalProfilePromise(ship.identity.code, state.activeConfig, selectedMap);
  if (inflight) return inflight;
  const query = new URLSearchParams({
    server: state.dataServer,
    lang: state.language,
    code: ship.identity.code,
    config: state.activeConfig,
    selected: modalSelectedCsv(selectedMap),
  });
  const promise = fetch(`/api/ship-profile?${query.toString()}`, { cache: "no-store" })
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`Failed to load /api/ship-profile for ${ship.identity.code}`);
      }
      const payload = await response.json();
      const profile = payload.profile || null;
      if (profile) {
        setCachedModalProfile(ship.identity.code, state.activeConfig, selectedMap, profile);
      }
      return profile;
    })
    .finally(() => {
      setCachedModalProfilePromise(ship.identity.code, state.activeConfig, selectedMap, null);
    });
  setCachedModalProfilePromise(ship.identity.code, state.activeConfig, selectedMap, promise);
  return promise;
}

async function loadModalProfilesBatch(ship, snapshots) {
  const missingSnapshots = (snapshots || []).filter((snapshot) => {
    if (getCachedModalProfile(ship.identity.code, state.activeConfig, snapshot)) return false;
    if (getCachedModalProfilePromise(ship.identity.code, state.activeConfig, snapshot)) return false;
    return true;
  });
  if (!missingSnapshots.length) return {};
  await loadStaticModalProfiles(state.dataServer, state.language, state.activeConfig, ship.identity.code);
  const staticProfiles = applyStaticModalProfiles(ship, missingSnapshots);
  const remainingSnapshots = missingSnapshots.filter((snapshot) => {
    if (getCachedModalProfile(ship.identity.code, state.activeConfig, snapshot)) return false;
    if (getCachedModalProfilePromise(ship.identity.code, state.activeConfig, snapshot)) return false;
    return true;
  });
  if (!remainingSnapshots.length) return staticProfiles;

  const query = new URLSearchParams({
    server: state.dataServer,
    lang: state.language,
    code: ship.identity.code,
    config: state.activeConfig,
  });
  remainingSnapshots.forEach((snapshot) => {
    query.append("selected", modalSelectedCsv(snapshot));
  });

  const batchPromise = fetch(`/api/ship-profile-batch?${query.toString()}`, { cache: "no-store" })
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`Failed to load /api/ship-profile-batch for ${ship.identity.code}`);
      }
      const payload = await response.json();
      const profiles = payload.profiles || {};
      remainingSnapshots.forEach((snapshot) => {
        const key = modalProfileCacheKey(ship.identity.code, state.activeConfig, snapshot);
        const profile = profiles[key];
        if (profile) {
          setCachedModalProfile(ship.identity.code, state.activeConfig, snapshot, profile);
        }
      });
      return { ...staticProfiles, ...profiles };
    });

  remainingSnapshots.forEach((snapshot) => {
    const perSnapshot = batchPromise
      .then((profiles) => profiles[modalProfileCacheKey(ship.identity.code, state.activeConfig, snapshot)] || null)
      .finally(() => {
        setCachedModalProfilePromise(ship.identity.code, state.activeConfig, snapshot, null);
      });
    setCachedModalProfilePromise(ship.identity.code, state.activeConfig, snapshot, perSnapshot);
  });

  return batchPromise;
}

function modalPrefetchSnapshots(ship) {
  const base = defaultModalSelections(ship);
  const groups = [...(ship?.module_options || [])];
  const priority = {
    Hull: 0,
    Artillery: 1,
    Suo: 2,
    Torpedoes: 3,
    Sonar: 4,
    Engine: 5,
  };
  groups.sort((a, b) => (priority[a.category] ?? 99) - (priority[b.category] ?? 99));
  const snapshots = [];
  groups.forEach((group) => {
    (group.options || []).forEach((option) => {
      if (!option?.upgrade_id) return;
      const snapshot = {
        ...base,
        [group.category]: option.upgrade_id,
      };
      snapshots.push(snapshot);
    });
  });
  const unique = new Map();
  snapshots.forEach((snapshot) => {
    unique.set(modalProfileCacheKey(ship.identity.code, state.activeConfig, snapshot), snapshot);
  });
  return [...unique.values()];
}

function scheduleModalProfilePrefetch(ship) {
  if (!ship) return;
  const snapshots = modalPrefetchSnapshots(ship);
  if (!snapshots.length) return;
  const runner = async () => {
    if (state.activeModalShipCode !== ship.identity.code) return;
    try {
      await loadModalProfilesBatch(ship, snapshots);
    } catch (_) {
      // Ignore background warmup failures; interactive clicks will surface errors.
    }
  };
  if (typeof window.requestIdleCallback === "function") {
    window.requestIdleCallback(() => {
      runner();
    }, { timeout: 800 });
  } else {
    window.setTimeout(() => {
      runner();
    }, 50);
  }
}

async function copyTextToClipboard(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return true;
  }
  const input = document.createElement("textarea");
  input.value = text;
  input.setAttribute("readonly", "");
  input.style.position = "fixed";
  input.style.opacity = "0";
  document.body.appendChild(input);
  input.select();
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } finally {
    input.remove();
  }
  return copied;
}

function renderShipModal(code) {
  hideFloatingTableHover();
  const ship = state.ships.find((item) => item.identity.code === code);
  if (!ship) return;
  const activeShip = modalShipView(ship);
  const compareSecondaryShip = state.modalCompare.enabled && state.modalCompare.secondaryCode
    ? state.ships.find((item) => item.identity.code === state.modalCompare.secondaryCode)
    : null;
  const tabs = modalTabsForShips(ship, compareSecondaryShip);

  if (!tabs.some(([key]) => key === state.activeModalTab)) {
    state.activeModalTab = "summary";
  }

  const modalName = shipModalDisplayName(ship);
  const compareMode = state.modalCompare.enabled ? modalCompareMode() : null;
  const modalIntroContent = compareMode === "inline"
    ? renderModalCompareHero(ship, compareSecondaryShip)
    : compareMode === "separate"
      ? ""
      : renderModalSingleIntro(ship);
  const modalBodyContent = compareMode === "separate"
    ? renderModalCompareSeparateLayout(ship, compareSecondaryShip, tabs)
    : `${renderModalTabs(tabs)}
      <div class="modal-panel modal-panel-single">
        <div class="modal-panel-body" id="modal-panel-body">
          ${compareMode === "inline" ? renderModalCompareLayout(ship, compareSecondaryShip) : renderModalTabContent(activeShip, state.activeModalTab)}
        </div>
      </div>`;
  const compareOneActive = compareMode === "inline";
  els.modal.classList.toggle("modal-compare-active", !!state.modalCompare.enabled);
  els.modal.classList.toggle("modal-compare-separate-active", compareMode === "separate");
  els.modalContent.innerHTML = `
    <div class="modal-sticky-title" id="modal-title">
      <span>${escapeHtml(modalName)}</span>
      <div class="modal-title-actions">
        <button type="button" class="modal-share-button" data-copy-ship-link title="${escapeHtml(t("modal.copyShipLink", "Copy ship link"))}" aria-label="${escapeHtml(t("modal.copyShipLink", "Copy ship link"))}">Link</button>
        <button type="button" class="modal-share-button ${compareOneActive ? "active" : ""}" data-modal-compare-start="inline" title="${escapeHtml(t("modal.compare", "Compare"))}" aria-label="${escapeHtml(t("modal.compare", "Compare"))}">${escapeHtml(t("modal.compare", "Compare"))}</button>
      </div>
    </div>
    ${modalIntroContent}
    ${state.modalProfileError ? `<div class="modal-profile-error">${escapeHtml(state.modalProfileError)}</div>` : ""}
    ${modalBodyContent}
    `;
  bindShipAngleInteractions(els.modalContent);
  bindShellChartZoomInteractions(els.modalContent);
  bindShellDispersionShotInputs();
  alignModalCompareRows();
  requestAnimationFrame(alignModalCompareRows);
  applyModalCompareHighlights();
  els.modalContent.querySelectorAll("[data-module-upgrade]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      const shipCode = button.dataset.shipCode || code;
      const category = button.dataset.moduleCategory;
      const upgradeId = button.dataset.moduleUpgrade;
      if (!shipCode || !category || !upgradeId) return;
      await selectModalModule(shipCode, category, upgradeId);
    });
  });
  els.modalContent.querySelectorAll(".modal-range-button[data-modal-range-group]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const group = button.dataset.modalRangeGroup;
      const step = Number(button.dataset.modalRangeStep || 0);
      const min = Number(button.dataset.modalRangeMin || 1);
      const max = Number(button.dataset.modalRangeMax || min);
      const current = state.modalParameterRanges[group] ?? min;
      state.modalParameterRanges[group] = clamp(current + step, min, max);
      renderShipModal(code);
    });
  });
  els.modalContent.querySelectorAll("[data-modal-tab]").forEach((button) => {
    button.onclick = (event) => {
      event.preventDefault();
      event.stopPropagation();
      const nextTab = button.dataset.modalTab;
      if (!nextTab || nextTab === state.activeModalTab) return;
      state.activeModalTab = nextTab;
      renderShipModal(code);
    };
  });
  els.modalContent.querySelectorAll("[data-modal-compare-start]").forEach((compareStartButton) => {
    compareStartButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      state.modalCompare.enabled = true;
      state.modalCompare.mode = "inline";
      if (state.modalCompare.secondaryCode === code) state.modalCompare.secondaryCode = null;
      if (!state.modalCompare.secondaryCode) {
        beginModalComparePick("secondary");
        return;
      }
      renderShipModal(code);
      syncActiveModalShareRoute();
    });
  });
  els.modalContent.querySelectorAll("[data-modal-compare-select]").forEach((compareSelect) => {
    compareSelect.addEventListener("change", (event) => {
      const slot = compareSelect.dataset.modalCompareSelect;
      const nextCode = event.target.value || null;
      if (slot === "primary" && nextCode && nextCode !== code) {
        openShipModal(nextCode, {
          compareState: {
            enabled: true,
            mode: modalCompareMode(),
            secondaryCode: state.modalCompare.secondaryCode === nextCode ? null : state.modalCompare.secondaryCode,
          },
        });
        return;
      }
      if (slot === "secondary") {
        state.modalCompare.secondaryCode = nextCode && nextCode !== code ? nextCode : null;
      }
      renderShipModal(code);
      syncActiveModalShareRoute();
    });
  });
  els.modalContent.querySelectorAll("[data-modal-compare-pick]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      beginModalComparePick(button.dataset.modalComparePick);
    });
  });
  const compareHighlight = els.modalContent.querySelector("[data-modal-compare-highlight]");
  if (compareHighlight) {
    compareHighlight.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      state.modalCompareHighlight = !state.modalCompareHighlight;
      renderShipModal(code);
    });
  }
  const compareClose = els.modalContent.querySelector("[data-modal-compare-close]");
  if (compareClose) {
    compareClose.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      resetModalCompare();
      renderShipModal(code);
      syncActiveModalShareRoute();
    });
  }
  els.modalContent.querySelectorAll("[data-shell-chart-compare-pick]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      beginShellChartComparePick(button.dataset.shellChartComparePick);
    });
  });
  els.modalContent.querySelectorAll("[data-shell-chart-compare-remove]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const removeCode = button.dataset.shellChartCompareRemove;
      state.modalChartCompareCodes = state.modalChartCompareCodes.filter((item) => item !== removeCode);
      renderShipModal(code);
    });
  });
  els.modalContent.querySelectorAll("[data-modal-nav]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const nextCode = button.dataset.modalNav;
      if (!nextCode) return;
      openShipModal(nextCode);
    });
  });
  const copyButton = els.modalContent.querySelector("[data-copy-ship-link]");
  if (copyButton) {
    copyButton.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      const url = new URL(modalSharePath(ship.identity.code), window.location.origin).toString();
      const copied = await copyTextToClipboard(url).catch(() => false);
      copyButton.textContent = copied ? t("common.copied", "Copied") : t("modal.copyFailed", "Copy failed");
      window.setTimeout(() => {
        copyButton.textContent = "Link";
      }, 1600);
    });
  }
  els.modal.classList.remove("hidden");
  updateModalStickyTitleHeight();
}

function openShipModal(code, options = {}) {
  const ship = state.ships.find((item) => item.identity.code === code);
  if (!ship) return;
  const nextCompareState = options.compareState && options.compareState.enabled
    ? {
      enabled: true,
      mode: "inline",
      secondaryCode: options.compareState.secondaryCode && options.compareState.secondaryCode !== code ? options.compareState.secondaryCode : null,
    }
    : null;
  if (typeof window.mkAnalyticsTrack === "function") {
    window.mkAnalyticsTrack("ship_open", {
      shipCode: ship.identity.code,
      shipName: shipModalDisplayName(ship),
    });
  }
  if (options.updateRoute !== false && state.routeReady && !state.applyingRoute) {
    const current = `${window.location.pathname}${window.location.search}`;
    if (!current.startsWith("/ship/")) {
      state.previousRouteBeforeModal = current;
    }
    const next = shipSharePath(ship, {
      compareCode: nextCompareState?.secondaryCode,
      compareMode: nextCompareState?.secondaryCode ? nextCompareState.mode : null,
    });
    if (next !== current) {
      window.history.pushState({}, "", next);
    }
  }
  if (options.fromRoute) {
    state.previousRouteBeforeModal = null;
  }
  state.activeModalShipCode = code;
  state.activeModalTab = options.activeTab || "summary";
  resetModalCompare();
  state.modalChartCompareCodes = Array.isArray(options.chartCompareCodes) ? [...options.chartCompareCodes] : [];
  if (nextCompareState) state.modalCompare = nextCompareState;
  state.modalParameterRanges = {};
  state.modalSelectedUpgrades = defaultModalSelections(ship);
  state.modalProfileOverride = getCachedModalProfile(code, state.activeConfig, state.modalSelectedUpgrades) || null;
  state.modalProfileError = null;
  state.modalProfileRequestSeq += 1;
  renderShipModal(code);
  if (!state.modalProfileOverride) {
    loadModalProfilesBatch(ship, [state.modalSelectedUpgrades, ...modalPrefetchSnapshots(ship)])
      .then((profile) => {
        if (state.activeModalShipCode !== code) return;
        const resolved = getCachedModalProfile(code, state.activeConfig, state.modalSelectedUpgrades);
        if (resolved) {
          state.modalProfileOverride = resolved;
          renderShipModal(code);
        }
      })
      .catch(() => {});
  }
  scheduleModalProfilePrefetch(ship);
}

function closeModal() {
  closeShipAngleZoom();
  closeShellChartZoom();
  hideFloatingTableHover();
  hideShellChartTooltip();
  els.modal.classList.add("hidden");
  els.modal.classList.remove("modal-compare-active");
  els.modal.classList.remove("modal-compare-separate-active");
  state.activeModalShipCode = null;
  resetModalCompare();
  state.modalChartCompareCodes = [];
  state.modalComparePick = null;
  renderComparePickBanner();
  state.modalParameterRanges = {};
  state.modalSelectedUpgrades = {};
  state.modalProfileOverride = null;
  state.modalProfileError = null;
  state.modalProfileRequestSeq += 1;
  state.modalProfilePromiseCache = {};
  if (state.routeReady && !state.applyingRoute && window.location.pathname.toLowerCase().startsWith("/ship/")) {
    const fallback = state.previousRouteBeforeModal || "/";
    state.previousRouteBeforeModal = null;
    window.history.replaceState({}, "", fallback);
  }
}

function resetDatasetScopedCaches() {
  closeModal();
  state.hardpoints = { main: {}, secondary: {}, torpedo: {} };
  state.hardpointsLoaded = false;
  state.hardpointsLoadingPromise = null;
  state.modalProfileCache = {};
  state.modalProfilePromiseCache = {};
  state.modalProfileOverride = null;
  state.modalProfileError = null;
  state.modalProfileRequestSeq += 1;
  state.loadedConfigProfiles = new Set();
  state.configProfilePromiseCache = {};
}

async function loadDataset() {
  await Promise.all([
    loadShips(),
    loadVersionHighlights(),
  ]);
  startHardpointsLoad();
  scheduleConfigProfileWarmup("stock");
}

async function fetchOptionalHardpointFile(filename, server = state.dataServer) {
  const urls = [
    `/data/${encodeURIComponent(server)}/hardpoints/${filename}?v=${DATA_VERSION}`,
    `/data/hardpoints/${filename}?v=${DATA_VERSION}`,
  ];
  for (const url of urls) {
    const response = await fetch(url);
    if (response.ok) return response.json();
    if (response.status !== 404) {
      throw new Error(`Failed to load ${url}`);
    }
  }
  return {};
}

async function loadHardpoints(server = state.dataServer, options = {}) {
  if (options.showStatus) {
    setLoadingStatus(localizedLoadingStatus("loading.hardpoints", "Downloading {server} hardpoint maps...", {
      server: serverDisplayName(server),
    }));
  }
  const specs = [
    ["main", "MainBattery.json"],
    ["secondary", "Secondary.json"],
    ["torpedo", "Torpedo.json"],
  ];
  const entries = await Promise.all(specs.map(async ([kind, filename]) => {
    const payload = await fetchOptionalHardpointFile(filename, server);
    return [kind, normalizeHardpointPayload(payload)];
  }));
  return withHardpointLayouts(Object.fromEntries(entries));
}

function startHardpointsLoad(options = {}) {
  if (state.hardpointsLoaded) return Promise.resolve(state.hardpoints);
  if (state.hardpointsLoadingPromise) return state.hardpointsLoadingPromise;
  const server = state.dataServer;
  state.hardpointsLoadingPromise = loadHardpoints(server, { showStatus: options.showStatus === true })
    .then((hardpoints) => {
      if (state.dataServer !== server) return hardpoints;
      state.hardpoints = hardpoints;
      state.hardpointsLoaded = true;
      state.hardpointsLoadingPromise = null;
      if (state.activeModalShipCode) {
        renderShipModal(state.activeModalShipCode);
      }
      return hardpoints;
    })
    .catch((error) => {
      if (state.dataServer === server) {
        state.hardpointsLoadingPromise = null;
        console.warn("Failed to load hardpoint maps", error);
      }
      return null;
    });
  return state.hardpointsLoadingPromise;
}

function configProfileCacheKey(server, language, config) {
  return `${server}:${language}:${config}`;
}

function scheduleConfigProfileWarmup(config) {
  if (config !== "stock") return;
  const run = () => {
    loadConfigProfiles(config, { silent: true }).catch((error) => {
      console.warn(`Failed to warm ${config} profiles`, error);
    });
  };
  if (typeof window.requestIdleCallback === "function") {
    window.requestIdleCallback(run, { timeout: 6000 });
  } else {
    window.setTimeout(run, 2000);
  }
}

async function loadConfigProfiles(config, options = {}) {
  if (config !== "stock") return;
  const requestServer = state.dataServer;
  const requestLanguage = state.language;
  const cacheKey = configProfileCacheKey(requestServer, requestLanguage, config);
  if (state.loadedConfigProfiles.has(cacheKey)) return;
  await loadStaticConfigProfilesData(requestServer, requestLanguage, config);
  const staticProfilesPayload = staticConfigProfilesPayload(requestServer, requestLanguage, config);
  if (staticProfilesPayload) {
    if (!options.silent) {
      setLoadingStatus(localizedLoadingStatus("loading.applyingProfiles", "Applying ship profiles..."));
    }
    const profiles = staticProfilesPayload.profiles || {};
    state.ships.forEach((ship) => {
      const profile = profiles[ship.identity.code];
      if (!profile) return;
      ship.profiles = {
        ...(ship.profiles || {}),
        [config]: profile,
      };
    });
    state.loadedConfigProfiles.add(cacheKey);
    return;
  }
  if (state.configProfilePromiseCache[cacheKey]) {
    if (!options.silent) {
      setLoadingStatus(localizedLoadingStatus("loading.stockProfilesDownload", "Downloading {server} {config} profiles...", {
        server: serverDisplayName(requestServer),
        config,
      }));
    }
    return state.configProfilePromiseCache[cacheKey];
  }
  if (!options.silent) {
    setLoadingStatus(localizedLoadingStatus("loading.stockProfilesDownload", "Downloading {server} {config} profiles...", {
      server: serverDisplayName(requestServer),
      config,
    }));
  }
  const query = new URLSearchParams({
    server: requestServer,
    lang: requestLanguage,
    config,
    v: DATA_VERSION,
  });
  const promise = (async () => {
    const response = await fetch(`/api/catalog-profiles?${query.toString()}`);
    if (!response.ok) {
      throw new Error(`Failed to load ${config} profiles`);
    }
    if (!options.silent) {
      setLoadingStatus(localizedLoadingStatus("loading.applyingProfiles", "Applying ship profiles..."));
    }
    const payload = await response.json();
    if (state.dataServer !== requestServer || state.language !== requestLanguage) return;
    const profiles = payload.profiles || {};
    state.ships.forEach((ship) => {
      const profile = profiles[ship.identity.code];
      if (!profile) return;
      ship.profiles = {
        ...(ship.profiles || {}),
        [config]: profile,
      };
    });
    state.loadedConfigProfiles.add(cacheKey);
  })().finally(() => {
    delete state.configProfilePromiseCache[cacheKey];
  });
  state.configProfilePromiseCache[cacheKey] = promise;
  return promise;
}

async function switchDataServer(nextServer, options = {}) {
  const next = normalizeDataServer(nextServer);
  if (next === state.dataServer) return;
  const previous = state.dataServer;
  state.dataServer = next;
  if (els.dataServer) els.dataServer.value = next;
  renderGameVersion();
  resetDatasetScopedCaches();
  showLoading(localizedLoadingStatus("loading.catalog", "Loading {server} catalog...", {
    server: serverDisplayName(next),
  }));

  try {
    await loadDataset();
    renderAppState();
    syncRoute({ replace: options.replace ?? false });
  } catch (error) {
    state.dataServer = previous;
    if (els.dataServer) els.dataServer.value = previous;
    renderGameVersion();
    renderAppState();
    window.alert(`Failed to load ${next === "test" ? "Test" : "Live"} data: ${error.message}`);
  } finally {
    hideLoading();
    configureAdSensePlacements();
  }
}

async function switchLanguage(nextLanguage, options = {}) {
  const next = normalizeLanguage(nextLanguage);
  if (next === state.language) return;
  const previous = state.language;
  state.language = next;
  rememberLanguage(next);
  if (els.uiLanguage) els.uiLanguage.value = next;
  resetDatasetScopedCaches();
  showLoading(localizedLoadingStatus("loading.catalog", "Loading {server} catalog...", {
    server: serverDisplayName(),
  }));

  try {
    await loadUiLocale(next);
    showLoading(localizedLoadingStatus("loading.catalog", "Loading {server} catalog...", {
      server: serverDisplayName(),
    }));
    await loadDataset();
    renderAppState();
    syncRoute({ replace: options.replace ?? false });
  } catch (error) {
    state.language = previous;
    rememberLanguage(previous);
    if (els.uiLanguage) els.uiLanguage.value = previous;
    try {
      await loadUiLocale(previous);
    } catch (_) {
      state.uiText = {};
    }
    renderAppState();
    window.alert(`Failed to load language data: ${error.message}`);
  } finally {
    hideLoading();
    configureAdSensePlacements();
  }
}

function setParameterExtremeHighlight(enabled) {
  state.parameterExtremeHighlight = !!enabled;
  renderSettingsControls();
  if (state.activeMainTab === "parameters") {
    renderParameterSection();
  }
}

async function switchDebugShips(enabled, options = {}) {
  const next = !!enabled;
  if (next === state.debugShips) return;
  const previous = state.debugShips;
  const selectedAllBaseGroups = GROUP_FILTERS.every((value) => state.filters.groups.has(value));
  state.debugShips = next;
  renderSettingsControls();
  resetDatasetScopedCaches();
  showLoading(localizedLoadingStatus("loading.catalog", "Loading {server} catalog...", {
    server: serverDisplayName(),
  }));

  try {
    await loadDataset();
    if (next && selectedAllBaseGroups) {
      availabilityFilterValues().forEach((value) => state.filters.groups.add(value));
    }
    renderAppState();
    syncRoute({ replace: options.replace ?? false });
  } catch (error) {
    state.debugShips = previous;
    renderSettingsControls();
    resetDatasetScopedCaches();
    await loadDataset();
    renderAppState();
    window.alert(`Failed to switch debug ships: ${error.message}`);
  } finally {
    hideLoading();
    configureAdSensePlacements();
  }
}

async function handlePopState() {
  state.applyingRoute = true;
  try {
    const nextServer = routeDataServer();
    const nextLanguage = routeLanguage();
    const nextDebugShips = routeDebugShips();
    if (nextServer !== state.dataServer || nextLanguage !== state.language || nextDebugShips !== state.debugShips) {
      state.dataServer = nextServer;
      state.language = nextLanguage;
      state.debugShips = nextDebugShips;
      if (els.dataServer) els.dataServer.value = nextServer;
      if (els.uiLanguage) els.uiLanguage.value = nextLanguage;
      renderSettingsControls();
      await loadUiLocale(nextLanguage);
      renderGameVersion();
      resetDatasetScopedCaches();
      showLoading(localizedLoadingStatus("loading.catalog", "Loading {server} catalog...", {
        server: serverDisplayName(nextServer),
      }));
      await loadDataset();
      hideLoading();
    }
    applyRouteFromLocation();
    renderAppState();
  } catch (error) {
    renderFatalLoadError(error);
  } finally {
    state.applyingRoute = false;
  }
}

function markFatalErrorNoIndex() {
  let robotsMeta = document.querySelector("meta[name='robots']");
  if (!robotsMeta) {
    robotsMeta = document.createElement("meta");
    robotsMeta.setAttribute("name", "robots");
    document.head.appendChild(robotsMeta);
  }
  robotsMeta.setAttribute("content", "noindex, nofollow");
}

function renderFatalLoadError(error) {
  console.error("MK Tool failed to load", error);
  hideLoading();
  markFatalErrorNoIndex();
  document.body.innerHTML = `
    <main class="app-shell">
      <div class="empty-panel">${escapeHtml(t("error.loadFailed", "Failed to load ship data. Please refresh the page."))}</div>
    </main>
  `;
}

function bindEvents() {
  if (els.modalClose) els.modalClose.textContent = "x";
  if (els.homeLink) els.homeLink.addEventListener("click", () => setMainTab("home"));
  if (els.settingsToggle) {
    els.settingsToggle.addEventListener("click", () => {
      setSettingsPanelOpen(!settingsPanelIsOpen());
    });
  }
  if (els.settingsClose) {
    els.settingsClose.addEventListener("click", () => setSettingsPanelOpen(false));
  }
  if (els.uiLanguage) els.uiLanguage.addEventListener("change", () => {
    switchLanguage(els.uiLanguage.value);
  });
  if (els.dataServer) els.dataServer.addEventListener("change", () => {
    switchDataServer(els.dataServer.value);
  });
  if (els.themeToggle) els.themeToggle.addEventListener("click", () => {
    applyTheme(state.theme === "dark" ? "light" : "dark", { remember: true });
  });
  if (els.parameterExtremeToggle) {
    els.parameterExtremeToggle.addEventListener("click", () => {
      setParameterExtremeHighlight(!state.parameterExtremeHighlight);
    });
  }
  if (els.debugShipsToggle) {
    els.debugShipsToggle.addEventListener("click", () => {
      switchDebugShips(!state.debugShips);
    });
  }
  els.tabButtons.forEach((button) => button.addEventListener("click", () => setMainTab(button.dataset.tab)));
  els.globalSearch.addEventListener("input", (event) => {
    state.globalSearch = event.target.value.trim();
    renderGlobalSearchResults();
  });
  els.globalSearch.addEventListener("focus", () => {
    renderGlobalSearchResults();
  });
  els.globalSearch.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      hideGlobalSearchResults();
      els.globalSearch.blur();
      return;
    }
    if (event.key !== "Enter") return;
    event.preventDefault();
    openGlobalSearchMatch();
  });
  document.addEventListener("pointerdown", (event) => {
    if (!els.globalSearchResults || !els.globalSearch) return;
    if (els.globalSearch.contains(event.target) || els.globalSearchResults.contains(event.target)) return;
    hideGlobalSearchResults();
  });
  document.addEventListener("pointerdown", (event) => {
    if (!settingsPanelIsOpen() || !els.settingsPanel || !els.settingsToggle) return;
    if (els.settingsPanel.contains(event.target) || els.settingsToggle.contains(event.target)) return;
    setSettingsPanelOpen(false);
  });
  els.parameterOutput.addEventListener("click", handleParameterOutputClick);
  els.parameterOutput.addEventListener("pointerover", handleParameterOutputPointerOver);
  els.parameterOutput.addEventListener("pointerout", handleParameterOutputPointerOut);
  els.nationTree.addEventListener("pointerover", handleNationTreePointerOver);
  els.nationTree.addEventListener("pointerout", handleNationTreePointerOut);
  els.modalContent.addEventListener("pointerover", handleModalPointerOver);
  els.modalContent.addEventListener("pointerout", handleModalPointerOut);
  els.modalContent.addEventListener("pointermove", handleShellChartPointerMove);
  els.modalContent.addEventListener("pointerleave", hideShellChartTooltip);
  els.pickModeButtons.forEach((button) => button.addEventListener("click", () => {
    state.activePickMode = button.dataset.pickMode;
    renderPickMode();
    refreshParameterView();
  }));
  if (els.pickJoinToggle) {
    els.pickJoinToggle.addEventListener("click", () => {
      state.pickJoinMode = state.pickJoinMode === "and" ? "or" : "and";
      renderPickMode();
      refreshParameterView();
    });
  }
  els.configRadios.forEach((radio, index) => {
    radio.checked = index === 1;
    radio.addEventListener("change", async () => {
      const nextConfig = index === 0 ? "stock" : "upgraded";
      const previousConfig = state.activeConfig;
      state.activeConfig = nextConfig;
      if (nextConfig === "stock") {
        showLoading(localizedLoadingStatus("loading.stockProfiles", "Loading {server} stock profiles...", {
          server: serverDisplayName(),
        }));
        try {
          await loadConfigProfiles(nextConfig);
        } catch (error) {
          state.activeConfig = previousConfig;
          els.configRadios.forEach((item, radioIndex) => {
            item.checked = state.activeConfig === (radioIndex === 0 ? "stock" : "upgraded");
          });
          window.alert(error.message);
        } finally {
          hideLoading();
        }
      }
      refreshParameterView();
    });
  });
  els.tierMin.addEventListener("input", (event) => {
    updateTierMinFromInput(event.target.value);
    refreshFilterAndParameterViewThrottled();
  });
  els.tierMax.addEventListener("input", (event) => {
    updateTierMaxFromInput(event.target.value);
    refreshFilterAndParameterViewThrottled();
  });
  els.tierMinDown?.addEventListener("click", () => {
    adjustTierMin(-1);
    refreshFilterAndParameterViewThrottled();
  });
  els.tierMaxUp?.addEventListener("click", () => {
    adjustTierMax(1);
    refreshFilterAndParameterViewThrottled();
  });
  els.selectSearch.addEventListener("input", (event) => {
    state.selectSearch = event.target.value.trim();
    renderSelectPane();
  });
  els.selectSearch.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const first = matchingSelectShips()[0];
    if (first) addShipToSelection(first.identity.code);
  });
  els.addVisible.addEventListener("click", () => {
    const first = matchingSelectShips()[0];
    if (first) addShipToSelection(first.identity.code);
  });
  els.clearSelected.addEventListener("click", () => {
    state.selectedCodes.clear();
    renderSelectPane();
    refreshParameterView();
  });
  document.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const button = target?.closest(".jump-pill[data-jump]");
    if (!button) return;
    const section = document.getElementById(nationSectionIdForJump(button.dataset.jump));
    section?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  document.querySelectorAll("[data-close='modal']").forEach((node) => node.addEventListener("click", closeModal));
  els.modalClose.addEventListener("click", closeModal);
  els.modalContent.addEventListener("click", async (event) => {
    const tabButton = event.target.closest("[data-modal-tab]");
    if (tabButton) {
      state.activeModalTab = tabButton.dataset.modalTab;
      if (state.activeModalShipCode) renderShipModal(state.activeModalShipCode);
      return;
    }

    const navButton = event.target.closest("[data-modal-nav]");
    if (navButton) {
      openShipModal(navButton.dataset.modalNav);
      return;
    }

    const moduleButton = event.target.closest("[data-module-upgrade]");
    if (moduleButton && state.activeModalShipCode) return;
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      setSettingsPanelOpen(false);
      closeModal();
    }
  });
  window.addEventListener("resize", () => {
    updateModalStickyTitleHeight();
    if (state.activeMainTab === "nation" && state.activeNation) renderNationView();
  });
  window.addEventListener("popstate", () => {
    handlePopState();
  });
}

async function loadShips() {
  const previousNation = state.activeNation;
  const query = new URLSearchParams({
    server: state.dataServer,
    lang: state.language,
    v: DATA_VERSION,
  });
  const catalogUrl = `/api/catalog?${query.toString()}`;
  await loadStaticCatalogData(state.dataServer, state.language);
  const staticPayload = staticCatalogPayload(state.dataServer, state.language);
  const payload = staticPayload || await fetchJsonWithLoadingProgress(catalogUrl, {
    status: localizedLoadingStatus("loading.downloadingCatalog", "Downloading {server} catalog...", {
      server: serverDisplayName(),
    }),
    parseStatus: localizedLoadingStatus("loading.buildingShipList", "Building ship list..."),
    errorMessage: `Failed to load ${catalogUrl}`,
  });
  if (staticPayload) {
    setLoadingStatus(localizedLoadingStatus("loading.buildingShipList", "Building ship list..."));
  }
  state.loadedConfigProfiles = new Set();
  state.configProfilePromiseCache = {};
  state.ships = (payload.ships || [])
    .filter((ship) => isDisplayableShip(ship))
    .map((ship) => enrichShip({ ...ship, profiles: ship.profiles || {} }));
  const nations = getNations();
  state.activeNation = nations.includes(previousNation) ? previousNation : nations[0] || null;
  const availabilityValues = availabilityFilterValues();
  state.filters.groups = new Set([...state.filters.groups].filter((value) => availabilityValues.includes(value)));
  const classes = getClasses();
  state.filters.classes = new Set([...state.filters.classes].filter((value) => classes.includes(value)));
  state.filters.nations = new Set([...state.filters.nations].filter((value) => nations.includes(value)));
  setLoadingStatus(localizedLoadingStatus("loading.preparingInterface", "Preparing interface..."));
}

async function start() {
  try {
    showLoading(localizedLoadingStatus("loading.catalog", "Loading {server} catalog...", {
      server: serverDisplayName(),
    }));
    bindEvents();
    configureSupportLinks();
    configureAdSensePlacements();
    window.addEventListener("resize", rafThrottle(configureAdSensePlacements));
    applyTheme(initialTheme());
    applyDataServerFromLocation();
    applyLanguageFromLocation();
    applyDebugShipsFromLocation();
    await loadUiLocale(state.language);
    showLoading(localizedLoadingStatus("loading.catalog", "Loading {server} catalog...", {
      server: serverDisplayName(),
    }));
    await Promise.all([
      initShellWasm(),
      loadGameVersions(),
      loadDataset(),
    ]);
    state.applyingRoute = true;
    applyRouteFromLocation();
    renderAppState();
    state.applyingRoute = false;
    state.routeReady = true;
    syncRoute({ replace: true });
    hideLoading();
    configureAdSensePlacements();
  } catch (error) {
    renderFatalLoadError(error);
  }
}

start();
