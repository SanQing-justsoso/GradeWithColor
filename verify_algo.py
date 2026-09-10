"""模拟验证 Grade with Color 的新算法（α-β + 双尺度融合）vs 旧算法（段累计差分）。
用 test_grade.fit 回放数据，参数与 View.mc 一致。"""
import math, fitparse

# ---------- 从 FIT 读回放数据 ----------
fs = fitparse.FitFile('/Users/galaxyxin/GarminProjects/GradeWithColor/test_grade.fit')
recs = []
for m in fs.get_messages('record'):
    f = {x.name: x.value for x in m.fields}
    recs.append((f.get('distance'), f.get('enhanced_altitude'), f.get('speed')))
recs = [(d,a,s) for d,a,s in recs if d is not None and a is not None]

def old_algo(recs, smoothM=50.0, startThr=1.0):
    """旧：段累计差分。返回坡度%序列"""
    out=[]
    lastD, lastA=recs[0][0],recs[0][1]
    segD,segA=0.0,0.0
    for d,a,s in recs[1:]:
        dAlt=a-lastA; dDist=d-lastD
        lastD,lastA=d,a
        if dDist<1.0: out.append(None); continue
        segD+=dDist; segA+=dAlt
        segG=segA/segD*100; instG=dAlt/dDist*100
        flipped=(segG>startThr and instG<-startThr) or (segG<-startThr and instG>startThr)
        if flipped or segD>=smoothM:
            segD,segA=dDist,dAlt
        out.append(segA/segD*100)
    return out

def new_algo(recs, mode='balance', smoothM=50.0, startThr=1.0):
    """新：α-β 估算垂直速度 + 双尺度融合"""
    if mode=='fast':   beta,alpha,afuse=0.55,0.7,0.8
    elif mode=='smooth':beta,alpha,afuse=0.15,0.5,0.6
    else:              beta,alpha,afuse=0.30,0.6,0.7
    hHat,vh=0.0,0.0
    lastD,lastA=recs[0][0],recs[0][1]
    segD,segA=0.0,0.0
    out=[]
    for d,a,s in recs[1:]:
        dAlt=a-lastA; dDist=d-lastD
        lastD,lastA=d,a
        if dDist<1.0: out.append(None); continue
        v=s if (s is not None and s>=0.5) else dDist
        dt=dDist/v
        dt=max(0.5,min(3.0,dt))
        hPred=hHat+vh*dt
        innov=a-hPred
        vh=vh+(beta/dt)*innov
        hHat=hPred+alpha*innov
        gradeFast=(vh/v)*100.0
        segD+=dDist; segA+=dAlt
        segG=segA/segD*100; instG=dAlt/dDist*100
        flipped=(segG>startThr and instG<-startThr) or (segG<-startThr and instG>startThr)
        if flipped or segD>=smoothM:
            segD,segA=dDist,dAlt
        gradeSlow=segA/segD*100
        out.append(afuse*gradeFast+(1-afuse)*gradeSlow)
    return out

# 真值坡度段（与 make_test_fit 一致）
SECTIONS=[(0.0,0),(2.0,0),(8.0,0),(3.0,0),(-8.0,0),(0.0,0)]  # 只存坡度，距离按30km/h·10s=83.3m
def true_grade(dist_m):
    seg_len=250.0
    grades=[0,2,8,3,-8,0]
    idx=min(int(dist_m//seg_len), len(grades)-1)
    return grades[idx]

old=new_old=None
o=old_algo(recs)
n=new_algo(recs,'balance')
nf=new_algo(recs,'fast')
ns=new_algo(recs,'smooth')

print("=== 坡度段边界响应对比（模拟器回放 30km/h，每10s=83.3m）===")
print("进入 8% 陡坡时刻约在 500m（第60s）")
print(f"{'距离m':>7} {'真值%':>6} {'旧算法%':>8} {'新-平衡%':>8} {'新-快速%':>8} {'新-平滑%':>8}")
target_dist=[100,250,400,470,500,530,600,700,800,900,1000,1030,1100,1200,1250,1350,1450]
for td in target_dist:
    # 找最接近该距离的帧
    idx=min(range(len(recs)), key=lambda i: abs(recs[i][0]-td))
    print(f"{recs[idx][0]:7.0f} {true_grade(recs[idx][0]):6.0f} {o[idx] if o[idx] is not None else float('nan'):8.2f} {n[idx] if n[idx] is not None else float('nan'):8.2f} {nf[idx] if nf[idx] is not None else float('nan'):8.2f} {ns[idx] if ns[idx] is not None else float('nan'):8.2f}")

# 量化：进入陡坡的响应快慢（从500m到坡度爬到>=7%所需的距离/帧数）
def settle_dist(algo_out, threshold=6.5, start_m=500):
    for i in range(len(recs)):
        if recs[i][0]>=start_m and algo_out[i] is not None and algo_out[i]>=threshold:
            return recs[i][0]-start_m
    return None
print("\n=== 进入8%陡坡后，坡度爬到7%所需距离（越小=响应越快）===")
print(f"旧算法: {settle_dist(o)}m")
print(f"新平衡: {settle_dist(n)}m")
print(f"新快速: {settle_dist(nf)}m")
print(f"新平滑: {settle_dist(ns)}m")