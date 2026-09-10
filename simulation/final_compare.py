#!/usr/bin/env python3
"""可复现的最终坡度算法对比（自包含，固定 seed，KPI 明确）。
注意: 不复用 sim_grade.py(其顶层有副作用+seed不同步), 这里独立生成数据并跑。
对比: α-β(现状/View.mc参数) vs KF-vz(正确建模Kalman)。
用户分析: "Kalman比10s滑动窗口好" —— 这里验证 Kalman(或α-β) 的实际 KPI。
KPI: 1) 入坡爬到真值90%延迟(s)  2) 稳定段噪声σ%  3) 稳态偏差  4) 峰值过冲
"""
import numpy as np
np.random.seed(1234)

# ---------- 数据生成 (模拟 Edge+1Hz+无轮速) ----------
DT=1.0
def grade_at(dist, rise=20.0):
    segs=[(0,0.0),(150,6.0),(600,-8.0),(1100,3.0),(1550,0.0)]
    g=np.full(len(dist),segs[0][1])
    for i in range(1,len(segs)):
        d0,g0=segs[i-1]; d1,g1=segs[i]
        mt=(dist>=d1-rise)&(dist<d1)
        g[mt]=g0+(g1-g0)*(1-(dist[mt]-(d1-rise))/rise)
        g[dist>=d1]=g1
    return g

# 速度: 真值8m/s+轻微波动
N=300
v_true=8.0+1.5*np.sin(np.arange(N)/60.0)+0.6*np.random.randn(N)
v_true=np.clip(v_true,3,14)
dist=np.cumsum(v_true)*DT
grade_true=grade_at(dist)
alt_true=np.cumsum(grade_true/100*v_true*DT)
# 噪声
sigma_h=0.40
h_obs=alt_true+np.random.randn(N)*sigma_h
sigma_v=0.30
v_gnss=v_true+np.random.randn(N)*sigma_v
v_gnss_delay=np.concatenate([[v_gnss[0]],v_gnss[:-1]])   # 1s延迟

# ---------- α-β (与 View.mc 相同参数) ----------
def alpha_beta(h,v,beta=0.30,alpha=0.60,afuse=0.70,smoothM=50.0,startThr=1.0):
    n=len(h);hHat,vh=0.0,0.0;segD,segA=0.0,0.0;lastA=h[0];lastD=0.0
    out=np.zeros(n)
    for k in range(n):
        dAlt=h[k]-lastA; dDist=v[k]*DT; lastA,lastD=h[k],lastD+dDist
        if dDist<1.0: out[k]=0; continue
        dt=max(0.5,min(3.0,dDist/max(v[k],0.5)))
        hPred=hHat+vh*dt; innov=h[k]-hPred
        vh+=(beta/dt)*innov; hHat=hPred+alpha*innov
        gf=(vh/max(v[k],0.5))*100.0
        segD+=dDist;segA+=dAlt
        segG=segA/segD*100;instG=dAlt/dDist*100
        flip=(segG>startThr and instG<-startThr)or(segG<-startThr and instG>startThr)
        if flip or segD>=smoothM: segD,segA=dDist,dAlt
        gs=segA/segD*100
        out[k]=afuse*gf+(1-afuse)*gs
    return out

# ---------- KF-vz: 状态[h,vz], 海拔观测累积vz, 坡度=vz/v ----------
def kalman_vz(h,v,r_h,q_vz):
    n=len(h);x=np.array([h[0],0.0]);P=np.eye(2)*2.0;H=np.array([1.0,0.0]);F=np.array([[1.0,1.0],[0.0,1.0]])
    out=np.zeros(n)
    for k in range(n):
        x=F@x;P=F@P@F.T+np.diag([0.0,q_vz])
        S=H@P@H.T+r_h;K=P@H/S
        x=x+K*(h[k]-H@x);P=(np.eye(2)-np.outer(K,H))@P
        out[k]=(x[1]/max(v[k],0.5))*100.0
    return out

# ---------- KPI ----------
def metrics(g):
    t_in=int(np.argmax(dist>=150)); target=6.0*0.9
    rt=next((k-t_in for k in range(t_in,len(g)) if g[k]>=target),None)
    sl=slice(int(np.argmax(dist>=210)),int(np.argmax(dist>=560)))
    ns=float(np.std(g[sl]))
    ss=slice(int(np.argmax(dist>=300)),int(np.argmax(dist>=560)))
    bias=float(np.mean(g[ss])-6.0)
    ov=float(max(0.0,np.max(g[t_in:int(np.argmax(dist>=600))])-6.0))
    return rt,ns,bias,ov

ga=alpha_beta(h_obs,v_gnss_delay)
gv1=kalman_vz(h_obs,v_gnss_delay,0.16,0.02)
gv2=kalman_vz(h_obs,v_gnss_delay,0.16,0.05)
gv3=kalman_vz(h_obs,v_gnss_delay,0.08,0.04)

print("="*72)
print("最终对比 seed=1234 | 1Hz | 气压σh=0.4m | GNSS speed(抖+1s延迟)")
print("入坡平路→6%过渡20m")
print(f"{'算法':14s} {'到90%真值延迟':>13s} {'稳定噪声σ%':>10s} {'稳态偏差%':>9s} {'过冲%':>7s}")
for name,g in [("α-β(现状)",ga),("KF-vz 轻降噪",gv1),("KF-vz 平衡",gv2),("KF-vz 响应快",gv3)]:
    rt,ns,bias,ov=metrics(g)
    print(f"{name:14s} {str(rt)+'s':>13s} {ns:9.2f}% {bias:8.2f}% {ov:6.2f}%")
print()
print("结论: 对比 α-β 与 KF-vz —— 若 KF-vz 在同/更低延迟下噪声更低 → Kalman 值得上真机。")