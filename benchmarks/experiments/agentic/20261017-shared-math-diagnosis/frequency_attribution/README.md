# 频率初始化细分诊断（同一任务补充）

本补充响应主控对`20261017-shared-math-diagnosis`的频率归因要求。仅诊断，父源码仍为官方883390/48.78的817f8364；未生成性能候选、未改canonical/ready/latest/正式runner/golden/阈值，也没有Axpy或SinCos改动。继承幅值FP16最大误差32完整保留。

## 测量与边界

只新增两项串行单卡任务，各max-time60。第一项8个已有冻结输入、16次启动；第二项仅tiny和DeepSeek FP16两项、4次启动，用于检查纯标量计时的编译器边界。每项均明确等待terminal及卡释放后才进入下一项，均exit0。全20次审计均每调用1kernel，10份输出与817/8d逐位相同，原精度、position0、y与独立trace首尾guard、每核行尾8格和未用核区域全部通过。所有原输入/父输出SHA重新核对。

每核独立96uint64 trace行，实际写88格；GM单独分配并经诊断ABI传入，不占用tiny的64B输出，也不覆盖其他核。仅本核PIPE_ALL，无跨核全局同步。原频率helper保留；诊断克隆按原运算顺序执行，五个选中类移除计时包装后与父版逐字一致。

原始[阶段数据](stages.json)、[标量对照](scalar_control/stages.json)、[任务记录](summary.json)、[源码同一性/旧证据范围](reused_evidence_and_math_proof.json)与[编译/二进制绑定](metadata.json)均归档。

旧`agentic_r2_v9_init_wide`的helper与817逐字一致，可复用其短任务初始化摊薄现象，但其PMU测的是1×7×17×1024完整算子，不能视作独立frequency-only时间。没有重复采这组PMU。

## 标量模式：实际分支与计时控制

所有本次输入theta=10000。K8每核7次Q31，0次歧义回退、0次root构建；K32每核31次Q31，2次回退、1次root构建、0次相同power复用。CPU已有模型列出K32回退列1/10，Device只记录计数2，没有导出列号，因此不声称Device逐列验证了这两个编号。root表原本已按需延迟一次生成；K512向量模式根本不调用该标量回退。

逐列细分后，scalar频率总tick相对旧粗测增为1.823倍（tiny）及3.196–3.324倍（K32）。Q31/reciprocal/store记录的是被强插桩程序；不能将其相加或换算原kernel占比。检查SDK发现GetSystemCycle的asm仅绑定SYS_CNT输出，无theta/log数据依赖；PIPE_ALL不证明纯整数指令不会跨边界移动。原细分log11/1.6–2.0tick因此不能作为孤立log延时。

为此只加一个有上限的标量对照：同一已有MOV SYS_CNT语法，在开始绑定read-write theta位值（指令保持它不变），结束消费log/log31；有memory clobber，强制纯函数位于两个时点之间。剩余循环整体计时，移除逐列探针。编译成功且输出逐位一致；没有新安装/不支持接口重试。

| 对照 | log53与log31设置/核ticks | 剩余标量循环/核ticks | frequency含包装/核ticks |
|---|---:|---:|---:|
| tiny | 47.750 | 45.000 | 102.375 |
| deepseek_half | 6.333 | 105.438 | 116.771 |

同一log算法在tiny与Aligned上下文中的结果差异明显：tiny范围40–53tick，Aligned为6–14tick。寄存器锚定、编译上下文、取指/调度均可能影响，但没有解码ISA证据可作因果确认。只能分别报告；不能将47.75或6.33外推为统一硬件log延时，也不能把两个独立span当原始关键路径精确占比。

K32细分的Q31约33.6–34.6、reciprocal/pack约31.1–32.1、fallback含root约12.6–13.5、nested root约2.2–2.4tick。它们有明显插桩扰动和纯标量调度边界限制，仅用于结合操作计数判断后续方向，不能宣称root只需某个百分比。

**判断**：tiny中log设置与剩余循环同量级，值得未来先CPU研究精度界和更廉价的同结果log设置；改root/fallback对该输入无收益。K32则逐列工作更重，不支持一律优先log剪枝。已否定的Q53尾项剪枝/累加折叠不因此复活。原Q31守卫16单位覆盖log截断及求值误差，低精度log不能直接沿用该保证；本任务没有实现lazy log或任何数值近似。

## 向量模式：chunk与恢复

以下为每核累计SYS_CNT tick，仅诊断图像，nested span不可相加为原始总耗时。`poly/table/power`包含补偿链、两次Gather、pow结果指数重建和缩放；`dst copy`仅最后DataCopy/drain，不含前面的指数恢复。

| 场景 | chunk几何 | log观察值* | Exp2表 | chunk含子阶段 | log乘积/range | poly/table/power | reciprocal/round | dst copy |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| prefill_h32_d1024_half | 512 | 6.48 | 22.21 | 234.94 | 41.85 | 143.15 | 25.29 | 1.02 |
| prefill_h32_d1024_float | 472+40 | 6.50 | 22.10 | 380.08 | 68.71 | 230.62 | 39.83 | 1.88 |
| sequence_d1024_half | 512 | 6.90 | 24.62 | 235.00 | 41.90 | 143.04 | 25.31 | 1.06 |
| sequence_d1024_float | 512 | 6.46 | 24.31 | 234.81 | 41.85 | 143.04 | 25.27 | 1.04 |

*LogTheta为未加寄存器依赖的纯标量span，存在同样的编译器移动风险；6.5–6.9tick仅观察值，不用于宣称其真实成本低。向量子链由有副作用的UB向量API和本核流水边界组成；仍没有解码ISA/真实UB事务和精确原始占比。

已选binary-width分支共211次源级API：ratio2，log乘积/range43，poly/table/power141，reciprocal24（含两次Div及补偿），dst copy1。一般非二次幂分支多38次，本轮未测。它们不是211条ISA。源级最多工作量与测量的poly/table/power较重相符；之前仅将部分Mul/Add折为vmla并未降低实测VEC且原生收益不可靠，故不能再次仅靠API计数提候选。

FP32多head的scratch8200float实际分为472+40两chunk，累计chunk380tick，另外三个512完整chunk约235tick。总频率细分相对旧粗测变化约−9%到+10%；跨card/图像不能把差值当改进。若未来研究workspace换取单chunk，需要覆盖全几何UB/liveness与native对照；本次不改tiling、scratch或算法。向量chunk主链优先于孤立的root表/最终copy。

## 后续排序与停止条件

1. tiny：先精度模型证明更廉价log与Q31守卫，关注设置摊薄；没有fallback可删。
2. K32：逐列Q31/reciprocal/UB写与控制，root已经lazy；不能根据未锚定短span宣称精确节省。
3. K512：补偿多项式/查表/pow恢复链、extra chunk与UB资源，比原本很小的末端copy更有证据。H1长序列中freq一次性设置仍远小于先前测到的重复trig，不能被本报告挤掉优先级。

上述只是主控后续选择方向的依据，不授权开发/新近似。Axpy头文件存在不代表IEEE FMA，本轮未测试其舍入，也没有替换SinCos。大幅值FP16继承失败max32未解决，原reference/阈值未动。停止新增NPU探针、候选与平台提交，等待主控审阅。

完整限制见[summary.json](summary.json)，包括量化、未解码ISA、仅最后一次trace、无CI、近unity/非对齐/极端theta未覆盖等；没有将这些probe event_us作为native收益。
