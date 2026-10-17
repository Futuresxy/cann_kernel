# 共用数学链阶段诊断（仅诊断）

请求 `20261017-shared-math-diagnosis` 已完成。只生成粗粒度/细粒度诊断副本，没有性能候选、数值近似、平台提交、ready或latest更新；现在等待主控审阅。未消费自动生成的887393通用任务。

性能比较源仍为官方883390、48.78分的817f8364。真实HeadTile提交887393（run20261017T073409479470Z-8d91182ab86e）15/15 Pass、48.29分、排名快照69。其本地1.525倍收益没有转化成可观察官方提分，不提升基线，也不推测隐藏shape或把平台编号对应到分支。

## 源绑定、方法与校准

先读取最新瓶颈复核、AGENTIC/kernel_requirement/forbidden、旧阶段/数值/SDK证据及负结果。以817完整源码克隆；五个实际类和全部共用数值helper在最新8d中逐字相同，22个相关注册设备text亦复用此前逐位一致的证据。见helper_identity_817_8d.json、reused_device_identity.json。**tiny实际走DirectFloatRotary，不能根据名称当成SmallRotary。**

8个原始公开输入来自固定33点；输入SHA与原生ABBA+BAAB报告一致。诊断分别从Init/Process中包围频率、angle、trig、rotation、Load/Store、positions、队列与GM搬运阶段。详细版将原SinCos的34个基础API按10/10/3/1/5/5分为range reduction、sin polynomial、sqrt input、Sqrt、double angle1/2，操作数、系数、顺序均保留。两版使用同一instrumented.asc，编译开关只控制内部边界。numerical_sequence_proof核对34个原数值调用未变。

独立GM trace区每核96个uint64（前后另有guard），不覆盖y、不修改输入。每次执行完整算子后导出本次调用记录，类实例每次重建，既不识别预热也不跨调用缓存。32个空标记/核用于分辨率校准；SharedTrace含672B私有计数/元数据，编译器可能改变寄存器/栈压力，未虚报其物理存储位置。

严格串行两项auto单卡task-submit，max-time均60；均分到device1。确认第一项terminal和释放锁后才提交第二项，第二项也已退出释放。每版8例×2调用（1预热+1记录），实际launch API审计共32次，每次1 kernel。前轮误并发device1数据仍保留并排除，本轮没有复用它；本轮合法串行使用device1与前轮例外是不同事件。原生旧对照在device0，不能将两者当同卡配对收益。

初次CPU编译发现Bulk position-broadcast内较早的col循环被误选为rotation起点，stamp变量作用域错误。两构建均在任何NPU运行前失败；起点改为LoadFp32之后，日志保留。没有失败NPU运行、没有数值改动或候选试错。

## 每族粗粒度实测

下表除native一列为独立旧817原生Task Duration/us，其他均为48核（tiny为8核）的**平均累计SYS_CNT tick**。SYS_CNT未换算成AIV core cycles或微秒。频率每核一次，trig/rotation等按该核实际job累计，不可跨案例把累计值直接理解成每次API成本。

|公开case|入口|native/us|frequency|trig|rotation|Load|Store|GM读/写|
|---|---|---:|---:|---:|---:|---:|---:|---:|
|tiny|DirectFloatRotary|2.6900|81.75|21.38|5.62|0.00|0.00|27.88/14.38|
|deepseek_half|AlignedRotary|17.2600|114.65|55.79|396.38|96.25|60.35|232.81/253.77|
|deepseek_float|DirectFloatRotary|18.3110|119.23|55.98|583.21|0.00|0.00|365.35/363.48|
|prefill_h32_d1024_half|LargeAlignedRotary|29.1305|311.85|104.54|831.71|91.23|54.81|247.71/209.33|
|prefill_h32_d1024_float|DirectFloatRotary|32.9210|453.56|80.40|1011.42|0.00|0.00|358.88/357.33|
|sequence8192|BulkPositionRotary|11.5200|114.21|160.90|57.98|7.21|6.60|29.44/31.04|
|sequence_d1024_half|BatchedRotary|87.2810|259.42|2264.58|1333.92|123.52|67.04|288.77/307.96|
|sequence_d1024_float|BatchedRotary|94.4520|311.69|2413.42|1511.94|102.40|104.48|386.96/423.52|

多head对齐的4例，rotation累计远大于trig；DeepSeek FP32另有较高的已测MTE2活跃度，不能因此称纯计算受限。FP16有Load/Store转换，DirectFloat两项为0，因为它已直接在队列计算。H1 FP32的Load/Store是DataCopy UB拷贝，不能称FP32 Cast。H1/D1024则trig累计高于rotation；H1/D64另有position向量广播/zero mask开销34.02tick。tiny频率约70.5–81.75tick，明显重于其rotation约5tick；其频率32位结果在每个核独立生成，不能缓存跨调用或移到Host。

Init与Process是inclusive总量：Batched/Bulk的Init包含频率；Aligned/Large/Direct的Process包含频率；trig总量包含细分标记。不能把这些列相加。GM读包围Prefetch并等完成，写包围出队/存储/释放并等完成，含队列API；Queue计数在强制排空条件下不等于原版队列等待。未覆盖的标量循环/分配、记录本身也不能凭差值精确分摊。

## trig子链与插桩扰动

|case|range|polynomial|sqrt输入|Sqrt|倍角1|倍角2|细/粗trig|空标记tick/次（粗/细）|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
|tiny|8.88|6.12|2.00|1.12|2.75|2.88|1.520|0.125/0.133|
|deepseek_half|16.79|16.96|5.21|2.67|8.48|8.71|1.397|0.129/0.124|
|deepseek_float|17.00|17.02|5.42|2.83|8.58|8.44|1.391|0.150/0.146|
|prefill_h32_d1024_half|33.60|31.15|8.35|4.65|15.00|14.83|1.213|0.128/0.150|
|prefill_h32_d1024_float|24.00|24.90|6.15|3.58|11.58|11.73|1.138|0.128/0.136|
|sequence8192|48.56|49.38|12.75|7.52|23.12|23.40|1.183|0.143/0.129|
|sequence_d1024_half|674.02|701.94|175.65|104.42|323.21|327.12|1.138|0.115/0.133|
|sequence_d1024_float|718.40|742.81|188.27|110.69|349.40|351.65|1.154|0.133/0.142|

在H1宽维的细分诊断里，range与polynomial分别约674–743tick，Sqrt约104–111tick；两次倍角也分别约323–352tick。孤立Sqrt不是这一链中最大的成本。精度诊断中的首个算术分歧在Sqrt，不意味着性能应优先优化Sqrt；也不能用替换sqrt来解决全部高幅值误差。

空标记均值约0.12–0.15tick，单个记录有量化；不作统一扣除。细版trig总量比粗版高1.138–1.520倍：新增屏障/标量计数、依赖和编译器寄存器/栈布局均有影响。未修改的频率计时也出现约-13.8%至+21.8%变动，所以这些不是独立原生重复或正式置信区间。报告原始范围、逐核记录和调用/元素数，不把隔离阶段之和当原kernel关键路径比例。

## 工作量、复用与生存期模型

|case|tile/group/trig batch|UB/B|freq元素/全核|trig调用/元素/全核|
|---|---:|---:|---:|
|tiny|1/1/1|512|64|7/56|
|deepseek_half|128/1/16|141440|1536|96/32768|
|deepseek_float|128/1/16|137472|1536|96/32768|
|prefill_h32_d1024_half|11/3/5|190528|24576|96/147456|
|prefill_h32_d1024_float|8/4/8|182400|24576|48/147456|
|sequence8192|64/1/64|140416|1536|128/262144|
|sequence_d1024_half|6/1/6|161792|24576|1366/4194304|
|sequence_d1024_float|5/1/5|176128|24576|1639/4194304|

每个模型的频率数、trig调用及角度元素数、rotation有效元素数，均与两版Device记录完全相符。数学旋转工作量为3*N*H*D基本FLOP，X/Y最低逻辑GM流量2*N*H*D*sizeof(T)，positions是int32；这些不等于实测DRAM事务。原trig34个基础API的逻辑UB读写模型为324B/angle，也不是实测UB端口流量或解码ISA条数。

D1024/H32 FP16 tile11、3group、trig batch5；FP32 tile8、4group、batch8。二者本次核分区均触及288个token（理想256），共147456个angle，边界重算仍存在，但没有在本任务改tiling。FP32 DirectFloat频率scratch8200float，按17槽+64结构得到472-lane stride，形成472+40两个块；H1/FP16足够大scratch为512一块。该区别来自源模型与实际尺寸，未量出每块独立耗时，不能把频率差异全部归给它。

主控1edff50的等IO模型已合并并逐项核对：GM字节、旋转FLOP和输入哈希全部一致。H32与H1的名义角度比32倍，加入实测核边界重复后为28.444倍（4194304/147456）。两shape还有H1 FP32显式UB拷贝、分离旋转算术、队列和tile差异，不能把约3倍原生时间差全归给trig。见coordinator_model_crosscheck.json。

原队列/工作区/trig生命周期均保留。H1没有H倍trig摊薄，8192个token共4194304个角度，每核频率512个另算一次。批量trig跨head复用时，对齐路径只缓存当前核访问的token，出调用后失效。没有新跨核共享、全局屏障或结果缓存。

## 排序与下一实验的预期指标

排序是公开族的诊断优先级，不是未知官方15点的得分权重：

1. **多head对齐旋转/操作数及搬运重叠**：4例rotation累计约396–1011tick，trig约56–105。优先解释掩码、广播、乘加读端口及依赖；FP32还要保留MTE2读关键路径分析。目标指标是rotation VEC时间/UB遍历或有效repeat减少，GM事务不增加。旧D64 GatherMask/head packing/layout_copy已失败，当前证据不足以重新跑那些方案。
2. **H1重复trig链**：D64和两种D1024都不能靠head摊薄，range/Horner/倍角比单独Sqrt更值得研究。目标是trig VEC及UB遍历下降，保留FP32范围缩减、数值顺序与舍入，MTE载荷不变。
3. **短调用与宽维频率设置**：tiny重复初始化明显；wide FP32的两块频率和288次token触及有具体模型。目标是每核设置或chunk数减少，不能以减少核数导致的并行损失换取表面设置减少。长H1里频率只初始化一次，不能泛称其占全算子大头。

供主控考虑的一个共用研究项是：**对已有大批量SinCos链做保持两次舍入的常量广播乘加合并**。这仅是proposal，不是本轮实现，也未运行探针。当前硬件vmadd已测为round(round(dst*src0)+src1)，因此可能合并三组现有Horner Mul+Adds，以及sqrt输入和两次倍角中的负比例+1，仍保留现有近似/系数和FP32分步乘积舍入；不能将它用于TwoProd的single-rounding残差。

结构预期为基础向量API遍历最多34→28，含常量向量读的逻辑UB模型约324→300B/angle；这不是解码指令数或时间收益。需要在Device本次调用生成5个64元素常量行，约1280B，以及额外初始化/掩码成本；wide FP16例子的UB模型为190528+1280=191808<192512，但所有公开几何、生存期和fallback仍须重新证明。small/tiny的设置成本可能压过收益，应依据公开工作量和资源条件保留原路径。多head中trig本来较小，端到端收益可能有限，不据此预测70分。

新授权后的第一门槛仍是实际vmadd下的完全舍入等价、别名/重复广播srcStride0、尾mask、次正规/溢出/非有限值、signed zero与UB端口；再用原阈值、单启动/模板、固定输入配对原生计时决定。若常量读取/冲突/控制抵消收益则拒绝。它与此前无增益的频率补偿folding、被否定的true-FMA残差和cos_poly替换不同；没有重试这些负方案。详见ranked_hypotheses.json。主控也可先审查更小的频率scratch容量模型项：wide FP32两个输出槽各多568float可容纳8768float频率workspace、模型UB186944B；仅是模型，未开发或测量。

## 精度、SDK及执行限制

两版8个输出均与父817逐位相同，且和8d此前输出相同；32次实际启动审计全部1 kernel/调用，trace与输出guard、原position0位模式和原阈值通过。8个性能输入不覆盖所有非有限/极端数值域，不能代替全域验收。原suite.generate只在新的诊断oracle目录按冻结seed重放，x/positions逐字节核对，没有改任何既有输入、golden、reference或阈值。

完整继承失败单列known_failure.json：[1,137,17,1024] FP16、theta10000，matched_ratio0.9999874208351224但max_abs_error32>0.1；817与8d输出SHA均248cf74c43ad2df74183f34549bce956ec72a37082a4c91e7eb2a0d357a80663。原冻结x/p/golden/output哈希重新核对，仅复用之前实测，未扩展本次NPU范围去重复它。先前频率/angle逐位一致；设备c/s重放旋转逐位一致；Sqrt首差不解释所有817个超0.1元素，高精度trig诊断仍115个超限，max32。当前FP32库舍入语义与隐藏平台backend未知，15/15Pass不解除这个失败。

现有SDK联合SinCos/SqrtConfig对dav-2201不可用；vmadd/vmla不能提取真正FMA残差；HiIPU反汇编不可解码的限制保留，本任务没有重复失败工具、安装或变更环境。34是源API数量，源码/头文件指令映射不是实际ISA条数，VEC忙碌率也不是有效lane或峰值FLOPS。

原生对照和replay PMU独立：此前source817的DeepSeek FP32、H1/D64 FP32、H1/D1024 FP32 PMU可作对应族旁证；宽维FP16旧PMU虽同shape但冻结seed不同，应明确标为同族证据。H1 FP16和多headD1024 FP32缺少本次相同输入的PMU，不能套用FP32 H1的89.4% VEC比例。原生/PMU/stamp计时不混算，也未测原始队列wait或实际DRAM/cache字节。

## 复现与停止状态

先读input_manifest、helper_identity、metadata与logs。CPU入口：work_model.py、analyze.py coarse/detailed、write_report.py。原始trace与输出留在build/agentic_r7；每核计数已导出coarse_stages/detailed_stages和CSV，含SHA。prepare.py用于从817生成诊断副本，含独立trace ABI和runner；严禁将instrumented.asc或diagnostic_runner提交平台。CMake只为离线诊断构建，没有修改原模板/链接/正式payload。

本轮两任务均已退出释放，没有运行中的NPU工作。仅提交诊断报告、source/input/binary绑定及保留的失败证据，不生成experimental_candidate.json，不改canonical/ready/latest，不消费泛化任务、不运行guarded-trig、software RN-FMA或新的HeadTile/generic流水变体。提交推送后停止，等待主控单独授权下一实验。
