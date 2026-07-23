{
    function add(a, b) {
        var c, d, e;
        try {
            c = a.toString().split(".")[1].length;
        } catch (f) {
            c = 0;
        }
        try {
            d = b.toString().split(".")[1].length;
        } catch (f) {
            d = 0;
        }
        return e = Math.pow(10, Math.max(c, d)), (mul(a, e) + mul(b, e)) / e;
    };

    function sub(a, b) {
        var c, d, e;
        try {
            c = a.toString().split(".")[1].length;
        } catch (f) {
            c = 0;
        }
        try {
            d = b.toString().split(".")[1].length;
        } catch (f) {
            d = 0;
        }
        return e = Math.pow(10, Math.max(c, d)), (mul(a, e) - mul(b, e)) / e;
    };

    function mul(a, b) {
        var c = 0,
            d = a.toString(),
            e = b.toString();
        try {
            c += d.split(".")[1].length;
        } catch (f) {
        }
        try {
            c += e.split(".")[1].length;
        } catch (f) {
        }
        return Number(d.replace(".", "")) * Number(e.replace(".", "")) / Math.pow(10, c);
    };

    function div(a, b) {
        var c, d, e = 0,
            f = 0;
        try {
            e = a.toString().split(".")[1].length;
        } catch (g) {
        }
        try {
            f = b.toString().split(".")[1].length;
        } catch (g) {
        }
        return c = Number(a.toString().replace(".", "")), d = Number(b.toString().replace(".", "")), mul(c / d, Math.pow(10, f - e));
    };

    function maxFixed(a, b) {
        var c = Math.pow(10, b);
        return parseInt(a.mul(c).toFixed(0)).div(c);
    };
    Number.prototype.add = function (arg) {
        return add(this, arg);
    };
    Number.prototype.sub = function (arg) {
        return sub(this, arg);
    };
    Number.prototype.mul = function (arg) {
        return mul(this, arg);
    };
    Number.prototype.div = function (arg) {
        return div(this, arg);
    };
    Number.prototype.maxFixed = function (arg) {
        return maxFixed(this, arg);
    };

    function getQueryVariable(variable) {
        var query = window.location.search.substring(1);
        var vars = query.split("&");
        for (var i = 0; i < vars.length; i++) {
            var pair = vars[i].split("=");
            if (pair[0] == variable) {
                return pair[1];
            }
        }
        return (false);
    }
}

var speciesNameMap = {
    'AirCarrier': '航空母舰',
    'Battleship': '战列舰',
    'Cruiser': '巡洋舰',
    'Destroyer': '驱逐舰',
    'Submarine': '潜艇',
    'Auxillary': '辅助舰艇'
};
$.fn.selectpicker.Constructor.BootstrapVersion = '4';

// 设置信息
var dapSettings = {};
// 图表缓存
var chartCache = {};
// 常用颜色列表
var colorList = ['aqua', 'black', 'blue', 'fuchsia', 'gray', 'green', 'lime', 'maroon', 'navy', 'olive', 'purple', 'red', 'silver', 'teal', 'yellow'];
// 当前颜色序号
var colorIndex = 0;

// 获取颜色
function getColor(add) {
    var color = null;
    if (colorIndex < colorList.length) {
        color = colorList[colorIndex];
    } else {
        color = 'rgb(' + (Math.random() * 255).toFixed(0) + ', ' + (Math.random() * 255).toFixed(0) + ', ' + (Math.random() * 255).toFixed(0) + ')';
    }
    if (add) {
        colorIndex++;
    }
    return color;
}

// 获取UUID
function guid() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
        var r = Math.random() * 16 | 0,
            v = c == 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

// 联动下拉框事件绑定
$('#nation-select').on('changed.bs.select', function (e, clickedIndex, isSelected, previousValue) {
    var nation = e.target.value;
    $('#species-select').empty();
    for (var species of Object.keys(dapData[nation]).sort()) {
        $('#species-select').append('<option value="' + species + '">' + species + '</option>');
    }
    $('#species-select').selectpicker('refresh');
    $('#species-select').selectpicker('val', $('#species-select option:eq(1)').val());
});
$('#species-select').on('changed.bs.select', function (e, clickedIndex, isSelected, previousValue) {
    var nation = $('#nation-select').val();
    var species = e.target.value;
    $('#ship-select').empty();
    for (var ship of Object.keys(dapData[nation][species]).sort()) {
        $('#ship-select').append('<option value="' + ship + '">' + ship + '</option>');
    }
    $('#ship-select').selectpicker('refresh');
    $('#ship-select').selectpicker('val', $('#ship-select option:eq(1)').val());
});
$('#ship-select').on('changed.bs.select', function (e, clickedIndex, isSelected, previousValue) {
    var nation = $('#nation-select').val();
    var species = $('#species-select').val();
    var ship = e.target.value;
    $('#ammo-select').empty();
    for (var ammo in dapData[nation][species][ship].ammo) {
        $('#ammo-select').append('<option value="' + ammo + '">' + dapData[nation][species][ship].ammo[ammo].name + '</option>');
    }
    $('#ammo-select').selectpicker('refresh');
    $('#ammo-select').selectpicker('val', $('#ammo-select option:eq(1)').val());

    $('#modifiers-div').empty();
    for (var i in dapData[nation][species][ship].modifiers) {
        var modifier = dapData[nation][species][ship].modifiers[i];
        $('#modifiers-div').append('<input type="checkbox" id="modifier-' + i + '-btn"/>');
        $('#modifier-' + i + '-btn').bootstrapSwitch({
            labelText: modifier.name,
            labelWidth: (16 * modifier.name.length + 3) + 'px',
            onText: '启',
            offText: '停',
            onColor: 'warning',
            offColor: 'primary'
        }).bootstrapSwitch('state', modifier['default']);
        var tooltipHtml = '';
        if (modifier.GMMaxDist != null) {
            tooltipHtml += '主炮最大射程' + (modifier.GMMaxDist > 1 ? '+' : '') + (modifier.GMMaxDist.sub(1).mul(100)) + '%<br/>';
        }
        if (modifier.GMIdealRadius != null) {
            tooltipHtml += '主炮最大偏差度' + (modifier.GMIdealRadius > 1 ? '+' : '') + (modifier.GMIdealRadius.sub(1).mul(100)) + '%<br/>';
        }
        if (modifier.GSMaxDist != null) {
            tooltipHtml += '副炮最大射程' + (modifier.GSMaxDist > 1 ? '+' : '') + (modifier.GSMaxDist.sub(1).mul(100)) + '%<br/>';
        }
        if (modifier.GSIdealRadius != null) {
            tooltipHtml += '副炮最大偏差度' + (modifier.GSIdealRadius > 1 ? '+' : '') + (modifier.GSIdealRadius.sub(1).mul(100)) + '%<br/>';
        }
        $('.bootstrap-switch-id-modifier-' + i + '-btn').attr('data-toggle', 'tooltip');
        $('.bootstrap-switch-id-modifier-' + i + '-btn').attr('data-trigger', 'hover');
        $('.bootstrap-switch-id-modifier-' + i + '-btn').attr('data-placement', 'top');
        $('.bootstrap-switch-id-modifier-' + i + '-btn').attr('data-title', tooltipHtml);
    }
    $("[data-toggle='tooltip']").tooltip({html: true});
});
$('#ammo-select').on('changed.bs.select', function (e, clickedIndex, isSelected, previousValue) {
    var nation = $('#nation-select').val();
    var species = $('#species-select').val();
    var ship = $('#ship-select').val();
    var ammo = e.target.value;
    var dapa = dapData[nation][species][ship].ammo[ammo];
    var name = ship.substr(4) + dapa.name;
    $('#name-input').val(name);
});

// 修改设置信息
function updateSettings(key, value) {
    dapSettings[key] = value;
    localStorage.dapSettings = JSON.stringify(dapSettings);
    refreshSettingsButtonStatus();
}

// 刷新设置按钮状态
function refreshSettingsButtonStatus() {
    $(".settings-hoop-type-btn").removeClass("btn-primary").addClass("btn-outline-primary");
    $("#settings-hoop-type-btn-" + dapSettings.hoopType).removeClass("btn-outline-primary").addClass("btn-primary");
    $(".settings-calc-type-btn").removeClass("btn-primary").addClass("btn-outline-primary");
    $("#settings-calc-type-btn-" + dapSettings.calcType).removeClass("btn-outline-primary").addClass("btn-primary");
}

// 获取弹道穿深数据
function getPdata(m, D, c_D, v_0, K, norm) {
    return dapSettings.calcType == 3 ?
        calculator3(m, D, c_D, v_0, K, norm) :
        calculator(m, D, c_D, v_0, K, norm);
}

// 绘制新图表
function drawNewChart(name, labelString) {
    chartCache[name] = new Chart($('#' + name + '-canvas').get(0).getContext('2d'), {
        type: 'line',
        data: {
            labels: Array(300).fill().map((item, index) => (index + 1) / 10),
            datasets: []
        },
        options: {
            tooltips: {
                enabled: true,
                mode: 'index',
                intersect: false,
            },
            scales: {
                xAxes: [{
                    display: true,
                    scaleLabel: {
                        display: true,
                        labelString: '距离(公里)'
                    }
                }],
                yAxes: [{
                    display: true,
                    scaleLabel: {
                        display: true,
                        labelString: labelString
                    }
                }]
            },
            animation: {
                duration: 0
            },
            hover: {
                mode: 'index',
                animationDuration: 0
            },
            legend: {
                display: true,
                position: 'right'
            },
            responsiveAnimationDuration: 0
        }
    });
}

// 计算并绘制散布弹道曲线
function calcAndDraw(dapa, dapm, name, disp = false, dispSc = false) {
    let pdata = getPdata(dapa.m, dapa.d, dapa.ad, dapa.s, dapa.k, dapa.cnma);
    let uuid = guid();
    let color = getColor(true);

    let hori = [];
    let vert = [];
    let squ = [];

    // 需要绘制散布图表
    if (disp) {
        // 获取修改选择情况
        let maxDist = dapa.md, dispCoeff = 1;
        for (let i in dapm) {
            if ($('#modifier-' + i + '-btn').bootstrapSwitch('state')) {
                if (dapm[i].GMMaxDist != null && dapa.gt == 'gm') {
                    maxDist = maxDist.mul(dapm[i].GMMaxDist);
                }
                if (dapm[i].GSMaxDist != null && dapa.gt == 'gs') {
                    maxDist = maxDist.mul(dapm[i].GSMaxDist);
                }
                if (dapm[i].GMIdealRadius != null && dapa.gt == 'gm') {
                    dispCoeff = dispCoeff.mul(dapm[i].GMIdealRadius);
                }
                if (dapm[i].GSIdealRadius != null && dapa.gt == 'gs') {
                    dispCoeff = dispCoeff.mul(dapm[i].GSIdealRadius);
                }
            }
        }

        // 计算散布
        let taperDisp = (dapa.td * dapa.ha + dapa.hb) / dapa.td;
        let delimDist = dapa.vd * maxDist;
        for (let r = 0.1; r <= maxDist; r = r.add(0.1)) {
            // 水平散布
            let horiValue = r < dapa.td ? (r * taperDisp * dispCoeff).maxFixed(1) : ((r * dapa.ha + dapa.hb) * dispCoeff).maxFixed(1);
            hori.push(horiValue);
            if ((r * 10 - 1) >= pdata.impact_angle.length) {
                continue;
            }
            // 垂直散布系数
            vertCoeff = r < delimDist ?
                (dapa.vrz + (dapa.vrd - dapa.vrz) * (r / delimDist)) :
                (dapa.vrd + (dapa.vrm - dapa.vrd) * (r - delimDist) / (maxDist - delimDist));
            // 根据视角进行三角函数计算
            let hoopScale = 1;
            if (dapSettings.hoopType == 1) {
                hoopScale = Math.sin(Math.PI / 180 * pdata.impact_angle[r * 10 - 1]);
            } else if (dapSettings.hoopType == 2) {
                hoopScale = Math.cos(Math.PI / 180 * pdata.impact_angle[r * 10 - 1]);
            }
            // 垂直散布及散布面积
            let vertValue = (horiValue * vertCoeff / hoopScale).maxFixed(1);
            vert.push(vertValue);
            squ.push((horiValue * vertValue * Math.PI / 1000).maxFixed(1));
        }
    }

    // 绘制弹道穿深图表
    chartCache['pene-flytime'].data.datasets.push({
        uuid: uuid,
        label: name,
        backgroundColor: color,
        borderColor: color,
        data: disp ? pdata.fly_time.slice(0, hori.length) : pdata.fly_time,
        fill: false,
        pointRadius: 1
    });
    if (dapa.at === 'AP') {
        chartCache['pene-armorvert'].data.datasets.push({
            uuid: uuid,
            label: name,
            backgroundColor: color,
            borderColor: color,
            data: disp ? pdata.armor_vert.slice(0, hori.length) : pdata.armor_vert,
            fill: false,
            pointRadius: 1
        });
    }
    chartCache['pene-impactangle'].data.datasets.push({
        uuid: uuid,
        label: name,
        backgroundColor: color,
        borderColor: color,
        data: disp ? pdata.impact_angle.slice(0, hori.length) : pdata.impact_angle,
        fill: false,
        pointRadius: 1
    });

    // 需要绘制散布图表
    if (disp) {
        // 绘制散布图表
        chartCache['disp-horizontal'].data.datasets.push({
            uuid: uuid,
            label: name,
            backgroundColor: color,
            borderColor: color,
            data: hori,
            fill: false,
            pointRadius: 1
        });
        chartCache['disp-vertical'].data.datasets.push({
            uuid: uuid,
            label: name,
            backgroundColor: color,
            borderColor: color,
            data: vert,
            fill: false,
            pointRadius: 1
        });
        chartCache['disp-square'].data.datasets.push({
            uuid: uuid,
            label: name,
            backgroundColor: color,
            borderColor: color,
            data: squ,
            fill: false,
            pointRadius: 1
        });
        // 修改期望散布图表
        if (dispSc) {
            let color2 = getColor(true);
            chartCache['disp-horizontal'].data.datasets.push({
                uuid: uuid,
                label: '[期望]' + name,
                backgroundColor: color2,
                borderColor: color2,
                data: hori.map(x => x.mul(dapa.sc).maxFixed(1)),
                fill: false,
                pointRadius: 1
            });
            chartCache['disp-vertical'].data.datasets.push({
                uuid: uuid,
                label: '[期望]' + name,
                backgroundColor: color2,
                borderColor: color2,
                data: vert.map(x => x.mul(dapa.sc).maxFixed(1)),
                fill: false,
                pointRadius: 1
            });
            chartCache['disp-square'].data.datasets.push({
                uuid: uuid,
                label: '[期望]' + name,
                backgroundColor: color2,
                borderColor: color2,
                data: squ.map(x => x.mul(dapa.sc).mul(dapa.sc).maxFixed(1)),
                fill: false,
                pointRadius: 1
            });
        }
    }

    // 刷新图表
    for (let cn of ['disp-horizontal', 'disp-vertical', 'disp-square', 'pene-flytime', 'pene-armorvert', 'pene-impactangle']) {
        chartCache[cn].update();
    }

    // 添加删除按钮
    $('#lines-div').append('<button id="del-line-btn-' + uuid + '" type="button" class="btn btn-outline-primary del-line-btn">' + name + '</button>');
    $('#del-line-btn-' + uuid).on('click', function () {
        let uuid = $(this).attr('id').substr(13);
        for (let cn of ['disp-horizontal', 'disp-vertical', 'disp-square', 'pene-flytime', 'pene-armorvert', 'pene-impactangle']) {
            // 重复一次，删除期望曲线
            for (let j = 0; j < 2; j++) {
                let index = -1;
                for (let i in chartCache[cn].data.datasets) {
                    if (chartCache[cn].data.datasets[i].uuid == uuid) {
                        index = i;
                    }
                }
                if (index > -1) {
                    chartCache[cn].data.datasets.splice(index, 1);
                    chartCache[cn].update();
                }
            }
        }
        $(this).remove();
    });
}

// 添加线条
$('#lsn-btn').on('click', function () {
    let nation = $('#nation-select').val();
    let species = $('#species-select').val();
    let ship = $('#ship-select').val();
    let ammo = $('#ammo-select').val();
    let dapa = dapData[nation][species][ship].ammo[ammo];
    let dapm = dapData[nation][species][ship].modifiers;
    let name = $('#name-input').val();

    calcAndDraw(dapa, dapm, name, true, $('#sc-line-check').bootstrapSwitch('state'));
});

// 显示自定义添加模态框
$('#custom-lsn-btn').on('click', function () {
    var nation = $('#nation-select').val();
    var species = $('#species-select').val();
    var ship = $('#ship-select').val();
    var ammo = $('#ammo-select').val();
    var dapa = dapData[nation][species][ship].ammo[ammo];
    $('#custom-append-input-name').val(ship.substr(4) + dapa.name);
    $('#custom-append-input-m').val(dapa.m);
    $('#custom-append-input-d').val(dapa.d);
    $('#custom-append-input-ad').val(dapa.ad);
    $('#custom-append-input-s').val(dapa.s);
    $('#custom-append-input-k').val(dapa.k);
    $('#custom-append-input-cnma').val(dapa.cnma);
    $("#custom-append-modal").modal();
});

// 确认自定义添加
$('#custom-append-confirm').on('click', function () {
    calcAndDraw({
        m: $('#custom-append-input-m').val(),
        d: $('#custom-append-input-d').val(),
        ad: $('#custom-append-input-ad').val(),
        s: $('#custom-append-input-s').val(),
        k: $('#custom-append-input-k').val(),
        cnma: $('#custom-append-input-cnma').val(),
        at: "AP"
    }, [], $('#custom-append-input-name').val(), false, false);

    $("#custom-append-modal").modal('hide');
});

// 显示设置模态框
$('#settings-btn').on('click', function () {
    refreshSettingsButtonStatus();
    $("#settings-modal").modal();
});

// 设置模态框应用并刷新
$('#settings-confirm').on('click', function () {
    location.reload();
});

$(document).ready(function () {
    // 初始化获取设置
    if (localStorage.dapSettings == undefined || localStorage.dapSettings == 'undefined') {
        localStorage.dapSettings = JSON.stringify({
            hoopType: 1,
            calcType: 3,
        });
    }
    dapSettings = JSON.parse(localStorage.dapSettings);

    // 绘制期望散布 按钮渲染
    $('#sc-line-check').bootstrapSwitch({
        labelText: '绘制期望散布',
        labelWidth: '100px',
        onText: '是',
        offText: '否',
        onColor: 'warning',
        offColor: 'primary'
    }).bootstrapSwitch('state', false);
    $('.bootstrap-switch-id-sc-line-check').attr('data-toggle', 'tooltip');
    $('.bootstrap-switch-id-sc-line-check').attr('data-trigger', 'hover');
    $('.bootstrap-switch-id-sc-line-check').attr('data-placement', 'top');
    $('.bootstrap-switch-id-sc-line-check').attr('data-title', '额外绘制基于sigma计算的期望散布曲线');

    // 升级品描述tooltip渲染
    $("[data-toggle='tooltip']").tooltip({html: true});

    // 船只选择器渲染
    $('#nation-select').empty();
    for (var nation of Object.keys(dapData).sort()) {
        $('#nation-select').append('<option value="' + nation + '">' + nation + '</option>');
    }
    $('#nation-select').selectpicker('refresh');
    $('#nation-select').selectpicker('val', $('#nation-select option:eq(1)').val());

    // 绘制基础图表
    drawNewChart('disp-horizontal', '水平散布半径(米)');
    drawNewChart('disp-vertical', '垂直散布半径(米)');
    drawNewChart('disp-square', '散布面积(千平方米)');
    drawNewChart('pene-flytime', '飞行时间(秒)');
    drawNewChart('pene-armorvert', '平行水面方向穿深(毫米)');
    drawNewChart('pene-impactangle', '入射角(度)');

    // 存在弹道曲线渲染请求
    if (localStorage.dapRequest != undefined && localStorage.dapRequest != 'undefined') {
        let dapRequest = JSON.parse(localStorage.dapRequest);
        if (dapRequest.length <= 10) {
            for (let i in dapRequest) {
                calcAndDraw(dapRequest[i], [], dapRequest[i].name, false, false);
            }
            $("#pene-flytime-btn").click();
        }
        delete localStorage.dapRequest;
    }

    console.log('TIRPITZ IS THE BEST!!!');
});