"""Plot measured activation times from a passive-chain suite verification JSON."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('verification');p.add_argument('destination');a=p.parse_args()
    report=json.loads(Path(a.verification).read_text());runs=report['runs'];series=[]
    for i,r in enumerate(runs['positive']):series.append((f'Clean start {i+1}',r,['#58bcd8','#42a8bd','#88d4da'][i%3],'-'))
    for r in runs['negative']:series.append((r['mode'].replace('_',' ').title(),r,'#ecaa60' if r['mode']=='broken_link' else '#ba8fb8','--'))
    series.append(('Raised table / shifted tray',runs['edit'],'#a1d584',':'))
    duration=max((n['activation_step']/60 for _,r,_,_ in series for n in r['bodies'].values() if n['activation_step'] is not None),default=1)+2
    total=len(runs['positive'][0]['bodies'])
    with plt.rc_context({'font.size':11,'axes.facecolor':'#15222c','figure.facecolor':'#101a22','text.color':'#e1ebef','axes.labelcolor':'#c9d8df','xtick.color':'#c9d8df','ytick.color':'#c9d8df','axes.edgecolor':'#46606d','grid.color':'#314752','legend.facecolor':'#15222c','legend.edgecolor':'#46606d','savefig.facecolor':'#101a22'}):
        fig,ax=plt.subplots(figsize=(10.5,5.3))
        for label,r,color,style in series:
            times=sorted(n['activation_step']/60 for n in r['bodies'].values() if n['activation_step'] is not None)
            ax.step([0,*times,duration],[0,*range(1,len(times)+1),len(times)],where='post',label=label,color=color,linestyle=style,linewidth=2 if style!='-' else 1.5,alpha=.9)
        ax.set(xlim=(0,duration),ylim=(-1,total+3),xlabel='Simulation time (s)',ylabel='Bodies reaching motion / tilt thresholds',title='One initial trigger: propagation and interventions')
        ax.grid(alpha=.55);ax.legend(loc='upper left',fontsize=9)
        fig.text(.125,.015,'Activation is measured motion, not final success. Receiving/stability and contact order are checked separately.',fontsize=8,color='#9db5c1')
        fig.tight_layout(rect=[0,.04,1,1]);destination=Path(a.destination);destination.parent.mkdir(parents=True,exist_ok=True);fig.savefig(destination,dpi=170);fig.savefig(destination.with_suffix('.pdf'));plt.close(fig)
    print(destination)

if __name__=='__main__':main()
