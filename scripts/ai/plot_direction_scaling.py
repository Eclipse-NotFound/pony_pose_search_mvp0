"""Standalone scientific learning-curve figure from every completed seed."""
import sys
sys.dont_write_bytecode = True
import os
from direction_scaling_select import OUT
os.environ['MPLCONFIGDIR']=str(OUT/'mpl_settings')
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from direction_pilot_data import read


def main():
    rows=read(OUT/'summary.json')['rows']
    assert read(OUT/'summary.json')['complete']
    font=FontProperties(fname='C:/Windows/Fonts/msyh.ttc')
    plt.rcParams.update({'font.family':font.get_name(),'axes.unicode_minus':False,'font.size':11})
    colors={'keypoint_heatmap':'#3077b0','direct_vector':'#d47a21'}
    labels={'keypoint_heatmap':'关键点 → 方向','direct_vector':'直接预测方向'}
    fig,axes=plt.subplots(2,2,figsize=(12.6,8.7),sharex=True,sharey=True)
    maximum=max(r['mae_deg']+r['seed_sd'] for r in rows if r['split'] in ['test','challenge_agent_reference'])
    for col,kind in enumerate(['best','final']):
        for row,split in enumerate(['test','challenge_agent_reference']):
            ax=axes[row,col]
            for arm in ['keypoint_heatmap','direct_vector']:
                data=[next(r for r in rows if r['selection']==kind and r['split']==split and r['arm']==arm and r['regime']==g) for g in ['n103','n203','n303']]
                x=np.asarray([r['train_images'] for r in data]); y=np.asarray([r['mae_deg'] for r in data]); sd=np.asarray([r['seed_sd'] for r in data])
                seed=np.asarray([r['per_seed_mae'] for r in data])
                for j in range(3): ax.plot(x,seed[:,j],color=colors[arm],alpha=.18,linewidth=1)
                ax.errorbar(x,y,yerr=sd,color=colors[arm],marker='o' if arm=='keypoint_heatmap' else 's',linewidth=2,capsize=4,label=labels[arm])
                for xx,yy in zip(x,y):
                    dy=-15 if arm=='keypoint_heatmap' else 10
                    ax.annotate(f'{yy:.1f}°',(xx,yy),textcoords='offset points',xytext=(8,dy),ha='left',fontsize=10,color='#24292c')
            ref='12张人工参考' if split=='test' else '16张AI待审参考'
            selected='验证图选出的模型' if kind=='best' else '统一训练结束时的模型'
            ax.set_title(ref+' · '+selected,fontsize=12,pad=12)
            ax.set_xlim(85,321); ax.set_ylim(0,max(45,np.ceil(maximum/5)*5+5)); ax.set_xticks([103,203,303])
            ax.tick_params(axis='x',labelbottom=True)
            ax.grid(axis='y',color='#dadede',linewidth=.6); ax.set_axisbelow(True)
            ax.spines[['top','right']].set_visible(False)
            ax.set_xlabel('训练图片数（张）')
            if col==0: ax.set_ylabel('平均方向误差（度，越小越好）')
    handles,names=axes[0,0].get_legend_handles_labels()
    fig.legend(handles,names,loc='lower center',bbox_to_anchor=(.5,.05),ncol=2,frameon=False)
    fig.suptitle('新增200张标注：训练集 103 → 203 → 303 张',fontsize=16,y=.98)
    fig.text(.5,.016,'每档同样训练1,200次更新；每种模型重复3次。误差棒为3次训练的标准差，浅线为各次结果。\n检验图沿用已有样本，尚不能代表新剧集或真实检索效果。',ha='center',fontsize=10,color='#50555a')
    fig.tight_layout(rect=(0,.12,1,.95))
    fig.savefig(OUT/'learning-curve.png',dpi=160)
    fig.savefig(OUT/'learning-curve.pdf')
    plt.close(fig)
    print(OUT/'learning-curve.png')


if __name__=='__main__': main()
