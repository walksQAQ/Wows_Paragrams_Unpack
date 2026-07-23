(function () {
  const STATIC_MODAL_PROFILES_SCRIPT = "/generated/static-modal-profiles.js?v=20260708a";
  const SUPPORT_URL = "https://ko-fi.com/mktool";
  const ADSENSE_CLIENT = "";
  const ADSENSE_PREVIEW = true;
  const ADSENSE_TEST_MODE = false;
  const ADSENSE_SLOTS = {
    "home-left": "",
    "home-right": "",
    "nation-bottom": "",
    "parameters-bottom": "",
  };
  const DATA_SERVERS = new Set(["live", "test"]);
  const DEFAULT_LANGUAGE = "en";
  const LANGUAGE_STORAGE_KEY = "mkShiptoolLanguage";
  const SUPPORTED_LANGUAGES = new Set(["en", "ru", "zh-cn", "zh-tw", "ja", "de", "es"]);
  const DEFAULT_THEME = "light";
  const THEME_STORAGE_KEY = "mkShiptoolTheme";
  const THEMES = new Set(["light", "dark"]);
  const GROUP_FILTERS = ["tech", "premium", "early", "test"];
  const CLASS_ORDER = ["Battleship", "Cruiser", "Destroyer", "Submarine", "AircraftCarrier"];
  const EXCLUDED_SHIP_CLASSES = new Set(["Auxiliary"]);
  const HIDDEN_SHIP_GROUPS = new Set(["clan", "coopOnly", "preserved", "disabled", "event"]);
  const DEBUG_AVAILABILITY_GROUPS = [
    "event",
    "disabled",
    "preserved",
    "coopOnly",
    "clan",
    "demoWithoutStats",
    "demoWithoutStatsPrem",
  ];
  const TEST_AVAILABILITY_GROUPS = new Set([
    "demoWithoutStatsPrem",
    "demoWithoutStats",
    "clan",
    "coopOnly",
    "preserved",
    "disabled",
    "event",
  ]);
  const CLASS_LABELS = {
    AircraftCarrier: "Aircraft carrier",
    Battleship: "Battleship",
    Cruiser: "Cruiser",
    Destroyer: "Destroyer",
    Submarine: "Submarine",
  };
  const SELECT_CLASS_LABELS = {
    AircraftCarrier: "CV",
    Battleship: "BB",
    Cruiser: "CA",
    Destroyer: "DD",
    Submarine: "SS",
  };
  const RANGE_DEFAULTS_KM = {
    "Main battery": 12,
    "AP Shells": 12,
    "HE Shells": 12,
    "SAP Shells": 12,
    "Secondaries": 6,
  };
  const RANGE_SELECTABLE_GROUPS = new Set(Object.keys(RANGE_DEFAULTS_KM));
  const BW_TO_METERS = 30;
  const TORPEDO_REACTION_SPEED_FACTOR = 2.686;
  const SHELL_DISPERSION_SAMPLE_COUNT = 300;
  const SHELL_DISPERSION_MIN_SHOTS = 1;
  const SHELL_DISPERSION_MAX_SHOTS = 2000;
  const SHELL_CHART_DEFAULT_MAX_KM = 30;
  const SECONDARY_GROUP_COLORS = ["#b3312c", "#1d39b8", "#087f5b", "#8a3ffc", "#c45a00", "#006d8f"];
  const SHELL_CHART_SERIES_COLORS = ["#24aeda", "#c3832c", "#8a7dff", "#28a868", "#d05ab5", "#d8a326"];
  const SHIP_ANGLE_VIEWBOX = {
    width: 390,
    height: 450,
    centerX: 195,
    sectorCenterY: 210.5,
    imageY: 56,
    imageWidth: 55.6,
    imageHeight: 285,
    sectorRadius: 173,
    secondarySectorRadius: 146,
    dotRadius: 6,
    labelY: 432,
    hardpointTopNorm: 0.08,
    hardpointBottomNorm: 0.92,
    hardpointLateralFactor: 0.62,
    secondaryLateralFactor: 0.92,
    secondaryDotRadius: 3.8,
    schematicLateralFactor: 0.82,
    hardpointLongitudinalPaddingRatio: 0.35,
    hardpointMinLongitudinalPadding: 1.0,
    hardpointLayoutXScale: 13.9,
    secondaryHardpointLayoutXScale: 24.0,
    hardpointLayoutYScale: 99,
    mainHardpointLayoutScale: 0.9,
    secondaryHardpointLayoutScale: 1.32,
    silhouetteScaleX: 1.15,
    silhouetteScaleY: 1.0,
    firepowerImageScale: 0.44,
    firepowerSampleStep: 2,
  };
  const SHIP_ANGLE_IMAGE_BOUNDS = [
    [0.003, 64, 66],
    [0.051, 45, 85],
    [0.1, 36, 94],
    [0.149, 29, 101],
    [0.2, 22, 108],
    [0.251, 17, 113],
    [0.3, 12, 118],
    [0.35, 9, 121],
    [0.401, 6, 124],
    [0.451, 4, 126],
    [0.501, 3, 127],
    [0.55, 2, 128],
    [0.601, 2, 128],
    [0.652, 2, 128],
    [0.701, 3, 127],
    [0.75, 4, 126],
    [0.801, 7, 123],
    [0.852, 10, 120],
    [0.901, 16, 114],
    [0.951, 24, 106],
    [0.997, 51, 79],
  ];
  const NATION_ROUTE_CODES = {
    Commonwealth: "C",
    Europe: "E",
    Events: "EV",
    France: "F",
    Germany: "G",
    Italy: "I",
    Japan: "J",
    Netherlands: "N",
    PanAmerica: "V",
    PanAsia: "Z",
    Spain: "S",
    UK: "B",
    USA: "A",
    USSR: "R",
  };
  const NATION_BY_ROUTE_CODE = Object.fromEntries(Object.entries(NATION_ROUTE_CODES).map(([nation, code]) => [code, nation]));
  const PARAMETER_ROUTE_CODES = {
    "General": "gnrl",
    "Survivability": "surv",
    "Diving": "dive",
    "Main battery": "mb",
    "Medium guns": "med",
    "AP Shells": "ap",
    "HE Shells": "he",
    "SAP Shells": "sap",
    "Sonar": "sonar",
    "Secondaries": "sec",
    "Torpedoes": "torp",
    "Anti-aircraft": "aa",
    "Depth charges": "dc",
    "Airstrike": "as",
    "Scouts": "scout",
    "Smoke Screen Aircraft": "ssa",
    "Escort Spotters": "esp",
    "Attack aircraft": "atk",
    "Torpedo bombers": "tb",
    "Bombers": "bomb",
    "Skip bombers": "skip",
    "Mine bombers": "mine",
    "Consumables": "con",
  };
  const PARAMETER_BY_ROUTE_CODE = Object.fromEntries(Object.entries(PARAMETER_ROUTE_CODES).map(([label, code]) => [code, label]));
  const PARAMETER_EXTREME_EXCLUDED_LABELS = new Set(["Ship", "Tier", "Class", "Year", "Combat instruction"]);
  const MODAL_COMPARE_EXTREME_EXCLUDED_LABELS = new Set([
    ...PARAMETER_EXTREME_EXCLUDED_LABELS,
    "Description",
    "Type",
    "Loaders",
    "Ricochet",
  ]);
  const PARAMETER_LOW_IS_GOOD_LABELS = new Set([
    "Detect. by sea",
    "Detect. by air",
    "Acceleration",
    "Rudder shift",
    "Turning radius",
    "Detectability",
    "Diving plane shift",
    "Depletion rate",
    "Fire duration",
    "Fire damage",
    "No of fires",
    "Flood duration",
    "Flooding damage",
    "No of floodings",
    "Reload",
    "180\u00b0 turn",
    "Hor. dispersion",
    "Ver. dispersion",
    "Flight time",
    "Drag coeff.",
    "Impact angle",
    "Reload time",
    "Fuse time",
    "Torpedo reload time",
    "Reaction time",
    "Sector time",
    "Cooldown time",
  ]);
  const CONSUMABLE_TYPE_LABELS = {
    crashCrew: "Damage con.",
    regenCrew: "Repair party",
    massHeal: "Mass heal",
    smokeScreen: "Smoke",
    smokeGenerator: "Smoke",
    rls: "Radar",
    sonar: "Hydro",
    engineBoost: "Engine boost",
    speedBoosters: "Engine boost",
    fighter: "Fighter",
    spotter: "Spotter",
    scout: "Spotter",
    boosterGunner: "MBRB",
    boosterAA: "DFAA",
    airDefenseDisp: "DFAA",
    artilleryBoosters: "MBRB",
    torpedoReloader: "TRB",
    callFighters: "Fighter",
    fastRudders: "Enhanced rudder",
    reserveBattery: "Res. Unit",
    reserveBatteryUnit: "Res. Unit",
    weaponReloadBooster: "Res. Unit",
    diveCapacity: "Dive cap.",
    submarineRls: "Sub radar",
  };

  globalThis.MKShipConstants = {
    ADSENSE_CLIENT,
    ADSENSE_PREVIEW,
    ADSENSE_SLOTS,
    ADSENSE_TEST_MODE,
    BW_TO_METERS,
    CLASS_LABELS,
    CLASS_ORDER,
    CONSUMABLE_TYPE_LABELS,
    DATA_SERVERS,
    DEBUG_AVAILABILITY_GROUPS,
    DEFAULT_LANGUAGE,
    DEFAULT_THEME,
    EXCLUDED_SHIP_CLASSES,
    GROUP_FILTERS,
    HIDDEN_SHIP_GROUPS,
    LANGUAGE_STORAGE_KEY,
    MODAL_COMPARE_EXTREME_EXCLUDED_LABELS,
    NATION_BY_ROUTE_CODE,
    NATION_ROUTE_CODES,
    PARAMETER_BY_ROUTE_CODE,
    PARAMETER_EXTREME_EXCLUDED_LABELS,
    PARAMETER_LOW_IS_GOOD_LABELS,
    PARAMETER_ROUTE_CODES,
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
    SUPPORTED_LANGUAGES,
    TEST_AVAILABILITY_GROUPS,
    THEME_STORAGE_KEY,
    THEMES,
    TORPEDO_REACTION_SPEED_FACTOR,
  };
}());

