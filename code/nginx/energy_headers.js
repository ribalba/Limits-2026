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

function responseHeaderValue(r, names) {
    if (!r.headersOut) {
        return null;
    }

    for (var i = 0; i < names.length; i++) {
        var name = names[i];
        var value = r.headersOut[name];
        if (value !== undefined) {
            return value;
        }

        value = r.headersOut[name.toLowerCase()];
        if (value !== undefined) {
            return value;
        }
    }

    return null;
}

function modelNumber(source, keys, fallback) {
    for (var i = 0; i < keys.length; i++) {
        var key = keys[i];
        if (source[key] !== undefined) {
            return toNumber(source[key], fallback);
        }
    }
    return fallback;
}

function energyConfigForPath(path) {
    var normalized = normalizePath(path);
    if (energy_config[normalized]) {
        return energy_config[normalized];
    }
    return null;
}

function featureValue(context, input) {
    if (input === "time") {
        return context.timeSec;
    }
    if (input === "prompt_tokens") {
        return context.promptTokens;
    }
    if (input === "generated_tokens") {
        return context.generatedTokens;
    }
    if (input === "total_tokens" || input === "token_count" || input === "tokens") {
        return context.totalTokens;
    }
    return context.dataSize;
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

    var xValue = featureValue(context, model.input);
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
        return modelNumber(model, ["value", "value_mWh"], 0);
    }

    if (kind === "linear") {
        return (
            modelNumber(model, ["intercept", "intercept_mWh"], 0) +
            modelNumber(model, ["time_coeff", "time_coeff_mWh_per_s"], 0) * context.timeSec +
            modelNumber(model, ["size_coeff", "size_coeff_mWh_per_byte"], 0) * context.dataSize +
            modelNumber(model, ["token_coeff", "token_coeff_mWh_per_token"], 0) * context.totalTokens +
            modelNumber(model, ["prompt_token_coeff", "prompt_token_coeff_mWh_per_token"], 0) * context.promptTokens +
            modelNumber(model, ["generated_token_coeff", "generated_token_coeff_mWh_per_token"], 0) * context.generatedTokens
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
        dataSize: dataSizeBytes(r),
        promptTokens: toNumber(responseHeaderValue(r, ["X-Prompt-Tokens"]), 0),
        generatedTokens: toNumber(responseHeaderValue(r, ["X-Generated-Tokens"]), 0)
    };
    context.totalTokens = context.promptTokens + context.generatedTokens;

    var energy = 0;
    var embodiedRate = 0;
    var gridIntensity = 0;

    if (endpointConfig) {
        energy = evaluateEnergy(endpointConfig.energy_model, context);
        embodiedRate = modelNumber(endpointConfig, ["embodied", "emboddied", "embodied_rate_gCO2e_per_s"], 0);
        gridIntensity = modelNumber(endpointConfig, ["grid_intensity", "grid_intensity_gCO2e_per_kWh"], 0);
    }

    var embodied = embodiedRate * timeSec;
    var embodiedMg = embodied * 1000;
    var operationalMg = (energy * gridIntensity) / 1000;
    var totalMg = embodiedMg + operationalMg;

    r.headersOut["Request-Energy"] = fixed(energy);
    r.headersOut["Grid-Intensity"] = fixed(gridIntensity);
    r.headersOut["Request-Embodied-CO2e"] = fixed(embodiedMg);
    r.headersOut["Request-SCI"] = fixed(totalMg);
}

export default { addCarbonHeaders };
