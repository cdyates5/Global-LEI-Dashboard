#!/usr/bin/env python3
"""
Build the Global Growth Leading Indicators dashboard.

Fetches source series from FRED, rebuilds the six calibrated LEI composites
(US, Australia, UK, Euro Area, Japan, China) and injects the data into
template.html -> index.html (a single self-contained file).

Requires env var FRED_API_KEY (free: https://fredaccount.stlouisfed.org/apikeys)
Run:  FRED_API_KEY=xxxx python build.py
"""
import os, sys, json, time, warnings, requests
import numpy as np, pandas as pd
from itertools import product
warnings.filterwarnings("ignore")

KEY = os.environ.get("FRED_API_KEY")
if not KEY:
    sys.exit("ERROR: set FRED_API_KEY (free key: https://fredaccount.stlouisfed.org/apikeys)")

SERIES = [
 "IRLTLT01AUM156N","IR3TIB01AUM156N","IRLTLT01GBM156N","IR3TIB01GBM156N","IRLTLT01JPM156N","IR3TIB01JPM156N",
 "BSCICP02GBM460S","BSCICP02EZM460S","CSCICP02EZM460S","CSCICP02JPM460S","CSCICP02GBM460S","CSCICP02AUM460S",
 "PMETAINDEXM","PCOPPUSDM","XTEXVA01KRM667S","XTEXVA01CNM667S","XTIMVA01CNM667S","VIXCLS","CHNLOLITOAASTSAM",
 "NGDPRSAXDCAUQ","NGDPRSAXDCGBQ","CLVMNACSCAB1GQEA19","JPNRGDPEXP",
 "AUSRECDM","GBRRECDM","JPNRECDM","EURORECDM","CHNRECDM","NIKKEI225",
 "T10Y2Y","BAA10Y","PERMIT","IC4WSA","UMCSENT","AWHMAN","NEWORDER","M2REAL","GDPC1","USREC",
 "CRDQUSAPABIS","CRDQGBAPABIS","CRDQJPAPABIS","CRDQAUAPABIS","CRDQXMAPABIS","CRDQCNAPABIS",
 "IR3TIB01CNM156N","CHNGDPNQDSMEI","IRLTLT01DEM156N","ECBMRRFR",
]

def fetch_all():
    raw, fails = {}, []
    for s in SERIES:
        for attempt in range(4):
            try:
                r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                    params={"series_id": s, "api_key": KEY, "file_type": "json"}, timeout=60)
                r.raise_for_status()
                raw[s] = [(o["date"], o["value"]) for o in r.json().get("observations", [])
                          if o["value"] not in (".", "")]
                break
            except Exception:
                time.sleep(2 + attempt * 2)
        else:
            fails.append(s)
    if fails:
        print("WARNING: could not fetch:", fails, file=sys.stderr)
        if len(fails) > 6:
            sys.exit("Too many series failed; aborting.")
    return raw

raw = fetch_all()

# ---------------- transforms & helpers ----------------
def S(sid):
    obs=raw[sid]; idx=pd.to_datetime([d for d,_ in obs]); val=pd.to_numeric([v for _,v in obs],errors="coerce")
    return pd.Series(val,index=idx).dropna()
def M(sid): return S(sid).resample("MS").mean()
def yoy(s): return s.pct_change(12, fill_method=None)*100
def zc(s):
    s=s.dropna(); return (s-s.mean())/s.std()
def gdp_yoy_m(sid):
    q=S(sid); return (q.pct_change(4, fill_method=None)*100).resample("MS").ffill()
def ycv(a,b): return (M(a)-M(b)).dropna()
def cm(l,f,tf,c,sh,co): return {"label":l,"id":f,"tf":tf,"cat":c,"short":sh,"col":co}
def v_survey(sid):
    m=M(sid); return [("level",m),("6m chg",m.diff(6)),("6m chg 3mma",m.diff(6).rolling(3).mean())]
def v_yoy(sid):
    y=yoy(M(sid)); return [("YoY %",y),("YoY % 3mma",y.rolling(3).mean())]
def v_inv_level(sid):
    m=-M(sid); return [("inv level",m),("inv 3mma",m.rolling(3).mean())]
def v_inv_yoy(sid):
    y=-yoy(M(sid)); return [("inv YoY %",y),("inv YoY 3mma",y.rolling(3).mean())]
def v_yoychg(sid):
    d=M(sid).diff(12); return [("YoY chg",d),("YoY chg 3mma",d.rolling(3).mean())]
def v_cli(sid):
    m=M(sid); return [("level",m),("6m chg",m.diff(6)),("6m chg 3mma",m.diff(6).rolling(3).mean())]
def v_credit(sid):
    q=S(sid); g=q.pct_change(4, fill_method=None)*100
    end=pd.Timestamp.today().normalize().replace(day=1)
    def up(x):
        x=x.dropna(); idx=pd.date_range(x.index[0], end, freq="MS")
        return x.reindex(idx).ffill(limit=8)      # BIS credit is quarterly: carry latest print up to 2q
    return [("credit YoY",up(g)),("credit impulse",up(g.diff(4))),("credit impulse 2q",up(g.diff(2)))]
def v_rate_inv(sid):
    m=M(sid); return [("inv level",-m),("inv 6m chg",-m.diff(6)),("inv 12m chg",-m.diff(12))]

W = range(3, 7)   # calibrate transforms to a 3-6 month design lead (VP style)

def build(name,code,cands,coincident,coin_name,rec_id,mav,rec_note):
    tgt=coincident.dropna(); zvars=[]
    for key,label,cat,short,col,fid,variants,opt in cands:
        opts=[None] if opt else []
        for tf,ser in variants: opts.append((cm(label,fid,tf,cat,short,col), zc(ser)))
        zvars.append((key,opts))
    best=None
    for combo in product(*[range(len(o)) for _,o in zvars]):
        cols={};metas={};order=[]
        for (key,opts),ci in zip(zvars,combo):
            v=opts[ci]
            if v is None: continue
            metas[key]=v[0];cols[key]=v[1];order.append(key)
        if len(order)<3: continue
        zdf=pd.DataFrame(cols).sort_index()
        comp=zdf.mean(axis=1).where(zdf.notna().sum(axis=1)>=mav).dropna()
        j=pd.concat([comp.rename("c"),tgt.rename("t")],axis=1,sort=False).dropna()
        rs=[j["c"].corr(j["t"].shift(-k)) for k in W]; score=np.nanmean(rs)
        if best is None or score>best[0]: best=(score,order,metas,zdf)
    score,order,metas,zdf=best
    navail=zdf.notna().sum(axis=1)
    comp_full=zdf.mean(axis=1).where(navail>=mav).dropna()
    anchor=navail[navail>=mav].index[-1]
    comp=comp_full[comp_full.index<=anchor]; start=comp.index[0]
    breadth=((zdf>0).sum(axis=1)/zdf.notna().sum(axis=1)*100).reindex(comp.index)
    coin=tgt[tgt.index>=start]
    j=pd.concat([comp.rename("c"),coin.rename("t")],axis=1,sort=False).dropna()
    cor={}
    for k in range(0,13):
        r=j["c"].corr(j["t"].shift(-k)); cor[k]=None if pd.isna(r) else round(float(r),3)
    LAG=max(W,key=lambda k: cor[k] if cor[k] is not None else -9)
    unck=max(range(0,13),key=lambda k: cor[k] if cor[k] is not None else -9)
    rec=S(rec_id).resample("MS").max(); rec=rec[rec.index>=start]
    spans=[];inr=False;s0=None
    for dt,v in rec.items():
        if v>=.5 and not inr: inr=True;s0=dt
        elif v<.5 and inr: inr=False;spans.append([s0.strftime("%Y-%m-%d"),dt.strftime("%Y-%m-%d")])
    if inr: spans.append([s0.strftime("%Y-%m-%d"),rec.index[-1].strftime("%Y-%m-%d")])
    zf=zdf.ffill(limit=3)
    contrib={k:(None if pd.isna(zf[k].get(anchor,np.nan)) else round(float(zf[k].get(anchor)),2)) for k in order}
    def ser(s):
        s=s.dropna(); return {"d":[d.strftime("%Y-%m") for d in s.index],"v":[round(float(x),3) for x in s.values]}
    print("%-14s z=%+.2f  lead %dm r=%s  ->%s  (n=%d)"%(name,comp.iloc[-1],LAG,cor[LAG],anchor.strftime("%Y-%m"),len(order)))
    return code,{"composite":ser(comp),"components":{k:ser(zdf[zdf.index>=start][k]) for k in order},
        "cmeta":metas,"order":order,"n_avail":ser(navail[navail.index>=start].astype(float)),"breadth":ser(breadth),
        "ip_yoy":ser(coin),"coin_name":coin_name,"recessions":spans,
        "leadlag":{"best_k":int(LAG),"best_r":cor[LAG],"corrs":cor,"uncon_k":int(unck),"uncon_r":cor[unck],"win_mean":round(float(score),3)},
        "contrib_latest":contrib,
        "meta":{"name":name,"code":code,"last_date":anchor.strftime("%B %Y"),
            "last_value":round(float(comp.iloc[-1]),2),"prev_value":round(float(comp.iloc[-2]),2),
            "yr_ago":round(float(comp.iloc[-13]),2) if len(comp)>13 else None,
            "breadth_last":round(float(breadth.dropna().iloc[-1]),0),
            "ip_last":round(float(coin.iloc[-1]),2),"ip_last_date":coin.index[-1].strftime("%B %Y"),
            "start":start.strftime("%Y"),"rec_note":rec_note}}

C_COM="#FFB36B";C_TR="#5FE0C0";C_MF="#74D98A";C_RT="#7FB4FF";C_S1="#F58FB0";C_S2="#E9D26B";C_RK="#C79BFF";C_CH="#F4A259";C_EQ="#8FD0E9";C_CR="#E0777D"
OR="OECD-dated recessions (to 2022)"
COUNTRIES={}
jobs=[
 ("United States","US",[
   ("yc","Yield curve (10y-2y)","Rates","YieldCv",C_RT,"T10Y2Y",[("level",M("T10Y2Y"))],False),
   ("credit","Credit spread (Baa, inv.)","Credit","Credit",C_RK,"BAA10Y",v_inv_level("BAA10Y"),False),
   ("permits","Building permits","Housing","Permits",C_COM,"PERMIT",v_yoy("PERMIT"),False),
   ("claims","Jobless claims (inv.)","Labour","Claims",C_TR,"IC4WSA",v_inv_yoy("IC4WSA"),False),
   ("sent","Consumer sentiment","Consumer","Sentmt",C_S1,"UMCSENT",v_survey("UMCSENT"),False),
   ("hours","Mfg weekly hours","Labour","Hours",C_MF,"AWHMAN",v_yoychg("AWHMAN"),False),
   ("capex","Core capex orders","Manufacturing","Capex",C_S2,"NEWORDER",v_yoy("NEWORDER"),False),
   ("m2","Real M2","Money","RealM2",C_EQ,"M2REAL",v_yoy("M2REAL"),False),
   ("creditimp","Credit impulse (BIS)","Credit","CredImp",C_CR,"CRDQUSAPABIS",v_credit("CRDQUSAPABIS"),True),
  ], gdp_yoy_m("GDPC1"),"GDP YoY","USREC",6,"NBER-dated recessions"),
 ("Australia","AU",[
   ("metals","Industrial commodities","Commodities","Metals",C_COM,"PMETAINDEXM",v_yoy("PMETAINDEXM"),False),
   ("kr_exp","Global trade (Korea exp.)","Trade","KRexp",C_TR,"XTEXVA01KRM667S",v_yoy("XTEXVA01KRM667S"),False),
   ("cn_exp","Global manufacturing (China exp.)","Manufacturing","CNexp",C_MF,"XTEXVA01CNM667S",v_yoy("XTEXVA01CNM667S"),False),
   ("yc","Yield curve (10y-3m)","Rates","YieldCv",C_RT,"AU 10Y - 3M",[("level",ycv("IRLTLT01AUM156N","IR3TIB01AUM156N"))],False),
   ("cci","Consumer confidence","Survey","ConsConf",C_S2,"CSCICP02AUM460S",v_survey("CSCICP02AUM460S"),True),
   ("creditimp","Credit impulse (BIS)","Credit","CredImp",C_CR,"CRDQAUAPABIS",v_credit("CRDQAUAPABIS"),True),
  ], gdp_yoy_m("NGDPRSAXDCAUQ"),"GDP YoY","AUSRECDM",3,OR),
 ("United Kingdom","UK",[
   ("bci","Business confidence","Survey","BizConf",C_S1,"BSCICP02GBM460S",v_survey("BSCICP02GBM460S"),False),
   ("cci","Consumer confidence","Survey","ConsConf",C_S2,"CSCICP02GBM460S",v_survey("CSCICP02GBM460S"),False),
   ("yc","Yield curve (10y-3m)","Rates","YieldCv",C_RT,"GB 10Y - 3M",[("level",ycv("IRLTLT01GBM156N","IR3TIB01GBM156N"))],False),
   ("vix_inv","Financial stress (inv.)","Risk","Stress",C_RK,"VIXCLS",v_inv_level("VIXCLS"),False),
   ("creditimp","Credit impulse (BIS)","Credit","CredImp",C_CR,"CRDQGBAPABIS",v_credit("CRDQGBAPABIS"),True),
  ], gdp_yoy_m("NGDPRSAXDCGBQ"),"GDP YoY","GBRRECDM",3,OR),
 ("Euro Area","EA",[
   ("bci","Business confidence","Survey","BizConf",C_S1,"BSCICP02EZM460S",v_survey("BSCICP02EZM460S"),False),
   ("cci","Consumer confidence","Survey","ConsConf",C_S2,"CSCICP02EZM460S",v_survey("CSCICP02EZM460S"),False),
   ("yc","Yield curve (Bund 10y - policy)","Rates","YieldCv",C_RT,"DE 10Y - ECB refi",[("level",ycv("IRLTLT01DEM156N","ECBMRRFR"))],False),
   ("kr_exp","Global trade (Korea exp.)","Trade","KRexp",C_TR,"XTEXVA01KRM667S",v_yoy("XTEXVA01KRM667S"),False),
   ("metals","Industrial commodities","Commodities","Metals",C_COM,"PMETAINDEXM",v_yoy("PMETAINDEXM"),True),
   ("creditimp","Credit impulse (BIS)","Credit","CredImp",C_CR,"CRDQXMAPABIS",v_credit("CRDQXMAPABIS"),True),
  ], gdp_yoy_m("CLVMNACSCAB1GQEA19"),"GDP YoY","EURORECDM",3,OR),
 ("Japan","JP",[
   ("cci","Consumer confidence","Survey","ConsConf",C_S2,"CSCICP02JPM460S",v_survey("CSCICP02JPM460S"),False),
   ("kr_exp","Global trade (Korea exp.)","Trade","KRexp",C_TR,"XTEXVA01KRM667S",v_yoy("XTEXVA01KRM667S"),False),
   ("cn_exp","Global manufacturing (China exp.)","Manufacturing","CNexp",C_MF,"XTEXVA01CNM667S",v_yoy("XTEXVA01CNM667S"),False),
   ("cn_cli","China LEI","China","CNlei",C_CH,"CHNLOLITOAASTSAM",v_cli("CHNLOLITOAASTSAM"),False),
   ("yc","Yield curve (10y-3m)","Rates","YieldCv",C_RT,"JP 10Y - 3M",[("level",ycv("IRLTLT01JPM156N","IR3TIB01JPM156N"))],False),
   ("nikkei","Equity prices (Nikkei)","Markets","Nikkei",C_EQ,"NIKKEI225",v_yoy("NIKKEI225"),True),
   ("creditimp","Credit impulse (BIS)","Credit","CredImp",C_CR,"CRDQJPAPABIS",v_credit("CRDQJPAPABIS"),True),
  ], gdp_yoy_m("JPNRGDPEXP"),"GDP YoY","JPNRECDM",3,OR),
 ("China","CN",[
   ("credit","Credit impulse (BIS)","Credit","Credit",C_RK,"CRDQCNAPABIS",v_credit("CRDQCNAPABIS"),False),
   ("cn_cli","OECD China LEI","China","CNlei",C_CH,"CHNLOLITOAASTSAM",v_cli("CHNLOLITOAASTSAM"),False),
   ("rate_inv","Monetary conditions (3m, inv.)","Rates","MonCon",C_RT,"IR3TIB01CNM156N",v_rate_inv("IR3TIB01CNM156N"),False),
   ("metals","Industrial commodities","Commodities","Metals",C_COM,"PMETAINDEXM",v_yoy("PMETAINDEXM"),False),
   ("cn_exp","Exports","Trade","Exports",C_MF,"XTEXVA01CNM667S",v_yoy("XTEXVA01CNM667S"),True),
  ], yoy(M("XTIMVA01CNM667S")),"Imports YoY","CHNRECDM",3,OR),
]
for name,code,cands,coin,cn,rec,mav,rn in jobs:
    c,p=build(name,code,cands,coin,cn,rec,mav,rn); COUNTRIES[c]=p

# China diagnostic: lead vs ACTUAL China GDP (nominal YoY, to ~2023)
_cnp=COUNTRIES["CN"]; _comp=pd.Series(_cnp["composite"]["v"],index=pd.to_datetime(_cnp["composite"]["d"]))
_gdp=(S("CHNGDPNQDSMEI").pct_change(4, fill_method=None)*100).resample("MS").ffill()
_j=pd.concat([_comp.rename("c"),_gdp.rename("g")],axis=1).dropna()
if len(_j)>20:
    _bk=max(range(0,13),key=lambda k:_j["c"].corr(_j["g"].shift(-k)) if not pd.isna(_j["c"].corr(_j["g"].shift(-k))) else -9)
    _cnp["leadlag"]["gdp_k"]=int(_bk); _cnp["leadlag"]["gdp_r"]=round(float(_j["c"].corr(_j["g"].shift(-_bk))),2); _cnp["leadlag"]["gdp_end"]=_gdp.dropna().index[-1].strftime("%Y")

DATA={"order":["US","AU","UK","EA","JP","CN"],
      "names":{"US":"United States","AU":"Australia","UK":"United Kingdom","EA":"Euro Area","JP":"Japan","CN":"China"},
      "fetched":pd.Timestamp.now("UTC").strftime("%Y-%m-%d")}
DATA.update(COUNTRIES)

# ---- inject into template -> index.html (self-contained) ----
tmpl=open("template.html",encoding="utf-8").read()
html=tmpl.replace("/*__DATA__*/{}", json.dumps(DATA))
open("index.html","w",encoding="utf-8").write(html)
print("Wrote index.html (%.1f KB), %d boards, fetched %s"%(len(html)/1024,len(DATA["order"]),DATA["fetched"]))
