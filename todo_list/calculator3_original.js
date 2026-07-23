function calcV3Pen(m, D, v_imp, K) {
    return Math.pow(m, 0.69) * Math.pow(v_imp, 1.38) * Math.pow(D, -1.07) * K * 0.0000001;
}

function calculator3(m, D, c_D, v_0, K, norm) {
    let originData;
    $.ajax({
        type: "GET",
        contentType: "application/json;charset=UTF-8",
        url: "dap/list-impact-speed",
        data: {
            "mass": m,
            "diametr": D,
            "airDrag": c_D,
            "speed": v_0,
        },
        async: false,
        success: function (result) {
            originData = result;
        },
        error: function (e) {
            console.log(e);
            alert('获取弹速数据失败，您可尝试使用V2版本弹速算法！');
        }
    });
    let data_dict = {
        distance: [],
        armor_abs: [],
        armor_vert: [],
        armor_hori: [],
        v_impact: [],
        fly_time: [],
        impact_angle: [],
        impact_angle2: [],
    };
    // 最小射程内的弹道数据
    let pen_abs = calcV3Pen(m, D, originData[0].velocity, K);
    let impact_angle = Math.max(0, originData[0].angle - norm);
    for (let i = 0.1; i < originData[0].dist; i += 0.1) {
        data_dict.distance.push(i);
        data_dict.armor_vert.push(maxFixed(pen_abs * Math.cos(Math.PI / 180 * impact_angle), 1));
        data_dict.fly_time.push(originData[0].time);
        data_dict.impact_angle.push(originData[0].angle);
    }
    // 弹道数据
    for (let i in originData) {
        pen_abs = calcV3Pen(m, D, originData[i].velocity, K);
        impact_angle = Math.max(0, originData[i].angle - norm);
        data_dict.distance.push(originData[i].dist);
        data_dict.armor_vert.push(maxFixed(pen_abs * Math.cos(Math.PI / 180 * impact_angle), 1));
        data_dict.fly_time.push(originData[i].time);
        data_dict.impact_angle.push(originData[i].angle);
    }
    return data_dict;
}