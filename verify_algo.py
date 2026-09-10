"""模拟验证 Grade with Color 当前算法（KF-vz 卡尔曼，与 View.mc 同一标量展开式）。
对比: KF-vz vs 旧段累计差分 vs α-β(之前版本)，用 test_grade.fit 回放数据（含极端坡度）。
验证: 极端坡度不发散、方向急转重置生效、档位正确。
"""
import fitparse

# ---------- 从 FIT 读回放数据 ----------
fs = fitparse.FitFile('/Users/galaxyxin/GarminProjects/GradeWithColor/test_grade.fit')
recs = []
for m in fs.get_messages('record'):
    f = {x.name: x.value for x in m.fields}
    recs.append((f.get('distance'), f.get('enhanced_altitude'), f.get('speed')))
recs = [(d,a,s) for d,a,s in recs if d is not None and a is not None]
N=len(recs)

# ---------- KF-vz (与 View.mc 相同的 2 状态标量展开) ----------
def kf_vz(recs, q_vz=0.02, r_h=0.16, startThr=1.0):
    out=[None]
    hHat=recs[0][1]; vh=0.0; P11=P22=1.0; P12=0.0
    lastD,lastA=recs[0][0],recs[0][1]
    # 首帧 grade 未初始化（与真机: 首帧只记基线 _grade 保持 null）
    grade=None
    for d,a,s in recs[1:]:
        dAlt=a-lastA; dDist=d-lastD
        lastD,lastA=d,a
        if dDist<1.0: out.append(None); continue
        v=s if (s is not None and s>=0.5) else dDist
        dt=dDist/v
        dt=max(0.5,min(3.0,dt))
        # KF 预测
        hPred=hHat+vh*dt
        P11p=P11+2*P12*dt+P22*dt*dt
        P12p=P12+P22*dt
        P22p=P22+q_vz
        # 方向急转重置（与 View.mc handleDirectionFlip 严格一致: 只重置 vh/hHat, 不重置协方差）
        if grade is not None:
            instPct=dAlt/dDist*100.0
            curG=grade
            fu=(curG>startThr and instPct<-startThr)
            fd=(curG<-startThr and instPct>startThr)
            if fu or fd:
                vh=dAlt/dt; hHat=a
        # KF 更新
        S=P11p+r_h
        K1=P11p/S; K2=P12p/S
        innov=a-hPred
        hHat=hPred+K1*innov
        vh=vh+K2*innov
        P11=(1-K1)*P11p; P12=(1-K1)*P12p; P22=P22p-K2*P12p
        grade=(vh/v)*100.0
        out.append(grade)
    return out

# ---------- 旧段累计差分（对照） ----------
def old_algo(recs, smoothM=50.0, startThr=1.0):
    out=[None]
    lastD,lastA=recs[0][0],recs[0][1]
    segD,segA=0.0,0.0
    for d,a,s in recs[1:]:
        dAlt=a-lastA; dDist=d-lastD
        lastD,lastA=d,a
        if dDist<1.0: out.append(None); continue
        segD+=dDist; segA+=dAlt
        segG=segA/segD*100; instG=dAlt/dDist*100
        flip=(segG>startThr and instG<-startThr) or (segG<-startThr and instG>startThr)
        if flip or segD>=smoothM: segD,segA=dDist,dAlt
        out.append(segA/segD*100)
    return out

def true_grade(dist_m):
    segments=[(0.0,30),(2.0,30),(8.0,30),(20.2,20),(-15.5,20),(3.0,15),(0.0,15)]
    acc=0.0
    for g,secs in segments:
        if dist_m<acc+secs*8.333: return g
        acc+=secs*8.333
    return 0.0

gkf=kf_vz(recs)
go=old_algo(recs)

print("=== KF-vz (真机算法) vs 旧段累计差分 —— 极端坡度验证 ===")
print(f"{'距离m':>7} {'真值%':>7} {'KF-vz%':>9} {'旧差分%':>9}")
target_dist=[100,300,550,730,760,850,900,916,940,980,1020,1050,1083,1110,1150,1200,1230,1300]
for td in target_dist:
    idx=min(range(len(recs)),key=lambda i:abs(recs[i][0]-td))
    kv=gkf[idx] if gkf[idx] is not None else float('nan')
    od=go[idx] if go[idx] is not None else float('nan')
    print(f"{recs[idx][0]:7.0f} {true_grade(recs[idx][0]):7.0f} {kv:9.2f} {od:9.2f}")

def stats(algo_out,name):
    vals=[x for x in algo_out if x is not None]
    mx=max(vals); mn=min(vals)
    nan=sum(1 for x in algo_out if x is not None and (x!=x))
    print(f"  {name:10s} 范围[{mn:6.2f}%, {mx:6.2f}%]  NaN数={nan}")
print("\n=== 全程数值稳定性 ===")
stats(gkf,'KF-vz'); stats(go,'旧差分')

def zone(g):
    if g is None: return 0
    if g<1.0: return 0
    for i,t in enumerate([3,6,9,13]):
        if g<t: return i+1
    return 4
print("\n=== 极端档位 (KF-vz) ===")
i20=min(range(len(recs)),key=lambda i:abs(recs[i][0]-850))   # 20.2段前部
i20m=min(range(len(recs)),key=lambda i:abs(recs[i][0]-916))
i15=min(range(len(recs)),key=lambda i:abs(recs[i][0]-1083))
for lbl,i in [('20.2%段前部',i20),('20.2%段中',i20m),('-15.5%段',i15)]:
    print(f"  {lbl}: 真值={true_grade(recs[i][0])}% KF-vz={gkf[i]:.2f}% 档={zone(gkf[i])} (1黄/2橙/3红/4紫)")