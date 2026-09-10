#!/usr/bin/env python3
"""生成测试 FIT：一段带坡度变化的路线（平 → 2% → 8% → 3% → -8% → 平），
用于模拟器回放测 Grade with Color 的坡度变色逻辑。
FIT 里 altitude 由坡度% × 距离累计出，speed 恒速 30km/h。"""
import time
from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.session_message import SessionMessage
from fit_tool.profile.messages.lap_message import LapMessage
from fit_tool.profile.profile_type import FileType, Manufacturer, Sport

OUT = '/Users/galaxyxin/GarminProjects/GradeWithColor/test_grade.fit'

now_ms = int(time.time() * 1000)
start_ms = now_ms - 300 * 1000  # 300 秒前

builder = FitFileBuilder()

file_id = FileIdMessage()
file_id.type = FileType.ACTIVITY
file_id.manufacturer = Manufacturer.DEVELOPMENT
file_id.product = 0
file_id.time_created = start_ms
builder.add(file_id)

# (坡度%, 时长秒) —— 每段 10 秒 @ 30km/h = 每 10 秒走 83.3m
speed_mps = 30.0 / 3.6   # ~8.33 m/s
segments = [
    (0.0, 30),   # 平路 30s (250m)
    (2.0, 30),   # 缓坡 2%
    (8.0, 30),   # 陡坡 8%
    (3.0, 30),   # 中坡 3%
    (-8.0, 30),  # 大下坡 -8%
    (0.0, 30),   # 回平路
]

total_dist_m = 0.0
total_alt = 0.0
rec = None
t = 0
for grade_pct, secs in segments:
    grade_frac = grade_pct / 100.0
    for sec in range(secs):
        rec = RecordMessage()
        rec.timestamp = start_ms + t * 1000
        rec.speed = speed_mps
        rec.enhanced_speed = speed_mps
        total_dist_m += speed_mps
        rec.distance = total_dist_m
        # 海拔 = 段起点海拔 + 坡度×水平距离
        total_alt += speed_mps * grade_frac
        rec.enhanced_altitude = total_alt
        rec.altitude = total_alt
        builder.add(rec)
        t += 1

session = SessionMessage()
session.start_time = start_ms
session.total_elapsed_time = float(t)
session.total_timer_time = float(t)
session.total_distance = total_dist_m
session.sport = Sport.CYCLING
builder.add(session)

# 增加 lap 消息（模拟器活动回放标准要求，缺它会回放无数据）
lap = LapMessage()
lap.start_time = start_ms
lap.total_elapsed_time = float(t)
lap.total_timer_time = float(t)
lap.total_distance = total_dist_m
lap.sport = Sport.CYCLING
builder.add(lap)

fit = builder.build()
data = fit.to_bytes()
with open(OUT, 'wb') as f:
    f.write(data)
print(f"生成完成: {OUT} ({len(data)} bytes, {t}s, {total_dist_m:.0f}m, 末海拔 {total_alt:.1f}m)")