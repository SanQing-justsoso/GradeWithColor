// View.mc - Grade with Color 坡度变色字段
// 实时显示上坡坡度%（环法配色按档位给数字标色），下坡清晰/平路中性色
// 右上角显示当前海拔。格子底色保持中性深灰，数字按坡度档位变色。
//
// 算法：连续坡度段累计 —— 用 info.altitude（气压计优先）差分 / info.elapsedDistance 差分
//      抗气压阶跃噪声。平滑窗口（累计米数）可调，起步阈值可调。
import Toybox.Activity;
import Toybox.Application;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.Math;
import Toybox.System;
import Toybox.Time;
import Toybox.WatchUi;

class GradeWithColorView extends WatchUi.DataField {

    // --- α-β 滤波状态（估计"垂直速度 vh"代替"等一段距离求高度差"）---
    private var _hHat as Float;   // 滤波后高度 (m)
    private var _vh as Float;     // 垂直速度估计 (m/s)，正=上升
    private var _lastAlt as Float?;   // 上次 altitude (m)
    private var _lastDist as Float?;  // 上次 elapsedDistance (m)
    private var _dt as Float;     // 上一帧时间步长 (s)，用距离差分/速度近似

    // 慢速坡度（稳定）：段累计法，保留作"慢速基准"防抖
    private var _segDist as Float;   // 当前段累计水平距离 (m)
    private var _segAlt as Float;    // 当前段累计爬升 (m)

    // 坡度估值（实时，%）
    private var _grade as Float?;

    // 分档阈值（缓坡/中坡/陡坡/极陡边界 %），默认兜底
    private var _zoneThr as Array = [3, 6, 9, 13] as Array;
    // 起步阈值：多大坡度才算上坡变色 %
    private var _startThr as Float = 1.0;
    // 平滑窗口：慢速坡度的段累计距离 (m)，越短响应越快
    private var _smoothM as Float = 50.0;
    // 快速/慢速融合权重（α_ab），越大越依赖 α-β 快速坡度（跟手但略抖）
    private var _alphaFuse as Float = 0.7;

    // α-β 参数（按 dt≈1s 调，受 Smoothing 档位映射）
    private var _alphaAB as Float = 0.6;   // 高度跟随
    private var _betaAB as Float = 0.3;    // 垂直速度响应

    // 颜色：0=平缓中性(不标色) 1=缓坡黄 2=中坡橙 3=陡坡红 4=极陡紫
    private var _zoneColors as Array = [
        0xFFFFFF,   // 默认白（中性，走 normColor 分支）
        0xFFFF00,   // 缓坡 黄
        0xFF7F00,   // 中坡 橙
        0xFF0000,   // 陡坡 红
        0xB000FF    // 极陡 紫
    ] as Array;

    private var _currentAlt as Float?;  // 当前海拔 (m)
    private var _altUnit as String;     // 海拔单位

    // 主题感知配色（昼夜两套，onUpdate 开头按码表夜间模式切换）
    private var _bg as Number = 0x000000;        // 背景色
    private var _neutralFg as Number = 0xFFFFFF; // 中性坡度字色（平路/下坡）
    private var _altFg as Number = 0xCCCCCC;     // 海拔字色

    function initialize() {
        DataField.initialize();
        loadSettings();

        var settings = System.getDeviceSettings();
        var isMetric = (settings.paceUnits == System.UNIT_METRIC);
        _altUnit = isMetric ? "m" : "ft";

        // 初始未定位
        _lastDist = null;
        _lastAlt = null;
        _hHat = 0.0;
        _vh = 0.0;
        _dt = 1.0;
        _segDist = 0.0;
        _segAlt = 0.0;
        _grade = null;
        _currentAlt = null;
    }

    // α-β 滤波 + 垂直速度法 + 双尺度融合
    //  核心：坡度%(≈tanθ) = vh / v，即"垂直速度 / 水平速度"
    //  —— 不用等一段距离，实时估计垂直速度，天然比窗口差分快半个窗口
    //  双尺度：快速坡度来自 α-β 的 vh（跟手），慢速坡度来自段累计（稳定），按 _alphaFuse 融合
    function compute(info as Activity.Info) as Numeric or Duration or String or Null {
        _currentAlt = info.altitude;

        var alt = info.altitude;
        var dist = info.elapsedDistance;
        var speed = info.currentSpeed;   // 水平速度 (m/s)，用于 vh/v

        if (alt == null || dist == null) {
            _grade = null;
            return null;
        }

        if (_lastDist == null || _lastAlt == null) {
            // 首帧：只记录基线
            _lastDist = dist;
            _lastAlt = alt;
            return null;
        }

        var dAlt = alt - _lastAlt;      // 这段爬升 (m)
        var dDist = dist - _lastDist;   // 这段水平距离 (m)
        _lastDist = dist;
        _lastAlt = alt;

        // 距离太短（接近静止/传感器暂停）忽略
        if (dDist < 1.0) {
            return null;
        }

        // 估计时间步长 dt：用距离差分/水平速度，避免依赖不稳定的时钟 tick
        var v = speed;
        if (v == null || v < 0.5) {
            v = dDist;   // 兜底：假设速度≈距离(即 dt≈1s)
        }
        _dt = dDist / v;
        if (_dt < 0.5) {
            _dt = 0.5;   // 夹住防除零/过小
        }
        if (_dt > 3.0) {
            _dt = 3.0;
        }

        // 本帧瞬时坡度（百分点），用于方向反转判断
        var instGradePct = (dDist > 0) ? (dAlt / dDist * 100.0) : 0.0;

        // ---------- α-β 滤波：预测 + 更新，估计垂直速度 vh ----------
        // 方向急转重置：瞬时坡度与当前估计坡度方向相反且幅度>起步阈值 →
        //   直接把 vh 重置为按本帧增量算的瞬时垂直速度(dAlt/dt)，
        //   解决 α-β 在"陡上坡→陡下坡"极速反转时惯性滞后几帧的问题
        handleDirectionFlip(instGradePct, dAlt, alt);

        var hHatPred = _hHat + _vh * _dt;                     // 预测高度
        var innov = alt - hHatPred;                           // 残差（新观测 vs 预测）
        _vh = _vh + (_betaAB / _dt) * innov;                  // 更新垂直速度（β 控制响应）
        _hHat = hHatPred + _alphaAB * innov;                  // 更新高度（α 控制跟随）

        // 快速坡度（α-β 垂直速度版）：坡度% ≈ vh / v
        // 注意 _betaAB 已含 dt 归一，这里 vh 已是 m/s
        var gradeFast = (_vh / v) * 100.0;

        // ---------- 慢速坡度（段累计，稳定基准）----------
        _segDist += dDist;
        _segAlt += dAlt;
        var segGrade = _segAlt / _segDist * 100.0;
        var instGrade = dAlt / dDist * 100.0;

        // 换段：方向翻转 或 达到窗口距离
        var flipped =
            (segGrade > _startThr && instGrade < -(_startThr)) ||
            (segGrade < -_startThr && instGrade > _startThr);
        var windowHit = (_segDist >= _smoothM);
        if (flipped || windowHit) {
            _segDist = dDist;
            _segAlt = dAlt;
        }
        var gradeSlow = _segAlt / _segDist * 100.0;

        // ---------- 双尺度融合（跟手 + 稳定）----------
        _grade = _alphaFuse * gradeFast + (1.0 - _alphaFuse) * gradeSlow;

        return null;
    }

    // 方向急转重置：α-β 在"陡上坡→陡下坡"极速反转时有惯性滞后，
    //   当瞬时坡度与当前估计坡度方向相反且幅度>起步阈值时，强制重定向垂直速度 vh
    function handleDirectionFlip(instPct, dAlt, alt) as Void {
        if (_grade == null) {
            return;
        }
        var curG = _grade.toFloat();
        var flippedUp = (curG > _startThr && instPct < -_startThr);   // 上坡突然变下坡
        var flippedDown = (curG < -_startThr && instPct > _startThr); // 下坡突然变上坡
        if (flippedUp || flippedDown) {
            // 按本帧增量重置垂直速度：dAlt / dt（m/s）
            _vh = dAlt / _dt;
            _hHat = alt;   // 高度对齐本轮观测
        }
    }

    // ---------- 设置 ----------

    function readThreshold(key as String, def as Number) as Float {
        var v = Application.Properties.getValue(key);
        if (v instanceof Lang.Number) {
            return (v as Lang.Number).toFloat();
        }
        return def.toFloat();
    }

    private function loadSettings() as Void {
        // 平滑档：30=快速(跟手) / 50=平衡 / 80=平滑(稳)
        // —— 映射到 α-β 的 β（垂直速度响应）与快慢融合权重
        var sm = 50;
        var s = Application.Properties.getValue("Smoothing");
        if (s instanceof Lang.Number) {
            sm = (s as Lang.Number);
        }
        _smoothM = sm.toFloat();   // 慢速基准的段累计窗口（米）
        if (sm <= 30) {
            _betaAB = 0.55;        // 快速：大幅提升垂直速度响应 → 跟手
            _alphaAB = 0.7;
            _alphaFuse = 0.8;      // 更依赖快速坡度
        } else if (sm >= 80) {
            _betaAB = 0.15;        // 平滑：压低响应 → 稳、抗抖
            _alphaAB = 0.5;
            _alphaFuse = 0.6;      // 更依赖慢速基准
        } else {
            _betaAB = 0.30;        // 平衡
            _alphaAB = 0.6;
            _alphaFuse = 0.7;
        }

        _startThr = readThreshold("StartThr", 1);
        _zoneThr = [
            readThreshold("Zone1Max", 3),
            readThreshold("Zone2Max", 6),
            readThreshold("Zone3Max", 9),
            readThreshold("Zone4Max", 13)
        ] as Array;
    }

    function onSettingsChanged() as Void {
        loadSettings();
    }

    // 当前坡度所在档位 0~4（0=平缓/不标色）
    function zoneIndex(g) {
        if (g == null) {
            return 0;
        }
        g = g.toFloat();
        if (g < _startThr) {
            return 0;   // 平路/缓坡不标色
        }
        for (var i = 0; i < _zoneThr.size(); i++) {
            if (g < (_zoneThr[i] as Number).toFloat()) {
                return i + 1;
            }
        }
        return _zoneThr.size();
    }

    // 背景亮度（保留，判深浅用）
    function luminance(color) {
        var r = (color / 0x10000) % 0x100;
        var g = (color / 0x100) % 0x100;
        var b = color % 0x100;
        return (r * 299 + g * 587 + b * 114) / 1000;
    }

    // 按码表夜间模式切换整套配色（每天 onUpdate 开头调用，运行中切模式即生效）
    function applyTheme() as Void {
        var settings = System.getDeviceSettings();
        // isNightModeEnabled 在 API 4.1.2+；运行时判断字段存在防旧设备崩溃
        if (settings has :isNightModeEnabled && settings.isNightModeEnabled) {
            _bg = 0x000000;          // 夜间深底
            _neutralFg = 0xFFFFFF;   // 中性字白
            _altFg = 0xCCCCCC;       // 海拔浅灰
            _zoneColors = [
                0xFFFFFF,            // 平缓（中性白）
                0xFFFF00,            // 缓坡 亮黄
                0xFF7F00,            // 中坡 橙
                0xFF0000,            // 陡坡 红
                0xB000FF             // 极陡 紫
            ] as Array;
        } else {
            _bg = 0xF0F0F0;          // 白天浅底（贴 Garmin off-white 默认）
            _neutralFg = 0x1A1A1A;   // 中性字深灰（浅底可读）
            _altFg = 0x555555;       // 海拔中灰
            _zoneColors = [
                0x1A1A1A,            // 平缓（中性深灰）
                0x8A6D00,            // 缓坡 深琥珀（浅底可读）
                0xB06500,            // 中坡 深橙
                0xB00000,            // 陡坡 深红
                0x6A0DAD             // 极陡 深紫
            ] as Array;
        }
    }

    function onUpdate(dc as Dc) as Void {
        var w = dc.getWidth();
        var h = dc.getHeight();

        // 按码表夜间模式切换整套配色（白天浅底 / 夜间深底）
        applyTheme();

        // 底色：白天浅灰 / 夜间黑（贴合 Garmin 默认主题，与周边字段协调）
        var bg = _bg;
        dc.setColor(bg, bg);
        dc.clear();

        // 字号：海拔小字
        var altFont = Graphics.FONT_XTINY;
        if (h >= 100) {
            altFont = Graphics.FONT_SMALL;
        }

        var grade = _grade;

        if (grade == null || _currentAlt == null) {
            // 未定位：中性色大字 "--"
            dc.setColor(_neutralFg, Graphics.COLOR_TRANSPARENT);
            dc.drawText(w / 2, h / 2, Graphics.FONT_NUMBER_HOT,
                "--",
                Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
            return;
        }

        // --- 坡度数字（大字，"xx.x%" 整串水平居中）---
        var gradeText = formatGrade(grade);   // 如 "4.6" / "-15.5"
        var gradeDisp = gradeText + "%";      // "4.6%" / "-15.5%"

        // 档位颜色：上坡才标色，下坡/平路用中性色
        var zi = zoneIndex(grade);
        var gradeColor = _zoneColors[zi];
        var isClimb = (zi > 0);
        var showColor = isClimb;
        var fgDisp = showColor ? gradeColor : _neutralFg;

        // 字号阶梯（从大到小），宽度不够时逐级降，防小格溢出
        var fonts = [Graphics.FONT_NUMBER_THAI_HOT, Graphics.FONT_NUMBER_HOT,
                     Graphics.FONT_NUMBER_MEDIUM, Graphics.FONT_NUMBER_MILD, Graphics.FONT_SMALL] as Array;
        // 按格高粗选起始档（大格用最大，小格直接用中档，再由宽度细调）
        var startIdx = 0;
        if (h < 65) {
            startIdx = 2;             // 超小格：从中号起
        } else if (h < 100) {
            startIdx = 1;             // 中格：从 HOT 起
        }
        var gradeFont = fonts[startIdx];
        // 宽度预算：整串 ≤ 格宽 92%（留边）
        var availW = w * 92 / 100;
        var i = startIdx;
        while (i < fonts.size()) {
            var f = fonts[i];
            var txtW = dc.getTextWidthInPixels(gradeDisp, f);
            if (txtW <= availW) {
                gradeFont = f;
                break;
            }
            i++;
        }

        // 底部 baseline（大字统一一行）
        var baseline = h * 86 / 100;
        var gradeAsc = Graphics.getFontAscent(gradeFont);
        var gradeDesc = Graphics.getFontDescent(gradeFont);
        var gradeY = baseline - (gradeAsc - gradeDesc) / 2;

        // 整串水平居中
        dc.setColor(fgDisp, Graphics.COLOR_TRANSPARENT);
        dc.drawText(w / 2, gradeY, gradeFont,
            gradeDisp,
            Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);

        // --- 右上角：当前海拔 (小字，中性色) 位置与 BiggerSpeed 右上角一致 ---
        var altText = formatAlt(_currentAlt);
        dc.setColor(_altFg, Graphics.COLOR_TRANSPARENT);
        dc.drawText(w * 75 / 100, h * 28 / 100, altFont,
            altText,
            Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
    }

    private function formatGrade(g) {
        // 一代小数（正负号保留，如 "4.6" / "-4.2"）
        if (g == null) {
            return "--";
        }
        var s = (g.toFloat()).format("%.1f");
        return s;
    }

    private function formatAlt(alt) {
        // 海拔：米→英尺按单位，整数米显示
        if (alt == null) {
            return "--";
        }
        var v = alt.toFloat();
        if (_altUnit == "ft") {
            v = v * 3.28084;
        }
        // 保留整数 + 单位
        return v.format("%d") + " " + _altUnit;
    }
}