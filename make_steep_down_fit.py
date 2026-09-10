#!/usr/bin/env python3
"""生成测试 FIT：全程恒定 -20.4% 大下坡（约60秒），用于看单值极端坡度显示效果。
speed 恒速 30km/h，海拔随坡度线性下降。"""
import time
from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.session_message import SessionMessage
from fit_tool.profile.messages.lap_message import LapMessage
from fit_tool.profile.profile_type import FileType, Manufacturer, Sport

OUT = '/Users/galaxyxin/GarminProjects/GradeWithColor/test_steep_down.fit'
GRADE_PCT = -20.4
DURATION_S = 60

now_ms = int(time.time() * 1000)
start_ms = now_ms - DURATION_S * 1000

builder = FitFileBuilder()
file_id = FileIdMessage()
file_id.type = FileType.ACTIVITY
file_id.manufacturer = Manufacturer.DEVELOPMENT
file_id.product = 0
file_id.time_created = start_ms
builder.add(file_id)

speed_mps = 30.0 / 3.6   # ~8.33 m/s
grade_frac = GRADE_PCT / 100.0
total_dist_m = 0.0
total_alt = 0.0
t = 0
for sec in range(DURATION_S):
    rec = RecordMessage()
    rec.timestamp = start_ms + t * 1000
    rec.speed = speed_mps
    rec.enhanced_speed = speed_mps
    total_dist_m += speed_mps
    rec.distance = total_dist_m
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
print(f"生成完成: {OUT} ({len(data)} bytes, {t}s, {total_dist_m:.0f}m, {GRADE_PCT}% 下坡, 末海拔 {total_alt:.1f}m)")