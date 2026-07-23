// Source: https://iwarship.net/wowsdb/static/js/dap.js?v=20260723091513
// 散布穿深计算器 - 浩舰 wowsdb
// 注意：此文件为压缩后单行 JS，以下为格式化版本的核心函数

// ============================================================
// 精度计算辅助函数 (高精度浮点数运算)
// ============================================================
function add(a, b) {
    var c, d, e;
    try { c = a.toString().split(".")[1].length; } catch (f) { c = 0; }
    try { d = b.toString().split(".")[1].length; } catch (f) { d = 0; }
    return e = Math.pow(10, Math.max(c, d)), (mul(a, e) + mul(b, e)) / e;
}
function sub(a, b) { /* 类似 add */ }
function mul(a, b) { /* 高精度乘法 */ }
function div(a, b) { /* 高精度除法 */ }
function maxFixed(a, b) { var c = Math.pow(10, b); return parseInt(a.mul(c).toFixed(0)).div(c); }
Number.prototype.add = function(arg) { return add(this, arg); };
Number.prototype.sub = function(arg) { return sub(this, arg); };
Number.prototype.mul = function(arg) { return mul(this, arg); };
Number.prototype.div = function(arg) { return div(this, arg); };
