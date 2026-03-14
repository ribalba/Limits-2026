var FEATURE_DATA_SIZE = 0;
var FEATURE_TIME = 1;
var FEATURE_PROMPT_TOKENS = 2;
var FEATURE_GENERATED_TOKENS = 3;
var FEATURE_TOTAL_TOKENS = 4;
var HEADER_PRECISION = 1000;

function toNumber(value, fallback) {
    var num = Number(value);
    if (isFinite(num)) {
        return num;
    }
    return fallback;
}

function clampNonNegative(value) {
    if (value < 0) {
        return 0;
    }
    return value;
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
    var text;
    var comma;

    if (!value || value === "-") {
        return 0;
    }

    text = String(value);
    comma = text.indexOf(",");
    if (comma !== -1) {
        text = text.slice(0, comma);
    }

    text = text.trim();
    if (!text || text === "-") {
        return 0;
    }

    return toNumber(text, 0);
}

function dataSizeBytes(r) {
    var requestBytes = toNumber(r.variables.request_length, 0);
    var responseBytes = toNumber(r.variables.body_bytes_sent, 0);
    if (responseBytes > requestBytes) {
        return responseBytes;
    }
    return requestBytes;
}

function headerNumber(headers, primaryName, secondaryName) {
    var value;

    if (!headers) {
        return 0;
    }

    value = headers[primaryName];
    if (value === undefined) {
        value = headers[secondaryName];
    }

    return toNumber(value, 0);
}

function pickNumber(source, keyA, keyB, keyC, fallback) {
    if (!source) {
        return fallback;
    }
    if (keyA && source[keyA] !== undefined) {
        return toNumber(source[keyA], fallback);
    }
    if (keyB && source[keyB] !== undefined) {
        return toNumber(source[keyB], fallback);
    }
    if (keyC && source[keyC] !== undefined) {
        return toNumber(source[keyC], fallback);
    }
    return fallback;
}

function formatHeaderValue(value) {
    var rounded = Math.round(clampNonNegative(value) * HEADER_PRECISION) / HEADER_PRECISION;
    if (!rounded) {
        return "0";
    }
    return String(rounded);
}

function featureCode(input) {
    if (input === "time") {
        return FEATURE_TIME;
    }
    if (input === "prompt_tokens") {
        return FEATURE_PROMPT_TOKENS;
    }
    if (input === "generated_tokens") {
        return FEATURE_GENERATED_TOKENS;
    }
    if (input === "total_tokens" || input === "token_count" || input === "tokens") {
        return FEATURE_TOTAL_TOKENS;
    }
    return FEATURE_DATA_SIZE;
}

function pointPair(rawPoint) {
    var x;
    var y;

    if (!rawPoint || rawPoint.length < 2) {
        return null;
    }

    x = toNumber(rawPoint[0], NaN);
    y = toNumber(rawPoint[1], NaN);
    if (!isFinite(x) || !isFinite(y)) {
        return null;
    }

    return [x, y];
}

function compileCurve(model) {
    var compiled = [];
    var i;
    var pair;

    if (!model || !model.points || !model.points.length) {
        return {
            inputCode: FEATURE_DATA_SIZE,
            points: compiled,
            clamp: false,
            needsTokens: false
        };
    }

    for (i = 0; i < model.points.length; i++) {
        pair = pointPair(model.points[i]);
        if (pair) {
            compiled.push(pair);
        }
    }

    compiled.sort(function (a, b) { return a[0] - b[0]; });

    return {
        inputCode: featureCode(model.input),
        points: compiled,
        clamp: model.extrapolate === "clamp",
        needsTokens: model.input === "prompt_tokens" ||
            model.input === "generated_tokens" ||
            model.input === "total_tokens" ||
            model.input === "token_count" ||
            model.input === "tokens"
    };
}

function compileRouteConfig(routeConfig) {
    var compiled = {
        embodiedRate: pickNumber(routeConfig, "embodied_rate_gCO2e_per_s", "embodied", "emboddied", 0),
        embodiedMgPerS: 0,
        gridIntensity: pickNumber(routeConfig, "grid_intensity_gCO2e_per_kWh", "grid_intensity", null, 0),
        gridIntensityHeader: "0",
        operationalMgPerMwh: 0,
        kind: "constant",
        constantEnergy: 0,
        constantEnergyHeader: "0",
        intercept: 0,
        timeCoeff: 0,
        sizeCoeff: 0,
        tokenCoeff: 0,
        promptTokenCoeff: 0,
        generatedTokenCoeff: 0,
        curve: null,
        needsTokens: false
    };
    var model = routeConfig ? routeConfig.energy_model : null;
    var kind;

    compiled.embodiedMgPerS = compiled.embodiedRate * 1000;
    compiled.gridIntensityHeader = formatHeaderValue(compiled.gridIntensity);
    compiled.operationalMgPerMwh = compiled.gridIntensity / 1000;

    if (typeof model === "number") {
        compiled.constantEnergy = clampNonNegative(model);
        compiled.constantEnergyHeader = formatHeaderValue(compiled.constantEnergy);
        return compiled;
    }

    kind = model && model.kind ? model.kind : "constant";
    compiled.kind = kind;

    if (kind === "linear") {
        compiled.intercept = pickNumber(model, "intercept_mWh", "intercept", null, 0);
        compiled.timeCoeff = pickNumber(model, "time_coeff_mWh_per_s", "time_coeff", null, 0);
        compiled.sizeCoeff = pickNumber(model, "size_coeff_mWh_per_byte", "size_coeff", null, 0);
        compiled.tokenCoeff = pickNumber(model, "token_coeff_mWh_per_token", "token_coeff", null, 0);
        compiled.promptTokenCoeff = pickNumber(
            model,
            "prompt_token_coeff_mWh_per_token",
            "prompt_token_coeff",
            null,
            0
        );
        compiled.generatedTokenCoeff = pickNumber(
            model,
            "generated_token_coeff_mWh_per_token",
            "generated_token_coeff",
            null,
            0
        );
        compiled.needsTokens = (
            compiled.tokenCoeff !== 0 ||
            compiled.promptTokenCoeff !== 0 ||
            compiled.generatedTokenCoeff !== 0
        );
        return compiled;
    }

    if (kind === "curve") {
        compiled.curve = compileCurve(model);
        compiled.needsTokens = compiled.curve.needsTokens;
        return compiled;
    }

    compiled.constantEnergy = clampNonNegative(pickNumber(model, "value_mWh", "value", null, 0));
    compiled.constantEnergyHeader = formatHeaderValue(compiled.constantEnergy);
    compiled.kind = "constant";
    return compiled;
}

function compileEnergyConfig() {
    var compiled = {};
    var route;
    var normalized;

    for (route in energy_config) {
        if (Object.prototype.hasOwnProperty.call(energy_config, route)) {
            normalized = normalizePath(route);
            compiled[normalized] = compileRouteConfig(energy_config[route]);
        }
    }

    return compiled;
}

function linearInterpolate(x, x0, y0, x1, y1) {
    if (x1 === x0) {
        return y1;
    }
    return y0 + ((x - x0) * (y1 - y0)) / (x1 - x0);
}

function featureValue(inputCode, timeSec, dataSize, totalTokens, promptTokens, generatedTokens) {
    if (inputCode === FEATURE_TIME) {
        return timeSec;
    }
    if (inputCode === FEATURE_PROMPT_TOKENS) {
        return promptTokens;
    }
    if (inputCode === FEATURE_GENERATED_TOKENS) {
        return generatedTokens;
    }
    if (inputCode === FEATURE_TOTAL_TOKENS) {
        return totalTokens;
    }
    return dataSize;
}

function evaluateCurve(curve, timeSec, dataSize, totalTokens, promptTokens, generatedTokens) {
    var points = curve.points;
    var xValue;
    var left;
    var right;
    var idx;

    if (!points || !points.length) {
        return 0;
    }

    xValue = featureValue(
        curve.inputCode,
        timeSec,
        dataSize,
        totalTokens,
        promptTokens,
        generatedTokens
    );

    left = points[0];
    right = points[points.length - 1];

    if (xValue <= left[0]) {
        if (curve.clamp || points.length < 2) {
            return left[1];
        }
        right = points[1];
        return linearInterpolate(xValue, left[0], left[1], right[0], right[1]);
    }

    if (xValue >= right[0]) {
        if (curve.clamp || points.length < 2) {
            return right[1];
        }
        left = points[points.length - 2];
        return linearInterpolate(xValue, left[0], left[1], right[0], right[1]);
    }

    for (idx = 0; idx < points.length - 1; idx++) {
        left = points[idx];
        right = points[idx + 1];
        if (xValue <= right[0]) {
            return linearInterpolate(xValue, left[0], left[1], right[0], right[1]);
        }
    }

    return right[1];
}

function evaluateEnergy(compiledConfig, timeSec, dataSize, totalTokens, promptTokens, generatedTokens) {
    if (!compiledConfig) {
        return 0;
    }

    if (compiledConfig.kind === "constant") {
        return compiledConfig.constantEnergy;
    }

    if (compiledConfig.kind === "linear") {
        return clampNonNegative(
            compiledConfig.intercept +
            compiledConfig.timeCoeff * timeSec +
            compiledConfig.sizeCoeff * dataSize +
            compiledConfig.tokenCoeff * totalTokens +
            compiledConfig.promptTokenCoeff * promptTokens +
            compiledConfig.generatedTokenCoeff * generatedTokens
        );
    }

    if (compiledConfig.kind === "curve") {
        return clampNonNegative(
            evaluateCurve(
                compiledConfig.curve,
                timeSec,
                dataSize,
                totalTokens,
                promptTokens,
                generatedTokens
            )
        );
    }

    return 0;
}

var compiled_energy_config = compileEnergyConfig();

function addCarbonHeaders(r) {
    var path = normalizePath(r.variables.uri || r.uri || "/");
    var endpointConfig = compiled_energy_config[path];
    var timeSec;
    var dataSize;
    var promptTokens = 0;
    var generatedTokens = 0;
    var totalTokens = 0;
    var energy;
    var embodiedMg;
    var totalMg;

    if (!endpointConfig) {
        return;
    }

    timeSec = parseTimeSeconds(r.variables.upstream_response_time);
    if (timeSec <= 0) {
        timeSec = parseTimeSeconds(r.variables.request_time);
    }

    dataSize = dataSizeBytes(r);

    if (endpointConfig.needsTokens) {
        promptTokens = headerNumber(r.headersOut, "X-Prompt-Tokens", "x-prompt-tokens");
        generatedTokens = headerNumber(r.headersOut, "X-Generated-Tokens", "x-generated-tokens");
        totalTokens = promptTokens + generatedTokens;
    }

    energy = evaluateEnergy(
        endpointConfig,
        timeSec,
        dataSize,
        totalTokens,
        promptTokens,
        generatedTokens
    );
    embodiedMg = endpointConfig.embodiedMgPerS * timeSec;
    totalMg = embodiedMg + (energy * endpointConfig.operationalMgPerMwh);

    if (endpointConfig.kind === "constant") {
        r.headersOut["Request-Energy"] = endpointConfig.constantEnergyHeader;
    } else {
        r.headersOut["Request-Energy"] = formatHeaderValue(energy);
    }
    r.headersOut["Grid-Intensity"] = endpointConfig.gridIntensityHeader;
    r.headersOut["Request-Embodied-CO2e"] = formatHeaderValue(embodiedMg);
    r.headersOut["Request-SCI"] = formatHeaderValue(totalMg);
}

export default { addCarbonHeaders };
