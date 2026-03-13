function toNumber(value, fallback) {
    var num = Number(value);
    if (isFinite(num)) {
        return num;
    }
    return fallback;
}

function normalizePath(path) {
    if (!path) {
        return "/";
    }
    if (path.length > 1 && path.charAt(path.length - 1) === "/") {
        return path.slice(0, path.length - 1);
    }
    return path;
}

function parseTimeSeconds(value) {
    if (!value || value === "-") {
        return 0;
    }
    var first = String(value).split(",")[0].trim();
    if (!first || first === "-") {
        return 0;
    }
    return toNumber(first, 0);
}

function dataSizeBytes(r) {
    var requestBytes = toNumber(r.variables.request_length, 0);
    var responseBytes = toNumber(r.variables.body_bytes_sent, 0);
    if (responseBytes > requestBytes) {
        return responseBytes;
    }
    return requestBytes;
}

function energyConfigForPath(path) {
    var normalized = normalizePath(path);
    if (energy_config[normalized]) {
        return energy_config[normalized];
    }
    return null;
}

function evaluateCurve(model, context) {
    if (!model.points || !model.points.length) {
        return 0;
    }

    var points = [];
    for (var i = 0; i < model.points.length; i++) {
        var point = model.points[i];
        if (!point || point.length < 2) {
            continue;
        }
        var x = toNumber(point[0], NaN);
        var y = toNumber(point[1], NaN);
        if (isFinite(x) && isFinite(y)) {
            points.push([x, y]);
        }
    }

    if (!points.length) {
        return 0;
    }

    points.sort(function (a, b) { return a[0] - b[0]; });

    var xValue = model.input === "time" ? context.timeSec : context.dataSize;
    var left = points[0];
    var right = points[points.length - 1];
    var extrapolate = model.extrapolate || "linear_tail";

    if (xValue <= left[0]) {
        if (extrapolate === "clamp" || points.length < 2) {
            return left[1];
        }
        right = points[1];
        return linearInterpolate(xValue, left[0], left[1], right[0], right[1]);
    }

    if (xValue >= right[0]) {
        if (extrapolate === "clamp" || points.length < 2) {
            return right[1];
        }
        left = points[points.length - 2];
        return linearInterpolate(xValue, left[0], left[1], right[0], right[1]);
    }

    for (var idx = 0; idx < points.length - 1; idx++) {
        left = points[idx];
        right = points[idx + 1];
        if (xValue >= left[0] && xValue <= right[0]) {
            return linearInterpolate(xValue, left[0], left[1], right[0], right[1]);
        }
    }

    return 0;
}

function linearInterpolate(x, x0, y0, x1, y1) {
    if (x1 === x0) {
        return y1;
    }
    return y0 + ((x - x0) * (y1 - y0)) / (x1 - x0);
}

function evaluateEnergy(model, context) {
    if (!model) {
        return 0;
    }

    if (typeof model === "number") {
        return model;
    }

    var kind = model.kind || "constant";
    if (kind === "constant") {
        return toNumber(model.value, 0);
    }

    if (kind === "linear") {
        return (
            toNumber(model.intercept, 0) +
            toNumber(model.time_coeff, 0) * context.timeSec +
            toNumber(model.size_coeff, 0) * context.dataSize
        );
    }

    if (kind === "curve") {
        return evaluateCurve(model, context);
    }

    return 0;
}

function fixed(value) {
    var num = toNumber(value, 0);
    if (num < 0) {
        num = 0;
    }
    return num.toFixed(6);
}

function addCarbonHeaders(r) {
    var path = normalizePath(r.variables.uri || r.uri || "/");
    var endpointConfig = energyConfigForPath(path);

    var timeSec = parseTimeSeconds(r.variables.upstream_response_time);
    if (timeSec <= 0) {
        timeSec = parseTimeSeconds(r.variables.request_time);
    }

    var context = {
        timeSec: timeSec,
        dataSize: dataSizeBytes(r)
    };

    var energy = 0;
    var embodiedRate = 0;
    var gridIntensity = 0;

    if (endpointConfig) {
        energy = evaluateEnergy(endpointConfig.energy_model, context);
        embodiedRate = toNumber(endpointConfig.embodied, toNumber(endpointConfig.emboddied, 0));
        gridIntensity = toNumber(endpointConfig.grid_intensity, 0);
    }

    var embodied = embodiedRate * timeSec;
    var operational = energy * gridIntensity;
    var total = embodied + operational;

    r.headersOut["X-Energy-Value"] = fixed(energy);
    r.headersOut["X-Embodied-Rate"] = fixed(embodiedRate);
    r.headersOut["X-Embodied-gCO2eq"] = fixed(embodied);
    r.headersOut["X-Grid-Intensity"] = fixed(gridIntensity);
    r.headersOut["X-Operational-gCO2eq"] = fixed(operational);
    r.headersOut["X-Request-Carbon-gCO2eq"] = fixed(total);
    r.headersOut["X-Request-Time-Sec"] = fixed(timeSec);
    r.headersOut["X-Data-Size-Bytes"] = String(context.dataSize);
}

export default { addCarbonHeaders };
