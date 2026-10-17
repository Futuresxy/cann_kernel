# HeadTile 阶段归因与周期布局实验

请求 `20261017-headtile-attribution` 已完成，保留一个供主控审阅的实验版本。没有提交平台、发布 production-ready 或修改 latest。所有诊断副本均不得提交。

父版为官方提交883390、48.78分的源码 `817f8364de18a96c242e3c19705fac3453077a69b7432839096671c0564c2556`；候选为本目录 `kernel.asc`，SHA256 **`8d91182ab86ed3937f8127f3d427bb0777bbf94cffff83977b1bab580428eaea`**。canonical仍为V9/591，不能将canonical路径误认为本实验源码。

## 先诊断，再决定实现

原RoPE每对输入需要4个FP32乘积和2次加减。频率与三角函数必须在Device计算；位置int32在合法范围内能精确转为FP32。HeadTile每job生成一份三角系数，再为多个head展开。H较大时，数学复用已经存在，成本仍可能集中在UB布局。当前分析不推测隐藏15点的shape。

已有817源码、a9c3fc4b二进制的D30/H128 PMU显示VEC约90.6%，MTE2约14/17%；FP16与FP32原生时间都约100us。这提示向量/UB关键路径，尚不能单独归因Gather。因此先制作一个加时间戳的诊断副本，覆盖D30/H128两类型，以及D18/H129、D62/H65两类型的合法尾块。

`diagnostics/instrumented.asc`只添加`GetSystemCycle`/PIPE_ALL阶段标记，并在各核自己首job输出区保存记录，不添加第二个kernel。正常旋转仍执行，但输出含诊断记录，不能用于精度或提交。每核20个uint64记录都在其独占job有效输出内；原生runner guard仍通过。输入及源码/二进制哈希见diagnostics/input_manifest.json和diag_build_metadata.json。

D30的48核平均SYS_CNT tick如下，均为整核累计值：

|阶段|FP16|FP32|
|---|---:|---:|
|分配/队列设置|52.60|125.25|
|频率生成|86.85|86.29|
|索引初始化|74.69|74.56|
|角度与原trig链|1007.02|1006.54|
|系数Gather两次|962.02|962.40|
|输入Load/Cast|133.25|114.21|
|输入拆半Gather两次|963.96|981.52|
|四乘与Sub/Add|657.71|671.23|
|输出打包Gather一次|960.21|971.06|
|Store/Cast与输出槽分配|157.10|154.00|
|出队/预取/position相关阶段|427.60|499.12|
|写回/队列释放阶段|426.21|476.17|
|空标记累计成本|64.19|64.73|

D18两类型的系数/输入/输出Gather约135/135/89 tick，旋转约109；D62约136/137/124，旋转约109。完整逐核记录、job数及尾核差异见diagnostics/stages.json。

这些标记**强制排空流水**，改变了原版重叠；出队/预取阶段会等待下一次输入DMA，写回阶段会等MTE3。标记本身还有标量和屏障成本。它们不是原始关键路径的可加百分比，SYS_CNT也不是直接记录的AIV core cycles，没有假设频率来换算us。诊断足以支持布局值得研究，但不能说Gather精确占原版多少。

## 指令与历史负结果

已安装dav_c220头文件将Gather映射到`vgather`，FP32 count接口按64元素repeat和尾mask拆分；Copy映射到`vcopy`。D30完整job的旧5次Gather处理12032个逻辑元素，按头文件为188个有效/尾repeat；候选Gather为4080元素、64个repeat，另外以124个规则Copy repeat处理7440元素。repeat、API调用、静态机器指令条数是不同概念。

设备`-S`导出被现有编译器拒绝。历史llvm-objdump对HiIPU显示`not available`的限制仍存在，未安装或更新工具，也未虚报解码后的机器指令数。保留此次导出尝试日志、SDK头文件SHA、设备text比较及受控实测。源码和已安装接口的指令映射加上PMU、原生计时，构成本轮能取得的证据边界。

已先阅读并保留以下负结果：

- round2 head_mask/head_packed：在对齐D64路径新增GatherMask/打包，布局成本超过算术收益。这不是当前已经包含5次Gather的非对齐HeadTile；本轮有独立阶段诊断。
- round3 layout_copy：D64逐head的半段strided Copy和MulAddDst未获益。本轮Copy只复制32B对齐的不可变短周期系数，不搬动每head输入半段，也不用MulAddDst。
- R4：FP16 compact改善，但FP32回退6.07%；未推广它，也没有重试通用广播计算。
- R5：通用非对齐流水本地1.7倍，官方885584反为48.44，低于817的48.78；保留其证据，本轮没有继续修改generic Rotary。

## 唯一实现及容量/数值证明

仅替换HeadTileRotary类。Host、dispatch、tile、GM事务和字节、队列深度2、预取、position0原协议、最后drain及所有FP32数值helper都保持父版。其他40/44个设备text入口逐位相同。

令`U=D*(8/gcd(D,8))`，这是FP32系数存储满足32B对齐的最短head周期。先在Device从本次trig结果Gather一个cos和signed-sin前缀，再用Copy复制：srcRepeatSize=0，dstRepeatSize=U/8，源前缀和所有目的范围不相交；每条mask<=64、repeat<=255。尾部用有效mask，首尾地址32B对齐。旋转只Gather一次完整rotate-half向量，两个整向量Mul和一次Add仍对应每对4个独立舍入的乘积与2次加减。

低半维使用`a*c + b*(-s)`；这不假设单次舍入FMA，也不降低FP32精度。离线百万组随机位模式、signed-zero/次正规模型有限位差为0，但CPU模型不是NPU证明，最终以设备1765项完整位比较为准，包括非有限值。

完整域D18..62（排除16倍数）、H33..256共4704个几何组合检查了周期、mask/repeat、索引及UB边界。每个有效输出的配对索引均在有效输入内；padding lane只在分配范围内计算，不能影响写回的有效元素。两个系数前缀均在独立空间生成，复制期间不可变。

原6capacity FP32工作区不变，频率scratch尺寸不变，不触发额外频率fallback。输出双槽先存FP32 sine，再在其死亡后存最终T结果。活跃期及检查见pre_implementation_model.json：FP16最高117312B，FP32最高133696B，均低于188KiB；含索引、mask和频率缓冲。禁止把队列slot在MTE3读完前重新写入，其复用仍由原TQue事件保证。

主控另推送2b2aa37的几何模型，与本轮独立检查的4704组合、完整D30元素数一致。注意实际候选在很小尾group仍构造完整U前缀：D30/H129最后1head处理272个Gather元素（2*120+32），不是该提案中缩小前缀的96。它安全但有额外工作，本轮没有为此再开发第二变体。D62/H65等尾块较重场景收益较小，与此成本一致，但尚未把差值单独归因为这一因素。

## 原生计时和PMU

冻结输入、同一进程同分配地址，ABBA及交换源码后的BAAB。每块5次预热、5个非replay Task Duration样本；每源码4个block median再取中位数。有效3600次调用=3600个设备task；33+12个计时输入的最终输出也全部与父版逐位相同（timed_output_identity.json）。原始样本/哈希在benchmarks/results/agentic_r6_{fixed33,family}_{forward,reverse}.json及对应profiles，汇总没有使用replay或runner event_us。

|目标|父版/us|候选/us|加速|
|---|---:|---:|---:|
|D30/H128 FP16 [2,1024,128,30]|99.9720|65.5315|1.52556×|
|同shape FP32|100.0120|65.6020|1.52453×|

两源码顺序分别约1.525/1.525。12个额外公开场景为D18/22/26/34/46/62、H129/255/65、N257、两dtype；两顺序均加速，范围1.14924–1.48659倍，几何平均1.34150倍。固定33点几何平均1.02837倍。31个未改入口对照几何平均1.00255倍；最差Packed小点7.14→7.25us（+1.54%）保留，不能归因于HeadTile优化或隐去回退。不声称4个block构成独立重复的正式置信区间。

有一次执行偏差必须记录：上一项任务尚未确认释放时提交了首次forward计时，队列分配到第二张卡device1。该次数据已完整保存于diagnostics/excluded_overlap_run和agentic_r6_excluded_overlap_forward，**完全排除**决策。确认两项结束后重新在device0串行收集forward，并在device0完成reverse及其余任务。任务13项、每项max-time60、均完成，详见tasks.json。未安装、改配置或管理驱动/队列。

源绑定PMU（诊断，不用于加速比分母）：

|48核平均活跃时间/us|FP16父/候选|FP32父/候选|
|---|---:|---:|
|VEC|88.7214 / 54.1910|88.9741 / 54.2832|
|MTE2|13.8456 / 13.8847|16.4268 / 16.8245|

MTE3也基本稳定；scalar活跃时间反而增加，FP16约18.38→22.05us，表明更多初始化/Copy控制并非免费。VEC下降而GM搬运基本不变，支持减少UB不规则重排/依赖的预期。不能据此把VEC比例解释为有效lane利用率，不能从MemoryUB平均带宽直接声称物理峰值或精确指令耗时。原始PMU与native输入SHA一致，见pmu_comparison.json。

## 验收与保留失败

- 既有1723冻结输入、golden、817输出哈希均核对，另加42项对齐周期、奇数head、零位置/NaN/Inf、近1和其他theta尾块。1765项**所有输出位均与父版相同**，包括非有限位模式；guard、position0、非有限分类全部通过。
- 候选1849次调用逐次审计均恰好1 kernel；新增父版126次审计也通过。
- 原阈值下1764/1765通过；唯一继承失败[1,137,17,1024] FP16 matched_ratio=0.9999874208351224，max_abs_error=32>0.1。输出SHA仍为248cf74c43ad2df74183f34549bce956ec72a37082a4c91e7eb2a0d357a80663，父/候选相同。先前定位的trig/参考库舍入敏感性未解决，未换golden或放宽阈值。
- 普通二进制52项原精度/guard/identity通过，且输出与父版逐位相同；独立非replay检查75次调用=75 task。
- 原模板7个其他文件逐字节相同，仅kernel.asc替换。原CMake/C++14/dav-2201编译成功，原main+verify_result通过，maxdiff2.6226e-6。普通、审计及模板的44/44设备text一致。
- 数值helper、原输入/参考、canonical、latest及用户规则SHA保持不变。payload仅自包含kernel.asc，不依赖离线NumPy或其他包、辅助文件、CMake/link改动。

## 决策与复现

保留一个实验归档交主控审阅，生产ready因继承精度失败而blocked；不修改latest，不自行提交平台，不启动下一变体或guarded-trig。即使目标本地收益约34%，也不能预测平台分数；R5的真实反例已保留。

CPU复现/审阅入口：model.py（几何/容量）、diagnostics/analyze.py（冻结trace解码）、validate.py analyze（原精度+父版位比较）、combine.py（两源码顺序原生样本）。构建使用现有tools/build_paired.sh、CMake和原模板；命令、source/binary/runner哈希在各metadata、task日志、correctness.json中。重新采集必须另经主控授权并串行task-submit max-time60；不得运行/提交诊断副本作为性能候选。
