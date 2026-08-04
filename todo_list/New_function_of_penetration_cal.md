# 穿深/散布计算器 — 功能规划文档

> 目标：为现有软件添加一个"穿深/散布计算器"按钮，弹出独立计算界面，基本复刻浩舰 (iwarship.net/wowsdb/dap) 的散布、穿深、落弹时间等计算逻辑。同时让原有详细信息面板可以调用部分计算公式显示穿深、散布等数据。

---

## 一、核心计算公式（来自浩舰原始源码）

以下所有公式均提取自浩舰 (iwarship.net/wowsdb/dap) 的原始 JavaScript 源码文件：
- `dap.js` — 散布计算、图表绘制、UI逻辑
- `calculator.js` (V2) — 弹道模拟 + 穿深计算（JS版本）
- `calculator3.js` (V3) — 调用后端 API 获取弹速数据后计算穿深

### 1. 弹道模拟 + 穿深计算（浩舰 calculator.js V2 原始代码）

```javascript
// ========== 浩舰 calculator.js 完整原始代码 ==========
// 参数：m=弹重(kg), D=口径(m), c_D=空气阻力系数, v_0=初速(m/s), K=Krupp, norm=转正角(°)
function calculator(m, D, c_D, v_0, K, norm) {
    // ---- 常量定义 ----
    C = 0.5561613;          // 穿深常数
    g = 9.81;               // 重力加速度 m/s²
    T_0 = 288;              // 海平面温度 K
    L = 0.0065;             // 温度递减率 K/m
    p_0 = 101325;           // 海平面气压 Pa
    R = 8.31447;            // 气体常数 J/(mol·K)
    M = 0.0289644;          // 空气摩尔质量 kg/mol
    cw_1 = 1;               // 空气阻力一次项系数
    cw_2 = 100 + 1000/3 * D; // 空气阻力二次项系数（与口径相关）
    C_pen = C * K / 2400;   // 穿深系数
    k = 0.5 * c_D * (D/2) * (D/2) * Math.PI / m;  // 弹道系数

    n_angle = 200;                      // 角度迭代数
    step_angle = 45 * Math.PI / 180 / n_angle;  // 每步角度增量 rad

    // ---- 弹头转正角默认值 ----
    if (norm == null) {
        if (D <= 0.13) { norm = 10; }      // ≤130mm: 10°
        else if (D <= 0.152) { norm = 8.5; } // ≤152mm: 8.5°
        else if (D <= 0.22) { norm = 7; }    // ≤220mm: 7°
        else { norm = 6; }                   // >220mm: 6°
    }
    norm = norm * Math.PI / 180;  // 转正角转换为弧度

    // ---- 遍历 200 个发射角计算弹道 ----
    var alpha = [];     // 发射角数组 rad
    var distance = [];  // 水平射程 m
    var armor_vert = []; // 垂直穿深 mm
    var armor_hori = []; // 水平穿深 mm
    var v_impact = [];  // 着速数组 m/s
    var fly_time = [];  // 飞行时间 s
    var impact_angle = []; // 落弹角 °

    for (i = 0; i < n_angle; i++) {
        alpha.push(i * step_angle);           // 发射角 0~45°
        // ...初始化数组
    }

    dt = 0.05;  // 步进时间 0.05s

    for (i = 0; i < n_angle; i++) {
        // ---- 初速度分量 ----
        v_x = v_0 * Math.cos(alpha[i]);   // 水平分速度
        v_y = v_0 * Math.sin(alpha[i]);   // 垂直分速度
        y = 0; x = 0; t = 0;

        // ---- 弹道步进积分 (while 循环直到落地 y <= 0) ----
        while (y >= -0) {
            // 位置更新
            x = x + dt * v_x;
            y = y + dt * v_y;

            // 大气模型：随高度变化的气温/气压/密度
            T = T_0 - L * y;                     // 温度随高度变化
            p = p_0 * Math.pow(T / T_0, g * M / R / L);  // 气压
            rho_g = p * M / R / T;               // 空气密度 kg/m³

            // 速度更新：阻力 + 重力
            v_x = v_x - dt * k * rho_g * (cw_1 * v_x * v_x + cw_2 * v_x);
            v_y = v_y - dt * g - dt * k * rho_g * (cw_1 * v_y * v_y + cw_2 * v_y);
            t += dt;
        }

        // ---- 着弹参数 ----
        v_imp = Math.sqrt(v_x * v_x + v_y * v_y);  // 着速 m/s

        // ---- AP穿深公式（浩舰原始公式）----
        pen_abs = K * Math.pow((m * Math.pow(v_imp, 2)), 0.69) 
                  * Math.pow(D, -1.07) * 0.0000001;
        // 等价于：pen = K * (m * V²)^0.69 * D^(-1.07) * 10^-7

        // ---- 落弹角 ----
        IA = Math.atan(Math.abs(v_y) / Math.abs(v_x));
        IA_vert_armor = Math.max(IA - norm, 0);   // 对垂直面的等效入射角
        IA_hori_armor = Math.min(IA + norm, 90);  // 对水平面的等效入射角

        // ---- 等效穿深 ----
        armor_abs = pen_abs;                         // 绝对穿深
        armor_vert[i] = pen_abs * Math.cos(IA_vert_armor);  // 垂直等效穿深
        armor_hori[i] = pen_abs * Math.sin(IA_hori_armor);  // 水平等效穿深
        distance[i] = x;
    }

    // ---- 插值到 100m 间距 ----
    // 将非均匀的弹道数据插值为每100m间隔的均匀数据
    // ...（线性插值逻辑）
    
    // ---- 飞行时间修正 ----
    // fly_time = fly_time / 3.1  （浩舰的飞行时间修正因子）

    // ---- 输出数据结构 ----
    var data_dict = {};
    data_dict.distance = [...];      // 距离 km
    data_dict.armor_abs = [...];     // 绝对穿深 mm
    data_dict.armor_vert = [...];    // 垂直穿深 mm（对装甲板等效）
    data_dict.armor_hori = [...];    // 水平穿深 mm
    data_dict.v_impact = [...];      // 着速 m/s
    data_dict.fly_time = [...];      // 飞行时间 s
    data_dict.impact_angle = [...];  // 落弹角 °
    return data_dict;
}
```

#### 核心公式总结（浩舰 V2 版本）

**穿深公式：**
$$P = K \times (m \times V^2)^{0.69} \times D^{-1.07} \times 10^{-7}$$

其中：
- $P$ = 绝对穿深 (mm)
- $K$ = Krupp 值
- $m$ = 弹重 (kg)
- $V$ = 着速 (m/s)
- $D$ = 口径 (m)

> 注意：这与简化的德马尔公式不同，浩舰使用的指数为 0.69 和 -1.07，且不直接使用口径的 0.7 次方形式。

**垂直等效穿深：**
$$P_{vert} = P \times \cos(\max(IA - norm, 0))$$

**水平等效穿深：**
$$P_{hori} = P \times \sin(\min(IA + norm, 90^\circ))$$

其中：
- $IA$ = 落弹角 (rad)
- $norm$ = 弹头转正角（≤130mm: 10°, ≤152mm: 8.5°, ≤220mm: 7°, >220mm: 6°）

**弹道步进（dt = 0.05s）：**
```
v_x -= dt * k * ρ * (cw_1 * v_x² + cw_2 * v_x)
v_y -= dt * g - dt * k * ρ * (cw_1 * v_y² + cw_2 * v_y)
x += dt * v_x
y += dt * v_y
```
其中：
- $k = 0.5 \times c_D \times (D/2)^2 \times \pi / m$ = 弹道系数
- $cw_1 = 1$, $cw_2 = 100 + 1000/3 \times D$ = 阻力系数
- $\rho$ = 空气密度（随高度变化的标准大气模型）
- $g = 9.81$ m/s²

**飞行时间修正：**
```
浩舰 V2 最终飞行时间 = 原始弹道模拟时间 / 3.1
```

---

### 2. 浩舰 V3 计算方式（调用后端 API）

```javascript
// calculator3.js - V3 版本
// 从后端 API 获取弹道数据后计算穿深

function calcV3Pen(m, D, v_imp, K) {
    // V3 穿深公式与 V2 相同
    return Math.pow(m, 0.69) * Math.pow(v_imp, 1.38) * Math.pow(D, -1.07) * K * 0.0000001;
    // 注意：m^0.69 * (v_imp^2)^0.69 = m^0.69 * v_imp^1.38
}

function calculator3(m, D, c_D, v_0, K, norm) {
    // 调用后端 API 获取弹道数据
    // GET dap/list-impact-speed?mass=m&diametr=D&airDrag=c_D&speed=v_0
    // 返回: [{dist, velocity, angle, time}, ...]
    
    // 然后使用 calcV3Pen 计算每个距离点的穿深
    // pen_abs = calcV3Pen(m, D, impactData[i].velocity, K)
    // impact_angle = Math.max(0, impactData[i].angle - norm)
    // armor_vert = pen_abs * Math.cos(impact_angle * π / 180)
    
    // 最小射程内使用第一个弹道数据点插值
}
```

---

### 3. 散布计算（浩舰 dap.js 原始代码）

#### 3.1 横向散布（水平散布）

```javascript
// ===== 浩舰 dap.js 散布计算原始代码 =====

// 散布参数来自弹药数据 dapa:
// dapa.td = 渐变距离阈值 (taperDist)
// dapa.ha = 斜率系数 (系数A)
// dapa.hb = 截距系数 (系数B)  
// dapa.vd = 垂直分割比例
// dapa.vrz = 零距离垂直系数
// dapa.vrd = 分割距离垂直系数
// dapa.vrm = 最大距离垂直系数
// dapa.sc = sigma值

// 计算渐变系数
let taperDisp = (dapa.td * dapa.ha + dapa.hb) / dapa.td;
let delimDist = dapa.vd * maxDist;  // 垂直分割距离

// 循环每 0.1km
for (let r = 0.1; r <= maxDist; r = r.add(0.1)) {
    // ---- 水平散布（浩舰原始公式）----
    let horiValue;
    if (r < dapa.td) {
        // 近距离：使用渐变系数
        horiValue = (r * taperDisp * dispCoeff).maxFixed(1);
    } else {
        // 正常距离：线性公式
        horiValue = ((r * dapa.ha + dapa.hb) * dispCoeff).maxFixed(1);
    }
    hori.push(horiValue);  // 水平散布 (m)

    // ---- 垂直散布 ----
    // 垂直系数：三段线性插值
    vertCoeff = r < delimDist ?
        (dapa.vrz + (dapa.vrd - dapa.vrz) * (r / delimDist)) :
        (dapa.vrd + (dapa.vrm - dapa.vrd) * (r - delimDist) / (maxDist - delimDist));

    // 根据设置选项进行三角函数修正
    let hoopScale = 1;
    if (dapSettings.hoopType == 1) {
        // 方式1：使用 sin(落弹角)
        hoopScale = Math.sin(Math.PI / 180 * pdata.impact_angle[r * 10 - 1]);
    } else if (dapSettings.hoopType == 2) {
        // 方式2：使用 cos(落弹角)
        hoopScale = Math.cos(Math.PI / 180 * pdata.impact_angle[r * 10 - 1]);
    }

    // ---- 垂直散布 = 水平散布 × 垂直系数 / 三角函数缩放 ----
    let vertValue = (horiValue * vertCoeff / hoopScale).maxFixed(1);
    vert.push(vertValue);

    // ---- 散布面积 = 水平 × 垂直 × π / 1000 (转换为千平方米) ----
    squ.push((horiValue * vertValue * Math.PI / 1000).maxFixed(1));
}
```

#### 3.2 期望散布（Sigma 修正）

```javascript
// 当勾选"绘制期望散布"时，追加期望曲线
if (dispSc) {
    // 期望水平散布 = 水平散布 × sigma
    chartCache['disp-horizontal'].data.datasets.push({
        data: hori.map(x => x.mul(dapa.sc).maxFixed(1)),
        ...
    });
    // 期望垂直散布 = 垂直散布 × sigma
    chartCache['disp-vertical'].data.datasets.push({
        data: vert.map(x => x.mul(dapa.sc).maxFixed(1)),
        ...
    });
    // 期望散布面积 = 散布面积 × sigma²
    chartCache['disp-square'].data.datasets.push({
        data: squ.map(x => x.mul(dapa.sc).mul(dapa.sc).maxFixed(1)),
        ...
    });
}
```

#### 3.3 散布公式的数据字段映射

| dap.js 字段 | 含义 | 说明 |
|-------------|------|------|
| `dapa.td` | taperDist | 渐变距离阈值 (km)，低于此距离使用渐变散布 |
| `dapa.ha` | coeffA | 散布线性公式斜率 |
| `dapa.hb` | coeffB | 散布线性公式截距 |
| `dapa.vd` | vertDelimRatio | 垂直分割比例 |
| `dapa.vrz` | vertRadiusZero | 零距离垂直散布系数 |
| `dapa.vrd` | vertRadiusDelim | 分割距离垂直散布系数 |
| `dapa.vrm` | vertRadiusMax | 最大距离垂直散布系数 |
| `dapa.sc` | sigmaCount | Sigma 精度系数 |
| `dapa.md` | maxDist | 最大射程 (km) |
| `dapa.gt` | gunType | 'gm'=主炮, 'gs'=副炮 |
| `dapa.at` | ammoType | 'AP'或其他 |

#### 3.4 散布椭圆 + 散布密度图（MKtool 原始代码）

MKtool 的散布椭圆/密度图在舰船详情弹窗中显示，使用 SVG 绘制。

#### 3.4.1 散布度量计算（MKtool app.js）

```javascript
// ===== MKtool horizontalDispersionMeters — 水平散布 =====
// 使用 BW（Battle Width，游戏内部单位）到米的转换
const BW_TO_METERS = ...;  // 来自 constants.js

function horizontalDispersionMeters(module, rangeMeters) {
  const distanceBw = rangeMeters / BW_TO_METERS;
  const idealDistanceBw = module.ideal_distance_bw;
  const idealRadiusBw = module.ideal_radius_bw;
  const minRadiusBw = module.min_radius_bw;
  const taperDistBw = module.taper_dist_m / BW_TO_METERS || 0;
  
  let radiusBw = distanceBw * (idealRadiusBw - minRadiusBw) / idealDistanceBw;
  if (taperDistBw > 0 && distanceBw <= taperDistBw) {
    radiusBw += minRadiusBw * (distanceBw / taperDistBw);  // 渐变区
  } else {
    radiusBw += minRadiusBw;  // 正常区
  }
  return radiusBw * BW_TO_METERS;
}

// ===== MKtool verticalDispersionMeters — 垂直散布 =====
function verticalDispersionMeters(module, rangeMeters) {
  const horizontal = horizontalDispersionMeters(module, rangeMeters);
  const distanceBw = rangeMeters / BW_TO_METERS;
  const maxDistBw = (module.max_dist_m || 0) / BW_TO_METERS;
  const delimDistBw = maxDistBw * (module.delim ?? 0);
  const radiusOnZero = module.radius_on_zero;
  const radiusOnDelim = module.radius_on_delim;
  const radiusOnMax = module.radius_on_max;
  
  let coeff;
  if (distanceBw < delimDistBw) {
    coeff = radiusOnZero + (radiusOnDelim - radiusOnZero) * (distanceBw / Math.max(delimDistBw, 1));
  } else {
    coeff = radiusOnDelim + (radiusOnMax - radiusOnDelim) * ((distanceBw - delimDistBw) / Math.max(maxDistBw - delimDistBw, 1));
  }
  return horizontal * coeff;
}

// ===== MKtool shellDispersionMetrics — 散布椭圆度量 =====
function shellDispersionMetrics(ship, projectile, context, groupLabel) {
  const module = mainBatteryModule(ship);
  const rangeM = context?.range_m;
  const lateralRadiusM = horizontalDispersionMeters(module, rangeM);       // 横向散布半径
  const perpendicularRadiusM = verticalDispersionMeters(module, rangeM);   // 垂直散布半径
  // ... 
  const result = shellResultAtRange(ship, projectile, context, groupLabel);
  const impactAngleDeg = Number(result?.impact_angle_deg);
  const impactAngleRad = (clamp(impactAngleDeg, 2, 45) * Math.PI) / 180;
  
  // 纵向散布半径 = 垂直散布半径 / sin(落弹角)
  const longitudinalRadiusM = perpendicularRadiusM / Math.max(Math.sin(impactAngleRad), 0.035);
  
  return {
    lateralRadiusM,         // 横向半径 (m)
    longitudinalRadiusM,    // 纵向半径 (m)
    sigma: module.sigma_count || 1,  // Sigma精度系数
  };
}
```

#### 3.4.2 高斯散布点生成（MKtool app.js）

```javascript
// ===== Box-Muller 变换生成高斯随机数 =====
function gaussianRandom(random) {
  let first = 0, second = 0;
  while (first === 0) first = random();
  while (second === 0) second = random();
  return Math.sqrt(-2 * Math.log(first)) * Math.cos(2 * Math.PI * second);
}

// ===== 生成单个炮弹落点偏移 =====
function randomShellDeviation(random, sigma) {
  const angle = random() * Math.PI;              // 随机方向角 0~180°
  const gaussian = gaussianRandom(random) / Math.max(Number(sigma) || 1, 0.2);  // Sigma控制聚散
  const fallback = random() * 2 - 1;              // 备用值
  const magnitude = Math.abs(gaussian) <= 1 ? gaussian : fallback;  // 钳制
  const lateral = Math.sin(angle) * magnitude;    // 横向偏移系数
  let longitudinal = Math.cos(angle) * magnitude; // 纵向偏移系数
  // 纵向特殊处理：正向偏移用对数压缩
  if (longitudinal > 0) longitudinal = 10 * Math.log(0.1 * longitudinal + 1);
  return { longitudinal, lateral };
}

// ===== 生成 N 个散布点 =====
function shellDispersionPoints(ship, projectile, context, groupLabel, metrics, shotCount) {
  const count = clampShellDispersionShots(shotCount);
  const seed = hashString32([...].join("|"));  // 用种子保证相同输入生成相同结果
  const random = seededRandom(seed);            // 确定性伪随机
  return Array.from({ length: count }, () => randomShellDeviation(random, metrics?.sigma));
}
```

#### 3.4.3 SVG 散布椭圆渲染（MKtool app.js）

```javascript
function renderShellDispersionGraph(ship, projectile, context, groupLabel, shotCount) {
  const metrics = shellDispersionMetrics(ship, projectile, context, groupLabel);
  const points = shellDispersionPoints(ship, projectile, context, groupLabel, metrics, shotCount);
  
  // SVG 视口与布局
  const viewWidth = 760, viewHeight = 350;
  const centerX = 390, centerY = 185;
  const radiusX = 280;  // 固定像素半径（纵向）
  // 椭圆短轴 = 固定长轴 × (横向半径 / 纵向半径)，限制 46~120px
  const radiusY = clamp(radiusX * (metrics.lateralRadiusM / metrics.longitudinalRadiusM), 46, 120);
  
  // 标签文字
  const horizontalLabel = `${metrics.longitudinalRadiusM * 2} m`;  // 纵向直径
  const verticalLabel = `${metrics.lateralRadiusM * 2} m`;         // 横向直径
  
  // 落点渲染（每个点一个 circle）
  const dotMarkup = points.map((point, index) => {
    const x = centerX + point.longitudinal * radiusX;
    const y = centerY + point.lateral * radiusY;
    const opacity = 0.24 + (index % 5) * 0.055;
    return `<circle cx="${x}" cy="${y}" r="${index % 7 === 0 ? 4.2 : 3.4}" opacity="${opacity}">`;
  }).join("");
  
  return `
    <svg viewBox="0 0 ${viewWidth} ${viewHeight}">
      <!-- 散布椭圆 -->
      <ellipse cx="${centerX}" cy="${centerY}" rx="${radiusX}" ry="${radiusY}"></ellipse>
      <!-- 散布点 -->
      ${dotMarkup}
      <!-- 水平/垂直尺寸标注线 + 标签 -->
      ...
    </svg>
  `;
}
```

#### 3.4.4 散布椭圆示意图

```
                   ← longitudinalRadiusM × 2 →
                ┌──────────────────────────────┐
                │    ●    ● ●  ●               │
                │  ●  ● ● ● ● ●  ●            │   ↑
                │ ● ● ● ● ● ● ● ● ●           │   l
                │ ● ● ●●●●●●●● ● ●            │   a
     ↑          │ ● ● ●●●⊙●●●● ● ●            │   t
     l          │ ● ● ●●●●●●●● ● ●            │   e
     a          │ ● ● ● ● ● ● ● ● ●           │   r
     t          │  ●   ● ● ● ●  ●             │   a
     e          │    ●   ●  ●                  │   l
     r          └──────────────────────────────┘   ↓
     a               ↑
     l               sigma控制密度
     ×              高斯分布落点
     2
```

#### 3.4.5 数据流总结

```
ship_artillery 表中的散布参数
  ideal_distance_bw, ideal_radius_bw
  min_radius_bw, taper_dist_m
  radius_on_zero, radius_on_delim, radius_on_max
  delim, sigma_count, max_dist_m
        │
        ▼
horizontalDispersionMeters(module, rangeM) ───→ 横向散布半径 (lateralRadiusM)
verticalDispersionMeters(module, rangeM) ─────→ 垂直散布半径 (perpendicularRadiusM)
        │
        ▼  shellResultAtRange() → impactAngleDeg
longitudinalRadiusM = perpendicularRadiusM / sin(impactAngleRad)
        │
        ▼
SVG 椭圆: rx=280(固定), ry=clamp(280 * lateral/longitudinal, 46, 120)
散布点:  高斯分布(μ=0, σ=1/sigma) × (rx, ry) 投影
```

### 3.5 散布修正（技能/升级品）

```javascript
// 浩舰 dap.js 中的修正逻辑
let maxDist = dapa.md, dispCoeff = 1;
for (let i in dapm) {
    if ($('#modifier-' + i + '-btn').bootstrapSwitch('state')) {
        if (dapm[i].GMMaxDist != null && dapa.gt == 'gm') {
            maxDist = maxDist.mul(dapm[i].GMMaxDist);     // 主炮射程修正
        }
        if (dapm[i].GSMaxDist != null && dapa.gt == 'gs') {
            maxDist = maxDist.mul(dapm[i].GSMaxDist);     // 副炮射程修正
        }
        if (dapm[i].GMIdealRadius != null && dapa.gt == 'gm') {
            dispCoeff = dispCoeff.mul(dapm[i].GMIdealRadius); // 主炮散布修正
        }
        if (dapm[i].GSIdealRadius != null && dapa.gt == 'gs') {
            dispCoeff = dispCoeff.mul(dapm[i].GSIdealRadius); // 副炮散布修正
        }
    }
}
```

---

### 4. 浩舰图表属性

```javascript
// 图表配置
chart = new Chart($('#' + name + '-canvas').get(0).getContext('2d'), {
    type: 'line',
    data: {
        labels: Array(300).fill().map((item, index) => (index + 1) / 10),  // 0.1~30km
        datasets: []
    },
    options: {
        scales: {
            xAxes: [{ scaleLabel: { labelString: '距离(公里)' } }],
            yAxes: [{ scaleLabel: { labelString: labelString } }]
        },
        animation: { duration: 0 },
        hover: { mode: 'index', animationDuration: 0 },
        legend: { display: true, position: 'right' }
    }
});

// 6张图表名称：
// disp-horizontal    — 水平散布
// disp-vertical      — 垂直散布
// disp-square        — 散布面积
// pene-flytime       — 落弹时间
// pene-armorvert     — 水平穿深（垂直等效）
// pene-impactangle   — 落弹角
```

---

## 二、数据源需求

### 2.1 弹药数据字段（浩舰 dap.js 中每条弹药记录的结构）

浩舰使用的弹药数据结构（从后端 `/wowsdb/dap` 页面加载的 `dapData` 对象）：

```javascript
// 每条弹药记录的字段（dapa对象）
dapa = {
    // ---- 弹道/穿深参数（传入 calculator.js）----
    m: 弹重 (kg),           // 如 1.373
    d: 口径 (m),            // 如 0.457
    ad: 空气阻力系数,        // 如 0.256
    s: 初速 (m/s),          // 如 800
    k: Krupp 值,            // 如 2500
    cnma: 弹头转正角 (°),    // 如 6.0

    // ---- 散布参数 ----
    md: 最大射程 (km),       // 如 12.0
    td: 渐变距离阈值 (km),   // taperDist
    ha: 散布斜率系数,        // 散布公式 = ha * 距离 + hb
    hb: 散布截距系数,
    vd: 垂直分割比例,
    vrz: 0距离垂直散布系数,
    vrd: 分割距离垂直散布系数,
    vrm: 最大距离垂直散布系数,
    sc: Sigma 精度系数,

    // ---- 类型标识 ----
    gt: 炮类型 ('gm'=主炮, 'gs'=副炮),
    at: 弹药类型 ('AP'=穿甲弹, 'HE'=高爆弹, ...),
    name: 弹药显示名称,
};
```

### 2.2 数据源映射到现有数据库

| 浩舰字段 | 含义 | 现有数据库来源 |
|----------|------|---------------|
| `m` | 弹重 (kg) | `projectile_bullet_ext.bullet_mass` |
| `d` | 口径 (m) | `projectile_bullet_ext.bullet_diameter` |
| `ad` | 空气阻力系数 | `projectile_bullet_ext.bullet_air_drag` |
| `s` | 初速 (m/s) | `projectile_bullet_ext.bullet_speed` |
| `k` | Krupp 值 | `projectile_bullet_ext.bullet_krupp` |
| `cnma` | 弹头转正角 (°) | `projectile_bullet_ext.bullet_cap_normalize_max` |
| `md` | 最大射程 (km) | `ship_artillery.max_dist` |
| `td` | 渐变距离 (km) | 由散布参数计算: `idealRadius * delim / minRadius` |
| `ha` | 散布斜率 | 由 `idealRadius`, `minRadius`, `idealDistance` 推算 |
| `hb` | 散布截距 | 同 `ha` |
| `vd` | 垂直分割比例 | 由散布参数计算 |
| `vrz` | 0距离垂直系数 | `ship_artillery.radius_on_zero` |
| `vrd` | 分割距离垂直系数 | `ship_artillery.radius_on_delim` |
| `vrm` | 最大距离垂直系数 | `ship_artillery.radius_on_max` |
| `sc` | Sigma 精度系数 | `ship_artillery.sigma` 或 `sigmaCount` |
| `gt` | 炮类型 | 'gm' 或 'gs' |
| `at` | 弹药类型 | 从弹药名称/类型推断 |

---

## 三、UI 需求

### 3.1 主界面入口
- 在顶部工具栏添加一个按钮：**"📊 穿深计算器"**（或类似图标+文字）
- 放置在现有按钮右侧（如 `btn_load`, `btn_lang`, `btn_refresh` 之后）

### 3.2 弹出窗口 (独立对话框)

新建 `ui/penetration_calculator.py`，样式与现有界面保持一致。

#### 3.2.1 选择区域（顶部）

```
┌────────────────────────────────────────────────────────────┐
│  国家: [▼]  舰种: [▼]  舰船: [▼]  主炮: [▼]  弹药: [▼]  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  [✓] 敌众我寡  [✓] 副炮专员  [✓] 眼花缭乱（目标）   │  │
│  └──────────────────────────────────────────────────────┘  │
│  [绘制期望散布]  [添加自定义对比]                          │
└────────────────────────────────────────────────────────────┘
```

**选择联动逻辑：**
1. 选择国家 → 过滤舰种下拉
2. 选择舰种 → 过滤舰船下拉（从 `ship_basic_info` 查询）
3. 选择舰船 → 加载该舰主炮列表（从 `ship_artillery` / `ship_secondary_artillery` 查询）
4. 选择主炮 → 加载该炮可用的弹药列表
5. 选择弹药 → 从 `projectile_bullet_ext` 加载弹道/穿深参数

#### 3.2.2 数据表格区域（中间）

```
┌────────────────────────────────────────────────────────────┐
│  可用列: [✓]水平散布 [✓]垂直散布 [✓]散布面积              │
│          [✓]落弹时间 [✓]水平穿深 [✓]落弹角                │
├─────┬──────┬──────┬──────┬──────┬──────┬──────┬──────────┤
│ 距离 │水平散布│垂直散布│散布面积│落弹时间│水平穿深│落弹角  │
├─────┼──────┼──────┼──────┼──────┼──────┼──────┼──────────┤
│ 1km │ ...  │ ...  │ ...  │ ...  │ ...  │ ...  │          │
│ 2km │ ...  │ ...  │ ...  │ ...  │ ...  │ ...  │          │
│ ... │ ...  │ ...  │ ...  │ ...  │ ...  │ ...  │          │
│ Nkm │ ...  │ ...  │ ...  │ ...  │ ...  │ ...  │          │
└─────┴──────┴──────┴──────┴──────┴──────┴──────┴──────────┘
```

- 表格行：距离从 1km 到最大射程，步长 1km（或 0.5km）
- 表格列：用户可通过复选框选择显示哪些列
- 支持排序（点击列头）

#### 3.2.3 图表区域（底部）

三个图表用 QWidget + matplotlib / PyQtGraph 绘制：

1. **穿深曲线图**：横轴=距离(km)，纵轴=穿深(mm)
   - 显示当前弹药的穿深随距离衰减曲线
   - 支持叠加对比线（"添加自定义对比"功能）

2. **飞行时间曲线图**：横轴=距离(km)，纵轴=时间(s)
   - 显示炮弹飞行时间随距离变化
   - 可切换显示模式：s / s·km⁻¹

3. **散布密度图**：散布椭圆 + 高斯散点
   - 绘制当前距离处的散布椭圆
   - 用 Sigma 值生成散点（1000 发模拟）
   - 中心到边缘密度渐变

---

### 3.3 与现有详情面板的集成

在 `presenters/ship_presenter.py` 的弹药详情渲染中，增强显示：

| 现有面板位置 | 新增内容 |
|-------------|---------|
| 炮弹详情段（AP/CS） | 添加"穿深曲线"按钮/迷你图 |
| 炮弹详情段（HE） | 显示 HE 固定穿深 |
| 主炮 segment | 显示散布公式 + Sigma |
| 炮弹详情段 | 显示各距离穿深表（精简版，如5/10/15/20km） |

具体修改 `_append_ammo_extra` 方法，在显示弹重/阻力系数等基础参数后，额外计算并添加：
- 各典型距离的穿深值（如 5km, 10km, 15km, 20km）
- 跳弹角区间
- 引信阈值
- 散布公式字符串

---

## 四、项目结构变更

```
Wows Paragrams Unpack/
├── services/
│   └── ballistics_service.py      # [新增] 弹道/穿深/散布计算核心
├── ui/
│   ├── penetration_calculator.py  # [新增] 穿深计算器窗口
│   └── toolbar_widget.py          # [修改] 添加"穿深计算器"按钮
├── presenters/
│   └── ship_presenter.py          # [修改] 弹药详情增加穿深/散布数据
```

### services/ballistics_service.py 职责

纯计算逻辑，无 UI 依赖，严格按浩舰 V2 原始公式实现，可被计算器窗口和详情面板共同调用：

```python
class BallisticsCalculator:
    """弹道/穿深/散布计算器（严格按浩舰原始公式实现）"""
    
    # ---- 常量（与浩舰 calculator.js 完全一致）----
    GRAVITY = 9.81                  # g
    GAS_CST_R = 8.31447             # R
    AIR_MOLAR_MASS = 0.0289644      # M
    SEALEVEL_TEMPERATURE = 288.0    # T_0
    STATIC_PRESSURE = 101325.0      # p_0
    TEMPERATURE_LAPSE_RATE = 0.0065 # L
    C_PEN = 0.5561613               # 穿深常数 C
    CW_1 = 1.0                      # 阻力一次项系数
    DT = 0.05                       # 步进时间 (与浩舰一致)
    N_ANGLE = 200                   # 发射角迭代数
    MAX_ANGLE_DEG = 45              # 最大发射角
    FLY_TIME_DIVISOR = 3.1          # 飞行时间修正因子
    
    @staticmethod
    def get_normalization_angle(caliber_m: float) -> float:
        """弹头转正角（与浩舰完全一致）
        D <= 0.13m (130mm): 10°
        D <= 0.152m (152mm): 8.5°
        D <= 0.22m (220mm): 7°
        D > 0.22m: 6°
        """
        if caliber_m <= 0.13: return 10.0
        elif caliber_m <= 0.152: return 8.5
        elif caliber_m <= 0.22: return 7.0
        else: return 6.0
    
    @staticmethod
    def simulate_trajectory(mass: float, caliber_m: float, 
                             air_drag: float, velocity: float,
                             angle_deg: float) -> dict:
        """弹道步进模拟（dt=0.05s，标准大气模型）
        
        返回: {distance_m, velocity, fly_time, impact_angle_deg}
        """
        # ... 实现与浩舰 calculator.js 完全一致的步进逻辑
        pass
    
    @staticmethod
    def calc_ap_penetration(krupp: float, mass_kg: float, 
                              velocity: float, caliber_m: float) -> float:
        """浩舰原始 AP 穿深公式
        P = K * (m * V²)^0.69 * D^(-1.07) * 10^-7
        """
        return krupp * (mass_kg * (velocity ** 2)) ** 0.69 \
               * (caliber_m ** -1.07) * 0.0000001
    
    @staticmethod
    def calc_equivalent_penetration(pen_abs: float, impact_angle_rad: float,
                                     norm_angle_rad: float) -> tuple:
        """计算等效穿深（与浩舰一致）
        Returns: (vertical_pen, horizontal_pen)
        """
        IA_vert = max(impact_angle_rad - norm_angle_rad, 0)
        IA_hori = min(impact_angle_rad + norm_angle_rad, math.pi/2)
        vert_pen = pen_abs * math.cos(IA_vert)
        hori_pen = pen_abs * math.sin(IA_hori)
        return vert_pen, hori_pen
    
    def calculate_full_ballistics(self, mass: float, caliber_m: float,
                                   air_drag: float, velocity: float,
                                   krupp: float, norm_angle: float = None) -> dict:
        """执行完整弹道模拟（复刻浩舰 calculator.js）
        
        遍历 200 个发射角 (0~45°)，步进模拟每条弹道，
        然后插值为 100m 间隔的均匀数据，返回完整弹道表。
        """
        # ... 完全按照浩舰 calculator.js 逻辑实现
        pass
    
    @staticmethod
    def calc_horizontal_dispersion(distance_km: float, params: dict) -> float:
        """水平散布（浩舰 dap.js 原始公式）
        
        params 需要包含:
          td: taperDist (渐变距离阈值)
          ha: 斜率系数
          hb: 截距系数
          dispCoeff: 散布修正系数（默认1.0）
        """
        td = params['td']
        ha = params['ha']
        hb = params['hb']
        coeff = params.get('dispCoeff', 1.0)
        
        if distance_km < td:
            taperDisp = (td * ha + hb) / td
            return round(distance_km * taperDisp * coeff, 1)
        else:
            return round((distance_km * ha + hb) * coeff, 1)
    
    @staticmethod
    def calc_vertical_dispersion(horiz_disp: float, distance_km: float,
                                  max_dist: float, params: dict,
                                  impact_angle_deg: float = None,
                                  hoop_type: int = 0) -> float:
        """垂直散布（浩舰 dap.js 原始公式）
        
        params: {vd, vrz, vrd, vrm}
        hoop_type: 0=无修正, 1=sin(落弹角), 2=cos(落弹角)
        """
        vd = params['vd']
        vrz = params['vrz']
        vrd = params['vrd']
        vrm = params['vrm']
        delimDist = vd * max_dist
        
        if distance_km < delimDist:
            vertCoeff = vrz + (vrd - vrz) * (distance_km / delimDist)
        else:
            vertCoeff = vrd + (vrm - vrd) * (distance_km - delimDist) / (max_dist - delimDist)
        
        hoopScale = 1.0
        if hoop_type == 1 and impact_angle_deg is not None:
            hoopScale = math.sin(math.radians(impact_angle_deg))
        elif hoop_type == 2 and impact_angle_deg is not None:
            hoopScale = math.cos(math.radians(impact_angle_deg))
        
        return round(horiz_disp * vertCoeff / hoopScale, 1)
    
    @staticmethod
    def calc_dispersion_area(horiz_disp: float, vert_disp: float) -> float:
        """散布面积 = 水平×垂直×π / 1000（浩舰公式，单位千平方米）"""
        return round(horiz_disp * vert_disp * math.pi / 1000, 1)
    
    @staticmethod
    def calc_expected_dispersion(dispersion: float, sigma: float) -> float:
        """期望散布 = 散布 × sigma（浩舰公式）"""
        return round(dispersion * sigma, 1)
    
    @staticmethod
    def calc_expected_area(area: float, sigma: float) -> float:
        """期望散布面积 = 面积 × sigma²"""
        return round(area * sigma * sigma, 1)
    
    def generate_full_table(self, ballistics_data: dict, disp_params: dict,
                             max_dist_km: float, step_km: float = 1.0,
                             hoop_type: int = 0) -> dict:
        """生成完整数据表（浩舰风格）
        
        返回:
        {
            distances: [1, 2, 3, ...],
            horizontal_disp: [...],
            vertical_disp: [...],
            disp_area: [...],
            fly_time: [...],
            penetration: [...],
            impact_angle: [...],
        }
        """
        # ... 生成从 1km 到 maxDist 的完整表格
        pass
```

---

## 五、实施任务分解

### Phase 1: 核心计算引擎
- [ ] 创建 `services/ballistics_service.py`
  - [ ] 实现 `simulate_trajectory()` — 弹道步进模拟
  - [ ] 实现 `calc_ap_penetration()` — 德马尔公式
  - [ ] 实现 `calc_he_penetration()` — HE 固定穿深
  - [ ] 实现散布相关计算（水平/垂直/面积/Sigma落点）
  - [ ] 实现跳弹/引信判断逻辑
  - [ ] 实现 `generate_full_table()` — 生成完整数据表
- [ ] 编写单元测试验证弹道/穿深/散布计算

### Phase 2: 计算器 UI
- [ ] 创建 `ui/penetration_calculator.py` — 独立对话框
  - [ ] 舰船/火炮/弹药四级联动选择器
  - [ ] 技能开关（敌众我寡/副炮专员/眼花缭乱）
  - [ ] 数据表格（6 列可选，距离行）
  - [ ] 穿深曲线图（matplotlib 嵌入）
  - [ ] 飞行时间曲线图
  - [ ] 散布密度散点图
  - [ ] 添加自定义对比功能
- [ ] 修改 `ui/toolbar_widget.py` — 添加入口按钮
- [ ] 修改 `ui/main_window.py` — 连接按钮信号与弹窗

### Phase 3: 详情面板集成
- [ ] 修改 `presenters/ship_presenter.py`
  - [ ] 在 `_append_ammo_extra` 中增加各距离穿深显示
  - [ ] 在主炮 section 增加散布公式和 Sigma 显示
- [ ] 修改 `ui/detail_panel.py`（如需）— 支持迷你图

### Phase 4: 打磨与优化
- [ ] 图表样式与现有主题保持一致
- [ ] 本地化支持
- [ ] 性能优化（弹道模拟缓存）
- [ ] 多舰对比的 CSV 导出功能（可选）

---

## 六、关键数据流

```
用户选择舰船+主炮+弹药
        │
        ▼
从数据库加载参数:
  ├─ 弹道参数: 弹重(m), 口径(D), 阻力系数(c_D), 初速(v_0), Krupp(K), 转正角(norm)
  └─ 散布参数: 最大射程(md), 渐变距离(td), 斜率(ha), 截距(hb),
               垂直分割(vd), 垂直系数(vrz/vrd/vrm), Sigma(sc)
        │
        ▼
技能修正（可选）:
  ├─ GMMaxDist/GSMaxDist → 修正最大射程
  └─ GMIdealRadius/GSIdealRadius → 修正散布系数(dispCoeff)
        │
        ▼
弹道模拟 (ballistics_service):
  ├─ 遍历 200 个发射角(0~45°), dt=0.05s 步进积分
  ├─ 标准大气模型 (温度/气压随高度变化)
  ├─ 输出: 每100m间隔的弹道表
  └─ 包含: 距离, 存速, 飞行时间(/3.1修正), 落弹角
        │
        ▼
数据表生成 (每0.1km或1km一个点):
  ├─ calc_horizontal_dispersion() → 水平散布 (m)
  ├─ calc_vertical_dispersion() → 垂直散布 (m)
  ├─ calc_dispersion_area() → 散布面积 (千m²)
  ├─ ap_pen = K*(m*V²)^0.69*D^(-1.07)*10^-7 → 绝对穿深
  ├─ 等效穿深 = ap_pen * cos/sin(落弹角 ± 转正角)
  └─ 飞行时间 = 弹道时间 / 3.1
        │
        ▼
渲染:
  ├─ QTableWidget → 数据表格 (6列可选)
  ├─ Chart.js 风格 → 穿深曲线 / 飞行时间曲线 / 散布曲线
  └─ 期望散布 = 散布 × sigma (可选)
```

---

## 七、注意事项 / 参考

1. **弹道模拟精度**：浩舰使用 dt=0.05s 的固定步长，遍历 200 个发射角 (0~45°)。建议严格复刻此参数以保证结果一致。

2. **穿深公式**：浩舰使用的是 $P = K \times (m \times V^2)^{0.69} \times D^{-1.07} \times 10^{-7}$，**不是**常见的德马尔公式变体。务必使用此精确公式。

3. **飞行时间修正**：浩舰 V2 将原始弹道模拟时间除以 3.1 作为最终飞行时间。

4. **散布公式**：浩舰的散布公式为 `平散布 = max(距离 × 渐变系数, 距离 × ha + hb)` 而非分段散布公式。渐变距离 `td` 以内使用渐变系数 `(td×ha+hb)/td`，以外使用线性公式。

5. **垂直散布**：垂直散布通过垂直散布系数乘以水平散布获得，并可选择用落弹角的三角函数修正（设置中的 hoopType 选项）。

6. **Sigma 值**：期望散布 = 散布 × sigma；期望散布面积 = 面积 × sigma²。

7. **技能修正**：
   - **敌众我寡**：对应 `GMIdealRadius` / `GSIdealRadius` 乘算散布
   - **副炮专员**：对应 `GSMaxDist` / `GSIdealRadius` 修正
   - **眼花缭乱（目标）**：对应散布增加修正

8. **图表库选择**：浩舰使用 Chart.js 绘制曲线图。建议 Python 端使用 `matplotlib`（功能全）或 `PyQtGraph`（性能好），嵌入 `FigureCanvasQTAgg`。如果需要 Chart.js 风格的交互，可使用 `pyqtchart`。

9. **参考实现**：
   - 浩舰散布穿深计算器: https://iwarship.net/wowsdb/dap
   - 原始 JS 源码已保存至: `todo_list/dap_original.js`, `todo_list/calculator_original.js`, `todo_list/calculator3_original.js`
   - MKtool 舰船详情页: https://mktool.info/ship/PRSB110
