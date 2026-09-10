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

# 真值坡度段（与 make_test_fit 一致，含极端 20.2% / -15.5%）
# 每段 @30km/h·10s=83.3m；段长 = secs*8.333
def true_grade(dist_m):
    segments=[  # (坡度%, 时长s)
        (0.0,30),(2.0,30),(8.0,30),(20.2,20),(-15.5,20),(3.0,15),(0.0,15)]
    acc=0.0
    for g,secs in segments:
        seglen=secs*8.333
        if dist_m < acc+seglen:
            return g
        acc+=seglen
    return 0.0

old=new_old=None
o=old_algo(recs)
n=new_algo(recs,'balance')
nf=new_algo(recs,'fast')
ns=new_algo(recs,'smooth')

print("=== 坡度段边界响应对比（模拟器回放 30km/h，每10s=83.3m）===")
print("焦点: 20.2% 极陡上坡 与 -15.5% 大下坡 极端切换")
print(f"{'距离m':>7} {'真值%':>7} {'旧算法%':>8} {'新-平衡%':>9} {'新-快速%':>9} {'新-平滑%':>9}")
# 段边界: 0%~250m, 2%~500m, 8%~750m, 20.2%~916m, -15.5%~1083m, 3%~1208m, 0%~1333m
target_dist=[100,300,550,730,760,850,900,916,940,980,1020,1050,1083,1110,1150,1200,1230,1300]
for td in target_dist:
    idx=min(range(len(recs)), key=lambda i: abs(recs[i][0]-td))
    print(f"{recs[idx][0]:7.0f} {true_grade(recs[idx][0]):7.0f} {o[idx] if o[idx] is not None else float('nan'):8.2f} {n[idx] if n[idx] is not None else float('nan'):9.2f} {nf[idx] if nf[idx] is not None else float('nan'):9.2f} {ns[idx] if ns[idx] is not None else float('nan'):9.2f}")

# 极端值稳定性：全程 max/min 与 NaN 检查
def stats(algo_out,name):
    vals=[x for x in algo_out if x is not None]
    mx=max(vals); mn=min(vals)
    nan=sum(1 for x in algo_out if x is not None and (x!=x))
    print(f"{name:12s} 范围[{mn:7.2f}%, {mx:7.2f}%]  NaN数={nan}")
print("\n=== 全程数值稳定性（无 NaN/发散）===")
stats(o,'旧算法'); stats(n,'新-平衡'); stats(nf,'新-快速'); stats(ns,'新-平滑')

# 极端档位检查：20.2% 应落最陡档(紫)，-15.5% 应中性不标色
def zone(g,thr=[3,6,9,13]):
    if g is None: return 0
    if g<1.0: return 0
    for i,t in enumerate(thr):
        if g<t: return i+1
    return len(thr)
print("\n=== 极端坡度档位 ===")
i20=min(range(len(recs)),key=lambda i:abs(recs[i][0]-916))   # 20.2段中部
i15=min(range(len(recs)),key=lambda i:abs(recs[i][0]-1083))  # -15.5段中部
for lbl,i in [('20.2%段',i20),('-15.5%段',i15)]:
    print(f"{lbl}: 真值={true_grade(recs[i][0])}% 平衡档={zone(n[i])} 快速档={zone(nf[i])} 平滑档={zone(ns[i])}  (档1黄/2橙/3红/4紫)")