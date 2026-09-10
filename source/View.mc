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

    // --- KF-vz 卡尔曼滤波状态（状态 x=[h, vz]，坡度=vz/v 导出）---
    // 仿真验证：比手写 α-β 同延迟下噪声 -35%，比短窗口差分好得多（σ~40%被淘汰）
    private var _hHat as Float;    // 状态x1: 滤波后高度 (m)
    private var _vh as Float;      // 状态x2: 垂直速度估计 (m/s)，正=上升
    private var _P11 as Float;     // 协方差 P[0][0]（高度方差）
    private var _P12 as Float;     // 协方差 P[0][1]
    private var _P22 as Float;     // 协方差 P[1][1]（垂直速度方差）
    private var _rH as Float = 0.16;    // 海拔观测噪声 R（气压计 σh²）
    private var _qVz as Float = 0.02;    // 垂直速度过程噪声 Q（控制响应/平滑权衡）
    private var _lastAlt as Float?;   // 上次 altitude (m)
    private var _lastDist as Float?;  // 上次 elapsedDistance (m)
    private var _dt as Float;     // 上一帧时间步长 (s)，用距离差分/速度近似

    // 坡度估值（实时，%）
    private var _grade as Float?;

    // 分档阈值（缓坡/中坡/陡坡/极陡边界 %），默认兜底
    private var _zoneThr as Array = [3, 6, 9, 13] as Array;
    // 起步阈值：多大坡度才算上坡变色 %
    private var _startThr as Float = 1.0;

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
        _P11 = 1.0;
        _P12 = 0.0;
        _P22 = 1.0;
        _dt = 1.0;
        _grade = null;
        _currentAlt = null;
    }

    // KF-vz 卡尔曼滤波：状态 x=[h, vz]，坡度=vz/v 导出
    //  核心(仿真验证, 见 simulation/): 比手写α-β同延迟下噪声-35%, 短窗差分被淘汰(σ~40%)
    //  不用"坡度硬约束/g·v锁定"(会钉死坡度), 用海拔观测驱动垂直速度累积, 再转坡度
    //  2状态标量展开(Monkey C 无矩阵库), 计算量可忽略
    function compute(info as Activity.Info) as Numeric or Duration or String or Null {
        _currentAlt = info.altitude;

        var alt = info.altitude;
        var dist = info.elapsedDistance;
        var speed = info.currentSpeed;   // 水平速度 (m/s)，用于 vz/v

        if (alt == null || dist == null) {
            _grade = null;
            return null;
        }

        if (_lastDist == null || _lastAlt == null) {
            // 首帧：初始化高度状态，只记基线
            _hHat = alt;
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

        // 估计时间步长 dt：用距离差分/水平速度（GNSS speed，避免位置差分卷入横向漂移）
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

        // 本帧瞬时坡度（仅用于方向急转重置判断）
        var instGradePct = (dDist > 0) ? (dAlt / dDist * 100.0) : 0.0;
        handleDirectionFlip(instGradePct, dAlt, alt);

        // ---------- KF-vz 预测步骤 ----------
        // x' = F·x,  F=[[1,dt],[0,1]]:  h' = h + vz*dt;  vz' = vz
        var hPred = _hHat + _vh * _dt;
        // P' = F·P·F^T + Q,  Q=diag(0, q_vz)
        var P11p = _P11 + 2.0 * _P12 * _dt + _P22 * _dt * _dt;
        var P12p = _P12 + _P22 * _dt;
        var P22p = _P22 + _qVz;

        // ---------- KF-vz 更新步骤（海拔观测, R=rH）----------
        var S = P11p + _rH;                       // 新息协方差
        var K1 = P11p / S;                        // 高度增益
        var K2 = P12p / S;                        // 垂直速度增益
        var innov = alt - hPred;                   // 新息
        _hHat = hPred + K1 * innov;               // 更新高度
        _vh = _vh + K2 * innov;                   // 更新垂直速度
        // 更新协方差 P = (I-K·H)·P'
        _P11 = (1.0 - K1) * P11p;
        _P12 = (1.0 - K1) * P12p;
        _P22 = P22p - K2 * P12p;

        // ---------- 坡度输出：vz / v（无慢速基准融合，KF本身够稳）----------
        _grade = (_vh / v) * 100.0;

        return null;
    }

    // 方向急转重置：KF 在"陡上坡→陡下坡"极速反转时有惯性滞后，
    //   当瞬时坡度与当前估计坡度方向相反且幅度>起步阈值时，强制重定向垂直速度 vz
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
        // —— 映射到 KF 垂直速度过程噪声 q_vz（响应/平滑权衡）与海拔观测噪声 r_h
        //   q_vz 大 → 更快跟手但略抖； q_vz 小 → 更稳但延迟略增（仿真标定）
        var sm = 50;
        var s = Application.Properties.getValue("Smoothing");
        if (s instanceof Lang.Number) {
            sm = (s as Lang.Number);
        }
        if (sm <= 30) {
            _qVz = 0.08;   // 快速：高过程噪声 → 强硬垂直速度响应
            _rH = 0.16;    // 观测噪声适中
        } else if (sm >= 80) {
            _qVz = 0.005;  // 平滑：低过程噪声 → 稳、抗抖
            _rH = 0.16;
        } else {
            _qVz = 0.02;   // 平衡（仿真最优，轻降噪）
            _rH = 0.16;
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