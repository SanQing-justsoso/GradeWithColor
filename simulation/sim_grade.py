#!/usr/bin/env python3
"""坡度算法仿真对比：α-β(现状) vs 3s窗口 vs Kalman(4态)
模拟 Edge 840 + 1Hz + 无轮速(GNSS speed + 气压计) 场景。

生成带噪声的典型公路车数据，跑三条坡度曲线，量化延迟/噪声。
决策产出：确定下一步真机代码重构方案（Kalman 是否值得上）。
"""
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

np.random.seed(42)   # 可复现

# ================= 1. 真值坡度剖面 =================
# 距离域剖面：平路→6%→-8%→3%，模拟真实大范围
# 1Hz @ 平均速度 8m/s → 时间种子
GRADE_TRUE_SEGS = [  # (距离m, 坡度%)
    (0, 0.0),
    (120, 6.0),     # 平路120m后进入6%爬坡
    (600, -8.0),    # 480m长爬坡后急转-8%下坡
    (1100, 3.0),    # 下坡500m后转3%
    (1600, 0.0),    # 收尾平路
]
DT = 1.0            # 1Hz

# 构造逐秒真值（距离随时间积分，速度带主趋势）
def true_profile():
    # 时间网格（主：恒速8m/s + 轻加速)
    v_true = []
    t = 0
    while len(v_true) < 300:
        # 40s油门微调，平均~8m/s，波动少量
        v = 8.0 + 1.5*np.sin(t/60.0) + 0.6*np.random.randn()
        v = max(3.0, min(14.0, v))
        v_true.append(v); t += DT
    v_true = np.array(v_true)
    dist = np.cumsum(v_true)*DT
    # 坡度 -> 距离域查表（分段常值 + 边界快速过渡[约20m]）
    grade_true = grade_at(dist)
    return dist, grade_true, v_true

def grade_at(dist, rise=20.0):
    """分段坡度：每段目标值, 在段边界用 rise 米做线性过渡(模拟真实公路渐变)。
    设计: 0m~150m平路0%, 150m~170m切到6%, 保持到600m, 600~620m转-8%,
          保持到1100m(略起伏), 1100~1120m转3%, 保持到1550m, 1550~1570m回0%。"""
    segs=[  # (起始dist, 目标坡度%)
        (0,   0.0),
        (150, 6.0),
        (600, -8.0),
        (1100, 3.0),
        (1550, 0.0),
    ]
    g = np.zeros(len(dist))
    # 初始段赋第一个目标
    g[:] = segs[0][1]
    for i in range(1, len(segs)):
        d0, g0 = segs[i-1]
        d1, g1 = segs[i]
        # 过渡区 [d1-rise, d1] 线性从 g0→g1，之后保持 g1
        mask_t = (dist >= d1-rise) & (dist < d1)
        g[mask_t] = g0 + (g1-g0) * (1 - (dist[mask_t]-(d1-rise))/rise)
        g[dist >= d1] = g1
    return g

dist, grade_true, v_true = true_profile()
N = len(dist)
# 真值海拔 = 坡度积分(米)
alt_true = np.cumsum(grade_true/100.0 * v_true * DT)

# ================= 2. 加传感器噪声 =================
sigma_h = 0.40     # 气压计海拔噪声 (m) —— 一阶差分后放大
h_obs = alt_true + np.random.randn(N)*sigma_h

# GNSS 速度：真值 + 抖动(σ) + ~1s延迟(模拟响应慢/位置噪声)
sigma_v = 0.30     # m/s 速度噪声
v_gnss = np.zeros(N)
for k in range(N):
    v_gnss[k] = v_true[k] + np.random.randn()*sigma_v
# 1s延迟：v_gnss[k] 反映的是 k-1 时刻
v_gnss_delay = np.concatenate([[v_gnss[0]], v_gnss[:-1]])

# ================= 3a. α-β（当前实现，参数照抄 View.mc）=================
def alpha_beta(h, v, beta=0.30, alpha=0.60, afuse=0.70, smoothM=50.0, startThr=1.0):
    n = len(h)
    hHat, vh = 0.0, 0.0
    segD, segA = 0.0, 0.0
    lastD, lastA = 0.0, h[0]
    out = np.zeros(n)
    for k in range(n):
        dAlt = h[k]-lastA
        dDist = v[k]*DT
        lastA, lastD = h[k], lastD + dDist
        if dDist < 1.0:
            out[k]=0; continue
        dt = dDist/max(v[k],0.5)
        dt = max(0.5,min(3.0,dt))
        hPred = hHat + vh*dt
        innov = h[k]-hPred
        vh += (beta/dt)*innov
        hHat = hPred + alpha*innov
        gradeFast = (vh/max(v[k],0.5))*100.0
        segD += dDist; segA += dAlt
        segG = segA/segD*100; instG = dAlt/dDist*100
        flipped = (segG>startThr and instG<-startThr) or (segG<-startThr and instG>startThr)
        if flipped or segD>=smoothM:
            segD,segA = dDist,dAlt
        gradeSlow = segA/segD*100
        out[k] = afuse*gradeFast + (1-afuse)*gradeSlow
    return out

# ================= 3b. 3s 窗口（速度积分，非位置差分）=================
def window3s(h, v, win=3, thr=0.000001):
    n=len(h); out=np.zeros(n); accalt=0.0; accs=0.0
    for k in range(n):
        # 滑动窗口：累积最近 win 秒的 速度积分 和 海拔差
        if k>=win:
            # 用前缀和
            pass
    # 向量化：前缀和
    cums = np.concatenate([[0], np.cumsum(v*DT)])
    cuma = np.concatenate([[0], np.cumsum(h)])
    out=np.zeros(n)
    for k in range(n):
        if k<win:
            ds=cums[k+1]-cums[0]; da=cuma[k+1]-cuma[0]
        else:
            ds=cums[k+1]-cums[k+1-win]; da=cuma[k+1]-cuma[k+1-win]
        out[k]=(da/ds*100.0) if ds>thr else 0.0
    return out

# ================= 3c. Kalman 四状态 =================
# x = [h, vz, g] ；GNSS speed 把 vz 转成坡度。坡度 g 作为状态平滑。
# 量测1：h(气压计海拔, R_h)
# 量测2：vz_obs = v_gnss * g_prior ?? 不，改用直接速度法:
#   关键: 不用"g*vz锁定"做硬约束(会钉死g)。改用:
#   - 先计算 2s 窗口坡度观测 g_obs = 2s海拔差/2s速度积分 (速度域抗噪)
#   - 把 g_obs 作为坡度的直接量测喂给 Kalman, 状态转移里 g 由过程噪声+缓慢变化
def kalman4(h, v_gnss, win=2, r_h=0.16, q_vz=0.01, q_g=0.08, r_g=0.5):
    n=len(h)
    # 状态 x=[h, vz, g]（1D 数组约定）
    x=np.array([h[0],0.0,0.0]); P=np.eye(3)*0.5
    out=np.zeros(n)
    cums=np.concatenate([[0],np.cumsum(h)])
    cumv=np.concatenate([[0],np.cumsum(v_gnss)])
    H1=np.array([1.0,0.0,0.0])   # 海拔量测
    H2=np.array([0.0,0.0,1.0])   # 坡度量测
    for k in range(n):
        dt=1.0
        F=np.array([[1,dt,0],[0,1,0],[0,0,1]])
        x=F@x
        Q=np.diag([0.02,q_vz,q_g])
        P=F@P@F.T+Q
        # 量测1: 海拔 h（标量观测，手动标量卡尔曼增益）
        S1=H1@P@H1.T+r_h
        K1=P@H1/S1
        x=x+K1*(h[k]-H1@x); P=(np.eye(3)-np.outer(K1,H1))@P
        # 量测2: 2s坡度观测 g_obs
        if k>=win:
            ds=(cumv[k+1]-cumv[k+1-win])
            da=(cums[k+1]-cums[k+1-win])
            if ds>1.0:
                g_obs=da/ds*100.0
                S2=H2@P@H2.T+r_g
                K2=P@H2/S2
                x=x+K2*(g_obs-H2@x); P=(np.eye(3)-np.outer(K2,H2))@P
        out[k]=x[2]
    return out

# ================= 4. 跑三方案 =================
g_ab = alpha_beta(h_obs, v_gnss_delay)
g_w3 = window3s(h_obs, v_gnss_delay)
g_kf = kalman4(h_obs, v_gnss_delay)

# ================= 5. 量化指标 =================
# 延迟：0→6% 突变(找到第一个到6%的距离=120m对应时间idx) 后爬到50%真值(3%)所需时间
def time_of(dist, target):
    return np.argmax(dist>=target)
t0=time_of(dist,120.0)  # 进入爬坡时刻
def rise_time(g, t_start, pct_of=0.5):
    # 从 t_start 起，首次达到 6%*pct_of
    target=6.0*pct_of
    for k in range(t_start, len(g)):
        if g[k]>=target: return k-t_start
    return None
# 稳定段噪声（纯6%区间 300-560m）
stable=slice(time_of(dist,300),time_of(dist,550))
def noise(g,sl): return np.std(g[sl])

print("="*60)
print("坡度算法仿真对比 (1Hz, GNSS speed + 气压计, 无轮速)")
print("="*60)
for name,g in [("α-β(现状)",g_ab),("3s窗口",g_w3),("Kalman4态",g_kf)]:
    rt=rise_time(g,t0)
    ns=noise(g,stable)
    print(f"{name:14s} 延迟(入6%坡爬到3%): {str(rt)+'s' if rt is not None else 'N/A':>6}  稳定段噪声(σ): {ns:.2f}%")

# ================= 6. 画图 =================
fig,ax=plt.subplots(2,1,figsize=(12,7))
ax[0].plot(dist,grade_true,'k-',lw=2,label='真值')
ax[0].plot(dist,g_ab,'-',lw=1.2,label='α-β(现状)')
ax[0].plot(dist,g_w3,'--',lw=1.2,label='3s窗口')
ax[0].plot(dist,g_kf,'-',lw=1.5,label='Kalman4态')
ax[0].set_ylabel('坡度 %'); ax[0].legend(); ax[0].set_title('坡度曲线')
ax[0].grid(alpha=0.3)
ax[1].plot(dist,h_obs,'-',alpha=0.6,label='海拔观测(带噪声)')
ax[1].plot(dist,alt_true,'k-',lw=1.5,label='真值海拔')
ax[1].set_xlabel('距离(m)'); ax[1].set_ylabel('海拔(m)'); ax[1].legend(); ax[1].grid(alpha=0.3)
plt.tight_layout()
plt.savefig('sim_grade_compare.png',dpi=120)
print("\n曲线已存 sim_grade_compare.png")